"""ConversationService — multi-turn estimation pipeline.

Orchestrates one conversational turn:

    1. Extract text from uploaded attachments (Camino B, local extraction).
    2. Build enriched description (transcript + attachment text).
    3. Run input guardrails on the combined text.
    4. Render the v2 system prompt injecting current ProjectMetadata.
    5. Call the LLM (structured, with full conversation history).
    6. Apply output guardrail.
    7. Run the LLM metadata extractor and merge into ProjectMetadata.
    8. Append the turn to ConversationHistory (with sliding-window eviction).
    9. Return the ConversationEstimateResponse.

This service intentionally does NOT use the exact-match or semantic caches
from EstimationService because each conversational turn is contextually unique
(the history changes the meaning of identical descriptions across sessions).
"""

from __future__ import annotations

from typing import Any

import structlog

from app.attachments import ExtractionResult, build_enriched_description
from app.guardrails.input import InputGuardrailViolation, check_input
from app.guardrails.output import enforce_scope_response
from app.prompts import render_estimation_prompt_with_metadata, render_metadata_prompt
from app.schemas.conversation import ConversationEstimateResponse
from app.schemas.estimation import EstimationRequest, EstimationResult
from app.sessions import ProjectMetadata, Session
from app.services.llm_wrapper import LLMWrapper

log = structlog.get_logger()


def _compact_assistant_message(result: EstimationResult) -> str:
    """Build a short assistant turn representation stored in ConversationHistory.

    We store only the summary and headline numbers rather than the full JSON so
    the history stays token-efficient while preserving enough context for the
    model to stay coherent across turns.
    """
    phases_summary = ", ".join(
        f"{p.name} ({p.duration_weeks}w, {p.cost_eur} EUR)" for p in result.phases
    )
    return (
        f"{result.summary}\n\n"
        f"Total: {result.total_cost_eur} EUR over {result.total_duration_weeks} weeks "
        f"(confidence {result.confidence_pct}%).\n"
        f"Phases: {phases_summary}."
    )


class ConversationService:
    """Orchestrates one multi-turn estimation request."""

    def __init__(self, *, llm_wrapper: LLMWrapper, openai_client: Any | None = None) -> None:
        self.llm_wrapper = llm_wrapper
        self.openai_client = openai_client

    def estimate(
        self,
        session: Session,
        request: EstimationRequest,
        attachments: list[ExtractionResult],
    ) -> ConversationEstimateResponse:
        """Run a single conversational turn and return the updated response.

        Mutates ``session.history`` and ``session.project_metadata`` in place.
        """
        # 1–2. Build enriched description.
        enriched_description = build_enriched_description(
            request.description, attachments
        )
        log.info(
            "conversation_turn_started",
            session_id=session.session_id,
            turn=session.history.turn_count + 1,
            description_chars=len(enriched_description),
            attachments=len(attachments),
        )

        # 3. Input guardrails on the combined text.
        check_input(enriched_description, openai_client=self.openai_client)

        # 4. Render v2 prompt with current ProjectMetadata.
        enriched_request = EstimationRequest(
            description=enriched_description,
            project_type=request.project_type,
            detail_level=request.detail_level,
            output_format=request.output_format,
        )
        system_prompt, user_message = render_estimation_prompt_with_metadata(
            enriched_request, session.project_metadata
        )

        # 5. LLM call with full conversation history (no cache for conv. turns).
        result, meta = self.llm_wrapper.complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            history=session.history.to_messages_list(),
            response_model=EstimationResult,
        )
        log.info(
            "conversation_estimation_generated",
            session_id=session.session_id,
            confidence_pct=result.confidence_pct,
            total_cost_eur=result.total_cost_eur,
            phases=len(result.phases),
            **meta,
        )

        # 6. Output guardrail.
        result = enforce_scope_response(result)

        # 7. LLM metadata extractor — update ProjectMetadata from this turn.
        updated_metadata = self._extract_and_merge_metadata(
            user_message=enriched_description,
            current_metadata=session.project_metadata,
        )
        session.project_metadata = updated_metadata

        # 8. Append turn to history (sliding window applied inside append).
        assistant_content = _compact_assistant_message(result)
        session.history.append(
            user_content=enriched_description,
            assistant_content=assistant_content,
        )

        log.info(
            "conversation_turn_completed",
            session_id=session.session_id,
            turn=session.history.turn_count,
            history_pairs=session.history.turn_count,
        )

        # 9. Return.
        return ConversationEstimateResponse(
            result=result,
            prompt_version="v2",
            cached=False,
            project_metadata=updated_metadata,
            turn=session.history.turn_count,
        )

    def _extract_and_merge_metadata(
        self,
        *,
        user_message: str,
        current_metadata: ProjectMetadata,
    ) -> ProjectMetadata:
        """Run the LLM metadata extractor and merge results into current_metadata."""
        system_prompt, user_prompt = render_metadata_prompt(user_message)
        try:
            extracted, _ = self.llm_wrapper.complete_structured(
                system_prompt=system_prompt,
                user_message=user_prompt,
                response_model=ProjectMetadata,
                max_tokens=512,
                max_retries=3,
            )
        except Exception as exc:  # noqa: BLE001 — extraction failure is non-fatal
            log.warning(
                "metadata_extraction_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return current_metadata

        merged = current_metadata.merge(extracted)
        log.info(
            "metadata_extracted_and_merged",
            project_name=merged.project_name,
            technologies=merged.mentioned_technologies,
            constraints=len(merged.explicit_constraints),
        )
        return merged
