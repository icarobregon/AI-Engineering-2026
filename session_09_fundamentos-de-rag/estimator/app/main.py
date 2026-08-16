import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.api.embeddings import router as embeddings_router
from app.api.search import router as search_router
from app.api.retrieval import router as retrieval_router
from app.api.estimate_rag import router as estimate_rag_router
from app.api import config as config_api
from app.api import estimations, ingestion, sessions
from app.rate_limit import limiter, rate_limit_handler


def configure_logging() -> None:
    """Set up structlog: JSON in production, human-readable in development."""
    settings = get_settings()

    if settings.APP_ENV == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    configure_logging()
    log = structlog.get_logger()
    settings = get_settings()
    # Session 6: fail fast on a malformed catalog rather than at the first
    # ingestion request. Catalogs are versioned in git; a broken one is a
    # deploy-time problem, not a request-time one.
    try:
        from app.dependencies import get_catalog

        catalog = get_catalog()
        log.info(
            "catalog_loaded",
            version=catalog.version,
            sources_total=len(catalog.sources),
            sources_included=len(catalog.included_sources()),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("catalog_load_failed", error=str(exc)[:400])
    log.info("application_started", environment=settings.APP_ENV)
    yield
    log.info("application_shutdown")


app = FastAPI(
    title="Software Estimation Service",
    description="AI-powered software estimation service with typed input and versioned prompts",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (Session 9). No default limits: only the endpoints that opt in
# with @limiter.limit are throttled, so the Session 2-8 routes keep behaving
# exactly as before.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

app.include_router(estimations.router)
app.include_router(sessions.router)
app.include_router(ingestion.router)
app.include_router(embeddings_router)
app.include_router(search_router)
app.include_router(config_api.router)
# Session 9: the two guarded surfaces, with separate keys and rate limits.
app.include_router(retrieval_router)
app.include_router(estimate_rag_router)


@app.get("/health")
async def health_check() -> dict:
    """Return service health status."""
    settings = get_settings()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.APP_ENV,
    }
