"""Streamlit form UI for the Estimador product (Session 04: form, not chat)."""

import os
import uuid

import httpx
import streamlit as st
import structlog
from dotenv import load_dotenv

from app.config import settings
from app.logging import get_logger, setup_logging
from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType

load_dotenv()
setup_logging(settings.LOG_LEVEL)
log = get_logger(__name__)


def _resolve_backend_url() -> str:
    try:
        return st.secrets["BACKEND_URL"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.environ.get("BACKEND_URL", "http://localhost:8000")


BACKEND_URL = _resolve_backend_url()
ESTIMATE_ENDPOINT = f"{BACKEND_URL}/api/v1/estimate"
REQUEST_TIMEOUT = 120.0


if "correlation_id" not in st.session_state:
    st.session_state.correlation_id = uuid.uuid4().hex[:8]
    log.info(
        "streamlit_session_started",
        correlation_id=st.session_state.correlation_id,
        backend_url=BACKEND_URL,
    )

structlog.contextvars.bind_contextvars(correlation_id=st.session_state.correlation_id)


PROJECT_TYPE_LABELS = {
    ProjectType.MOBILE_APP: "Mobile app",
    ProjectType.WEB_SAAS: "Web / SaaS",
    ProjectType.INTERNAL_TOOL: "Internal tool",
    ProjectType.DATA_PIPELINE: "Data pipeline",
}

DETAIL_LEVEL_LABELS = {
    DetailLevel.SUMMARY: "Resumen",
    DetailLevel.MEDIUM: "Medio",
    DetailLevel.DETAILED: "Detallado",
}

OUTPUT_FORMAT_LABELS = {
    OutputFormat.PHASES_TABLE: "Tabla por fases",
    OutputFormat.LINE_ITEMS: "Lista de items",
    OutputFormat.NARRATIVE: "Narrativo",
}


st.title("Estimador — formulario de proyecto")
st.caption(f"Backend: `{BACKEND_URL}`")

with st.form("estimation_form"):
    description = st.text_area(
        "Descripción del proyecto",
        placeholder="Describe el alcance, módulos, integraciones y restricciones del proyecto…",
        height=200,
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        project_type = st.selectbox(
            "Tipo de proyecto",
            options=list(ProjectType),
            format_func=lambda v: PROJECT_TYPE_LABELS[v],
        )
    with col2:
        detail_level = st.selectbox(
            "Nivel de detalle",
            options=list(DetailLevel),
            format_func=lambda v: DETAIL_LEVEL_LABELS[v],
            index=1,
        )
    with col3:
        output_format = st.selectbox(
            "Formato de salida",
            options=list(OutputFormat),
            format_func=lambda v: OUTPUT_FORMAT_LABELS[v],
        )
    submitted = st.form_submit_button("Generar estimación")


if submitted:
    payload = {
        "description": description,
        "project_type": project_type.value,
        "detail_level": detail_level.value,
        "output_format": output_format.value,
    }
    log.info(
        "estimation_request_started",
        project_type=payload["project_type"],
        detail_level=payload["detail_level"],
        output_format=payload["output_format"],
        description_length=len(description),
    )
    try:
        with st.spinner("Generando estimación..."):
            response = httpx.post(
                ESTIMATE_ENDPOINT,
                json=payload,
                headers={"X-Correlation-ID": st.session_state.correlation_id},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        st.session_state["last_response"] = data
        log.info(
            "estimation_request_completed",
            model=data.get("model"),
            provider=data.get("provider"),
            prompt_version=data.get("prompt_version"),
        )
    except httpx.HTTPStatusError as e:
        log.error(
            "estimation_request_failed",
            status_code=e.response.status_code,
            error_msg=str(e),
        )
        st.error(f"Backend devolvió {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        log.error("estimation_request_failed", error_type=type(e).__name__, error_msg=str(e))
        st.error(f"No se pudo contactar con el backend en {BACKEND_URL}: {e}")


last = st.session_state.get("last_response")
if last:
    st.markdown(last["estimation"])

with st.sidebar:
    st.header("Última llamada")
    if last:
        st.metric("Modelo", f"{last['provider']} / {last['model']}")
        st.metric("Versión del prompt", last["prompt_version"])
    else:
        st.caption("Aún no has hecho ninguna llamada.")
