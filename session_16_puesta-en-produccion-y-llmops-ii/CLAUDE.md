# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

The AI service for the Master en AI Engineering programme:

- `estimator/` — FastAPI service. The AI side: prompts, LLM calls, structured output, guardrails, semantic cache. All AI logic lives here; the rest of the programme evolves this codebase module by module.

The business frontend/client lives in `business-backend/` as of Session 15: a Next.js app that is both the UI and the BFF, and the only public entry point of the system. The live sessions invoke the AI service directly via httpie/curl (stack-agnostic), from inside the Compose network.

There is ONE `docker-compose.yml`, at the root of the session folder, and it defines every service: `business-backend` (the only one publishing a port, `3000:3000`), `business-migrate`, `ai-service`, `estimator-postgres` and `redis`. `business-migrate` is a one-shot off the `builder` stage that applies the Prisma schema and exits 0; `business-backend` waits on it with `condition: service_completed_successfully`, which is why the Prisma CLI does not ship in the runtime image. Run it from that directory, always — Compose derives the project name, and therefore the volume names, from where it is launched, so starting from a subdirectory would create a second, empty corpus.

**The frontier is not negotiable**: only `business-backend` publishes a port. The AI service custodies the LLM key and sits below the business rules, so it is reachable only from inside the network, by service name (`http://ai-service:8000`) and, on everything the BFF calls, with the `X-API-Key` shared secret. Two barriers, not one: the network keeps the service unreachable from outside, and the key keeps it unusable by whatever else happens to run inside. `ESTIMATE_API_KEY` now guards the estimation routes (`/api/v1/estimate` and the graph's start/resume/state), `/sessions/*` (the conversation — it spends provider tokens), `/embeddings/*` (ingest WRITES to the corpus; compare can call paid models) and `/api/v1/config/*` (the most powerful surface there is: whoever writes here picks the model everything else runs on). `/api/v1/ingestion/*` shares that key — it launches offline pipeline runs that WRITE to the corpus, same as `/embeddings/ingest`. `RETRIEVAL_API_KEY` guards the retrieval routes and, since Session 15, the Session 8 `POST /search` too: giving the legacy route a different key from the route that supersedes it would have been incoherent. **The only thing still open is `/health`**, and on purpose — closing it would kill the Docker healthcheck and with it Compose's ordered startup. The datastores are private for the same reason — which is why `estimator-postgres` no longer publishes 5433 and `redis` no longer publishes 6379.

Session guides for the instructor live in `guides/` (git-ignored). `guides/session-4-live-guide.md` is the most recent.

The port is complete bar one piece, and that piece is named where it belongs, in
the frontend's own "Limitaciones conocidas": **the chunking lab does not persist
its runs**, which is what the reference app's history exists for — the four paid
strategies cost money and take minutes. It needs a table and two routes, and zero
Python. The other gap is not a gap but a product decision, documented in the same
place: **the reference app's SECOND human gate**. Our three triggers (confidence,
historical band, no precedent) are all computed AFTER estimating; before it there
is nothing to test, so a second gate would mean inventing the criterion — and
"always pause" destroys the signal, because a reviewer who is sent everything
starts approving in bulk.

## Common commands (estimator)

Dependency / runtime management uses **uv** (Astral) and Python 3.11.

```bash
cd estimator

# Run the API locally with hot reload
uv run uvicorn app.main:app --reload

# Tests
uv run pytest -v
uv run pytest tests/test_schemas.py::test_total_cost_is_derived_from_phases -v

# Lint
uv run ruff check .
uv run ruff format .

# Docker: from the SESSION FOLDER root, not from here — there is no
# estimator/docker-compose.yml any more, and the image carries the code COPIED
# in, with no bind-mount and no --reload. Touching app/ means rebuilding.
cd .. && docker compose up --build
```

Service listens on `http://localhost:8000`; `/docs` (Swagger) and `/redoc` are enabled. Health probe at `GET /health`. Main API endpoints: `POST /api/v1/estimate` (S04 CAG estimate) and, from S09, `POST /v1/retrieval/search` + `POST /v1/estimate/from-transcript` (RAG retrieval + grounded estimate; see the Session 9 design point below).

## Architecture (layered: foundation / domain / generation / api)

The estimator is organized around the **three AI architectures it stacks** — CAG (caches), RAG
(retrieval) and Agentic (Actor-Critic-Boss) — which **compose only through a single conductor**.
Full contract in **`estimator/ARCHITECTURE.md`** — respect it for all new session code.

`app/` layers (each may import only from layers above it):

```
app/
├── config.py · dependencies.py · main.py   # composition root, above the layers
├── foundation/   llm · prompts · guardrails · attachments · persistence  (no AI-arch opinion)
├── domain/       schemas/ (the contract) + estimation_service.py (the conductor)
├── generation/   cag/ · rag/ · agentic/ · conversation/   (the 3 architectures + substrate)
├── ingestion/    offline batch pipeline that feeds RAG
└── api/          thin routers (transport)
```

Five-layer request pipeline. Free-text in, validated structured JSON out:

```
POST /api/v1/estimate
  └→ app/api/estimations.py    (thin HTTP layer, error mapping)
       └→ app/domain/estimation_service.py::EstimationService.estimate()
            1. app/foundation/guardrails/input.py::check_input()      (moderation + injection + PII)
            2. app/generation/cag/exact.py::EstimationCache.get()     (exact-match SHA-256)
            3. app/generation/cag/semantic.py::EstimationSemanticCache.lookup()
                                                                (redisvl vector similarity)
            4. app/foundation/prompts/loader.py::render_estimation_prompt()  (Jinja2 versioned)
            5. app/foundation/llm/wrapper.py::complete_structured()
                                                                (Instructor + Pydantic validators
                                                                 with automatic re-prompt)
            6. app/foundation/guardrails/output.py::enforce_scope_response() (filter policy)
            7. cache.set() + semantic_cache.store()
            8. return EstimationResponse(result, prompt_version, cached)
```

**Layering rules** (see `estimator/ARCHITECTURE.md` for the full table):
- `foundation/` imports only `config`. `domain/schemas` imports `foundation`. `generation/<x>`
  imports `foundation` + `domain/schemas` but **never another `generation` sibling** (the one
  exception: `agentic` may import `conversation`).
- The `generation` siblings (cag/rag/agentic) meet **only** inside the conductor
  (`domain/estimation_service.py`). New cross-layer composition goes there, never in a router
  and never via a sibling import.
- `api/` is transport only (error mapping); `dependencies.py` is the composition root that wires
  every singleton and is allowed to import anything.

Key design points future changes should respect:

- **The router has no business logic.** It only catches three exceptions and turns them into HTTP statuses: `InputGuardrailViolation` → 400, anything else from the pipeline (including `instructor.exceptions.InstructorRetryException`) → 502, plus Pydantic 422 from `EstimationRequest` validation. Since Session 15 it also carries `dependencies=[Depends(require_estimate_key)]`, so 401 joins the list — still not business logic: the dependency is declarative and `/health` stays open. Add new policies inside `EstimationService.estimate()`, not in the router.
- **Schema is the contract.** `EstimationResult` (in `app/domain/schemas/estimation.py`) is what Instructor enforces against the LLM. One `model_validator` is left, `low_confidence_requires_out_of_scope_prefix` — when it raises, Instructor re-prompts the LLM. `phases_sum_matches_total` is GONE, and with it the whole failure mode: `total_cost_eur` is now a `@computed_field` over `phases`, so the identity holds by construction. Instructor's `Mode.TOOLS` does not put computed fields in the tool schema, so the model never sees the total, cannot get it wrong, and cannot be re-prompted about it; it still travels in the JSON the API serialises.
- **Field order matters with Instructor.** `phases` is declared BEFORE `total_duration_weeks` on purpose: the LLM emits phases first (autoregressive) and then only needs to sum, instead of picking a round total and back-fitting phases. It no longer applies to `total_cost_eur`, which is not asked for at all — field order used to be the defence against `gpt-4o-mini`'s arithmetic, and deriving the total replaced it with something the model cannot break.
- **Two caches in series.** Both live in the CAG layer (`app/generation/cag/`). The exact-match cache (`app/generation/cag/exact.py`) keys on SHA-256 of the typed request + prompt_version + model. The semantic cache (`app/generation/cag/semantic.py`) layers on top: same bucket (`prompt_version:project_type:detail_level:output_format`) + cosine similarity ≥ `SEMANTIC_CACHE_THRESHOLD` (default 0.85). The semantic cache requires Redis Stack (`redis/redis-stack-server:7.4.0-v0`), not vanilla Redis — RediSearch is mandatory for vector queries.
- **Guardrails are policies, not features.** `check_input` uses `exception` policy (raise on violation). `enforce_scope_response` uses `filter` (rewrite the summary). The schema validators use `re-prompt` (Instructor handles it). The split is documented in the live-session guide.
- **The model catalogue is hand-curated, and says so.** `AVAILABLE_MODELS`
  (`app/config.py`) is a hand-written list kept in lockstep with `MODEL_COSTS`
  (`app/foundation/llm/wrapper.py`): a model selectable without a price row is
  billed at zero, and `_estimate_cost` defaults to zero silently. It is NOT
  everything the API keys can reach — the keys reach far more — and the endpoint's
  filter only checks that the provider's key is non-empty, never that the key can
  actually serve that model. Because nothing refreshes it, the catalogue carries
  its own provenance (`MODEL_CATALOG_GENERATED_AT` / `MODEL_CATALOG_SOURCES`),
  surfaced verbatim on the Settings screen. Regenerating it is an explicit,
  human-initiated task: query each provider's `GET /v1/models` with the real keys,
  price every entry against the provider's published pricing page (standard tier —
  fast-mode figures are roughly double and circulate widely), and update both lists
  plus the timestamp together. `GET /api/v1/config/models` also serves
  `model_prices` (USD per million tokens, input/output) so the Settings picker can
  show what a knob costs; the catalogue spans 0.05 to 600, and several knobs run on
  every turn.
  **The silent trap is the provider inference.** `_provider_from_model` reads the
  name: `gpt…` and `claude…` by prefix, the o-series by shape (`^o\d`). Anything
  else returns "unknown", "unknown" has no entry in `PROVIDER_KEY_FIELDS`, and
  `_available_models` therefore drops the model from the catalogue with no error
  anywhere. `o4-mini` was doing exactly that until Session 15. A Gemini model added
  to the list would vanish the same way.
- **Cost that reads as zero is a bug, twice over.** The price table is one half;
  the other is the usage reading. `complete_structured_chat` shipped without the
  `**_usage_from(...)` its single-shot sibling has, and `estimation_service` read
  flat `tokens_in`/`tokens_out` keys off `meta` when `_usage_from` nests them under
  `usage`. Either one alone was enough to make `TurnObservation` report 0 tokens
  and $0 for every conversational turn — with the defensive `or 0` turning a
  missing key into a number. Both fixed in Session 15; the lesson is the one in
  `_usage_from`'s own comment: a cost of zero is worse than no cost at all,
  because a dashboard will believe it.
- **Settings are a cached singleton** via `app/config.py::get_settings` (`@lru_cache`). Any change to `.env` requires recreating the container (`docker compose up -d --force-recreate`); a `--reload` is not enough. **Exception: the LLM model knobs** (`PRIMARY_MODEL`, `FALLBACK_MODEL`, `CRITIC_MODEL`, metadata/compression/chunker models) can be overridden at runtime via `PUT /api/v1/config/models` (Redis-backed `app/foundation/llm/runtime_config.py`) — overrides survive `--reload` and restarts, and both caches partition by model.
- **Logging** is `structlog`. JSON in `production`, console in dev (chosen by `APP_ENV`). Use `structlog.get_logger()` rather than stdlib `logging`. **`LOG_LEVEL` filters, and only since Session 15**: `configure_logging` passed `structlog.stdlib.BoundLogger` as the `wrapper_class`, and `add_log_level` only LABELS the level on the event — it discards nothing. So the knob existed, was typed, reached the container through `env_file`, and did nothing: the service emitted all 181 of its events at any setting, and a production deployment on JSON output had no way to quieten them. It is now `make_filtering_bound_logger(logging.getLevelName(settings.LOG_LEVEL))`, and `tests/test_logging_level.py` pins it — a disconnected knob is not visible on screen, it is visible in the log bill three months later.
- **Three Session 2/3 settings were removed in Session 15 because nothing read them.** `LLM_PROVIDER` and `LLM_MODEL` were superseded long ago — the provider is INFERRED from the model name (`_provider_from_model`) and the model comes from `PRIMARY_MODEL`, the per-stage knobs or the runtime override — and `ESTIMATOR_API_BASE_URL` as a *Settings field* was never read by anything in the repo's history (the env var survives: `streamlit_app.py` reads it straight from the environment with `os.getenv`, and Streamlit is a dev dependency that never ships in the image). The two `Literal` ones were not inert, which is why they were worth removing rather than leaving: nobody consulted their value, but pydantic still validated it, so `LLM_PROVIDER=gemini` — or, after a careless edit, `LLM_PROVIDER=` — raised `ValidationError` and the service would not start. Their only live effect was the ability to break the boot. `Settings` carries `extra="ignore"`, so a `.env` that still holds those lines is silently ignored.
- **The LLM wrapper bypasses the Router for streaming and for structured calls** (see `_dispatch`). LiteLLM's Router does round-robin between deployments, which would non-deterministically route to a fallback that may be unreachable. For deterministic behaviour `complete_structured` always uses the primary model directly.
- **Session 9 closes the transcript → estimate loop (RAG generation).** A second, RAG-native estimate path lives entirely in `app/generation/rag/` and is exposed by two independently-secured routers in `app/api/routers/`:
  - `POST /v1/retrieval/search` (auth `RETRIEVAL_API_KEY`, 120/min) — metadata-filtered k-NN with a relevance threshold + soft-fail. It supersedes the unauthenticated Session 8 `POST /search`, which stays only for backwards compatibility (Chunking Lab / S08 demos).
  - `POST /v1/estimate/from-transcript` (auth `ESTIMATE_API_KEY`, 10/min, idempotent on `idempotency_key`) — runs `estimate_from_transcript`: `reformulate_query` → `compose_search_text` + embed → `search_chunks` (soft-fail short-circuits to `confidence="insufficient"`) → `truncate_to_token_budget` → `build_context_block` (XML `<source>` delimiters) → `generate_estimate` → `validate_citations` (one corrective retry on fabricated ids) → coherence check.
  This path **reuses `LLMWrapper`** (Instructor + LiteLLM) for both reformulation (`REFORMULATION_MODEL`, default `gpt-5-mini`) and generation (`GENERATION_MODEL`, default `gpt-5`, `reasoning_effort="high"`, `max_tokens=GENERATION_MAX_TOKENS` default 64000 — reasoning tokens count against the budget) — NOT the raw OpenAI Responses API. It emits the hours-based `Estimate` schema: a nested `modules` → `tasks` breakdown (`WorkModule`/`TaskItem`, each task with `engineer_days` + `sources`) plus `total_engineer_days` and mandatory `SourceCitation`s + `Assumption`s — distinct from and coexisting with the Session 4 euro/weeks `EstimationResult`. The engineer-day numbers are **LLM-inferred**, grounded in the historical `estimated_hours` the model reads from the retrieved `<source>` chunk text (the retriever does no numeric aggregation). To ground the *task-granular* breakdown there is an optional task-level corpus: `scripts/build_task_corpus.py` deterministically synthesises projects decomposed into modules→tasks (each task = a `BudgetComponent` carrying the new optional `module` field, surfaced by the structural chunker), writes `data/task_corpus.json`, and `--ingest`s it via `/embeddings/ingest` tagged `document_type='historical_task_breakdown'` / `chunk_type='historical_task'` (filterable; `IngestRequest.chunk_type` defaults to `budget_component`, so S08 ingest is unchanged). The default corpus is **60 projects / ~1.5k tasks** across **eight sectors** (`finance`, `ecommerce`, `healthcare`, `industrial`, `logistics`, `education`, `media`, `government` — the `Sector` literal in `app/generation/rag/schemas.py`) with a broad module catalog, so the Session 10 per-task hours search (`POST /v1/estimate/tasks/hours`, weighted-consensus over the nearest historical tasks) has many analogs to match; `--count`/`--seed` tune it. It coexists with the base corpus; wipe with `DELETE FROM documents WHERE document_type='historical_task_breakdown'`. A teaching-only set of per-stage endpoints (`POST /v1/estimate/stages/{reformulate,retrieve,assemble,generate,structure}`, `app/api/routers/estimate_stages.py`) exposes each pipeline step, reusing the same pure functions. **Session 10 reshaped the client wizard flow**: it no longer retrieves/augments before generation — the structure is a FREE LLM decomposition of the reformulated brief via `POST /v1/estimate/stages/structure` (`generate_structure` + `build_structure_system_prompt`, no `<sources>`, no citations, `engineer_days` null), grounding the *structure* in retrieved budgets impoverished the tree. Retrieval re-enters **per task** in `POST /v1/estimate/tasks/hours` (`app/generation/rag/task_hours.py`): each reviewed task is searched via `retrieve()` (hybrid + cross-encoder reranking, per the runtime `RERANKER_ENABLED`) filtered to `chunk_type='historical_task'`, and the hours come from a distance-weighted **consensus** of the nearest neighbours with a reliability score (no match under `TASK_HOURS_DISTANCE_THRESHOLD` → no hours, flagged red). The wizard steps are now `transcript → reformulation → generation(structure) → review → hours → verification`; `from-transcript` (grounded, hours inline) and `/stages/generate` stay as the Session 9 comparison path. Cross-cutting: per-API-key rate limiting (`app/api/rate_limiting.py`, slowapi), constant-time key checks (`app/api/security.py`, `secrets.compare_digest`), idempotency store (`app/generation/rag/idempotency.py`, Redis or in-process fallback), and an `X-Request-ID` correlation header set by middleware in `app/main.py` (per-stage logs via `log_stage`).

- **Session 10 adds advanced retrieval (multi-index, routing, expansion, decay).** The corpus is partitioned into **three chunk tables** — `budget_chunks` (the Session 8 `chunks` table, renamed in migration `0004_session10_multi_index`), `transcript_chunks` and `technical_doc_chunks` — sharing the `_ChunkColumns` ORM mixin but each with its own JSONB metadata schema (Article 5 "Opción B": schemas that diverge → separate tables). `ChunkRow` stays an alias of `BudgetChunkRow` so Session 8/9 imports are unaffected; `ChunkStore` search/persist methods take a `model=` (default `BudgetChunkRow`). The whole advanced layer lives under `app/generation/rag/retrieval/`: `collections.py` (the `Collection` StrEnum + registry: per-collection model, date accessor, rule patterns, hard-filter clauses), `router.py` (cascade routing: explicit collection → deterministic vocab rules → LLM classifier with structured 1–3 targets + reason → fallback-to-all), `query_transform.py` (expansion vs decomposition chosen by a length/connectors heuristic, ≤4 sub-queries via structured output), `fusion.py` (`reciprocal_rank_fusion` for expansion consensus + `round_robin_merge` for decomposition coverage, deduped by `(collection, id)` since ids only collide-free within a table), `temporal.py` (exponential decay, applied LAST on a non-negative base — reranker logits are sigmoid'd first), and `advanced_pipeline.py` (the conductor: query transform → routing → hard filters → hybrid search → differentiated fusion → rerank → temporal decay → top-k, every stage gated by a `StageConfig`). It is exposed by `POST /v1/retrieval/advanced-search` (`app/api/routers/retrieval_advanced.py`, auth `RETRIEVAL_API_KEY`, 120/min) whose response surfaces the routing decision, technique, sub-queries and per-collection cardinality. **The Session 9 `POST /v1/retrieval/search` and the estimate path are untouched** (`retrieve()` keeps its single-collection contract; it just gained a `collection=` default of budget). Stage toggles flip at runtime via `RuntimeRetrievalConfig` → `PUT /api/v1/config/retrieval`. New sample collections: `data/transcripts_sample.json` + `data/technical_docs_sample.json`, seeded by `scripts/build_multi_index_corpus.py` (run inside the container); the harness `scripts/eval_retrieval_s10.py` runs named `StageConfig`s (data, not code branches) against the extended multi-collection golden set. **tsvector config stays `english`** everywhere (the shipped corpus is English; see migration 0003) and **all advanced LLM calls reuse `LLMWrapper`** (Instructor), NOT the raw Responses API — flagged because the articles taught `responses.parse`.

- **Session 11 moves citation from the estimate down to the LINE, and adds the RAGAS harness.** `TaskItem` (the line) now carries `sources: list[SourceReference]` — `chunk_id` (the `id` attribute of its `<source>`), `document_id` and the VERBATIM `evidence` span — plus a mandatory `grounded` flag, declared BEFORE `engineer_days` so the model commits to its evidence before it commits to a figure. `document_id` is resolved server-side from the retrieved chunk, never asked of the model: it is derivable from `chunk_id`, so asking for it would only add a surface to hallucinate on (this is why `context_assembler` is unchanged). `app/generation/rag/validation.py` splits reporting from policy: `verify_citations()` returns a `CitationReport` classifying every line as `grounded`/`dangling`/`insufficient` and changes nothing, while `enforce_citation_policy()` resolves document ids, prunes citations that do not resolve, demotes the lines left without backing to `grounded=False` with null hours, re-derives `total_engineer_days` from what survived, and collapses the whole estimate to the canonical insufficient shape when no line survives. The Session 9 `validate_citations()` is gone: both of its callers read `report.dangling_source_ids`, the same set with the per-line verdict attached. The integrity rule is a post-generation check, NOT a Pydantic validator, on purpose: a validator makes Instructor re-prompt silently up to six times inside `complete_structured`, which is the opposite of the requirement to *log* the outcome. `estimate_from_transcript` verifies → retries once on fabricated ids → logs `citation_report` (via `observability.log_citation_report`, correlated by `request_id`) → enforces; the coherence-repair branch re-enforces because it is a fresh generation. `POST /v1/estimate/stages/generate` reports (`GenerateResult.citation_report`) but does NOT enforce — it is the teaching aid that surfaces raw model output; `/stages/structure` leaves the report `None`. Evaluation: `evals/golden_retrieval.json` gains a `ground_truth` on Q1–Q5 (Q6–Q8 stay retrieval-only: they are cross-collection QA, not estimation requests) and `scripts/eval_ragas_s11.py` scores faithfulness / answer_relevancy / context_precision / context_recall on the host. **Two RAGAS traps**: `ragas` 0.4.3 hard-imports `langchain_community.chat_models.vertexai`, so the dev group pins `langchain-community<0.4`; and `evaluate()` rejects the newer `ragas.metrics.collections` classes, so the harness pairs the modern `EvaluationDataset`/`SingleTurnSample` schema with the classic metric objects.

- **Session 12 adds a hand-written agentic layer (manual Responses API loop).** Where the S9-S11 estimate path is a FIXED pipeline (reformulate → retrieve → generate), the agent DECIDES at each step how many budget searches to run and in what order — the shape a transcript needs when it mixes unrelated components (business backend + ERP integration + mobile app + analytics). It lives in `app/generation/agentic/` beside the untouched S4 ACB files (`boss.py`/`critic.py`): `agent_schemas.py` (tool args + `AgentStep`/`AgentTrace` with `render()` + the LIGHT result `AgentEstimate`, deliberately not the heavy RAG `Estimate`), `agent_tools.py` (three FLAT Responses tool schemas with `strict:true` — `search_budgets`, `calculate_estimate`, `validate_estimate` — plus impls and `dispatch_tool`), and `agent_loop.py` (`run_estimation_agent`). **This is the one deliberate exception to the "everything goes through `LLMWrapper`" rule** — the agent drives `client.responses.create`/`.parse` by hand, because seeing the loop IS the exercise (do NOT "fix" it). Loop mechanics: stateful chaining (`store=True` + `previous_response_id`, sending only the new `function_call_output` items, so the server keeps reasoning-item ordering); `instructions` are re-sent on every call because they do NOT travel with `previous_response_id`; `reasoning={"effort":…,"summary":"auto"}` feeds the trace; tool errors are returned as the tool output so the model self-corrects instead of crashing the loop; on `max_iterations` the loop does NOT solicit a turn it cannot answer — the pending outputs ride along with the closing `responses.parse`, because chaining onto an unanswered `function_call` is rejected by the API. `search_budgets` reaches retrieval through an INJECTED backend (`dependencies.get_budget_search_backend()`), never an import: ARCHITECTURE.md §3 forbids `agentic` importing `rag`, and the same seam is what `--stub` swaps for the kit's canned corpus. **That backend searches TASKS and answers with MODULES**: the corpus is one chunk per task (17-47h) but the agent estimates subsystems, so each distinct (project, module) behind the hits is returned once, priced at the sum of all its tasks — feeding raw task hours to a median prices an ERP integration at ~30h, and a live gpt-5 run correctly refused to use numbers that small. Run it with `scripts/run_agent_s12.py` (`--model`/`--effort`/`--max-iterations`/`--stub`/`--out`). Its delivered trace and review notes live on the `session_12_*` branch, not here; what survives in `exercises/session-12/` is what Session 13 still uses: the two transcripts and the offline retrieval stub that `--stub` loads by path. No HTTP endpoint or UI this session. Tests are network-free (`tests/generation/agentic/`, a scripted fake `AsyncOpenAI`).

- **Session 13 re-expressed the estimate flow as an explicit LangGraph, and Session 14 took the control flow away from the edges.** The S13 shape (typed shared state, one responsibility per node, a checkpoint after every step, a span per node) is still the substrate; what changed is who decides the order. There is no linear topology any more: `START → supervisor`, and **every other transition lives inside a `Command`**, so the path is chosen at runtime and only exists afterwards, in `routing_trail`. It lives in `app/domain/graph/` — the CONDUCTOR level, the layer allowed to compose `generation` siblings — as `state.py` (`EstimationState`, `total=False`; `budget_matches`, `errors`, `proposals` and `routing_trail` are `Annotated[..., operator.add]` accumulators), `digest.py`, `supervisor.py`, `agents.py`, `hitl.py`, `band.py`, `llm.py`, `schemas.py`, `build.py`, `checkpointer.py`, `observability.py`.

  **Topology.** `supervisor` routes; `requirements_extractor` (no business tools) turns the transcript into requirements + components; `budget_searcher` (`search_budgets`) finds analogues one component at a time; `estimate_generator` (`calculate_estimate`) prices them; `coherence_validator` (`validate_estimate`) produces the confidence signal; `human_review_gate` pauses; `finalize` is the single writer of `status`. The supervisor is **hybrid**: the four preconditions are plain `if`s, and the model is asked exactly one question — the validator flagged thin evidence, so search again or hand it to a human? `MAX_ROUTING_STEPS` is the real ceiling and `GRAPH_RECURSION_LIMIT` only the net, because LangGraph counts recursion **per invoke** and a run that pauses gets a fresh budget on every resume.

  **Three traps this session paid for, all verified against langgraph 1.0.1.** (1) The supervisor's preconditions read *who has already acted* (from `routing_trail`), never *which output field is empty*: "the searcher has not run" and "the searcher found nothing" are different facts, and reading `budget_matches` makes a transcript with no precedent bounce until the routing budget dies — never reaching the gate, which is exactly where it belongs. (2) `Command` and `Literal` are imported at MODULE level in every file that defines a node: LangGraph resolves the `Command[Literal[...]]` return annotation against the function's own `__globals__`, and under `from __future__ import annotations` a `TYPE_CHECKING` import silently loses it, taking the mermaid diagram and the compile-time unknown-target check with it. A `goto` to a node that does not exist does NOT raise — it logs "wrote to unknown channel" and the run ends looking finished. (3) `interrupt()` re-runs the whole node body on resume and discards what the interrupted pass wrote, so `human_review_gate` does nothing but read the state and interrupt, and its `logfire.span` opens AFTER the interrupt (a span wrapping it is closed by the `GraphInterrupt` and exported with `status=ERROR` — a normal pause arriving in the dashboard as a failure).

  **The numbers are the tool's, the prose is the model's.** `estimate_generator` asks `calculate_estimate` for the hours (median of the references × 1.15 contingency) and the model only for `rationale`/`notes`, so "a model invents a number" is not an available failure mode. The tool is keyed by our own `Component.id`, never by a name the model wrote — matching estimate lines to evidence by model-authored NAME flagged all seven components as unbacked on a real run, and `[c1]` vs `c1` did it again (`_normalise_id`). `confidence` is COMPUTED, not asked for: `0.5·grounded_ratio + 0.3·evidence_density + 0.2·proximity − 0.2·arithmetic_issues`, clamped (and `arithmetic_issues` subtracts the ungrounded lines from the issue count, because the tool emits one issue per unreferenced component and `grounded_ratio` already measures exactly that — counting the whole list penalised every unpriced component TWICE) — a model scoring its own output rates it highly, and the deliverable depends on the pause being reproducible.

  **The human gate.** It fires on any of three signals: confidence below `GRAPH_CONFIDENCE_THRESHOLD`, the estimate outside the historical band (`band.py`; the band is **scaled by coverage**, which is the only reason the trigger is reachable at all — a band built from the same references the tool priced from contains the result by construction), or the searcher having run and found nothing. The `interrupt()` payload is the reviewer's INTERFACE (estimate, confidence, triggers, concerns, the band, the matches), not a log line. `POST /v1/estimate/graph` keeps the S9 contract and gains one VALUE, `status="awaiting_human_review"`, plus `review_payload`; `POST /v1/estimate/graph/{id}/resume` folds `approve`/`adjust`/`reject` into the state and `GET /v1/estimate/graph/{id}/state` reports where a run stands. All three carry `require_estimate_key` + rate limiting. The start verb has **three** branches: finished → replay; **pending interrupt → report, never re-invoke** (an interrupted thread has values AND a non-empty `next`, so the S13 two-branch version restarted it and doubled every accumulator); otherwise → invoke. Resume is idempotent by reading `aget_state` first, so a second reviewer approving the same case is a no-op rather than a second run.

  **Least privilege is enforced, not described** (`app/domain/security/`). `AGENT_TOOL_GRANTS` is data; `@grants(...)` stamps the declared tools onto the node and **returns the same function object** (a wrapper would break LangGraph's annotation lookup); `verify_tool_grants` runs in the `lifespan` BEFORE the checkpointer and raises, so a mis-granted agent fails the deploy rather than degrading into the 503 that means "Postgres is down". Every tool call goes through `execute_guarded` → `guard_action` (privilege, then deterministic argument rules over the three real tools) → `structlog`, with denied actions logged at WARNING and arguments redacted to their shape. `execute_guarded` takes the tool as an ARGUMENT so `domain/security` never imports `generation`.

  **Tests pin the result and the invariants, never the path** (`tests/domain/graph/`, `tests/domain/security/`): an estimate was produced, no agent acted before its precondition, `routing_steps` stayed under the ceiling, the pause fired, the resume left `human_decision` in the state, and the gate spent nothing on the pause. The three S12 tools are used for real in those tests — they are deterministic Python and faking them would test the fake. Run it with `scripts/run_graph_s14.py` (`--memory`/`--stub`/`--decision`/`--out`), which drives BOTH legs inside one parent span: over HTTP the resume is a separate request and OpenTelemetry cannot retro-join two traces. `exercises/session-14/sample_transcript_edge_case.txt` is the transcript designed to trip the pause (computer vision, an ML forecast, embedded firmware and a 3D digital twin — none of which the historical corpus covers). **`exercises/session-15/sample_transcript_mixed.txt` trips it differently, and that difference is the point**: it mixes work the corpus knows (identity and roles, back-office, an ERP integration, notifications) with work it does not (vision on a conveyor, scale firmware, sonar signal processing), so the run pauses with a MIX of grounded and ungrounded lines instead of the degenerate all-ungrounded case. Measured on a real run: 11 components, 8 grounded, confidence **0.594**, and the pause fires on the confidence trigger ALONE — not on "no comparable budget was found". Note what makes it land there: with 73% of lines grounded, `grounded_ratio` and `evidence_density` are healthy and it is `proximity` that sinks it (mean distance ~0.56 against a `_MAX_USEFUL_DISTANCE` of 0.6), which is the corpus saying "I found something, but only just". The three ungrounded components come back at 0 h, which is exactly the state a reviewer has to resolve line by line.

- **Session 15 un-blocks the graph and teaches it to write.** Two pieces rescued from the reference app's S13 wizard — the only two worth having without rebuilding its graph. Porting that wizard faithfully would mean ADDING a second graph rather than changing this one — their repository keeps both sessions' artefacts side by side because teaching S13 and S14 demands it; here the graph evolves, and carrying two contracts, two test suites and a shared checkpointer to namespace is a cost with no return.

  **`POST /v1/estimate/graph/start` answers 202 and runs the graph behind it.** Its sibling `POST /graph` holds the HTTP connection open for the minutes the multi-agent system takes, which leaves no room for a progress feed — there is nothing to poll while the caller is blocked on the answer — and makes every client's read timeout a ceiling on how long an estimation may legitimately take. The three branches are the sibling's, for the same reasons: a finished thread is answered, a paused one is reported, only a new one is launched. It uses FastAPI `BackgroundTasks`, so the work starts after the response is sent. **A crash in there has no response to fail**, so `_run_detached` writes `run_failed: …` into the run's own `errors` channel via `aupdate_state` (which works on a crashed thread, verified against langgraph 1.0.1, and needs no `as_node`). Without that marker a dead run is indistinguishable from a slow one — `next` still names the node that died — and a screen polls it forever.

  **`GET /v1/estimate/graph/{id}/progress` derives the timeline from the checkpoint HISTORY** (`app/domain/graph/progress.py`, pure and testable with no graph). The state has no timestamps at all; the checkpointer has been stamping one per superstep all along. Attributing a snapshot to a node takes one observation: LangGraph's checkpoint metadata carries no `writes` in this version, but every snapshot knows what runs NEXT, so the node named by snapshot N finished when snapshot N+1 was written. That is what makes this feed report **completions with durations**, unlike `routing_trail`, whose entry the supervisor writes BEFORE the specialist runs. Rate limit is the polling one (120/min) so it never shares a budget with the verbs that spend money. Its three honest limits are documented in the module: no intra-agent granularity, per-agent cost/tokens live only as span attributes (`llm.py::stamp_llm`, exported only with `LOGFIRE_TOKEN`), and `GET .../state` still returns the whole transcript so it is not the verb to poll.

  **`POST /v1/estimate/graph/{id}/proposal` drafts the client-facing document** from a finished run (`app/domain/proposal.py`, a conductor beside `estimation_service.py`; prompt in `foundation/prompts/proposal/v1/`, knob `GRAPH_PROPOSAL_MODEL` default `gpt-4o`, reusing `GRAPH_LLM_TIMEOUT`). **A separate verb, never a graph node**: the happy path already spends five of the eight `GRAPH_MAX_ROUTING_STEPS` dispatches, so a node would compete for budget with the work that produces the estimate, teach the supervisor a destination it has no reason to reason about, and stop `finalize` being the single terminal. As a verb over the finished checkpoint it costs zero routing steps and can be redrafted without paying for the estimation again. The reference implementation reached the same conclusion from the other side. `CommercialProposal` carries **no total**: the hours belong to `calculate_estimate` and travel in the estimate, and a second copy can disagree with what it describes — `engineer_days` is computed in Python and handed to the prompt, which forbids deriving any figure. A run still awaiting a reviewer is a 409, not a draft: writing a client document from a figure nobody approved is the accident the check exists for. Nothing is persisted here; which drafts existed and which was sent is business history and lives in the business backend, like `human_decision`.

- **Session 15 draws a line between a default and a piece of infrastructure.** `DATABASE_URL` and `REDIS_URL` lost their defaults and are now REQUIRED: a default that names a host, a port and a set of credentials is the one that produces "works on my machine", and these two had already drifted — both said `localhost:5433` / `localhost:6379`, ports that stopped being published in this very session when the datastores went private, and nobody noticed because Compose overrides them. The old `DATABASE_URL` default also carried `estimator:estimator` in versioned source. The ~70 remaining knobs KEEP their defaults on purpose: requiring seventy environment variables to boot produces copy-pasted `.env` files nobody reads, and for a threshold the default IS the documentation. The rule is the distinction, not the count — **a default is fine for a value that TUNES behaviour, and wrong for one that NAMES infrastructure or identity**.
  Two consequences worth knowing. **`docker-compose.yml` now spells out every interpolation**: the 11 bare `${VAR}` became `${VAR:?…}`. They were already covered, but only transitively — a `:?` anywhere in the file aborts the whole command, even `docker compose up ai-service`, which is verified behaviour — and that coverage was an accident of the file's shape: delete the `business-backend` service and `ESTIMATE_API_KEY: ${AI_SERVICE_TOKEN}` silently becomes an empty string. The `$${POSTGRES_USER}` inside the postgres healthcheck is NOT interpolation (the `$$` escapes it for the container's own shell) and must stay as it is. **And `tests/conftest.py` now sets `DATABASE_URL`, `REDIS_URL` and a fake `OPENAI_API_KEY` before importing the app**, because the suite was never hermetic and it did not show: `litellm/__init__.py` calls `load_dotenv()` on import, so the developer's `.env` landed in `os.environ` as a side effect and the tests that pass `_env_file=None` believing they are isolated were reading the file anyway. The suite now passes with and without a `.env`, which it never did before.

## Configuration

There are TWO `.env` files and they are not the same kind of thing.
`estimator/.env` (copied from `estimator/.env.example`) drives the AI service via
`pydantic-settings`, and everything below documents it. The one at the ROOT of the
session folder is read by Compose itself, by interpolation, and holds what the
services need to find each other: `AI_SERVICE_TOKEN`,
`AI_SERVICE_RETRIEVAL_TOKEN`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
Several are declared `${VAR:?...}`, so `docker compose up` aborts loudly rather
than starting with an empty secret.

Session 2/3 vars:
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — at least one required.
- `PRIMARY_MODEL` / `FALLBACK_MODEL` — LiteLLM Router config.
- `LLM_TIMEOUT` / `LLM_RETRIES` — `LLM_RETRIES` is per call; `LLM_TIMEOUT` is NOT. Instructor turns it into `stop_after_delay(timeout)` over the WHOLE retry chain, so it is a deadline for all attempts together. It has to stay below the client's own timeout (180 s in `business-backend`) or the caller walks away while the service keeps spending. Mind the two defaults: the field in `config.py` says 30, the shipped `.env.example` says 120, and the effective value is whatever `.env` has (120 today). Only a run with no `.env` at all gets the shorter deadline.
- `REDIS_URL` — points to the Redis Stack container in compose.

Session 4 vars:
- `EMBEDDING_MODEL` — defaults to `text-embedding-3-small`.
- `SEMANTIC_CACHE_THRESHOLD` — cosine similarity threshold (0..1). 0.85 default = the typical range mentioned in the live guide. Lower = more hits, more false positives.
- `SEMANTIC_CACHE_TTL` — seconds (24h default).
- `SEMANTIC_CACHE_LOG_ONLY` — when `true`, the cache logs would-be hits but never serves them. Use it to calibrate the threshold against real traffic before flipping on.

Session 9 vars (RAG estimation):
- `RETRIEVAL_API_KEY` / `ESTIMATE_API_KEY` — independent keys (header `X-API-Key`). Blank disables the routes it guards (401 on every request). `RETRIEVAL_API_KEY` covers `/v1/retrieval/search` and `/v1/retrieval/advanced-search`. `ESTIMATE_API_KEY` is the token for EVERY estimation route, including the Session 4 `POST /api/v1/estimate` since Session 15, and the graph's start/resume/state. Under Compose both are fed from the root `.env` (`AI_SERVICE_TOKEN` / `AI_SERVICE_RETRIEVAL_TOKEN`).
- `REFORMULATION_MODEL` / `GENERATION_MODEL` / `GENERATION_REASONING_EFFORT` — default `gpt-5-mini` / `gpt-5` / `medium`. In `AVAILABLE_MODELS`, so switchable at runtime via `PUT /api/v1/config/models`.
- `RETRIEVAL_TOP_K` / `RETRIEVAL_DISTANCE_THRESHOLD` — locked defaults `10` / `0.6` (cosine distance).
- `MAX_CONTEXT_TOKENS` — token budget for the assembled `<source>` block (tiktoken `cl100k_base`; default 16384).
- `IDEMPOTENCY_TTL` — seconds (24h). Idempotency store uses `REDIS_URL` when reachable, else an in-process dict.

Session 10 vars (advanced retrieval):
- `RETRIEVAL_ROUTING_ENABLED` / `QUERY_TRANSFORM_ENABLED` / `TEMPORAL_DECAY_ENABLED` — per-stage toggles (defaults `true`/`true`/`false`). Also flip at runtime via `PUT /api/v1/config/retrieval` (Redis-backed `RuntimeRetrievalConfig`).
- `ROUTER_MODEL` / `QUERY_TRANSFORM_MODEL` — default `gpt-4o-mini` (small, non-reasoning, in `AVAILABLE_MODELS`).
- `TEMPORAL_DECAY_HALF_LIFE_DAYS` — default `900` (≈2.5y; `weight = 0.5 ** (age_days / half_life)`).
- `QUERY_MAX_SUBQUERIES` / `ROUTER_MAX_TARGETS` — caps for expansion/decomposition (`4`) and routing targets (`3`).
- Reuses the S10 pre-work knobs: `RETRIEVAL_SEARCH_MODE`, `RERANKER_ENABLED`, `RERANKER_MODEL`, `RETRIEVAL_RECALL_TOP_K`, `RERANK_TOP_N`, `RRF_K`.

Session 12 vars (hand-written agent):
- `AGENT_MODEL` / `AGENT_REASONING_EFFORT` — default `gpt-5` / `medium`. Plain settings, NOT runtime-config: there is no live endpoint this session, only `scripts/run_agent_s12.py`, which overrides them per run (`gpt-5-mini` while debugging the loop).
- `AGENT_MAX_ITERATIONS` — default `10`. Safeguard on top of the natural stop (a turn with no `function_call`).
- `AGENT_SEARCH_TOP_K` / `AGENT_SEARCH_DISTANCE_THRESHOLD` / `AGENT_TASKS_PER_MODULE` — default `5` / `0.6` / `4`. What `search_budgets` passes to `retrieve()`; the last one over-fetches tasks because several of them collapse into the same module.

Session 13 vars (graph orchestration):
- `LOGFIRE_TOKEN` — unset is a supported mode: spans still run, they are just not exported.
- `GRAPH_RECURSION_LIMIT` — default `40` (raised from 25 in S14). The SAFETY NET, not the strategy: a supervisor↔specialist round trip costs two supersteps, and at 25 the recursion limit fired before the routing budget and turned a controlled `routing_budget_exhausted` into a `GraphRecursionError`.
- `GRAPH_LLM_TIMEOUT` — default `300`. The estimate node's own timeout; `LLM_TIMEOUT` (30s) is sized for chat-shaped calls and times a reasoning model out on every attempt.

Session 15 vars (commercial proposal):
- `GRAPH_PROPOSAL_MODEL` — default `gpt-4o`. Prose for a client from numbers that are already decided: a non-reasoning model is the right tool, and `gpt-5` at high effort would be paying reasoning tokens to write paragraphs. It reuses `GRAPH_LLM_TIMEOUT` rather than adding a knob — that value is a deadline, not a delay, so a generous one costs nothing on a call that finishes in seconds.

Session 14 vars (multi-agent supervisor + human-in-the-loop):
- `GRAPH_SUPERVISOR_MODEL` / `GRAPH_SUPERVISOR_TIMEOUT` — default `gpt-5-mini` / `30`. The router asks for a two-field decision; reusing `GRAPH_LLM_TIMEOUT` would let one confused routing call block a run for five minutes without producing any work.
- `GRAPH_MAX_ROUTING_STEPS` — default `8`. How many specialists the supervisor may dispatch. This is the ceiling that actually holds: LangGraph's recursion budget resets on every resume, a counter persisted in the state does not.
- `GRAPH_CONFIDENCE_THRESHOLD` — default `0.7`. Below it the graph pauses for a human. Calibrate against real runs: a threshold that sends everything to review destroys the signal, because the reviewer starts approving in bulk.
- `GRAPH_HISTORICAL_BAND_TOLERANCE` — default `0.25`, as a fraction of the band's own bounds. At 0.25 the out-of-range trigger fires once roughly a third of the project has no comparable budget; much past 0.4 it becomes unreachable.

## Docker

Multi-stage Dockerfile: `builder` installs prod-only deps with `uv sync --no-install-project --no-dev`, `runtime` is a clean `python:3.11-slim` carrying `/app/.venv`, `app/`, `alembic/` + `alembic.ini`, `data/` and `scripts/`, and runs as non-root `appuser`. The last three are there so the container can migrate itself and seed the corpus with nothing mounted. There is a Docker-native HEALTHCHECK against `/health`. **No bind-mount and no `--reload`**: the session's `docker-compose.yml` gives `ai-service` no `volumes:` at all, so the code that runs is the code COPIED into the image and a change under `app/` needs `docker compose up --build`. Redis uses `redis/redis-stack-server:7.4.0-v0` for RediSearch.

For running tests inside the container the prod image lacks pytest. Two options:
```bash
# 1. Run on the host with uv
cd estimator && uv sync && uv run pytest

# 2. Install ad-hoc inside the container (lost on rebuild)
docker compose exec ai-service bash -c '
  python -m ensurepip --upgrade && \
  python -m pip install --quiet pytest pytest-asyncio fakeredis httpx
'
docker compose exec ai-service python -m pytest tests/ -v
```
