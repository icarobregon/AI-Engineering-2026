# Estimador — Sesión 04

Refactor del estimador de la Sesión 3 hacia un **producto**: el cliente pasa de chat a formulario tipado, el prompt sale del código y vive como artefacto versionado (`app/prompts/estimation/v1/`), y el endpoint `POST /api/v1/estimate` consume un `EstimationRequest` con campos explícitos.

## Bonus opcional implementado

- **`v2/` con calibración conservadora.** Mismo rol y formato que `v1`, pero el system fuerza un margen de seguridad del 25–40%, baja la `confidence_pct` por defecto a 50–70% y exige una sección `### Risks` con 3–5 riesgos por estimación. Selecciónalo vía `?prompt_version=v2`.
- **`reference_projects` server-side.** El backend lee `app/prompts/reference_projects.json`, filtra por `project_type` y inyecta los proyectos coincidentes en un bloque `<reference_projects>` del system. Añadir nuevos casos = editar el JSON y reiniciar la app. No se expone en el formulario Streamlit.
- **Logging del prompt.** Cada render emite un evento structlog `prompt_rendered` con `version`, `prompt_hash` (SHA-256 truncado a 12 chars), `num_references`, `project_type`, `detail_level` y `output_format`.

Ejemplo `curl` con `v2`:

```bash
curl -X POST 'http://localhost:8000/api/v1/estimate?prompt_version=v2' \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Mobile app with login, in-app chat and Stripe checkout for iOS and Android.",
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table"
  }'
```

Versiones desconocidas devuelven `404 { "detail": "Unknown prompt_version: '...'" }`. Versiones que no cumplen el formato `v\d+` se rechazan con `422`.

## Cambios vs. Sesión 3

- `EstimationRequest` ya no acepta `transcription: str`. Acepta `description`, `project_type`, `detail_level`, `output_format`.
- El system prompt se construye renderizando `app/prompts/estimation/v1/{system,user,examples}.j2` con Jinja2 (`StrictUndefined`).
- `EstimationResponse` añade `prompt_version`.
- Eliminado el endpoint `POST /api/v1/estimate/stream` y todo el soporte SSE.
- Streamlit pasa de chat a `st.form` (`streamlit_app.py`, único). Los niveles 1–3 quedan en el branch de la sesión 3.
- `app/context/examples.py` se elimina; los few-shots viven ahora en `examples.j2`.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Instalación

```bash
cd session_04_productos-ia-avanzados/estimador-cag
uv sync
cp .env.example .env   # añade tus API keys
```

## Arrancar local

```bash
# Terminal 1 — backend
uv run uvicorn app.main:app --reload

# Terminal 2 — UI
uv run streamlit run streamlit_app.py
```

Backend: `http://localhost:8000` (docs en `/docs`). UI: `http://localhost:8501`.

## Ejemplo de uso (curl)

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Mobile app with login, chat and push notifications across iOS and Android.",
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table"
  }'
```

## Docker

```bash
docker compose up --build
```

El backend arranca primero; el frontend espera al healthcheck de `/health` antes de levantarse. El `BACKEND_URL` se inyecta como `http://backend:8000` dentro de la red de compose.

## Tests

```bash
uv run pytest -v
```

Los tests de plantilla (`tests/prompts/test_estimation_v1.py`) renderizan los templates sin llamar al LLM — se ejecutan en milisegundos y sirven en CI sin coste de API.

## Estructura relevante

```
app/
├── main.py
├── routers/estimations.py        # POST /api/v1/estimate
├── schemas/estimation.py         # ProjectType, DetailLevel, OutputFormat, EstimationRequest, EstimationResponse
├── services/llm_service.py       # generate_estimation(request) → dict
└── prompts/
    ├── loader.py                 # render_estimation_prompt(request, version="v1")
    ├── references.py             # load_reference_projects(project_type)
    ├── reference_projects.json   # seed de proyectos pasados (server-side)
    └── estimation/
        ├── v1/                   # baseline
        │   ├── system.j2
        │   ├── user.j2
        │   └── examples.j2
        └── v2/                   # calibración conservadora
            ├── system.j2
            ├── user.j2
            └── examples.j2
streamlit_app.py                  # formulario único
tests/
├── prompts/test_estimation_v1.py # composición del prompt (sin API)
├── test_estimations.py
├── test_middleware.py
├── test_configuration.py
└── test_health.py
```

## Variables de entorno

| Variable            | Descripción                                                                           | Por defecto             |
| ------------------- | ------------------------------------------------------------------------------------- | ----------------------- |
| `APP_ENV`           | `local` o `development` o `staging` o `production`                                    | `local`                 |
| `LOG_LEVEL`         | `debug`, `info`, `warning`, `error`, `critical`                                       | `debug`                 |
| `LLM_PROVIDER`      | `openai` o `anthropic`                                                                | `openai`                |
| `LLM_MODEL`         | `gpt-4o-mini` o `claude-haiku-4-5`                                                    | `gpt-4o-mini`           |
| `BACKEND_URL`       | URL que consume Streamlit                                                             | `http://localhost:8000` |
| `OPENAI_API_KEY`    | API key de OpenAI                                                                     | —                       |
| `ANTHROPIC_API_KEY` | API key de Anthropic                                                                  | —                       |

## Fuera de scope (queda para el directo)

- JSON estructurado en la salida (Instructor / `response_model` con Pydantic).
- Guardrails de input (Moderation API, prompt-injection) y output (`model_validator`, LLM-as-judge).
- Cache semántico con Redis + `redisvl`.
