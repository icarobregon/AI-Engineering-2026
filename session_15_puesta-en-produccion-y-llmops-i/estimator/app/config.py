from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Session 2 fields ---------------------------------------------------
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    # TypeSafe (PoC S15). Opcional y fuera de validate_at_least_one_api_key a
    # proposito: un despliegue que solo tuviera esta clave NO debe arrancar,
    # porque un modelo de decision no sabe redactar una estimacion.
    TYPESAFE_API_KEY: str | None = None
    # Parametro y no constante: con esto, poner un gateway delante en la S16 es
    # cambiar esta variable, sin tocar codigo. Lleva default porque nombra al
    # proveedor, que no se mueve; un `http://litellm-proxy:4000` si nombraria
    # infraestructura nuestra y entonces tendria que ser obligatoria.
    TYPESAFE_API_BASE: str = "https://api.typesafe.ai"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    # El volumen de los logs. Es un Literal porque llega hasta
    # `make_filtering_bound_logger` como nivel de stdlib: un valor fuera de esta
    # lista no se descubriría al arrancar sino al primer log que no saliera.
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"
    # LLM_PROVIDER y LLM_MODEL estaban aquí desde la Sesión 2 y NADIE las leía.
    # El proveedor se infiere del nombre del modelo (`_provider_from_model`) y el
    # modelo sale de PRIMARY_MODEL, de los knobs por etapa o del override en
    # caliente. Declaradas como Literal, su único efecto vivo era tumbar el
    # arranque con un valor fuera de la lista: validación sobre algo que nadie
    # consultaba. `extra="ignore"` hace que un .env viejo que aún las traiga no
    # rompa nada.

    # --- Session 3 fields (LiteLLM wrapper, Redis cache, Streamlit transport) ---
    PRIMARY_MODEL: str = "gpt-4o-mini"
    FALLBACK_MODEL: str = "claude-haiku-4-5-20251001"
    LLM_TIMEOUT: int = 120
    LLM_RETRIES: int = 2
    # Catalogo de modelos seleccionables en caliente vIa PUT /api/v1/config/models.
    # Curado A MANO contra los catalogos que las claves alcanzan de verdad
    # (GET /v1/models de cada proveedor) y alineado con MODEL_COSTS en
    # app/foundation/llm/wrapper.py: lo que este aqui sin precio alli se
    # contabiliza a cero. El endpoint lo filtra ademas por las claves
    # configuradas. Ordenado por proveedor, familia y precio, que es como se
    # lee el desplegable.
    #
    # Fuera a proposito: modelos retirados (gpt-3.5, gpt-4-0613, davinci,
    # babbage), los `-instruct`, los que no son de texto (voz, realtime,
    # imagen, embeddings) y los alias `*-chat-latest`, que apuntan a un modelo
    # movil; aqui el nombre del modelo particiona las caches, asi que un alias
    # que cambia debajo invalidaria comparaciones sin avisar.
    AVAILABLE_MODELS: list[str] = [
        # OpenAI · GPT-4
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-nano",
        "gpt-4.1-mini",
        "gpt-4.1",
        # OpenAI · GPT-5
        "gpt-5-nano",
        "gpt-5-mini",
        "gpt-5",
        "gpt-5-pro",
        "gpt-5.1",
        "gpt-5.2",
        "gpt-5.2-pro",
        "gpt-5.4-nano",
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.4-pro",
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        # OpenAI · GPT-6
        "gpt-6-astra",
        # OpenAI · razonadores de la serie o
        "o3-mini",
        "o4-mini",
        "o3",
        "o1",
        "o1-pro",
        # Anthropic
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5",
        "claude-sonnet-4-6",
        "claude-sonnet-5",
        "claude-opus-4-5-20251101",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-fable-5",
        "claude-fable-5-1",
        # TypeSafe · modelos de DECISION (PoC S15). No generan texto: devuelven
        # una eleccion con su probabilidad, por su propio endpoint. Solo son
        # legales en GRAPH_SUPERVISOR_MODEL — ver DECISION_ONLY_KNOBS abajo.
        "jev-latest",
        "jev-1.13.0",
        "jev-preview",
        # El mismo Jev por el AI Gateway de Vercel: ahi el id lleva el prefijo
        # del proveedor. Cual sirve depende de a donde apunte TYPESAFE_API_BASE.
        "typesafe-ai/jev",
    ]

    # Que knobs admiten un modelo de decision, y por tanto cuales NO.
    #
    # AVAILABLE_MODELS es una lista global y hasta ahora bastaba: todo lo que
    # habia dentro sabia hablar. Un modelo que solo devuelve una eleccion no
    # sirve para redactar una estimacion ni para resumir una conversacion, asi
    # que elegirlo en cualquier otro knob es un fallo en caliente. Vive aqui,
    # como DATO junto al catalogo, y no como un `if` en api/: esa capa lee dato
    # de foundation, nunca conducta (ARCHITECTURE.md §3).
    DECISION_ONLY_KNOBS: list[str] = ["GRAPH_SUPERVISOR_MODEL"]

    # Procedencia del catalogo de arriba. Se cura A MANO, asi que dice cuando se
    # genero y de que catalogos: nada lo mantiene fresco solo. Si aparece un
    # proveedor nuevo o el proveedor publica modelos nuevos, esta lista no se
    # entera — hay que pedir explicitamente que se regenere.
    MODEL_CATALOG_GENERATED_AT: str = "2026-09-23T16:00:00+02:00"
    MODEL_CATALOG_SOURCES: list[str] = ["OpenAI", "Anthropic", "TypeSafe"]

    # SIN valor por defecto, y es deliberado. Un default que nombra una máquina y
    # un puerto es el que produce «en mi máquina funciona»: hasta la S15 decía
    # `redis://localhost:6379`, un puerto que dejó de publicarse cuando los
    # datastores se hicieron privados, y nadie se enteró porque Compose lo pisaba.
    # Sin default, una configuración incompleta falla al construir Settings
    # diciendo qué falta, en vez de marcar un puerto que no existe.
    REDIS_URL: str
    CACHE_TTL: int = 86400

    # --- Session 4 fields (semantic cache) ---
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEMANTIC_CACHE_THRESHOLD: float = 0.85
    SEMANTIC_CACHE_TTL: int = 86400
    # When True, the semantic cache LOGS potential hits but does NOT serve them.
    # Used to gather metrics before flipping the cache on in production.
    SEMANTIC_CACHE_LOG_ONLY: bool = False

    # ESTIMATOR_API_BASE_URL NO está aquí a propósito. La variable sigue viva,
    # pero su único lector es `streamlit_app.py`, que la coge del entorno con
    # `os.getenv` y nunca pasó por Settings. Un campo que ningún módulo lee sólo
    # sirve para hacer creer que el servicio se configura con él.

    # --- Session 5 fields (conversational memory + attachments) ---
    # MAX_CONVERSATION_TURNS counts user+assistant pairs. The system prompt is
    # always preserved as an invariant on top of the window.
    MAX_CONVERSATION_TURNS: int = 6
    # Hard cap per extracted attachment (in characters) to protect the context
    # window. Real chunking enters in module 3.
    MAX_ATTACHMENT_CHARS: int = 60_000
    # The metadata extractor runs once per turn; a small/cheap model is enough.
    METADATA_EXTRACTOR_MODEL: str = "gpt-4o-mini"

    # --- Session 5 live: compression + tier + ACB ---
    # Anchor detector: "heuristic" (regex over key phrases) or "llm" (binary
    # classifier via Instructor). Heuristic is the default for cost.
    ANCHOR_DETECTION_MODE: Literal["heuristic", "llm"] = "heuristic"
    # Cheap model used by the cumulative summarizer (history compression).
    COMPRESSION_MODEL: str = "gpt-4o-mini"
    # Conversational prompt version used by ``estimate_conversational``.
    # v2 = pre-live-session baseline. v3 = adds <audience> block driven by tier
    # and an optional <critic_feedback> block consumed by the Boss.
    CONVERSATIONAL_PROMPT_VERSION: str = "v3"
    # Critic model (read-only auditor; cheap is fine).
    CRITIC_MODEL: str = "gpt-4o-mini"
    # Max iterations the Boss can drive (each iteration = 1 actor + 1 critic call).
    # Three is the practical floor: one initial draft + two directed retries.
    # With only two iterations the actor often cannot address all flagged issues
    # in the single available retry, and the loop falls back without converging.
    BOSS_MAX_ITERATIONS: int = 3

    # --- Session 6 fields (data-driven AI: persistence + ingestion + PII) ---
    # Postgres connection string. pgvector/pgvector:pg16 image; the extension
    # is dormant in S06 (no CREATE EXTENSION vector) and only activates in S07.
    #
    # SIN valor por defecto, por lo mismo que REDIS_URL y por una razón más: el
    # default traía usuario y contraseña escritos en código versionado, y
    # apuntaba a `localhost:5433`, un puerto cerrado desde la S15. Tres capas
    # decían tres cosas distintas y sólo Compose acertaba.
    DATABASE_URL: str
    # Where the YAML catalog lives. Resolved relative to the working directory.
    CATALOG_PATH: Path = Path("data/catalog/catalog.yaml")
    # Root where ``CatalogSource.location`` entries are resolved against.
    INGESTION_DATA_ROOT: Path = Path("data/seed")
    # spaCy model loaded by the Presidio AnalyzerEngine. Must be the Spanish
    # one for the live session; ``es_core_news_md`` is the recommended size.
    PRESIDIO_SPACY_MODEL: str = "es_core_news_md"
    # Locale used by Faker to generate consistent pseudonyms per entity_type.
    PSEUDONYM_FAKER_LOCALE: str = "es_ES"
    # HMAC salt. Stored in env so it can be rotated independently of the code.
    PSEUDONYM_HASH_SALT: str = "change-me-in-prod"

    # --- Session 7 live fields (chunking strategies that call external APIs) ---
    # LLM that decomposes a component into atomic propositions (one call per
    # component). A small/cheap model is enough.
    PROPOSITIONAL_CHUNKER_MODEL: str = "gpt-4o-mini"
    # Claude model used by Contextual Retrieval to situate each chunk inside its
    # parent budget. Prompt caching makes the (large) parent document cheap to
    # reuse across the chunks of the same budget.
    CONTEXTUAL_CHUNKER_MODEL: str = "claude-sonnet-4-5"

    # --- Session 9 fields (RAG estimation: transcript → grounded estimate) ---
    # Query understanding distills a transcript into an EstimationQuery; a small
    # model is enough. Generation reasons over retrieved budgets, so it uses the
    # strongest model with medium reasoning effort. Both go through LLMWrapper.
    REFORMULATION_MODEL: str = "gpt-5-mini"
    GENERATION_MODEL: str = "gpt-5"
    # "high" drives a deeper, more consistent module→task decomposition (the S09
    # article used "medium"; we raise it for the granular modular breakdown).
    GENERATION_REASONING_EFFORT: Literal["minimal", "low", "medium", "high"] = "high"
    # Token ceiling (reasoning + output) for the RAG structured calls. gpt-5 is a
    # reasoning model: its reasoning tokens count against this budget, so the
    # 4000 wrapper default leaves nothing for the JSON and the call truncates
    # (finish_reason='length'). Generous headroom so high-effort reasoning can
    # finish AND emit the larger nested (modules→tasks) Estimate. It is a CAP,
    # not a target — the model only spends what it needs, so a high value adds no
    # latency on its own.
    GENERATION_MAX_TOKENS: int = 64000
    # Retrieval knobs (locked defaults from the Session 9 articles).
    RETRIEVAL_TOP_K: int = 10
    RETRIEVAL_DISTANCE_THRESHOLD: float = 0.6
    # Token budget for the assembled <source> context block (tiktoken cl100k_base).
    MAX_CONTEXT_TOKENS: int = 16384
    # Idempotency cache for POST /v1/estimate/from-transcript (seconds; 24h).
    IDEMPOTENCY_TTL: int = 86400
    # API keys for the two Session 9 routers. None disables the router (401 on
    # every request) — set them in .env to enable the endpoints.
    RETRIEVAL_API_KEY: str | None = None
    ESTIMATE_API_KEY: str | None = None

    # --- Session 10 fields (hybrid search + cross-encoder reranking) ---
    # Default retrieval mode. "vector" reproduces the Session 9 baseline; "hybrid"
    # fuses the dense and lexical (full-text) branches with RRF. Switchable per
    # request (RetrievalRequest.search_mode) and at runtime (RuntimeRetrievalConfig).
    RETRIEVAL_SEARCH_MODE: Literal["vector", "hybrid"] = "vector"
    # Whether the cross-encoder reranks by default. Off keeps the baseline cheap;
    # the recall-then-rerank path turns on per request / at runtime.
    RERANKER_ENABLED: bool = False
    # Multilingual cross-encoder (ES+EN), small enough for CPU at teaching latency.
    RERANKER_MODEL: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    # Recall width before reranking/fusion (recall-then-rerank): retrieve this many
    # candidates cheaply, then the cross-encoder rescores them down to RERANK_TOP_N.
    RETRIEVAL_RECALL_TOP_K: int = 50
    RERANK_TOP_N: int = 5
    # RRF smoothing constant (Cormack et al. default). Larger = a document must
    # rank well in BOTH branches to win; smaller = a single #1 can dominate.
    RRF_K: int = 60

    # --- Session 10 live fields (advanced retrieval: multi-index pipeline) ------
    # Each advanced-retrieval stage is independently switchable so it can be
    # measured in isolation (the full pipeline is the MAX path, not the only one).
    # These are the .env defaults; routing/transform/decay also flip at runtime
    # (RuntimeRetrievalConfig → PUT /api/v1/config/retrieval). Search mode +
    # reranking reuse the existing RETRIEVAL_SEARCH_MODE / RERANKER_ENABLED
    # toggles above.
    RETRIEVAL_ROUTING_ENABLED: bool = True
    QUERY_TRANSFORM_ENABLED: bool = True
    # Soft re-weight; off by default — turn on only with evidence (Article 6's
    # warning against magic-number boosts).
    TEMPORAL_DECAY_ENABLED: bool = False
    # Small, fast models for the router classifier and the query transformer
    # (both in AVAILABLE_MODELS, so switchable via PUT /api/v1/config/models).
    # Non-reasoning models on purpose: cheap and no reasoning-token budget to
    # starve the JSON.
    ROUTER_MODEL: str = "gpt-4o-mini"
    QUERY_TRANSFORM_MODEL: str = "gpt-4o-mini"
    # Exponential half-life for temporal decay (weight = 0.5 ** (age/half_life)).
    # ≈2.5 years: budgets age slowly, so recency only breaks ties.
    TEMPORAL_DECAY_HALF_LIFE_DAYS: int = 900
    # Caps for the query transformer (sub-queries) and the router (targets).
    QUERY_MAX_SUBQUERIES: int = 4
    ROUTER_MAX_TARGETS: int = 3

    # --- Session 10 live fields (per-task hours estimation) ---------------------
    # The structure-only generation leaves tasks without hours; each task is then
    # matched against the historical task corpus (chunk_type 'historical_task') and
    # the hours come from a weighted consensus of the nearest neighbours. These two
    # knobs change mid-session (calibrating the red threshold against the corpus),
    # so they flip at runtime via RuntimeRetrievalConfig →
    # PUT /api/v1/config/retrieval.
    TASK_HOURS_TOP_K: int = 5
    # Cosine-distance floor: a task whose nearest historical task is farther than
    # this gets NO hours (red flag in the UI) instead of a low-confidence guess.
    TASK_HOURS_DISTANCE_THRESHOLD: float = 0.45

    # --- Session 12 fields (hand-written agentic layer) -------------------------
    # The agent drives a MANUAL tool loop over the raw OpenAI Responses API, so it
    # needs its own model knob: this path does NOT go through LLMWrapper and does
    # not read GENERATION_MODEL. Plain settings, not runtime config — there is no
    # HTTP endpoint this session, only scripts/run_agent_s12.py, which overrides
    # them per run (gpt-5-mini while debugging the loop, gpt-5 for the real run).
    AGENT_MODEL: str = "gpt-5"
    AGENT_REASONING_EFFORT: Literal["minimal", "low", "medium", "high"] = "medium"
    # Safeguard on top of the natural stop (a turn with no function_call). One
    # iteration == one Responses API round-trip, plus one closing call that
    # asks for the typed estimate.
    AGENT_MAX_ITERATIONS: int = 10
    # What the search_budgets tool passes to retrieve(). Looser than the per-task
    # defaults on purpose: the agent asks broad per-component questions, not
    # task-level ones, so it needs a wider net to find comparable budgets.
    AGENT_SEARCH_TOP_K: int = 5
    # search_budgets answers with historical MODULES (subsystems), not single
    # tasks, so it over-fetches this many tasks per module wanted: several
    # tasks of the same module usually match the same query.
    AGENT_TASKS_PER_MODULE: int = 4
    AGENT_SEARCH_DISTANCE_THRESHOLD: float = 0.6

    # --- Session 13 fields (graph orchestration) --------------------------------
    # Write token for https://logfire.pydantic.dev. Unset is a supported mode, not
    # a degraded one: the spans still open and close, they just are not exported,
    # so the service behaves identically on a laptop with no account.
    LOGFIRE_TOKEN: str | None = None
    # Supersteps the graph may run before LangGraph aborts. Raised from 25 in
    # Session 14: a supervisor↔specialist round trip costs TWO supersteps, so
    # GRAPH_MAX_ROUTING_STEPS dispatches need 2N+2 plus the gate. At 25 the
    # recursion limit fired BEFORE the routing budget and turned a controlled
    # "routing_budget_exhausted" into a GraphRecursionError — the net catching the
    # ball before the strategy could.
    GRAPH_RECURSION_LIMIT: int = 40
    # The estimate node runs a reasoning model at GENERATION_REASONING_EFFORT,
    # which spends minutes thinking before it answers. LLM_TIMEOUT (120s) is sized
    # for the chat-shaped calls the rest of the service makes and times this one
    # out on every attempt.
    GRAPH_LLM_TIMEOUT: int = 300

    # El mismo problema que GRAPH_LLM_TIMEOUT, en la ruta RAG. Las dos etapas que
    # corren GENERATION_MODEL con razonamiento alto —la generacion fundamentada y
    # la estructura libre— pasan de los cinco minutos con transcripciones
    # corrientes. Con LLM_TIMEOUT (120 s) cada intento se corta antes de que el
    # modelo termine, Instructor reintenta, y el resultado es un fallo despues de
    # seis minutos habiendo pagado tres generaciones que nadie llego a ver.
    # 600 y no 900: el deadline del servicio tiene que quedar POR DEBAJO del
    # timeout del cliente (900 s en business-backend), o el cliente se va mientras
    # el servicio sigue gastando.
    GENERATION_TIMEOUT: int = 600

    # --- Session 14 fields (multi-agent supervisor + human-in-the-loop) ---------
    # The supervisor only ever asks for a two-field decision, so it runs on the
    # cheap model and with its own short timeout: reusing GRAPH_LLM_TIMEOUT (300s,
    # sized for the reasoning estimate) would let one confused routing call block
    # a run for five minutes without producing any work.
    GRAPH_SUPERVISOR_MODEL: str = "gpt-5-mini"
    GRAPH_SUPERVISOR_TIMEOUT: int = 30
    # How many times the supervisor may dispatch a specialist. This is the
    # STRATEGY; GRAPH_RECURSION_LIMIT below is the safety net. It has to be a
    # counter in the state rather than a recursion limit because LangGraph counts
    # its budget per invoke, so a run that pauses and resumes gets a fresh one.
    GRAPH_MAX_ROUTING_STEPS: int = 8
    # Below this the estimate goes to a human. Deliberately not a module constant:
    # the right threshold is corpus-dependent and gets calibrated against real
    # runs, and one that sends everything to review destroys the reviewer's signal.
    GRAPH_CONFIDENCE_THRESHOLD: float = 0.7
    # How far outside the historical band an estimate may fall before it is sent
    # to a human, as a fraction of the band's own bounds. At 0.25 the trigger
    # fires once roughly a third of the project has no precedent, and it cannot
    # fire on a fully covered estimate: calculate_estimate prices from the same
    # references the band is built from, so the result is inside it by
    # construction. Raising it much past 0.4 makes the trigger unreachable.
    GRAPH_HISTORICAL_BAND_TOLERANCE: float = 0.25

    # --- Session 15 field (commercial proposal) ---------------------------------
    # Prose for a client, from numbers that are already decided: a non-reasoning
    # model is the right tool and gpt-5 at high effort would be paying reasoning
    # tokens to write paragraphs. It reuses GRAPH_LLM_TIMEOUT rather than adding
    # a knob — that value is a deadline, not a delay, so a generous one costs
    # nothing on a call that finishes in seconds.
    GRAPH_PROPOSAL_MODEL: str = "gpt-4o"

    @model_validator(mode="after")
    def validate_at_least_one_api_key(self) -> "Settings":
        """LiteLLM may try either provider via fallback, so we require at least one key."""
        if not self.OPENAI_API_KEY and not self.ANTHROPIC_API_KEY:
            raise ValueError("At least one of OPENAI_API_KEY or ANTHROPIC_API_KEY must be set")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()
