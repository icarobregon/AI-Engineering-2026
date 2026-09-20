# Estimator — Servicio IA de estimación de software

Servicio IA en FastAPI que estima proyectos de software a partir de un formulario tipado. Es la pieza Python del programa **Master en AI Engineering**: un endpoint pensado para ser consumido por un backend de negocio (Rails, Streamlit u otro), no por un usuario final.

A partir de la **Sesión 04** el contrato es deliberadamente estrecho:
- entrada tipada (`description` + tres enums),
- salida estructurada y validada (`EstimationResult` vía Instructor + Pydantic),
- prompt fuera del código en templates Jinja2 versionados (`app/foundation/prompts/<use_case>/<version>/`).

La inteligencia adicional (output estructurado, guardrails, cache semántico) se construye encima de esta base en directo.

## Cómo levantar

### Con Docker (recomendado)

```bash
cd ..                 # el compose vive en la raíz de la carpeta de la sesión
cp estimator/.env.example estimator/.env   # al menos OPENAI_API_KEY o ANTHROPIC_API_KEY
cp .env.example .env                       # secreto de servicio y credenciales de Postgres
docker compose up --build
```

Desde la Sesión 15 el servicio IA **no publica puerto al host**: es alcanzable solo desde la red interna, por nombre de servicio (`http://ai-service:8000`) y con la cabecera `X-API-Key`. El punto de entrada público es `http://localhost:3000`, el backend de negocio. Para hablar con la API a mano:

```bash
docker compose exec business-backend curl -sS http://ai-service:8000/health
```

### Sin Docker

```bash
cd estimator
uv sync
uv run uvicorn app.main:app --reload
```

### Probar el endpoint

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ESTIMATE_API_KEY" \
  -d '{
    "description": "A small B2B SaaS to manage employee equipment loans across teams. Role-based access, audit trail, weekly digest.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table"
  }'
```

Desde la **Sesión 15** el endpoint exige el token de servicio (`require_estimate_key`).
Sin la cabecera responde 401, y con `ESTIMATE_API_KEY` en blanco responde 401 a todo.

Respuesta:

```json
{
  "result": {
    "summary": "…",
    "confidence_pct": 75,
    "phases": [
      { "name": "Discovery", "duration_weeks": 2, "cost_eur": 5000, "summary": "…" }
    ],
    "total_duration_weeks": 13,
    "total_cost_eur": 35250
  },
  "prompt_version": "v1",
  "cached": false
}
```

`total_cost_eur` es un `@computed_field`: se deriva de las fases y no se le pide al
modelo, así que no puede descuadrar. Instructor no lo incluye en el tool schema, de
modo que el modelo ni lo ve.

### Cliente Streamlit

El cliente Streamlit es un formulario que construye el JSON y muestra el resultado recibido. Corre fuera de Docker y consume la API por HTTP:

```bash
cd estimator
uv run streamlit run streamlit_app.py
# Abrir http://localhost:8501
```

La URL del servicio se lee de `ESTIMATOR_API_BASE_URL` (default `http://localhost:8000`),
y desde la Sesión 15 necesita además `ESTIMATE_API_KEY`, que envía como cabecera
`X-API-Key`. Sin ella el formulario recibe 401.

## Cómo testar

```bash
cd estimator
uv run pytest
```

La batería corre en milisegundos sin tocar APIs externas. Cubre cuatro categorías:

- `tests/test_schemas.py` — validaciones del `EstimationRequest` (longitudes, enums, campos obligatorios).
- `tests/test_prompts.py` — render del template `v1`: `description` aparece dentro de `<project_description>`, los bloques condicionales por `output_format` y `detail_level` solo se incluyen cuando aplica, y `StrictUndefined` falla early ante variables faltantes.
- `tests/test_estimate_endpoint.py` — endpoint con el wrapper LLM mockeado vía `app.dependency_overrides`: comprueba el contrato 200/422, que `system_prompt` y `user_message` viajan separados, y que la respuesta lleva `prompt_version="v1"`.
- `tests/test_llm_wrapper.py` y `tests/test_cache.py` — wrapper y cache de la Sesión 03, intactos.

## Estructura del proyecto

```
estimator/
├── app/
│   ├── main.py                        # FastAPI app, CORS, lifespan, /health
│   ├── config.py                      # Settings (Pydantic Settings, .env) + AVAILABLE_MODELS
│   ├── dependencies.py                # composition root: wiring de todos los singletons
│   ├── api/                           # TRANSPORTE — routers finos
│   │   ├── estimations.py             #   POST /api/v1/estimate (exige X-API-Key)
│   │   ├── sessions.py                #   S05 — conversación con memoria y ACB
│   │   ├── embeddings.py              #   S07/S08 — troceado, ingest y búsqueda
│   │   ├── config.py                  #   GET/PUT /api/v1/config/models
│   │   ├── security.py                #   require_estimate_key / require_retrieval_key
│   │   └── routers/                   #   S09-S14 — estimate, stages, tasks, retrieval, graph
│   ├── domain/                        # EL CONTRATO Y LOS CONDUCTORES
│   │   ├── schemas/estimation.py      #   EstimationRequest/Result/Response, TurnObservation
│   │   ├── estimation_service.py      #   conductor CAG/RAG/ACB (S04-S11)
│   │   ├── graph/                     #   conductor multi-agente (S13-S14)
│   │   └── security/                  #   privilegios de tool, guard y auditoría
│   ├── foundation/                    # PLOMERÍA, sin opinión de arquitectura AI
│   │   ├── llm/wrapper.py             #   LiteLLM + Instructor + MODEL_COSTS
│   │   ├── llm/runtime_config.py      #   overrides de modelo en Redis
│   │   ├── prompts/                   #   loader Jinja2 + plantillas versionadas
│   │   ├── guardrails/                #   input (moderación+injection+PII) / output
│   │   ├── attachments/               #   extracción de texto de PDF/DOCX
│   │   └── persistence/               #   engine SQLAlchemy + repositories
│   ├── generation/                    # LAS TRES ARQUITECTURAS
│   │   ├── cag/                       #   cache exacta + semántica
│   │   ├── rag/                       #   chunking, retrieval, generación citada
│   │   ├── agentic/                   #   Actor-Critic-Boss y el agente a mano (S12)
│   │   └── conversation/              #   ventana, anclas, resumen, metadata
│   └── ingestion/                     # pipeline offline que alimenta RAG
├── tests/                             # batería sin red ni clave
├── alembic/                           # migraciones del esquema del servicio IA
├── data/                              # corpus de muestra
├── scripts/                           # siembra del corpus y runners de sesión
├── streamlit_app.py                   # Formulario que consume /api/v1/estimate
├── Dockerfile                         # Multi-stage con uv
└── pyproject.toml
```

El contrato completo de capas —quién puede importar a quién— vive en
[`ARCHITECTURE.md`](ARCHITECTURE.md), que es normativo.

### Versionado de prompts

La estructura `app/foundation/prompts/<use_case>/<version>/` no es opcional: `v1/` ya existe desde el primer día porque versionar un prompt es la forma más barata de habilitar A/B testing y rollback en producción. Cuando una iteración del prompt se cocina, se crea `v2/` al lado y `render_estimation_prompt(request, version="v2")` lo recoge sin tocar router ni schemas.

Lo que vive **fuera** del template (en código): el contrato (`EstimationRequest`), el switch de versión y el wrapper. Todo lo demás (rol del modelo, reglas, ejemplos, formatos de salida, niveles de detalle) vive dentro del `.j2`. Si para cambiar el comportamiento del modelo hay que tocar Python, la separación está rota.

## Variables de entorno

| Variable | Default | Notas |
|---|---|---|
| `OPENAI_API_KEY` | — | Requerido al menos uno de los dos |
| `ANTHROPIC_API_KEY` | — | Requerido al menos uno de los dos |
| `PRIMARY_MODEL` | `gpt-4o-mini` | Modelo principal del Router |
| `FALLBACK_MODEL` | `claude-haiku-4-5-20251001` | Se usa si el primario falla |
| `REDIS_URL` | `redis://localhost:6379` | Cache exact-match |
| `CACHE_TTL` | `86400` | Segundos |
| `APP_ENV` | `development` | Controla el renderer de structlog |
| `ESTIMATE_API_KEY` | — | **Obligatoria desde la S15.** Token (`X-API-Key`) de todas las rutas de estimación (incluida `POST /api/v1/estimate`), de `/sessions/*`, de `/embeddings/*`, de `/api/v1/config/*` y de `/api/v1/ingestion/*`. En blanco ⇒ 401 en todas. Bajo Compose la inyecta `AI_SERVICE_TOKEN` del `.env` de la raíz de la sesión |
| `RETRIEVAL_API_KEY` | — | Token de `/v1/retrieval/search`, `/v1/retrieval/advanced-search` y de la `POST /search` de la S08, que lleva la misma clave que su sustituta |

`/health` es la única ruta abierta, y a propósito: cerrarla mataría el healthcheck de Docker.
| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | Lo lee el cliente Streamlit |

`get_settings()` es un singleton cacheado con `lru_cache`: cualquier cambio en `.env` requiere reiniciar uvicorn (no basta con `--reload`). **Excepción: los modelos LLM** — ver la sección siguiente.

## Configuración de modelos en runtime

Los knobs de modelo (`PRIMARY_MODEL`, `FALLBACK_MODEL`, `CRITIC_MODEL`, `METADATA_EXTRACTOR_MODEL`, `COMPRESSION_MODEL`, `PROPOSITIONAL_CHUNKER_MODEL`, `CONTEXTUAL_CHUNKER_MODEL`) se pueden **sobreescribir en caliente** sin tocar `.env` ni recrear contenedores — pensado para cambiar de modelo en mitad de un directo.

```
GET /api/v1/config/models
  → {"models": {KEY: {"effective", "default", "overridden"}},
     "available_models": [...],
     "embedding_model": "...", "embedding_model_note": "...",
     "catalog_generated_at": "2026-09-20T01:14:55+02:00",
     "catalog_sources": ["OpenAI", "Anthropic"],
     "model_prices": {MODEL: {"input": 0.15, "output": 0.60}}}   # US$ por millón de tokens

PUT /api/v1/config/models
  Body: {"models": {"PRIMARY_MODEL": "gpt-4o", "CRITIC_MODEL": null}}   # null = reset
  → mismo shape que el GET (snapshot fresco)
  422 key desconocida / modelo fuera de catálogo · 400 modelo sin API key · 503 Redis caído
```

Cómo funciona (`app/foundation/llm/runtime_config.py`):

- Los overrides viven en un hash de Redis (`estimator:runtime_config`): **sobreviven a `--reload` y reinicios**, y todos los workers los ven al instante. `.env` sigue siendo la capa de defaults.
- El wrapper y el servicio resuelven el modelo **por llamada** (properties), así que el cambio aplica en la siguiente petición. El catálogo (`AVAILABLE_MODELS`) se filtra por las API keys configuradas.
- Con un override de primario activo no hay fallback automático de provider (misma semántica que `model_override`: llamada directa, sin Router).
- Las caches se particionan por modelo (la exacta ya lo hacía; la semántica incluye el modelo en su bucket desde este cambio), así que cambiar de modelo nunca sirve respuestas generadas por otro.
- `EMBEDDING_MODEL` queda fuera a propósito: cambiarlo invalidaría todos los vectores almacenados.

**El catálogo se cura a mano, y por eso dice cuándo se hizo.** `AVAILABLE_MODELS`
(`app/config.py`, 38 entradas) va en lockstep con `MODEL_COSTS`
(`app/foundation/llm/wrapper.py`, 40 filas — las dos de más son alias fechados, que
necesitan fila propia porque el precio se busca por el nombre que se pide). Un
modelo añadido sólo al primero es seleccionable y **se factura a cero en silencio**:
`_estimate_cost` cae a `{"input": 0.0, "output": 0.0}` por defecto. No es «todo lo
que la clave alcanza» —las claves alcanzan bastante más—, y el filtro del endpoint
sólo comprueba que la variable del proveedor no esté vacía, nunca que esa clave
pueda servir ese modelo.

Por eso viaja con su procedencia: `MODEL_CATALOG_GENERATED_AT` y
`MODEL_CATALOG_SOURCES`, que la pantalla de Ajustes pinta tal cual. Regenerarlo es
una tarea explícita: consultar `GET /v1/models` de cada proveedor con las claves
reales, poner precio a cada entrada contra la página oficial (tier estándar — las
cifras de *fast mode* son casi el doble y circulan mucho) y actualizar las dos
listas y la fecha en el mismo commit.

**La trampa silenciosa es la inferencia de proveedor.** `_provider_from_model` lee
el nombre: `gpt…` y `claude…` por prefijo, la serie o por forma (`^o\d`). Cualquier
otra cosa devuelve «unknown», «unknown» no tiene entrada en `PROVIDER_KEY_FIELDS`, y
`_available_models` descarta el modelo sin error en ninguna parte. `o4-mini` hacía
exactamente eso hasta la S15.

```bash
http PUT :8000/api/v1/config/models models:='{"PRIMARY_MODEL": "gpt-4o"}'
http PUT :8000/api/v1/config/models models:='{"PRIMARY_MODEL": null}'     # volver al .env
```

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

4. **Cada turno viaja con su telemetría.** `EstimationResponse.observation` es un
   `TurnObservation`: `tokens_in` / `tokens_out` / `cost_usd` / `latency_ms`, más el
   estado de la memoria (mensajes en ventana, anclas, caracteres de resumen) y el
   tier resuelto. Un solo evento estructurado por turno, `turn_observed`, para que
   el runner de estrés lea `response.observation` y no tenga que reconciliar
   timestamps. **Hasta la S15 los tres primeros campos eran siempre cero**, por dos
   fallos encadenados: `complete_structured_chat` no leía el uso —le faltaba el
   `**_usage_from(...)` que sí tiene su hermana de un disparo— y el conductor leía
   claves planas `tokens_in`/`tokens_out` que `_usage_from` anida bajo `usage`. El
   `or 0` defensivo convertía la clave ausente en un número, que es la peor forma de
   fallar: un panel se lo cree. El modo ACB no trae observación, sólo su traza.

5. **Cachés desactivadas en el path conversacional.** Cada turno depende del historial + metadata + adjuntos: dos transcripciones idénticas en sesiones distintas **no** son la misma llamada. El método nuevo `EstimationService.estimate_conversational` por tanto no consulta ni el cache exact-match ni el semántico, y `EstimationResponse.cached` siempre es `false` en este path. El endpoint transaccional original `POST /api/v1/estimate` sigue usando las dos cachés sin cambios.

6. **Ventana deslizante con `MAX_CONVERSATION_TURNS=6` por defecto.** El system prompt se regenera fresco cada turno desde el `ProjectMetadata` actual, así que no consume slot. Lo que llega al LLM en el turno N es: `[system_v2] + últimos N pares (user, assistant) + nuevo user`. Cuando el historial supera el tope, los pares más antiguos se descartan en bloque para preservar la alternancia de roles. El siguiente paso (resumen acumulativo + anclas) lo construimos en el directo.

### Variables de entorno nuevas

| Variable | Default | Notas |
|---|---|---|
| `MAX_CONVERSATION_TURNS` | `6` | Pares user+assistant que mantiene la ventana. |
| `MAX_ATTACHMENT_CHARS` | `60000` | Corte por archivo extraído. Trunca, no rechaza. |
| `METADATA_EXTRACTOR_MODEL` | `gpt-4o-mini` | Modelo de la segunda llamada por turno. |

### Tests del Paso 7

```bash
uv run pytest tests/test_sessions_metadata.py tests/test_sessions_attachments.py tests/test_sessions_window.py -v
```

Los tres tests son de integración con `TestClient`, un `FakeLLMWrapper` que captura cada llamada y devuelve resultados scripted, y un `SessionStore` aislado por test (sin singleton). Cubren los tres criterios del enunciado: dos turnos acumulan metadata, el contenido de un PDF llega al `messages` del LLM, y enviar más turnos que `MAX_CONVERSATION_TURNS` nunca infla el array de mensajes más allá del límite.

## Sesión 7 — Pipeline de embeddings

Primer paso hacia la búsqueda semántica: convertir presupuestos históricos (JSON) en vectores. El módulo nuevo vive en `app/generation/rag/` y expone un único endpoint. En la Sesión 07 no se persistía nada — los vectores se generaban en memoria y se devolvían por HTTP; **desde la Sesión 08 el endpoint persiste en pgvector** (ver la sección de la Sesión 8 más abajo).

Piezas:

- `chunker.py` (`JSONStructuralChunker`) — chunking **estructural**: un componente del presupuesto = un chunk. A cada chunk se le antepone una cabecera de contexto del presupuesto padre (proyecto, sector, tecnología) para que no pierda la pista de a quién pertenece. Cuenta tokens con `tiktoken`.
- `embedder.py` (`OpenAIEmbedder`) — invoca `text-embedding-3-small` (1536 dims) en **batches** de 100, con reintento exponencial (1s/2s/4s) ante `RateLimitError` y logging por batch.
- `router.py` — orquesta `chunk → embed → stats`.

### Endpoint nuevo

> **Contrato actualizado en la Sesión 08.** El contrato original de la S07
> (`{"budgets": [...]}` → chunks+vectores por HTTP, sin persistencia) fue
> reemplazado por el contrato persistente de un documento por petición que se
> documenta en la sección de la Sesión 8. Las piezas de esta sección (chunker,
> embedder) siguen siendo las mismas; lo que cambió es qué se hace con los
> vectores.

Con el sample completo: 17 presupuestos → 60 chunks (`text-embedding-3-small`, 1536 dims).

### Script CLI `compare.py`

Sanity check de los embeddings: embebe dos textos y devuelve su similitud coseno (calculada a mano, sin numpy). Reutiliza `OpenAIEmbedder`.

```bash
# Fuera del contenedor (desde estimator/, con el .env cargado):
uv run python scripts/compare.py \
  --text-a "OAuth 2.0 authentication backend for fintech" \
  --text-b "JWT-based authorization service for banking app"

# Dentro del contenedor (scripts/ está bind-montado en docker-compose.yml):
docker compose exec ai-service python scripts/compare.py \
  --text-a "..." --text-b "..."
```

Los resultados de las tres parejas de validación del enunciado están en [`app/generation/rag/SANITY_CHECK.md`](app/generation/rag/SANITY_CHECK.md).

### Comparativa de estrategias de chunking (sesión en vivo)

Ocho estrategias de chunking tras una interfaz común (`app/generation/rag/chunking/base.py::Chunker`): `structural`, `fixed_size`, `recursive`, `sentence_window`, `semantic`, `propositional`, `contextual_retrieval`, `hierarchical`. Viven en `app/generation/rag/chunking/strategies/` (el estructural en `structural.py`).

```
POST /embeddings/compare
  Input:  {"budgets": [...], "queries": [...], "strategies": [...], "top_k": 3}
  Output: {"stats_per_strategy": {...}, "queries_per_strategy": {...}}
```

CLI del comparador (la herramienta de las demos), que carga `data/budgets_sample.json` + `data/test_queries.json`:

```bash
# Estadísticos + coste de todas las estrategias
uv run python scripts/compare_chunkers.py --strategies all --queries all --show-stats --show-cost

# Top-k de una consulta para dos estrategias
uv run python scripts/compare_chunkers.py --strategies sentence-window,structural \
  --queries "OAuth authentication for fintech mobile app" --show-top-k 3

# Comparar dimensiones del modelo (1536 vs 768 / Matryoshka)
uv run python scripts/compare_chunkers.py --models small-1536,small-768

# Generar el reporte de respaldo
uv run python scripts/compare_chunkers.py --strategies all --queries all \
  --show-stats --show-cost --output app/generation/rag/COMPARISON_REPORT.md
```

Las estrategias `semantic`, `propositional` y `contextual_retrieval` llaman a APIs externas durante la ingesta (necesitan `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) y reportan su coste en `chunking_done`. `sentence_window` usa NLTK (`punkt`/`punkt_tab`, descarga perezosa). El endpoint de comparación no persiste nada — la persistencia vectorial vive en `/embeddings/ingest` desde la **Sesión 08**.

### Dependencias y scope

- Dependencias del pre-ejercicio: `tiktoken>=0.7.0` (`openai` ya estaba desde Sesión 01).
- Dependencias de la sesión en vivo: `langchain-text-splitters`, `langchain-experimental`, `langchain-openai`, `nltk` (`anthropic` ya estaba). No se añade numpy/scikit-learn ni `sentence-transformers`; la coseno y los percentiles son stdlib.
- **Late chunking** se trata como concepto en el directo (no hay código ejecutable: requiere modelos con token-level embeddings que no son el del proyecto).
- **Fuera de scope** → **Sesión 08**: persistencia vectorial (pgvector), búsqueda semántica / retrieval real y métricas formales de retrieval (recall@k, NDCG).
- El guion del directo está en `guides/session-7-live-guide.md` (git-ignored, material de instructor).

## Sesión 8 — Persistencia vectorial y búsqueda semántica

El pipeline de la S07 deja de devolver vectores por HTTP y los persiste en Postgres + pgvector (`pgvector/pgvector:pg16`, ya presente en compose). Schema gestionado con Alembic (`alembic/versions/0002_session8_pgvector.py`: extensión `vector` + tablas `documents` y `chunks`). Código nuevo: `app/generation/rag/store/` (modelos ORM + repositorio async con `asyncpg`), `app/generation/rag/ingest_service.py` (orquestación chunk → embed → persist) y `app/generation/rag/retriever.py` (búsqueda). El stack async convive con el sync de la S06: una sola `DATABASE_URL`, el engine async deriva el driver.

### Endpoints

```
POST /embeddings/ingest   (refactorizado: ahora persiste)
  Input:  {"source_path": "...", "document_type": "historical_budget", "content": <Budget>}
  Output: {"document_id": 1, "chunks_created": 4, "embedding_dimension": 1536, "ingestion_time_ms": 2431}
  200 OK · 409 {"detail": "Document already ingested", "document_id": N} · 422 · 500
  Todo en UNA transacción: si el embedder falla, rollback — sin documents huérfanos.

POST /search
  Input:  {"query": "REST API with OAuth authentication", "k": 5}
  Output: {"query", "k", "search_time_ms", "results": [{chunk_id, document_id, chunk_type, content, distance, metadata}]}
  k-NN por distancia coseno (operador <=>) vía SQL. Sin índice vectorial: sequential scan.
```

### Script `query_examples.py`

Ingesta el corpus completo (idempotente: los 409 se saltan) y lanza 5 queries que ejercitan ángulos distintos (match directo, reformulación semántica, dominio ajeno, ambigua, muy específica). Su salida real contra el corpus está en [`output_examples.txt`](output_examples.txt).

```bash
docker compose up -d
docker compose run --rm ai-service python scripts/query_examples.py
```

No hay tests de integración con BD viva (no existen fixtures de Postgres en la suite); la evidencia end-to-end es este script. Los tests HTTP usan fakes vía `dependency_overrides`.

### Decisiones de schema

- **Dos tablas y no una.** Un presupuesto produce N chunks: es un uno-a-muchos real. Una tabla única duplicaría la metadata del documento en cada fila y perdería integridad referencial. Con `ON DELETE CASCADE`, borrar un presupuesto elimina sus chunks automáticamente; `documents` posee la procedencia (`source_path`, `ingested_at`), `chunks` posee los vectores.
- **`metadata` como JSONB y no columnas tipadas.** Lo estable (tipo de documento, tipo de chunk, fechas) va en columnas tipadas; lo que el chunker puede enriquecer (sector, tecnologías, horas) va a JSONB. El índice GIN permite consultar por claves arbitrarias sin una migración por cada clave nueva. Una columna se promociona a tipada solo cuando se convierte en filtro caliente.
- **`cosine_distance` y no L2 ni inner product.** Los embeddings de OpenAI vienen normalizados, así que el ranking sería equivalente; usamos coseno por convención de la literatura RAG y, sobre todo, para quedar alineados con la operator class `vector_cosine_ops` del índice HNSW que se añade en el directo. Si la query usa un operador y el índice está construido con otra operator class, Postgres ignora el índice **en silencio** y cae a sequential scan.
- **Sin índice vectorial todavía (deliberado).** Con 17 presupuestos / 60 chunks el sequential scan responde en pocos cientos de ms y es el baseline contra el que el directo mide el impacto del HNSW. Añadirlo ahora ocultaría justamente lo que queremos observar.
- **`embedding` nullable.** Permite insertar el chunk y rellenar el vector después (ingesta asíncrona, sesiones posteriores). En esta sesión chunk+embedding se escriben atómicamente.
- **`vector(1536)` hardcodeado.** Es la dimensionalidad de `text-embedding-3-small`; cambiarla implica re-embedear todo el corpus, no es configuración dinámica.

**Fuera de scope (se construye en el directo):** índices vectoriales (HNSW/IVFFlat), filtros por metadata en SQL, búsqueda híbrida (full-text + vector) y tuning de Postgres.

## Live Session 08 — Indexación vectorial y operación

Material de la sesión en vivo que cierra el Módulo 3: cómo se **indexa** (HNSW), **optimiza** (halfvec) y **opera** (monitorización + mantenimiento) la base de datos vectorial construida en el previo. Foco exclusivo en la capa de datos — el retrieval llega en las Sesiones 09 y 10.

### Scripts Python (`scripts/*_s08.py`)

Todos se ejecutan con `docker compose run --rm ai-service python scripts/<script>` (o `docker compose exec ai-service python scripts/<script>` con el stack levantado). Reutilizan la configuración, la sesión async y el embedder del proyecto; `s08_common.py` es el módulo compartido (no es un script).

| Script | Qué hace |
|---|---|
| `measure_baseline_s08.py` | Latencia SQL de las 5 queries del benchmark (warm-up + 2 mediciones, media y desviación). Ejecutar antes y después de crear el índice. Imprime al final el literal pgvector de la primera query para los demos en psql. |
| `sweep_ef_search_s08.py` | Barre `hnsw.ef_search` en [10..200], mide latencia y recall contra la verdad de fondo (seq scan forzado) e imprime la tabla con la recomendación ★. |
| `compare_indexes_s08.py` | Las 5 queries contra el índice `vector` y el `halfvec` (forzados por expresión, sin dropear nada): top-5, overlap y latencias lado a lado. |
| `report_index_sizes_s08.py` | Estado de los índices de `chunks`: tipo (btree/gin/hnsw), tamaño, `idx_scan`, último uso. Ejecutar antes/después de cada decisión. |
| `insert_synthetic_chunks_s08.py` | Inserta chunks sintéticos con embeddings **reales** (`count` posicional, default 100). Con `30000` engorda el corpus en el pre-flight para que el baseline sin índice sea medible. Limpieza: `DELETE FROM documents WHERE document_type = 'synthetic_test';` |

### Snippets SQL (`scripts/sql_s08/`)

Se ejecutan en psql, en este orden durante el directo. psql vive en el contenedor de Postgres (que no monta `scripts/`), así que: redirigir el archivo o pegar bloques.

```bash
# Archivo completo:
docker compose exec -T estimator-postgres psql -U estimator -d estimator \
  < estimator/scripts/sql_s08/01_create_hnsw.sql
# Interactivo (pegar bloques):
docker compose exec estimator-postgres psql -U estimator -d estimator
```

| Orden | Snippet | Bloque del directo |
|---|---|---|
| 1 | `01_create_hnsw.sql` | Construcción del índice HNSW (`vector_cosine_ops`, m=16, ef_construction=128) |
| 2 | `02_test_antipatron.sql` | El antipatrón silencioso: `<=>` vs `<->` con `EXPLAIN ANALYZE` |
| 3 | `03_create_halfvec.sql` | Índice halfvec paralelo sobre `(embedding::halfvec(1536))` |
| 4 | `04_monitoring_queries.sql` | Monitorización con `pg_stat_user_indexes` |
| 5 | `05_maintenance_cycle.sql` | ANALYZE → VACUUM → REINDEX CONCURRENTLY |

### Operational queries

La query canónica de monitorización — para tenerla a mano siempre:

```sql
SELECT indexrelname, idx_scan, last_idx_scan,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE relname = 'chunks'
ORDER BY idx_scan DESC;
```

Si un índice vectorial tiene `idx_scan = 0` después de servir queries semánticas: casi seguro el operador de la query no coincide con la operator class del índice (p. ej. `<->` contra `vector_cosine_ops`). Verificación de operator classes y estadísticas de tabla: en `scripts/sql_s08/04_monitoring_queries.sql`.

El tuning de Postgres para builds de índices vive en `docker-compose.yml` (servicio `estimator-postgres`): `shm_size`, `shared_buffers`, `maintenance_work_mem`, `max_parallel_maintenance_workers`. Valores conservadores de desarrollo; en producción escalan con la RAM.

### Entregable post-directo (a Lia)

1. Repositorio actualizado: índice halfvec activo, flags de tuning en compose, queries de monitorización en el README.
2. Documento corto con los números observados en **vuestro** barrido de `ef_search` (tabla del script) y la decisión razonada del valor adoptado: qué recall ganáis y qué latencia pagáis frente a las alternativas.

---

> Este proyecto forma parte del **Master en AI Engineering** y es la base sobre la que se construye en directo el resto de la Sesión 04 (output estructurado, guardrails, cache semántico) y de la Sesión 05 (compresión avanzada de memoria con anclas, tier dinámico, patrón Actor-Critic-Boss).
