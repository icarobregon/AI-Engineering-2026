# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

The AI service for the Master en AI Engineering programme:

- `estimator/` — FastAPI service. The AI side: prompts, LLM calls, structured output, guardrails, semantic cache. All AI logic lives here; the rest of the programme evolves this codebase module by module.

The business frontend/client is out of scope in this repo — we will build our own. The live sessions invoke `estimator` directly via httpie/curl (stack-agnostic).

A root-level `docker-compose.yml` pulls in `estimator/docker-compose.yml` via the `include:` directive (Compose v2.20+). Running `docker compose up` from the repo root brings up the three services (`estimator`, `redis`, `estimator-postgres`) on a shared network. The Postgres service is named `estimator-postgres` (not plain `postgres`), uses the pgvector image on host port 5433 and the volume `estimator_postgres_data`.

**Trap to be aware of**: launching from the root vs from `estimator/` creates *different* Compose projects, which means the named volumes (`estimator_postgres_data`, `redis_data`) are not shared between the two modes. Pick a mode per workflow and stay with it.

Session guides for the instructor live in `guides/` (git-ignored). `guides/session-4-live-guide.md` is the most recent.

## Common commands (estimator)

Dependency / runtime management uses **uv** (Astral) and Python 3.11.

```bash
cd estimator

# Run the API locally with hot reload
uv run uvicorn app.main:app --reload

# Tests
uv run pytest -v
uv run pytest tests/test_schemas.py::test_phases_sum_must_equal_total_cost -v

# Lint
uv run ruff check .
uv run ruff format .

# Docker (recommended dev path — bind-mounts app/ and tests/ for live reload)
docker compose up --build
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

- **The router has no business logic.** It only catches three exceptions and turns them into HTTP statuses: `InputGuardrailViolation` → 400, anything else from the pipeline (including `instructor.exceptions.InstructorRetryException`) → 502, plus Pydantic 422 from `EstimationRequest` validation. Add new policies inside `EstimationService.estimate()`, not in the router.
- **Schema is the contract.** `EstimationResult` (in `app/domain/schemas/estimation.py`) is what Instructor enforces against the LLM. The two `model_validator`s (`phases_sum_matches_total`, `low_confidence_requires_out_of_scope_prefix`) are the business rules — when they raise, Instructor re-prompts the LLM up to `max_retries=6` times.
- **Field order matters with Instructor.** `phases` is declared BEFORE `total_cost_eur` / `total_duration_weeks` on purpose: the LLM emits phases first (autoregressive) and then only needs to sum, instead of picking a round total and back-fitting phases. With smaller models like `gpt-4o-mini` this is the difference between consistent success and arithmetic failures.
- **Two caches in series.** Both live in the CAG layer (`app/generation/cag/`). The exact-match cache (`app/generation/cag/exact.py`) keys on SHA-256 of the typed request + prompt_version + model. The semantic cache (`app/generation/cag/semantic.py`) layers on top: same bucket (`prompt_version:project_type:detail_level:output_format`) + cosine similarity ≥ `SEMANTIC_CACHE_THRESHOLD` (default 0.85). The semantic cache requires Redis Stack (`redis/redis-stack:7.4.0-v0`), not vanilla Redis — RediSearch is mandatory for vector queries.
- **Guardrails are policies, not features.** `check_input` uses `exception` policy (raise on violation). `enforce_scope_response` uses `filter` (rewrite the summary). The schema validators use `re-prompt` (Instructor handles it). The split is documented in the live-session guide.
- **Settings are a cached singleton** via `app/config.py::get_settings` (`@lru_cache`). Any change to `.env` requires recreating the container (`docker compose up -d --force-recreate`); a `--reload` is not enough. **Exception: the LLM model knobs** (`PRIMARY_MODEL`, `FALLBACK_MODEL`, `CRITIC_MODEL`, metadata/compression/chunker models) can be overridden at runtime via `PUT /api/v1/config/models` (Redis-backed `app/foundation/llm/runtime_config.py`) — overrides survive `--reload` and restarts, and both caches partition by model.
- **Logging** is `structlog`. JSON in `production`, console in dev. Use `structlog.get_logger()` rather than stdlib `logging`.
- **The LLM wrapper bypasses the Router for streaming and for structured calls** (see `_dispatch`). LiteLLM's Router does round-robin between deployments, which would non-deterministically route to a fallback that may be unreachable. For deterministic behaviour `complete_structured` always uses the primary model directly.
- **Session 9 closes the transcript → estimate loop (RAG generation).** A second, RAG-native estimate path lives entirely in `app/generation/rag/` and is exposed by two independently-secured routers in `app/api/routers/`:
  - `POST /v1/retrieval/search` (auth `RETRIEVAL_API_KEY`, 120/min) — metadata-filtered k-NN with a relevance threshold + soft-fail. It supersedes the unauthenticated Session 8 `POST /search`, which stays only for backwards compatibility (Chunking Lab / S08 demos).
  - `POST /v1/estimate/from-transcript` (auth `ESTIMATE_API_KEY`, 10/min, idempotent on `idempotency_key`) — runs `estimate_from_transcript`: `reformulate_query` → `compose_search_text` + embed → `search_chunks` (soft-fail short-circuits to `confidence="insufficient"`) → `truncate_to_token_budget` → `build_context_block` (XML `<source>` delimiters) → `generate_estimate` → `validate_citations` (one corrective retry on fabricated ids) → coherence check.
  This path **reuses `LLMWrapper`** (Instructor + LiteLLM) for both reformulation (`REFORMULATION_MODEL`, default `gpt-5-mini`) and generation (`GENERATION_MODEL`, default `gpt-5`, `reasoning_effort="high"`, `max_tokens=GENERATION_MAX_TOKENS` default 64000 — reasoning tokens count against the budget) — NOT the raw OpenAI Responses API. It emits the hours-based `Estimate` schema: a nested `modules` → `tasks` breakdown (`WorkModule`/`TaskItem`, each task with `engineer_days` + `sources`) plus `total_engineer_days` and mandatory `SourceCitation`s + `Assumption`s — distinct from and coexisting with the Session 4 euro/weeks `EstimationResult`. The engineer-day numbers are **LLM-inferred**, grounded in the historical `estimated_hours` the model reads from the retrieved `<source>` chunk text (the retriever does no numeric aggregation). To ground the *task-granular* breakdown there is an optional task-level corpus: `scripts/build_task_corpus.py` deterministically synthesises projects decomposed into modules→tasks (each task = a `BudgetComponent` carrying the new optional `module` field, surfaced by the structural chunker), writes `data/task_corpus.json`, and `--ingest`s it via `/embeddings/ingest` tagged `document_type='historical_task_breakdown'` / `chunk_type='historical_task'` (filterable; `IngestRequest.chunk_type` defaults to `budget_component`, so S08 ingest is unchanged). The default corpus is **60 projects / ~1.5k tasks** across **eight sectors** (`finance`, `ecommerce`, `healthcare`, `industrial`, `logistics`, `education`, `media`, `government` — the `Sector` literal in `app/generation/rag/schemas.py`) with a broad module catalog, so the Session 10 per-task hours search (`POST /v1/estimate/tasks/hours`, weighted-consensus over the nearest historical tasks) has many analogs to match; `--count`/`--seed` tune it. It coexists with the base corpus; wipe with `DELETE FROM documents WHERE document_type='historical_task_breakdown'`. A teaching-only set of per-stage endpoints (`POST /v1/estimate/stages/{reformulate,retrieve,assemble,generate,structure}`, `app/api/routers/estimate_stages.py`) exposes each pipeline step, reusing the same pure functions. **Session 10 reshaped the client wizard flow**: it no longer retrieves/augments before generation — the structure is a FREE LLM decomposition of the reformulated brief via `POST /v1/estimate/stages/structure` (`generate_structure` + `build_structure_system_prompt`, no `<sources>`, no citations, `engineer_days` null), grounding the *structure* in retrieved budgets impoverished the tree. Retrieval re-enters **per task** in `POST /v1/estimate/tasks/hours` (`app/generation/rag/task_hours.py`): each reviewed task is searched via `retrieve()` (hybrid + cross-encoder reranking, per the runtime `RERANKER_ENABLED`) filtered to `chunk_type='historical_task'`, and the hours come from a distance-weighted **consensus** of the nearest neighbours with a reliability score (no match under `TASK_HOURS_DISTANCE_THRESHOLD` → no hours, flagged red). The wizard steps are now `transcript → reformulation → generation(structure) → review → hours → verification`; `from-transcript` (grounded, hours inline) and `/stages/generate` stay as the Session 9 comparison path. Cross-cutting: per-API-key rate limiting (`app/api/rate_limiting.py`, slowapi), constant-time key checks (`app/api/security.py`, `secrets.compare_digest`), idempotency store (`app/generation/rag/idempotency.py`, Redis or in-process fallback), and an `X-Request-ID` correlation header set by middleware in `app/main.py` (per-stage logs via `log_stage`).

- **Session 10 adds advanced retrieval (multi-index, routing, expansion, decay).** The corpus is partitioned into **three chunk tables** — `budget_chunks` (the Session 8 `chunks` table, renamed in migration `0004_session10_multi_index`), `transcript_chunks` and `technical_doc_chunks` — sharing the `_ChunkColumns` ORM mixin but each with its own JSONB metadata schema (Article 5 "Opción B": schemas that diverge → separate tables). `ChunkRow` stays an alias of `BudgetChunkRow` so Session 8/9 imports are unaffected; `ChunkStore` search/persist methods take a `model=` (default `BudgetChunkRow`). The whole advanced layer lives under `app/generation/rag/retrieval/`: `collections.py` (the `Collection` StrEnum + registry: per-collection model, date accessor, rule patterns, hard-filter clauses), `router.py` (cascade routing: explicit collection → deterministic vocab rules → LLM classifier with structured 1–3 targets + reason → fallback-to-all), `query_transform.py` (expansion vs decomposition chosen by a length/connectors heuristic, ≤4 sub-queries via structured output), `fusion.py` (`reciprocal_rank_fusion` for expansion consensus + `round_robin_merge` for decomposition coverage, deduped by `(collection, id)` since ids only collide-free within a table), `temporal.py` (exponential decay, applied LAST on a non-negative base — reranker logits are sigmoid'd first), and `advanced_pipeline.py` (the conductor: query transform → routing → hard filters → hybrid search → differentiated fusion → rerank → temporal decay → top-k, every stage gated by a `StageConfig`). It is exposed by `POST /v1/retrieval/advanced-search` (`app/api/routers/retrieval_advanced.py`, auth `RETRIEVAL_API_KEY`, 120/min) whose response surfaces the routing decision, technique, sub-queries and per-collection cardinality. **The Session 9 `POST /v1/retrieval/search` and the estimate path are untouched** (`retrieve()` keeps its single-collection contract; it just gained a `collection=` default of budget). Stage toggles flip at runtime via `RuntimeRetrievalConfig` → `PUT /api/v1/config/retrieval`. New sample collections: `data/transcripts_sample.json` + `data/technical_docs_sample.json`, seeded by `scripts/build_multi_index_corpus.py` (run inside the container); the harness `scripts/eval_retrieval_s10.py` runs named `StageConfig`s (data, not code branches) against the extended multi-collection golden set. **tsvector config stays `english`** everywhere (the shipped corpus is English; see migration 0003) and **all advanced LLM calls reuse `LLMWrapper`** (Instructor), NOT the raw Responses API — flagged because the articles taught `responses.parse`.

- **Session 11 moves citation from the estimate down to the LINE, and adds the RAGAS harness.** `TaskItem` (the line) now carries `sources: list[SourceReference]` — `chunk_id` (the `id` attribute of its `<source>`), `document_id` and the VERBATIM `evidence` span — plus a mandatory `grounded` flag, declared BEFORE `engineer_days` so the model commits to its evidence before it commits to a figure. `document_id` is resolved server-side from the retrieved chunk, never asked of the model: it is derivable from `chunk_id`, so asking for it would only add a surface to hallucinate on (this is why `context_assembler` is unchanged). `app/generation/rag/validation.py` splits reporting from policy: `verify_citations()` returns a `CitationReport` classifying every line as `grounded`/`dangling`/`insufficient` and changes nothing, while `enforce_citation_policy()` resolves document ids, prunes citations that do not resolve, demotes the lines left without backing to `grounded=False` with null hours, re-derives `total_engineer_days` from what survived, and collapses the whole estimate to the canonical insufficient shape when no line survives. The Session 9 `validate_citations()` is gone: both of its callers read `report.dangling_source_ids`, the same set with the per-line verdict attached. The integrity rule is a post-generation check, NOT a Pydantic validator, on purpose: a validator makes Instructor re-prompt silently up to six times inside `complete_structured`, which is the opposite of the requirement to *log* the outcome. `estimate_from_transcript` verifies → retries once on fabricated ids → logs `citation_report` (via `observability.log_citation_report`, correlated by `request_id`) → enforces; the coherence-repair branch re-enforces because it is a fresh generation. `POST /v1/estimate/stages/generate` reports (`GenerateResult.citation_report`) but does NOT enforce — it is the teaching aid that surfaces raw model output; `/stages/structure` leaves the report `None`. Evaluation: `evals/golden_retrieval.json` gains a `ground_truth` on Q1–Q5 (Q6–Q8 stay retrieval-only: they are cross-collection QA, not estimation requests) and `scripts/eval_ragas_s11.py` scores faithfulness / answer_relevancy / context_precision / context_recall on the host. **Two RAGAS traps**: `ragas` 0.4.3 hard-imports `langchain_community.chat_models.vertexai`, so the dev group pins `langchain-community<0.4`; and `evaluate()` rejects the newer `ragas.metrics.collections` classes, so the harness pairs the modern `EvaluationDataset`/`SingleTurnSample` schema with the classic metric objects.

- **Session 12 adds a hand-written agentic layer (manual Responses API loop).** Where the S9-S11 estimate path is a FIXED pipeline (reformulate → retrieve → generate), the agent DECIDES at each step how many budget searches to run and in what order — the shape a transcript needs when it mixes unrelated components (business backend + ERP integration + mobile app + analytics). It lives in `app/generation/agentic/` beside the untouched S4 ACB files (`boss.py`/`critic.py`): `agent_schemas.py` (tool args + `AgentStep`/`AgentTrace` with `render()` + the LIGHT result `AgentEstimate`, deliberately not the heavy RAG `Estimate`), `agent_tools.py` (three FLAT Responses tool schemas with `strict:true` — `search_budgets`, `calculate_estimate`, `validate_estimate` — plus impls and `dispatch_tool`), and `agent_loop.py` (`run_estimation_agent`). **This is the one deliberate exception to the "everything goes through `LLMWrapper`" rule** — the agent drives `client.responses.create`/`.parse` by hand, because seeing the loop IS the exercise (do NOT "fix" it). Loop mechanics: stateful chaining (`store=True` + `previous_response_id`, sending only the new `function_call_output` items, so the server keeps reasoning-item ordering); `instructions` are re-sent on every call because they do NOT travel with `previous_response_id`; `reasoning={"effort":…,"summary":"auto"}` feeds the trace; tool errors are returned as the tool output so the model self-corrects instead of crashing the loop; on `max_iterations` the loop does NOT solicit a turn it cannot answer — the pending outputs ride along with the closing `responses.parse`, because chaining onto an unanswered `function_call` is rejected by the API. `search_budgets` reaches retrieval through an INJECTED backend (`dependencies.get_budget_search_backend()`), never an import: ARCHITECTURE.md §3 forbids `agentic` importing `rag`, and the same seam is what `--stub` swaps for the kit's canned corpus. **That backend searches TASKS and answers with MODULES**: the corpus is one chunk per task (17-47h) but the agent estimates subsystems, so each distinct (project, module) behind the hits is returned once, priced at the sum of all its tasks — feeding raw task hours to a median prices an ERP integration at ~30h, and a live gpt-5 run correctly refused to use numbers that small. Run it with `scripts/run_agent_s12.py` (`--model`/`--effort`/`--max-iterations`/`--stub`/`--out`). Its delivered trace and review notes live on the `session_12_*` branch, not here; what survives in `exercises/session-12/` is what Session 13 still uses: the two transcripts and the offline retrieval stub that `--stub` loads by path. No HTTP endpoint or UI this session. Tests are network-free (`tests/generation/agentic/`, a scripted fake `AsyncOpenAI`).

- **Session 13 re-expresses the estimate flow as an explicit LangGraph.** Same work as the S12 loop, different shape: typed shared state, one responsibility per node, edges that own the control, a checkpoint after every step and a span per node. It lives in `app/domain/graph/` — the CONDUCTOR level, the layer allowed to compose `generation` siblings: `state.py` (`EstimationState` TypedDict; `budget_matches` and `errors` are `Annotated[..., operator.add]` accumulators, chosen NOW because the live session fans `search_budgets` out and an overwrite field under fan-out silently keeps one branch), `schemas.py` (the LLM nodes' contracts), `nodes.py`, `build.py`, `checkpointer.py`, `observability.py`. Topology: START → extract_requirements → classify_components → search_budgets → generate_estimate → validate_and_consolidate, then ONE conditional edge (validated → END, otherwise → flag_for_review → END). **The nodes come from a factory** (`build_nodes(llm=…, search_backend=…)`, wired by `dependencies.get_graph_nodes()`): `app/domain/` may not import `app.dependencies` (ARCHITECTURE.md §3), so the layer declares the seam and the composition root fills it — and `scripts/run_graph_s13.py` uses that same factory rather than wiring its own, because when it did, fixes applied to the service never reached it. **Joins go by an id we assign** (`Component.id`, echoed back as `EstimatedComponent.component_id`, normalised on read): matching estimate lines to their evidence by the model-authored NAME flagged all seven components as unbacked on the first real run, and `[c1]` vs `c1` did it again. `Component` also carries `search_query` in ENGLISH — the corpus is English and the same query in Spanish retrieves nothing (measured in S12). `validate_and_consolidate` ALWAYS writes `status` (None when it fails): it is a last-write-wins channel the checkpointer restores, so writing it only on success let a reused thread inherit a previous run's `validated`. The estimate node runs `GENERATION_MODEL` at `GENERATION_REASONING_EFFORT` with `GENERATION_MAX_TOKENS` and `GRAPH_LLM_TIMEOUT` (300s): reasoning tokens count against max_tokens and the 30s `LLM_TIMEOUT` times the call out on every attempt. `POST /v1/estimate/graph` (`app/api/routers/estimate_graph.py`) keeps the S9 contract — transcript in, estimate + `status` out — and ANSWERS a finished thread instead of re-invoking it, because a second invocation appends to the accumulators and can certify components as grounded on the previous run's evidence. The graph and its `AsyncPostgresSaver` are built once in the `lifespan` (`app.state.graph`; `None` + a 503 when Postgres is unreachable, never silently unpersisted). Checkpointer tables live in the project's Postgres beside the embeddings. Run it with `scripts/run_graph_s13.py` (`--memory`/`--stub`/`--out`); the delivered run is `exercises/session-13/example_run_complex.txt`.

## Configuration

`.env` (copied from `.env.example`) drives everything via `pydantic-settings`.

Session 2/3 vars:
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — at least one required.
- `PRIMARY_MODEL` / `FALLBACK_MODEL` — LiteLLM Router config.
- `LLM_TIMEOUT` / `LLM_RETRIES` — per LLM call.
- `REDIS_URL` — points to the Redis Stack container in compose.

Session 4 vars:
- `EMBEDDING_MODEL` — defaults to `text-embedding-3-small`.
- `SEMANTIC_CACHE_THRESHOLD` — cosine similarity threshold (0..1). 0.85 default = the typical range mentioned in the live guide. Lower = more hits, more false positives.
- `SEMANTIC_CACHE_TTL` — seconds (24h default).
- `SEMANTIC_CACHE_LOG_ONLY` — when `true`, the cache logs would-be hits but never serves them. Use it to calibrate the threshold against real traffic before flipping on.

Session 9 vars (RAG estimation):
- `RETRIEVAL_API_KEY` / `ESTIMATE_API_KEY` — independent keys for the two routers (header `X-API-Key`). Blank disables the router (401 on every request).
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
- `GRAPH_RECURSION_LIMIT` — default `25`. The sequential flow needs six.
- `GRAPH_LLM_TIMEOUT` — default `300`. The estimate node's own timeout; `LLM_TIMEOUT` (30s) is sized for chat-shaped calls and times a reasoning model out on every attempt.

## Docker

Multi-stage Dockerfile: `builder` installs prod-only deps with `uv sync --no-install-project --no-dev`, `runtime` is a clean `python:3.11-slim` that only carries `/app/.venv` and `app/`, runs as non-root `appuser`. There is a Docker-native HEALTHCHECK against `/health`. `docker-compose.yml` bind-mounts `./app` and `./tests` for development; `--reload` is on. Redis service uses `redis/redis-stack:7.4.0-v0` for RediSearch.

For running tests inside the container the prod image lacks pytest. Two options:
```bash
# 1. Run on the host with uv
cd estimator && uv sync && uv run pytest

# 2. Install ad-hoc inside the container (lost on rebuild)
docker compose exec estimator bash -c '
  python -m ensurepip --upgrade && \
  python -m pip install --quiet pytest pytest-asyncio fakeredis httpx
'
docker compose exec estimator python -m pytest tests/ -v
```
