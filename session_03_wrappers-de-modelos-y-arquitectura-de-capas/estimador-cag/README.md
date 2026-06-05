# Estimador CAG

API REST de estimación de proyectos de software usando el patrón **Cache Augmented Generation (CAG)**. El modelo recibe ejemplos reales de estimaciones inyectados en el system prompt para calibrar su salida sin necesidad de fine-tuning.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Instalación

```bash
cd session_03_wrappers-de-modelos-y-arquitectura-de-capas/estimador-cag
uv sync
cp .env.example .env
# Edita .env y añade tus API keys
```

## Arrancar la API

```bash
uv run uvicorn app.main:app --reload
```

La API quedará disponible en `http://localhost:8000`.
Documentación interactiva: `http://localhost:8000/docs`

## Ejemplo de uso

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{"transcription": "El cliente necesita una landing page con formulario de contacto, integración con HubSpot, y blog con editor WYSIWYG. Plazo 4 semanas. Diseño ya existe en Figma."}'
```

## Interfaz Streamlit (Sesión 3 — Nivel 1)

Chat web que envía cada transcripción al endpoint `POST /api/v1/estimate` y muestra la estimación devuelta. Cada mensaje del usuario se trata como una transcripción independiente; el historial se conserva en pantalla pero no se reenvía al LLM.

Requiere el backend arriba en otra terminal:

```bash
# Terminal 1: backend
uv run uvicorn app.main:app --reload

# Terminal 2: interfaz
uv run streamlit run streamlit_app_level_1.py
```

La UI quedará en `http://localhost:8501`. Por defecto apunta a `http://localhost:8000`; para cambiarlo, exporta `BACKEND_URL` o defínelo en `.streamlit/secrets.toml`.

## Interfaz Streamlit (Sesión 3 — Nivel 2)

Misma funcionalidad que el Nivel 1, pero la respuesta del LLM se renderiza token a token (streaming) en lugar de aparecer de golpe. Consume el endpoint `POST /api/v1/estimate/stream` (Server-Sent Events) en lugar del síncrono.

El stream emite tres tipos de eventos: `delta` (fragmentos de texto), `meta` (modelo + tokens + finish_reason, una sola vez al final) y `error` (si la generación falla a mitad). El front renderiza los deltas con `st.write_stream`, guarda el `meta` en `st.session_state["last_meta"]` para uso futuro (sidebar del Nivel 3) e inyecta los errores como marker visible.

```bash
# Terminal 1: backend
uv run uvicorn app.main:app --reload

# Terminal 2: interfaz
uv run streamlit run streamlit_app_level_2.py
```

Smoke test del endpoint vía curl (`-N` desactiva el buffering para ver los eventos llegar progresivamente):

```bash
curl -N -X POST http://localhost:8000/api/v1/estimate/stream \
  -H "Content-Type: application/json" \
  -d '{"transcription": "El cliente necesita una landing page con formulario de contacto y blog. Plazo 4 semanas."}'
```

## Interfaz Streamlit (Sesión 3 — Nivel 3)

Misma funcionalidad de streaming que el Nivel 2 más una `st.sidebar` con visibilidad sobre el contexto CAG y telemetría de la última llamada:

- **System prompt** activo (solo lectura, dentro de un expander).
- **Ejemplos inyectados** desde `app/context/examples.py` (resumen + estimación de cada uno).
- **Última llamada**: provider/modelo, tokens de entrada, tokens de salida y latencia en ms (se rellena tras la primera respuesta).

`latency_ms` se transmite ahora en el evento `meta` del stream junto a `tokens_in`/`tokens_out`/`finish_reason`. El system prompt y los ejemplos se obtienen importando directamente desde `app.services.llm_service` y `app.context.examples` — el front y el backend conviven en el mismo proyecto Python.

```bash
# Terminal 1: backend
uv run uvicorn app.main:app --reload

# Terminal 2: interfaz
uv run streamlit run streamlit_app_level_3.py
```

## Tests

```bash
uv run pytest -v
```

## Variables de entorno

| Variable            | Descripción                                                                           | Por defecto   |
| ------------------- | ------------------------------------------------------------------------------------- | ------------- |
| `APP_ENV`           | `local` o `development` o `staging` o `production`                                    | `local`       |
| `LOG_LEVEL`         | `notset` o `debug` o `info` o `warning` o `warn` o `error` o `exception` o `critical` | `debug`       |
| `LLM_PROVIDER`      | `openai` o `anthropic`                                                                | `openai`      |
| `LLM_MODEL`         | `gpt-4o-mini` o `claude-haiku-4-5`                                                    | `gpt-4o-mini` |
| `BACKEND_URL`       | URL del backend que consume la interfaz Streamlit                                     | `http://localhost:8000` |
| `OPENAI_API_KEY`    | API key de OpenAI                                                                     | —             |
| `ANTHROPIC_API_KEY` | API key de Anthropic                                                                  | —             |
