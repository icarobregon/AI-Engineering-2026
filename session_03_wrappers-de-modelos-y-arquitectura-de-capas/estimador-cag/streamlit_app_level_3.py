"""Streamlit chat UI for the Estimador CAG backend (Level 3: streaming + sidebar)."""

import json
import os
import time
import uuid

import httpx
import streamlit as st
import structlog
from dotenv import load_dotenv
from httpx_sse import EventSource

from app.config import settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.logging import get_logger, setup_logging
from app.services.llm_service import _build_system_prompt

load_dotenv()
setup_logging(settings.LOG_LEVEL)
log = get_logger(__name__)


def _resolve_backend_url() -> str:
    try:
        return st.secrets["BACKEND_URL"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.environ.get("BACKEND_URL", "http://localhost:8000")


BACKEND_URL = _resolve_backend_url()
STREAM_ENDPOINT = f"{BACKEND_URL}/api/v1/estimate/stream"
REQUEST_TIMEOUT = 120.0


def stream_estimation_events(transcription: str):
    """Generator yielding text chunks for `st.write_stream`.

    Captures the `meta` event into `st.session_state["last_meta"]` so the
    upcoming Level 3 sidebar can read it. Renders `error` events as a visible
    inline marker after whatever text has already been streamed.
    """
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    log.info("estimation_request_started", transcription_length=len(transcription))
    start = time.perf_counter()
    st.session_state["last_meta"] = None

    try:
        with httpx.stream(
            "POST",
            STREAM_ENDPOINT,
            json={"transcription": transcription},
            headers={"X-Correlation-ID": st.session_state.correlation_id},
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()
            for sse in EventSource(response).iter_sse():
                if sse.event == "delta":
                    yield sse.data
                elif sse.event == "meta":
                    st.session_state["last_meta"] = json.loads(sse.data)
                elif sse.event == "error":
                    yield f"\n\n[ERROR: {sse.data}]"
        log.info(
            "estimation_request_completed",
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            meta=st.session_state.get("last_meta"),
        )
    except httpx.HTTPStatusError as e:
        log.error(
            "estimation_request_failed",
            error_type=type(e).__name__,
            error_msg=str(e),
            status_code=e.response.status_code,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        yield f"\n\n[ERROR {e.response.status_code} del backend: {e.response.text}]"
    except httpx.RequestError as e:
        log.error(
            "estimation_request_failed",
            error_type=type(e).__name__,
            error_msg=str(e),
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        yield f"\n\n[ERROR: no se pudo contactar con el backend en {BACKEND_URL}: {e}]"
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

st.title("Estimador CAG — streaming + contexto")
st.caption(f"Streaming token-a-token vía SSE. Backend: `{BACKEND_URL}`")

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
        events = stream_estimation_events(prompt)
        with st.spinner("Generando estimación..."):
            first = next(events, "")

        def _stream():
            if first:
                yield first
            yield from events

        estimation = st.write_stream(_stream())
    st.session_state.messages.append({"role": "assistant", "content": estimation})

with st.sidebar:
    st.header("Contexto CAG")
    with st.expander("System prompt", expanded=False):
        st.code(_build_system_prompt(), language="markdown")
    with st.expander(f"Ejemplos inyectados ({len(ESTIMATION_EXAMPLES)})", expanded=False):
        for i, ex in enumerate(ESTIMATION_EXAMPLES, 1):
            st.markdown(f"**Ejemplo {i}** — {ex['meeting_summary'][:120]}…")
            st.code(ex["estimation"], language="markdown")

    st.divider()
    st.header("Última llamada")
    meta = st.session_state.get("last_meta")
    if meta:
        st.metric("Modelo", f"{meta['provider']} / {meta['model']}")
        col1, col2 = st.columns(2)
        col1.metric("Tokens in", meta["tokens_in"])
        col2.metric("Tokens out", meta["tokens_out"])
        st.metric("Latencia (ms)", meta["latency_ms"])
    else:
        st.caption("Aún no has hecho ninguna llamada.")
