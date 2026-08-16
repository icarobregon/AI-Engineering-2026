# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

The AI service for the Master en AI Engineering programme:

- `estimator/` — FastAPI service. The AI side: prompts, LLM calls, structured output, guardrails, semantic cache. All AI logic lives here; the rest of the programme evolves this codebase module by module.

The business frontend/client is out of scope in this repo — we will build our own. The live sessions invoke `estimator` directly via httpie/curl (stack-agnostic).

Run everything from the `estimator/` directory. `estimator/docker-compose.yml` brings up three services — `estimator`, `redis` and `estimator-postgres` (pgvector image, host port 5433, volume `estimator_postgres_data`) — on a shared network: `cd estimator && docker compose up`.

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

Service listens on `http://localhost:8000`; `/docs` (Swagger) and `/redoc` are enabled. Health probe at `GET /health`. Main API endpoints are `POST /api/v1/estimate` (Session 4 path) and `POST /v1/estimate/from-transcript` (Session 9 RAG flow).

Integration tests are excluded from the default run and need the compose stack up:

```bash
uv run pytest                 # unit only, no infrastructure
uv run pytest -m integration  # real Postgres + pgvector
```

## Architecture (layered: foundation / domain / generation / api)

The estimator is organized around the **three AI architectures it stacks** — CAG (caches), RAG
(retrieval) and Agentic (Actor-Critic-Boss) — which **compose only through a single conductor**.
Full contract in **`estimator/ARCHITECTURE.md`** — respect it for all new session code.

`app/` layers (each may import only from layers above it):

```
app/
├── config.py · dependencies.py · main.py · rate_limit.py   # composition root, above the layers
├── foundation/   llm · prompts · guardrails · attachments · persistence · observability  (no AI-arch opinion)
├── domain/       schemas/ (the contract) + estimation_service.py (the conductor)
├── generation/   cag/ · rag/ · agentic/ · conversation/   (the 3 architectures + substrate)
├── ingestion/    offline batch pipeline that feeds RAG
└── api/          thin routers (transport) + security.py
```

**Session 9 — the RAG request pipeline.** Transcript in, cited estimate out:

```
POST /v1/estimate/from-transcript      (X-API-Key: ESTIMATE_API_KEY · 10/min)
  └→ app/api/estimate_rag.py
       └→ app/domain/estimation_service.py::estimate_from_transcript()
            0. idempotency_store.get()                        (Redis, 24h TTL)
            1. generation/rag/query_reformulator.py           (transcript → EstimationQuery →
                                                               search_text; fallback to rewriting)
            2. generation/rag/retriever.py::retrieve()        (top-K + distance threshold +
                                                               JSONB filters; soft-fail →
                                                               NO generation without evidence)
            3. generation/rag/context_assembler.py            (<source> blocks + token budget)
            4. generation/rag/generator.py                    (grounded generation + citation
                                                               validation + one retry)
            5. validation → EstimateResponse(needs_manual_review, retrieval trace)
```

Each stage is wrapped in `foundation/observability.py::log_stage`, so one `request_id` (returned as
the `X-Request-ID` header) reconstructs the whole request with per-stage `duration_ms`.

Five-layer request pipeline (Session 4 path). Free-text in, validated structured JSON out:

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
- **Two LLM entry points, on purpose.** The CAG path goes through `foundation/llm/wrapper.py`
  (LiteLLM + Instructor: provider fallback, cost accounting, runtime model overrides). The Session 9
  RAG stages go through `foundation/llm/responses.py` (OpenAI Responses API: `strict` structured
  output and `reasoning.effort`, neither of which the wrapper can express). Do not "unify" them
  without replacing what each one provides.
- **Retrieval filters read `chunks.metadata` (JSONB, GIN-indexed)**, not columns on `documents` —
  sector, country, year and technology all travel with the chunk. And the vector index is an
  *expression* index over `embedding::halfvec(1536)`: any new query must rank by that same
  expression or Postgres silently falls back to a sequential scan.
- **Never generate without retrieved evidence.** If nothing beats the distance threshold, the
  conductor returns `estimate: null` with `needs_manual_review`. An LLM asked to estimate from an
  empty context returns numbers that look exactly like the grounded ones.
- **Logging** is `structlog`. JSON in `production`, console in dev. Use `structlog.get_logger()` rather than stdlib `logging`.
- **The LLM wrapper bypasses the Router for streaming and for structured calls** (see `_dispatch`). LiteLLM's Router does round-robin between deployments, which would non-deterministically route to a fallback that may be unreachable. For deterministic behaviour `complete_structured` always uses the primary model directly.

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
