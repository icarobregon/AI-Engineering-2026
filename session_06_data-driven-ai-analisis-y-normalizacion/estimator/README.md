# Estimator — Servicio IA de estimación de software

Servicio IA en FastAPI que estima proyectos de software a partir de un formulario tipado. Es la pieza Python del programa **Master en AI Engineering**: un endpoint pensado para ser consumido por un backend de negocio (Rails, Streamlit u otro), no por un usuario final.

A partir de la **Sesión 04** el contrato es deliberadamente estrecho:

- entrada tipada (`description` + tres enums),
- salida en texto libre,
- prompt fuera del código en templates Jinja2 versionados (`app/prompts/<use_case>/<version>/`).

La inteligencia adicional (output estructurado, guardrails, cache semántico) se construye encima de esta base en directo.

## Cómo levantar

### Con Docker (recomendado)

```bash
cd estimator
cp .env.example .env  # añade al menos OPENAI_API_KEY o ANTHROPIC_API_KEY
docker compose up --build
```

El servicio queda en `http://localhost:8000` (Swagger en `/docs`, health en `/health`). Redis arranca como servicio vecino para el cache exact-match del wrapper.

### Sin Docker

```bash
cd estimator
uv sync
uv run uvicorn app.main:app --reload
```

### Probar el endpoint transaccional (v1)

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "description": "A small B2B SaaS to manage employee equipment loans across teams. Role-based access, audit trail, weekly digest.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table"
  }'
```

Respuesta:

```json
{
  "result": {
    "summary": "…",
    "phases": [{ "name": "…", "duration_weeks": 4, "cost_eur": 20000, "summary": "…" }],
    "total_duration_weeks": 8,
    "total_cost_eur": 40000,
    "confidence_pct": 72
  },
  "prompt_version": "v1",
  "cached": false
}
```

### Cliente Streamlit (interfaz conversacional)

El cliente Streamlit mantiene sesiones conversacionales: crea una sesión al arrancar y envía cada estimación como `multipart/form-data` al endpoint `/sessions/{id}/estimate`. Corre fuera de Docker y consume la API por HTTP:

```bash
cd estimator
uv run streamlit run streamlit_app.py
# Abrir http://localhost:8501
```

La URL del servicio se lee de `ESTIMATOR_API_BASE_URL` (default `http://localhost:8000`).

> **Nota:** el cliente Streamlit usa el endpoint conversacional (`/sessions`), no el transaccional (`/api/v1/estimate`). Para el flujo conversacional completo con httpie ver la sección «Sesión 5» más abajo.

## Cómo testar

```bash
cd estimator
uv run pytest
```

La batería corre sin tocar APIs externas (200 tests en ~12 s). Categorías principales:

- `tests/test_schemas.py` — validaciones del `EstimationRequest`.
- `tests/test_prompts.py` / `test_prompts_v3.py` — render de templates Jinja2.
- `tests/test_estimate_endpoint.py` — endpoint v1 con servicio mockeado.
- `tests/test_llm_wrapper.py` / `tests/test_cache.py` / `tests/test_cache_semantic.py` — wrapper, exact-match cache y semantic cache.
- `tests/test_sessions_*.py` — pipeline conversacional (metadata, adjuntos, ventana, ACB).
- `tests/test_guardrails_*.py`, `tests/test_critic.py`, `tests/test_boss_orchestration.py` — guardrails y orquestador.
- `tests/test_stress_metrics.py` — métricas del stress test (LatencyBudget, CostBudget, MemoryDrift).
- `tests/test_dependencies.py` / `tests/test_estimation_service.py` — factories de DI y pipeline de estimación.

## Estructura del proyecto

```
estimator/
├── app/
│   ├── main.py                        # FastAPI app, CORS, lifespan, /health
│   ├── config.py                      # Settings (Pydantic Settings, .env)
│   ├── dependencies.py                # Singletons cacheados con lru_cache
│   ├── routers/
│   │   ├── estimations.py             # POST /api/v1/estimate (transaccional)
│   │   └── sessions.py                # POST /sessions, POST /sessions/{id}/estimate
│   ├── schemas/
│   │   ├── estimation.py              # EstimationRequest/Response, enums, ACBResponse
│   │   ├── acb.py                     # ACBResponse y tipos del orquestador Boss
│   │   └── critic.py                  # CriticFeedback
│   ├── prompts/
│   │   ├── loader.py                  # Jinja2 + render_estimation_prompt / render_conversational_prompt
│   │   └── estimation/v1/, v2/, v3/   # Templates versionados
│   ├── attachments/
│   │   └── extractor.py               # Extracción local PDF/DOCX (Camino B)
│   ├── cache/
│   │   └── semantic.py                # Vector cache (redisvl + Redis Stack)
│   ├── guardrails/
│   │   ├── input.py                   # check_input: moderación + prompt injection + PII
│   │   └── output.py                  # enforce_scope_response
│   ├── sessions/
│   │   ├── models.py                  # Session, ProjectMetadata, ConversationHistory
│   │   ├── store.py                   # SessionStore (dict en memoria)
│   │   ├── tier_resolver.py           # Tier dinámico (executive/technical/default)
│   │   ├── metadata_extractor.py      # Segunda llamada LLM por turno
│   │   └── compression/               # Anclas, política, summarizer
│   └── services/
│       ├── llm_wrapper.py             # LiteLLM Router + Instructor + cost tracking
│       ├── cache.py                   # Redis exact-match cache
│       ├── estimation.py              # Pipeline principal (estimate / estimate_conversational)
│       ├── critic.py                  # Crítico del patrón ACB
│       └── boss.py                    # Orquestador Actor-Critic-Boss
├── evals/
│   ├── metrics.py                     # MetricResult + métricas golden (exactitud, coherencia…)
│   └── stress/
│       ├── scenarios.py               # Perfiles growing / pivot / contradiction
│       ├── fixtures.py                # generate_pdf_bytes + ATTACHMENT_SIZES_KB
│       ├── metrics.py                 # LatencyBudgetMetric, CostBudgetMetric, MemoryDriftMetric
│       ├── run.py                     # Runner CLI → results.csv + REPORT.md
│       └── REPORT.md                  # Generado al ejecutar el runner
├── tests/                             # 200 tests unitarios e integración
├── streamlit_app.py                   # UI conversacional → /sessions/{id}/estimate
├── Dockerfile                         # Multi-stage con uv
├── docker-compose.yml                 # estimator + redis-stack
└── pyproject.toml
```

### Versionado de prompts

La estructura `app/prompts/<use_case>/<version>/` no es opcional: `v1/` ya existe desde el primer día porque versionar un prompt es la forma más barata de habilitar A/B testing y rollback en producción. Cuando una iteración del prompt se cocina, se crea `v2/` al lado y `render_estimation_prompt(request, version="v2")` lo recoge sin tocar router ni schemas.

Lo que vive **fuera** del template (en código): el contrato (`EstimationRequest`), el switch de versión y el wrapper. Todo lo demás (rol del modelo, reglas, ejemplos, formatos de salida, niveles de detalle) vive dentro del `.j2`. Si para cambiar el comportamiento del modelo hay que tocar Python, la separación está rota.

## Variables de entorno

| Variable                        | Default                     | Notas                                         |
| ------------------------------- | --------------------------- | --------------------------------------------- |
| `OPENAI_API_KEY`                | —                           | Requerido al menos uno de los dos             |
| `ANTHROPIC_API_KEY`             | —                           | Requerido al menos uno de los dos             |
| `PRIMARY_MODEL`                 | `gpt-4o-mini`               | Modelo principal del Router                   |
| `FALLBACK_MODEL`                | `claude-haiku-4-5-20251001` | Se usa si el primario falla                   |
| `REDIS_URL`                     | `redis://localhost:6379`    | Cache exact-match y Redis Stack               |
| `CACHE_TTL`                     | `86400`                     | TTL del cache exact-match (segundos)          |
| `APP_ENV`                       | `development`               | Controla el renderer de structlog             |
| `ESTIMATOR_API_BASE_URL`        | `http://localhost:8000`     | Lo lee el cliente Streamlit                   |
| `MAX_CONVERSATION_TURNS`        | `6`                         | Pares user+assistant en la ventana deslizante |
| `MAX_ATTACHMENT_CHARS`          | `60000`                     | Corte de texto extraído por adjunto           |
| `METADATA_EXTRACTOR_MODEL`      | `gpt-4o-mini`               | Segunda llamada LLM por turno                 |
| `COMPRESSION_MODEL`             | `gpt-4o-mini`               | Modelo del summarizer y extractor de anclas   |
| `ANCHOR_DETECTION_MODE`         | `heuristic`                 | `heuristic` o `llm`                           |
| `CONVERSATIONAL_PROMPT_VERSION` | `v3`                        | Versión del template conversacional           |
| `CRITIC_MODEL`                  | `gpt-4o-mini`               | Modelo del Crítico (patrón ACB)               |
| `BOSS_MAX_ITERATIONS`           | `2`                         | Iteraciones máximas del Boss                  |
| `EMBEDDING_MODEL`               | `text-embedding-3-small`    | Embeddings del cache semántico                |
| `SEMANTIC_CACHE_THRESHOLD`      | `0.92`                      | Similitud coseno mínima para hit semántico    |
| `SEMANTIC_CACHE_TTL`            | `86400`                     | TTL del cache semántico (segundos)            |
| `SEMANTIC_CACHE_LOG_ONLY`       | `false`                     | Si `true`, mide sin servir desde caché        |

`get_settings()` es un singleton cacheado con `lru_cache`: cualquier cambio en `.env` requiere reiniciar uvicorn (no basta con `--reload`).

---

## Sesión 5 — Memoria conversacional y adjuntos

A partir de la Sesión 05 el estimator deja de ser puramente transaccional y soporta **sesiones conversacionales**: el cliente puede refinar el alcance del proyecto a lo largo de varios turnos, subir documentos (PDF/Word) y el sistema recuerda el proyecto en curso entre llamadas. El endpoint `POST /api/v1/estimate` original se mantiene intacto para compatibilidad y para la demo transaccional.

### Endpoints nuevos

```
POST /sessions                              → 201 {"session_id": "<uuid>"}
GET  /sessions/{session_id}                 → 200 {session_id, message_count, max_turns, metadata}
POST /sessions/{session_id}/estimate        → 200 EstimationResponse
   (multipart/form-data: transcript, project_type, detail_level, output_format, attachments[])
```

Ejemplo end-to-end con httpie:

```bash
http POST :8000/sessions
# {"session_id": "abc-123"}

http -f POST :8000/sessions/abc-123/estimate \
  transcript="Queremos estimar un CRM llamado Nimbus en React + Postgres para el equipo de ventas." \
  project_type=web_saas detail_level=medium output_format=phases_table \
  attachments@spec.pdf

http GET :8000/sessions/abc-123
# Inspecciona el ProjectMetadata acumulado y el tamaño del historial.
```

Y un segundo turno reutilizando el mismo `session_id` sin repetir el contexto:

```bash
http -f POST :8000/sessions/abc-123/estimate \
  transcript="Añade un módulo de facturación con Stripe." \
  project_type=web_saas detail_level=medium output_format=phases_table
```

La respuesta del segundo turno integra Nimbus + React + Postgres + facturación porque el `<project_metadata>` se inyecta en el system prompt y el historial reciente viaja en el array `messages`.

### Decisiones de diseño

1. **Camino B para los adjuntos.** Extraemos el texto del PDF/Word **dentro del servicio IA** con `pypdf` y `python-docx`, lo recortamos a `MAX_ATTACHMENT_CHARS` y lo concatenamos al transcript con fences explícitos (`--- attachment: spec.pdf ---`). La alternativa (Camino A: subir el binario a la Files API de OpenAI o Anthropic) habría sido más corta de implementar pero acopla el wrapper a un proveedor multimodal concreto. Camino B mantiene `complete_structured_chat` agnóstico de proveedor (texto en, texto fuera vía LiteLLM Router + Instructor) y prepara el terreno para el chunking real de RAG en el módulo 3. La extracción es robusta a páginas corruptas (fallos por página se loguean y se ignoran) y a archivos vacíos.

2. **`project_metadata` con extractor LLM, no heurística.** Tras cada respuesta del estimador, una **segunda llamada** al LLM (modelo barato configurable vía `METADATA_EXTRACTOR_MODEL`, por defecto `gpt-4o-mini`) lee el último turno y devuelve un `ProjectMetadata` parcial vía Instructor. Lo fusionamos con el previo: campos escalares sobrescriben si vienen no-nulos, la lista de tecnologías se une case-insensitively. Se eligió el extractor LLM frente a una heurística regex porque el coste de una llamada con prompt corto es marginal y la robustez frente a paráfrasis del usuario es mucho mejor — y porque el curso enseña precisamente cómo construir estos pasos con LLMs. Si la llamada falla, se loguea y se conserva la metadata previa: la conversación no se cae por una extracción rota.

3. **Memoria en proceso, no Redis ni Postgres.** El `SessionStore` es un `dict` en memoria del worker FastAPI. La volatilidad (estado perdido al reiniciar el contenedor) es **intencional** para esta fase y está documentada en el docstring del store. La persistencia entre reinicios entra en el directo cuando hablemos de compresión de memoria con anclas.

4. **Cachés desactivadas en el path conversacional.** Cada turno depende del historial + metadata + adjuntos: dos transcripciones idénticas en sesiones distintas **no** son la misma llamada. El método nuevo `EstimationService.estimate_conversational` por tanto no consulta ni el cache exact-match ni el semántico, y `EstimationResponse.cached` siempre es `false` en este path. El endpoint transaccional original `POST /api/v1/estimate` sigue usando las dos cachés sin cambios.

5. **Ventana deslizante con `MAX_CONVERSATION_TURNS=6` por defecto.** El system prompt se regenera fresco cada turno desde el `ProjectMetadata` actual, así que no consume slot. Lo que llega al LLM en el turno N es: `[system_v2] + últimos N pares (user, assistant) + nuevo user`. Cuando el historial supera el tope, los pares más antiguos se descartan en bloque para preservar la alternancia de roles. El siguiente paso (resumen acumulativo + anclas) lo construimos en el directo.

### Variables de entorno nuevas

| Variable                   | Default       | Notas                                           |
| -------------------------- | ------------- | ----------------------------------------------- |
| `MAX_CONVERSATION_TURNS`   | `6`           | Pares user+assistant que mantiene la ventana.   |
| `MAX_ATTACHMENT_CHARS`     | `60000`       | Corte por archivo extraído. Trunca, no rechaza. |
| `METADATA_EXTRACTOR_MODEL` | `gpt-4o-mini` | Modelo de la segunda llamada por turno.         |

### Tests del Paso 7

```bash
uv run pytest tests/test_sessions_metadata.py tests/test_sessions_attachments.py tests/test_sessions_window.py -v
```

Los tres tests son de integración con `TestClient`, un `FakeLLMWrapper` que captura cada llamada y devuelve resultados scripted, y un `SessionStore` aislado por test (sin singleton). Cubren los tres criterios del enunciado: dos turnos acumulan metadata, el contenido de un PDF llega al `messages` del LLM, y enviar más turnos que `MAX_CONVERSATION_TURNS` nunca infla el array de mensajes más allá del límite.
