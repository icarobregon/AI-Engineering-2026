"""Streamlit chat UI for the Estimador CAG backend."""

import os
import time
import uuid

import httpx
import streamlit as st
import structlog
from dotenv import load_dotenv

from app.config import settings
from app.logging import get_logger, setup_logging

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


def request_estimation(transcription: str) -> str:
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    log.info("estimation_request_started", transcription_length=len(transcription))
    start = time.perf_counter()
    try:
        response = httpx.post(
            ESTIMATE_ENDPOINT,
            json={"transcription": transcription},
            headers={"X-Correlation-ID": st.session_state.correlation_id},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        estimation = response.json()["estimation"]
        log.info(
            "estimation_request_completed",
            status_code=response.status_code,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            estimation_length=len(estimation),
        )
        return estimation
    except httpx.HTTPStatusError as e:
        log.error(
            "estimation_request_failed",
            error_type=type(e).__name__,
            error_msg=str(e),
            status_code=e.response.status_code,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return f"Error {e.response.status_code} del backend: {e.response.text}"
    except httpx.RequestError as e:
        log.error(
            "estimation_request_failed",
            error_type=type(e).__name__,
            error_msg=str(e),
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return f"No se pudo contactar con el backend en {BACKEND_URL}: {e}"
    finally:
        structlog.contextvars.unbind_contextvars("request_id")


if "correlation_id" not in st.session_state:
    st.session_state.correlation_id = uuid.uuid4().hex[:8]
    log.info(
        "streamlit_session_started",
        correlation_id=st.session_state.correlation_id,
        backend_url=BACKEND_URL,
    )

structlog.contextvars.bind_contextvars(correlation_id=st.session_state.correlation_id)

st.title("Estimador CAG")
st.caption(f"Pega una transcripción de reunión y recibirás una estimación. Backend: `{BACKEND_URL}`")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Pega aquí la transcripción de la reunión"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Generando estimación..."):
            estimation = request_estimation(prompt)
        st.markdown(estimation)
    st.session_state.messages.append({"role": "assistant", "content": estimation})
