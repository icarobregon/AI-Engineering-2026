"""FastAPI application entry point."""

from fastapi import FastAPI

from app.config import settings
from app.logging import get_logger, setup_logging
from app.routers import estimations

setup_logging(settings.LOG_LEVEL)

log = get_logger(__name__)

app = FastAPI(
    title="Estimador CAG",
    description="API de estimación de proyectos con Cache Augmented Generation",
    version="0.1.0",
)

app.include_router(estimations.router, prefix="/api/v1")

log.info(
    "application_started",
    provider=settings.LLM_PROVIDER,
    model=settings.LLM_MODEL,
    env=settings.APP_ENV,
    log_level=settings.LOG_LEVEL,
)


@app.get("/health")
def health_check() -> dict:
    """Return API health status."""
    log.debug("health_check_called")
    return {"status": "healthy"}
