"""Streamlit conversational UI for the Estimador (Session 05).

Connects to POST /sessions and POST /sessions/{id}/estimate on the FastAPI
backend.  Maintains a session across turns, shows the accumulated
ProjectMetadata in a sidebar panel, and displays the full conversation
history.

The URL of the backend is read from ESTIMATOR_API_BASE_URL (same .env as the
API service), falling back to http://localhost:8000.
"""

from __future__ import annotations

import os
import uuid

import httpx
import streamlit as st
import structlog
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_URL = os.environ.get("ESTIMATOR_API_BASE_URL", "http://localhost:8000").rstrip("/")
SESSIONS_ENDPOINT = f"{BACKEND_URL}/sessions"
REQUEST_TIMEOUT = 120.0

# ---------------------------------------------------------------------------
# Logging (mirrors session_04 approach)
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

PROJECT_TYPE_LABELS = {
    "mobile_app": "Mobile app",
    "web_saas": "Web / SaaS",
    "internal_tool": "Internal tool",
    "data_pipeline": "Data pipeline",
}

DETAIL_LEVEL_LABELS = {
    "summary": "Resumen",
    "medium": "Medio",
    "detailed": "Detallado",
}

OUTPUT_FORMAT_LABELS = {
    "phases_table": "Tabla por fases",
    "line_items": "Lista de items",
    "narrative": "Narrativo",
}

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _create_session() -> str | None:
    """Call POST /sessions and return the session_id, or None on error."""
    try:
        resp = httpx.post(SESSIONS_ENDPOINT, timeout=10.0)
        resp.raise_for_status()
        return resp.json()["session_id"]
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo crear la sesión en {BACKEND_URL}: {exc}")
        return None


def _init_session_state() -> None:
    """Ensure all required keys exist in st.session_state."""
    if "correlation_id" not in st.session_state:
        st.session_state.correlation_id = uuid.uuid4().hex[:8]
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "conversation" not in st.session_state:
        # List of dicts: {"role": "user"|"assistant", ...}
        st.session_state.conversation = []
    if "project_metadata" not in st.session_state:
        st.session_state.project_metadata = {}

    # Auto-create a backend session on first load.
    if st.session_state.session_id is None:
        session_id = _create_session()
        if session_id:
            st.session_state.session_id = session_id
            log.info("session_created", session_id=session_id)


def _new_conversation() -> None:
    """Reset all session state and create a new backend session."""
    st.session_state.session_id = None
    st.session_state.conversation = []
    st.session_state.project_metadata = {}
    _init_session_state()


# ---------------------------------------------------------------------------
# Render helper
# ---------------------------------------------------------------------------


def _render_estimation(data: dict) -> None:
    """Render a structured ConversationEstimateResponse from the API."""
    result = data.get("result", {})
    cached = data.get("cached", False)
    prompt_version = data.get("prompt_version", "?")
    turn = data.get("turn", "?")

    badge = "🟡 caché" if cached else "🟢 nuevo"
    st.markdown(
        f"**Turno {turn}** · prompt `{prompt_version}` · {badge} · "
        f"confianza **{result.get('confidence_pct', '?')}%**"
    )
    st.markdown(f"_{result.get('summary', '')}_")

    phases = result.get("phases", [])
    if phases:
        cols = st.columns([3, 1, 1, 3])
        cols[0].markdown("**Fase**")
        cols[1].markdown("**Semanas**")
        cols[2].markdown("**Coste (€)**")
        cols[3].markdown("**Descripción**")
        for phase in phases:
            c = st.columns([3, 1, 1, 3])
            c[0].write(phase.get("name", ""))
            c[1].write(str(phase.get("duration_weeks", "")))
            c[2].write(f"{phase.get('cost_eur', 0):,}")
            c[3].write(phase.get("summary", ""))

    st.markdown(
        f"**Total:** {result.get('total_cost_eur', 0):,} € · "
        f"{result.get('total_duration_weeks', '?')} semanas"
    )


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Estimador — Sesión 05",
    page_icon="📊",
    layout="wide",
)
st.title("📊 Estimador de proyectos")
st.caption(f"Backend: `{BACKEND_URL}` · Multi-turno con memoria conversacional")

_init_session_state()

# ---------------------------------------------------------------------------
# Sidebar — ProjectMetadata panel + controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Sesión activa")
    if st.session_state.session_id:
        st.code(st.session_state.session_id[:8] + "…", language="text")
    else:
        st.caption("Sin sesión")

    st.divider()

    st.subheader("📋 Contexto del proyecto")
    meta = st.session_state.project_metadata
    if not meta or all(v is None or v == [] for v in meta.values()):
        st.caption("Aún no hay hechos conocidos sobre el proyecto.")
    else:
        if meta.get("project_name"):
            st.markdown(f"**Nombre:** {meta['project_name']}")
        if meta.get("assumed_team_size"):
            st.markdown(f"**Equipo:** {meta['assumed_team_size']} personas")
        if meta.get("agreed_scope"):
            st.markdown(f"**Alcance:** {meta['agreed_scope']}")
        if meta.get("mentioned_technologies"):
            st.markdown("**Tecnologías:** " + ", ".join(meta["mentioned_technologies"]))
        if meta.get("explicit_constraints"):
            st.markdown("**Restricciones:**")
            for c in meta["explicit_constraints"]:
                st.markdown(f"  - {c}")
        if meta.get("rejected_options"):
            st.markdown("**Descartado:**")
            for r in meta["rejected_options"]:
                st.markdown(f"  - {r}")

    st.divider()

    st.subheader("⚙️ Configuración")
    primary = os.getenv("PRIMARY_MODEL", "gpt-4o-mini")
    fallback = os.getenv("FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    st.markdown(f"**Modelo primario:** `{primary}`")
    st.markdown(f"**Fallback:** `{fallback}`")

    st.divider()
    if st.button("🔄 Nueva conversación", use_container_width=True):
        _new_conversation()
        st.rerun()

# ---------------------------------------------------------------------------
# Conversation history display
# ---------------------------------------------------------------------------

for entry in st.session_state.conversation:
    if entry["role"] == "user":
        with st.chat_message("user"):
            st.markdown(entry["content"])
    else:
        with st.chat_message("assistant"):
            _render_estimation(entry["data"])

# ---------------------------------------------------------------------------
# Input form
# ---------------------------------------------------------------------------

with st.expander("📝 Nueva estimación", expanded=not st.session_state.conversation):
    with st.form("estimation_form", clear_on_submit=True):
        description = st.text_area(
            "Transcripción / descripción del proyecto",
            placeholder="Describe el alcance, módulos, integraciones y restricciones…",
            height=180,
        )
        uploaded_files = st.file_uploader(
            "Adjuntos (PDF o DOCX, opcional)",
            type=["pdf", "docx"],
            accept_multiple_files=True,
            help="El texto de los documentos se extrae localmente y se añade al contexto.",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            project_type = st.selectbox(
                "Tipo de proyecto",
                options=list(PROJECT_TYPE_LABELS.keys()),
                format_func=lambda v: PROJECT_TYPE_LABELS[v],
                index=1,
            )
        with col2:
            detail_level = st.selectbox(
                "Nivel de detalle",
                options=list(DETAIL_LEVEL_LABELS.keys()),
                format_func=lambda v: DETAIL_LEVEL_LABELS[v],
                index=1,
            )
        with col3:
            output_format = st.selectbox(
                "Formato de salida",
                options=list(OUTPUT_FORMAT_LABELS.keys()),
                format_func=lambda v: OUTPUT_FORMAT_LABELS[v],
            )

        submitted = st.form_submit_button("Generar estimación ▶", type="primary")

# ---------------------------------------------------------------------------
# Form submission
# ---------------------------------------------------------------------------

if submitted:
    if not st.session_state.session_id:
        st.error("No hay sesión activa. Recarga la página.")
    elif len(description.strip()) < 20:
        st.error("La descripción debe tener al menos 20 caracteres.")
    else:
        session_id = st.session_state.session_id
        form_data = {
            "description": description.strip(),
            "project_type": project_type,
            "detail_level": detail_level,
            "output_format": output_format,
        }
        files_payload = [
            ("files", (f.name, f.read(), f.type or "application/octet-stream"))
            for f in (uploaded_files or [])
        ]
        log.info(
            "conversation_estimate_request",
            session_id=session_id[:8],
            description_chars=len(description),
            attachments=len(files_payload),
        )
        with st.spinner("Generando estimación…"):
            try:
                resp = httpx.post(
                    f"{SESSIONS_ENDPOINT}/{session_id}/estimate",
                    data=form_data,
                    files=files_payload if files_payload else None,
                    headers={"X-Correlation-ID": st.session_state.correlation_id},
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                body = resp.json()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.json().get("detail", exc.response.text)
                st.error(f"Error {exc.response.status_code}: {detail}")
                body = None
            except httpx.RequestError as exc:
                st.error(f"No se pudo contactar con el backend: {exc}")
                body = None

        if body:
            # Append user turn to local history.
            user_label = description.strip()
            if files_payload:
                user_label += f"\n_({len(files_payload)} adjunto(s))_"
            st.session_state.conversation.append({"role": "user", "content": user_label})

            # Append assistant turn.
            st.session_state.conversation.append({"role": "assistant", "data": body})

            # Update sidebar metadata.
            st.session_state.project_metadata = body.get("project_metadata", {})

            log.info(
                "conversation_estimate_completed",
                session_id=session_id[:8],
                turn=body.get("turn"),
                cached=body.get("cached"),
            )
            st.rerun()
