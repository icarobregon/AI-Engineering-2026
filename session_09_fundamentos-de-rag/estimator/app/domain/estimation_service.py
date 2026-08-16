"""Pipeline orchestrator. Glue between guardrails, caches, prompt rendering and
the LLM wrapper. The router holds none of this logic — its only job is to
translate HTTP errors.

Pipeline (Session 4, final):

    1. Input guardrails (moderation + prompt injection + PII heuristics)
    2. Exact-match cache lookup  → return cached=True on hit
    3. Semantic cache lookup     → return cached=True on hit
    4. Render the versioned prompt
    5. LLM call via Instructor with response_model=EstimationResult
    6. Output guardrail (enforce_scope_response, filter policy)
    7. Write to BOTH caches (exact + semantic)
    8. Return EstimationResponse with cached=False

Order rationale: guardrails go before any cache because a malicious or PII
description should never be served from cache. The exact-match cache goes
before the semantic cache because it's the cheapest (no embedding call). The
semantic cache write happens AFTER output validation so we never cache failed
estimations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import structlog

from app.generation.cag.semantic import EstimationSemanticCache
from app.foundation.guardrails.input import check_input
from app.foundation.guardrails.output import enforce_scope_response
from app.foundation.prompts import render_estimation_prompt
from app.foundation.prompts.loader import render_conversational_prompt
from app.domain.schemas.critic import CriticFeedback
from app.domain.schemas.estimation import (
    ACBResponse,
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    EstimationResult,
    OutputFormat,
    ProjectType,
    TurnObservation,
)
from app.generation.agentic.boss import Boss
from app.generation.cag.exact import EstimationCache
from app.generation.agentic.critic import Critic
from app.foundation.llm.wrapper import LLMWrapper
from app.foundation.observability import log_stage, new_request_id
from app.domain.schemas.rag_estimate import EstimateResponse, RetrievalTrace
from app.generation.rag.query_reformulator import derive_filters
from app.generation.conversation.compression import apply_compression
from app.generation.conversation.metadata_extractor import update_metadata
from app.generation.conversation.models import Session
from app.generation.conversation.tier_resolver import Tier, resolve_tier

log = structlog.get_logger()


def _exact_cache_key(request: EstimationRequest, prompt_version: str, model: str) -> str:
    """Deterministic SHA-256 key over the typed request + prompt_version + model."""
    payload = json.dumps(
        {
            "description": request.description,
            "project_type": request.project_type.value,
            "detail_level": request.detail_level.value,
            "output_format": request.output_format.value,
            "prompt_version": prompt_version,
            "model": model,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"estimation:v2:{digest}"


class RagFlowUnavailable(Exception):
    """The RAG collaborators are not wired (missing API key or Postgres)."""


class EstimationService:
    """Single entry point for the structured estimation pipeline."""

    def __init__(
        self,
        *,
        llm_wrapper: LLMWrapper,
        exact_cache: EstimationCache,
        semantic_cache: EstimationSemanticCache | None = None,
        openai_client: Any | None = None,
        prompt_version: str = "v1",
        conversational_prompt_version: str = "v3",
        metadata_extractor_model: str = "gpt-4o-mini",
        compression_model: str = "gpt-4o-mini",
        anchor_detection_mode: str = "heuristic",
        critic_model: str = "gpt-4o-mini",
        boss_max_iterations: int = 2,
        runtime_config: Any | None = None,
        # --- Session 9: the RAG flow collaborators. Optional so every existing
        # call site (and every test) keeps constructing the service unchanged;
        # the flow refuses to run rather than half-run when they are missing.
        query_reformulator: Any | None = None,
        retriever: Any | None = None,
        context_assembler: Any | None = None,
        estimate_generator: Any | None = None,
        idempotency_store: Any | None = None,
        rag_top_k: int = 10,
        rag_distance_threshold: float = 0.6,
    ) -> None:
        self.llm_wrapper = llm_wrapper
        self.exact_cache = exact_cache
        self.semantic_cache = semantic_cache
        self.openai_client = openai_client
        self.prompt_version = prompt_version
        self.conversational_prompt_version = conversational_prompt_version
        # Constructor values are the fallbacks; with a runtime config wired
        # (Settings UI), the auxiliary models resolve per call instead.
        self.metadata_extractor_model = metadata_extractor_model
        self.compression_model = compression_model
        self.anchor_detection_mode = anchor_detection_mode
        self.critic_model = critic_model
        self.boss_max_iterations = boss_max_iterations
        self._runtime_config = runtime_config
        self.query_reformulator = query_reformulator
        self.retriever = retriever
        self.context_assembler = context_assembler
        self.estimate_generator = estimate_generator
        self.idempotency_store = idempotency_store
        self.rag_top_k = rag_top_k
        self.rag_distance_threshold = rag_distance_threshold

    # ------------------------------------------------------------------
    # Effective auxiliary models (runtime override > constructor default)
    # ------------------------------------------------------------------

    def _effective_model(self, key: str, fallback: str) -> str:
        if self._runtime_config is not None:
            return self._runtime_config.effective(key)
        return fallback

    def _metadata_model(self) -> str:
        return self._effective_model("METADATA_EXTRACTOR_MODEL", self.metadata_extractor_model)

    def _compression_model(self) -> str:
        return self._effective_model("COMPRESSION_MODEL", self.compression_model)

    def _critic_model(self) -> str:
        return self._effective_model("CRITIC_MODEL", self.critic_model)

    def estimate(self, request: EstimationRequest) -> EstimationResponse:
        # 1. Input guardrails — raises InputGuardrailViolation on rejection.
        check_input(request.description, openai_client=self.openai_client)

        # 2. Exact-match cache lookup.
        cache_key = _exact_cache_key(request, self.prompt_version, self.llm_wrapper.primary_model)
        cached = self.exact_cache.get(cache_key)
        if cached:
            log.info("estimation_cache_hit", kind="exact", key_prefix=cache_key[:24])
            result = EstimationResult.model_validate(cached["result"])
            return EstimationResponse(
                result=result, prompt_version=self.prompt_version, cached=True
            )

        # 3. Semantic cache lookup (bucketed by model: a hit from another
        # model must never be served — the primary can change at runtime).
        if self.semantic_cache is not None:
            semantic_hit = self.semantic_cache.lookup(
                request, self.prompt_version, self.llm_wrapper.primary_model
            )
            if semantic_hit is not None:
                log.info("estimation_cache_hit", kind="semantic")
                return EstimationResponse(
                    result=semantic_hit,
                    prompt_version=self.prompt_version,
                    cached=True,
                )

        # 4. Render the versioned prompt.
        system_prompt, user_message = render_estimation_prompt(request, version=self.prompt_version)

        # 5. LLM call with Instructor + Pydantic validators (re-prompts on failure).
        result, meta = self.llm_wrapper.complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=EstimationResult,
        )
        log.info(
            "estimation_generated",
            prompt_version=self.prompt_version,
            confidence_pct=result.confidence_pct,
            total_cost_eur=result.total_cost_eur,
            phases=len(result.phases),
            **meta,
        )

        # 6. Output guardrail (filter): normalises low-confidence answers.
        result = enforce_scope_response(result)

        # 7. Cache the validated payload only (never persist failed validations).
        self.exact_cache.set(
            cache_key,
            {
                "result": result.model_dump(mode="json"),
                "prompt_version": self.prompt_version,
            },
        )
        if self.semantic_cache is not None:
            self.semantic_cache.store(
                request, result, self.prompt_version, self.llm_wrapper.primary_model
            )

        # 8. Return.
        return EstimationResponse(result=result, prompt_version=self.prompt_version, cached=False)

    def estimate_conversational(
        self,
        *,
        session: Session,
        transcript: str,
        project_type: ProjectType,
        detail_level: DetailLevel,
        output_format: OutputFormat,
        tier: Tier | None = None,
        attachments_total_chars: int = 0,
    ) -> EstimationResponse:
        """Multi-turn estimation pipeline (Session 5).

        Differences with ``estimate``:
        - No exact/semantic caching: every turn depends on the conversation
          history + metadata, so two identical transcripts in different
          sessions are NOT the same call. ``cached`` is always ``False``.
        - The system prompt is the v2 template, which embeds the current
          ``ProjectMetadata`` block. The LLM also receives the prior
          user/assistant turns.
        - After validation, the session's history is appended and a second
          LLM call refreshes ``ProjectMetadata``.
        """
        # 1. Input guardrail on the enriched transcript (the caller has
        #    already concatenated any extracted attachment text into it).
        check_input(transcript, openai_client=self.openai_client)

        # 2. Resolve the audience tier. Override (when the caller passed one)
        #    wins; otherwise the rule chain decides from transcript + metadata.
        resolved_tier, rule = resolve_tier(
            transcript=transcript,
            metadata=session.metadata,
            override=tier,
        )
        session.last_resolved_tier = resolved_tier.value
        session.last_tier_rule = rule

        # 3. Render the conversational system + user prompts. v3 carries the
        #    <audience> block driven by the resolved tier; v2 ignores it.
        system_prompt, user_message = render_conversational_prompt(
            description=transcript,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
            metadata=session.metadata,
            version=self.conversational_prompt_version,
            tier=resolved_tier,
        )

        # 3. Build the messages array: fresh system + prior history (already
        #    bounded by the sliding window) + current user.
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(session.history.to_messages())
        messages.append({"role": "user", "content": user_message})

        log.info(
            "estimation_conversational_request",
            session_id=session.session_id,
            history_messages=len(session.history.messages),
            metadata_is_empty=session.metadata.is_empty(),
            transcript_chars=len(transcript),
        )

        # 4. LLM call with Instructor + Pydantic validators.
        result, meta = self.llm_wrapper.complete_structured_chat(
            messages=messages,
            response_model=EstimationResult,
        )
        log.info(
            "estimation_conversational_generated",
            session_id=session.session_id,
            confidence_pct=result.confidence_pct,
            total_cost_eur=result.total_cost_eur,
            phases=len(result.phases),
            **meta,
        )

        # 5. Output guardrail (filter policy: normalises low-confidence answers).
        result = enforce_scope_response(result)

        # 6. Append the turn to the history. The append is a pure data
        #    operation now — compression (anchor promotion + cumulative
        #    summary + sliding window) is the next, explicit step.
        session.history.append(user=user_message, assistant=result.model_dump_json())
        # Capture turn_index BEFORE compression: post-compression the sliding
        # window plateaus at ``max_turns`` and ``len(messages) // 2`` would
        # stop reflecting how many turns the session has actually seen.
        turn_index = len(session.history.messages) // 2
        apply_compression(
            session.history,
            llm_wrapper=self.llm_wrapper,
            compression_model=self._compression_model(),
            anchor_detection_mode=self.anchor_detection_mode,
        )

        # 7. Second-pass extractor refreshes ProjectMetadata. Failure is
        #    swallowed inside update_metadata (returns previous unchanged).
        session.metadata = update_metadata(
            previous=session.metadata,
            transcript=transcript,
            result=result,
            llm_wrapper=self.llm_wrapper,
            model=self._metadata_model(),
        )

        # 8. Emit the unified per-turn observation. Single structured event
        #    (rather than five log lines) makes the stress runner trivial: it
        #    reads ``response.observation`` straight from the JSON and never
        #    has to reconcile timestamps. ``cache_hit_kind`` is "none"
        #    because the conversational path bypasses both caches by design.
        observation = TurnObservation(
            turn_index=max(1, turn_index),
            session_id=session.session_id,
            enriched_transcript_chars=len(transcript),
            attachments_total_chars=attachments_total_chars,
            messages_in_window=len(session.history.messages),
            anchors_count=len(session.history.anchors),
            summary_chars=len(session.history.summary or ""),
            tokens_in=int(meta.get("tokens_in", 0) or 0),
            tokens_out=int(meta.get("tokens_out", 0) or 0),
            cost_usd=float(meta.get("cost_usd", 0.0) or 0.0),
            latency_ms=int(meta.get("latency_ms", 0) or 0),
            cache_hit_kind="none",
            last_resolved_tier=session.last_resolved_tier,
        )
        log.info("turn_observed", **observation.model_dump())

        return EstimationResponse(
            result=result,
            prompt_version=self.conversational_prompt_version,
            cached=False,
            observation=observation,
        )

    def estimate_with_acb(
        self,
        *,
        session: Session,
        transcript: str,
        project_type: ProjectType,
        detail_level: DetailLevel,
        output_format: OutputFormat,
        tier: Tier | None = None,
    ) -> ACBResponse:
        """Actor-Critic-Boss variant of the conversational pipeline.

        The session is updated **only** with the final Boss-approved (or
        Boss-synthesized) result — intermediate actor drafts are throwaway.
        That keeps the conversation state coherent: from the user's point of
        view, the turn produced exactly one assistant message.
        """

        # 1. Input guardrail.
        check_input(transcript, openai_client=self.openai_client)

        # 2. Resolve tier (same as actor path).
        resolved_tier, rule = resolve_tier(
            transcript=transcript,
            metadata=session.metadata,
            override=tier,
        )
        session.last_resolved_tier = resolved_tier.value
        session.last_tier_rule = rule

        log.info(
            "estimation_acb_request",
            session_id=session.session_id,
            tier=resolved_tier.value,
            tier_rule=rule,
            transcript_chars=len(transcript),
        )

        # 3. Build the actor callable. It re-renders the prompt each
        #    iteration so that critic feedback (if any) is woven in. The
        #    output guardrail runs on every actor draft; if a draft is
        #    eventually accepted by the Boss, that same guardrailed result
        #    is the one persisted to the session below.
        def _actor(critic_feedback: CriticFeedback | None) -> EstimationResult:
            system_prompt, user_message = render_conversational_prompt(
                description=transcript,
                project_type=project_type,
                detail_level=detail_level,
                output_format=output_format,
                metadata=session.metadata,
                version=self.conversational_prompt_version,
                tier=resolved_tier,
                critic_feedback=critic_feedback,
            )
            messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
            messages.extend(session.history.to_messages())
            messages.append({"role": "user", "content": user_message})

            draft, meta = self.llm_wrapper.complete_structured_chat(
                messages=messages,
                response_model=EstimationResult,
            )
            log.info(
                "acb_actor_draft",
                with_critic_feedback=critic_feedback is not None,
                issues_in_feedback=(
                    len(critic_feedback.issues) if critic_feedback is not None else 0
                ),
                confidence_pct=draft.confidence_pct,
                total_cost_eur=draft.total_cost_eur,
                **meta,
            )
            return enforce_scope_response(draft)

        # 4. Build the critic callable.
        critic = Critic(llm_wrapper=self.llm_wrapper, model=self._critic_model())

        def _critic(draft: EstimationResult) -> CriticFeedback:
            return critic.review(
                transcript=transcript,
                metadata=session.metadata,
                tier=resolved_tier,
                result=draft,
            )

        # 5. Boss orchestrates.
        boss = Boss(max_iterations=self.boss_max_iterations)
        final_result, trace = boss.run(actor=_actor, critic=_critic)

        # 6. Persist the final result into the session (single turn append).
        session.history.append(user=transcript, assistant=final_result.model_dump_json())
        apply_compression(
            session.history,
            llm_wrapper=self.llm_wrapper,
            compression_model=self._compression_model(),
            anchor_detection_mode=self.anchor_detection_mode,
        )

        # 7. Refresh metadata from the final result.
        session.metadata = update_metadata(
            previous=session.metadata,
            transcript=transcript,
            result=final_result,
            llm_wrapper=self.llm_wrapper,
            model=self._metadata_model(),
        )

        return ACBResponse(
            result=final_result,
            prompt_version=self.conversational_prompt_version,
            cached=False,
            acb=trace,
        )

    # The four stages compose ONLY here, as ARCHITECTURE.md §7 requires: the
    # reformulator, the retriever, the assembler and the generator never import one
    # another. Adding reranking (Session 10) means changing the retriever and this
    # method, and nothing else.
    async def estimate_from_transcript(
        self, transcript: str, idempotency_key: str | None = None
    ) -> EstimateResponse:
        """Full RAG flow: transcript → grounded, cited estimate.

        Input guardrails are deliberately NOT applied here. ``check_input`` runs an
        ``exception`` policy on PII, and a real sales-meeting transcript is full of
        legitimate personal data — names, emails, phone numbers of the people in
        the room. Rejecting those would make the endpoint useless. Pseudonymization
        of anything that reaches the corpus already happens offline, in the
        ingestion pipeline (Session 6); this path never persists the transcript.
        """
        if not all(
            (
                self.query_reformulator,
                self.retriever,
                self.context_assembler,
                self.estimate_generator,
            )
        ):
            raise RagFlowUnavailable("RAG flow is not configured")

        request_id = new_request_id()

        if idempotency_key and self.idempotency_store is not None:
            cached = self.idempotency_store.get(idempotency_key)
            if cached:
                log.info("estimate_idempotent_hit", request_id=request_id, key=idempotency_key)
                response = EstimateResponse.model_validate_json(cached)
                # Keep the original request_id in the payload for traceability, but
                # mark the delivery as cached so the caller knows it did not pay.
                return response.model_copy(update={"cached": True})

        # 1 — Query: transcript → structured query → text worth embedding.
        with log_stage("reformulation", request_id, transcript_chars=len(transcript)) as stage_log:
            reformulation = await asyncio.to_thread(
                self.query_reformulator.reformulate, transcript
            )
            stage_log.info(
                "reformulation.result",
                used_fallback=reformulation.used_fallback,
                search_text_chars=len(reformulation.search_text),
            )

        filters = derive_filters(reformulation.query)

        # 2 — Retrieval: top-K + threshold + structural filters.
        with log_stage(
            "retrieval",
            request_id,
            sectors=filters.sectors,
            top_k=self.rag_top_k,
            distance_threshold=self.rag_distance_threshold,
        ):
            retrieval = await self.retriever.retrieve(
                search_text=reformulation.search_text,
                top_k=self.rag_top_k,
                distance_threshold=self.rag_distance_threshold,
                filters=filters,
            )

        trace = RetrievalTrace(
            chunks_retrieved=len(retrieval.chunks),
            chunks_used=0,
            total_candidates_considered=retrieval.total_candidates_considered,
            best_distance=retrieval.chunks[0].distance if retrieval.chunks else None,
            worst_distance=retrieval.chunks[-1].distance if retrieval.chunks else None,
            filters_applied=filters.model_dump(exclude_none=True),
            used_reformulation_fallback=reformulation.used_fallback,
            search_text=reformulation.search_text,
        )

        # Soft-fail. The generator is never called with an empty context: a model
        # asked to estimate from nothing produces numbers indistinguishable from
        # grounded ones, which is the worst possible failure for this product.
        if retrieval.low_confidence:
            log.warning(
                "estimate_low_confidence_no_context",
                request_id=request_id,
                total_candidates_considered=retrieval.total_candidates_considered,
                distance_threshold=self.rag_distance_threshold,
            )
            return EstimateResponse(
                request_id=request_id,
                estimate=None,
                low_confidence=True,
                needs_manual_review=True,
                review_reason=(
                    "No historical chunk passed the distance threshold "
                    f"({self.rag_distance_threshold}); "
                    f"{retrieval.total_candidates_considered} candidates considered"
                ),
                retrieval=trace,
            )

        # 3 — Augmentation: bounded, delimited context block.
        with log_stage("context_assembly", request_id, chunks=len(retrieval.chunks)) as stage_log:
            context = self.context_assembler.assemble(retrieval.chunks)
            stage_log.info(
                "context_assembly.result", used=len(context.chunks), dropped=context.dropped
            )
        trace.chunks_used = len(context.chunks)

        # 4 — Generation (includes the single citation-repair retry).
        with log_stage("generation", request_id, chunks_in_context=len(context.chunks)):
            outcome = await asyncio.to_thread(
                self.estimate_generator.generate,
                context=context,
                query=reformulation.query,
                search_text=reformulation.search_text,
            )

        # 5 — Validation: the verdict on whether a human must look at this.
        with log_stage(
            "validation", request_id, confidence=outcome.estimate.confidence
        ) as stage_log:
            stage_log.info(
                "validation.result",
                invalid_citations=outcome.invalid_citations,
                warnings=outcome.warnings,
                needs_manual_review=outcome.needs_manual_review,
            )

        response = EstimateResponse(
            request_id=request_id,
            estimate=outcome.estimate,
            low_confidence=outcome.estimate.confidence == "insufficient",
            needs_manual_review=outcome.needs_manual_review,
            review_reason=outcome.review_reason,
            retrieval=trace,
        )

        if idempotency_key and self.idempotency_store is not None:
            self.idempotency_store.set(idempotency_key, response.model_dump_json())

        return response
