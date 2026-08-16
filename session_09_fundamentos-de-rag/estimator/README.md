# Estimator — Servicio IA de estimación de software

Servicio IA en FastAPI que estima proyectos de software a partir de un formulario tipado. Es la pieza Python del programa **Master en AI Engineering**: un endpoint pensado para ser consumido por un backend de negocio o una UI propia (Streamlit u otra), no por un usuario final.

A partir de la **Sesión 04** el contrato es deliberadamente estrecho:
- entrada tipada (`description` + tres enums),
- salida en texto libre,
- prompt fuera del código en templates Jinja2 versionados (`app/foundation/prompts/<use_case>/<version>/`).

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

### Probar el endpoint

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
  "text": "| phase | duration_weeks | cost_eur | confidence_pct | …",
  "prompt_version": "v1"
}
```

### Cliente Streamlit

El cliente Streamlit es un formulario que construye el JSON y muestra el `text` recibido. Corre fuera de Docker y consume la API por HTTP:

```bash
cd estimator
uv run streamlit run streamlit_app.py
# Abrir http://localhost:8501
```

La URL del servicio se lee de `ESTIMATOR_API_BASE_URL` (default `http://localhost:8000`).

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
│   ├── config.py                      # Settings (Pydantic Settings, .env)
│   ├── dependencies.py                # Singletons cacheados: cache + LLMWrapper
│   ├── routers/
│   │   └── estimations.py             # POST /api/v1/estimate
│   ├── schemas/
│   │   └── estimation.py              # EstimationRequest, EstimationResponse, enums
│   ├── prompts/
│   │   ├── loader.py                  # Environment Jinja2 + render_estimation_prompt
│   │   └── estimation/
│   │       └── v1/
│   │           ├── system.j2          # rol + reglas + bloques condicionales + include
│   │           ├── user.j2            # bloque <project_description>
│   │           └── examples.j2        # few-shot examples
│   └── services/
│       ├── llm_wrapper.py             # LiteLLM Router con fallback y cost tracking
│       └── cache.py                   # Redis exact-match cache
├── tests/
│   ├── test_schemas.py
│   ├── test_prompts.py
│   ├── test_estimate_endpoint.py
│   ├── test_llm_wrapper.py
│   └── test_cache.py
├── streamlit_app.py                   # Formulario que consume /api/v1/estimate
├── Dockerfile                         # Multi-stage con uv
├── docker-compose.yml                 # Servicio IA + Redis
└── pyproject.toml
```

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
| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | Lo lee el cliente Streamlit |

`get_settings()` es un singleton cacheado con `lru_cache`: cualquier cambio en `.env` requiere reiniciar uvicorn (no basta con `--reload`). **Excepción: los modelos LLM** — ver la sección siguiente.

## Configuración de modelos en runtime

Los knobs de modelo (`PRIMARY_MODEL`, `FALLBACK_MODEL`, `CRITIC_MODEL`, `METADATA_EXTRACTOR_MODEL`, `COMPRESSION_MODEL`, `PROPOSITIONAL_CHUNKER_MODEL`, `CONTEXTUAL_CHUNKER_MODEL`) se pueden **sobreescribir en caliente** sin tocar `.env` ni recrear contenedores — pensado para cambiar de modelo en mitad de un directo.

```
GET /api/v1/config/models
  → {"models": {KEY: {"effective", "default", "overridden"}},
     "available_models": [...], "embedding_model": "..."}

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

4. **Cachés desactivadas en el path conversacional.** Cada turno depende del historial + metadata + adjuntos: dos transcripciones idénticas en sesiones distintas **no** son la misma llamada. El método nuevo `EstimationService.estimate_conversational` por tanto no consulta ni el cache exact-match ni el semántico, y `EstimationResponse.cached` siempre es `false` en este path. El endpoint transaccional original `POST /api/v1/estimate` sigue usando las dos cachés sin cambios.

5. **Ventana deslizante con `MAX_CONVERSATION_TURNS=6` por defecto.** El system prompt se regenera fresco cada turno desde el `ProjectMetadata` actual, así que no consume slot. Lo que llega al LLM en el turno N es: `[system_v2] + últimos N pares (user, assistant) + nuevo user`. Cuando el historial supera el tope, los pares más antiguos se descartan en bloque para preservar la alternancia de roles. El siguiente paso (resumen acumulativo + anclas) lo construimos en el directo.

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
docker compose exec estimator python scripts/compare.py \
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
docker compose run --rm estimator python scripts/query_examples.py
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

Todos se ejecutan con `docker compose run --rm estimator python scripts/<script>` (o `docker compose exec estimator python scripts/<script>` con el stack levantado). Reutilizan la configuración, la sesión async y el embedder del proyecto; `s08_common.py` es el módulo compartido (no es un script).

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

## Sesión 9 — Flujo RAG completo y capa de servicio

Cierra el circuito que la S08 dejó abierto: hasta ahora `POST /search` devolvía chunks y
`POST /api/v1/estimate` generaba estimaciones, pero ninguno de los dos hablaba con el otro. La S09
añade las cuatro etapas canónicas (Query → Retrieval → Augmentation → Generation), las compone en el
conductor y las expone tras una capa de servicio con autenticación, rate limiting e idempotencia.

### Módulos nuevos

```
app/
├── foundation/
│   ├── llm/responses.py              # Responses API (structured output strict + reasoning effort)
│   ├── observability.py              # log_stage(): request_id + duration_ms por etapa
│   ├── persistence/idempotency.py    # store Redis, TTL 24 h
│   └── prompts/rag_estimation/v1/    # system.j2 + user.j2 (incluye bloque de reintento)
├── domain/
│   ├── schemas/rag_estimate.py       # Estimate, EstimateRequest/Response, RetrievalTrace
│   └── estimation_service.py         # + estimate_from_transcript(): las 4 etapas componen AQUÍ
├── generation/rag/
│   ├── query_reformulator.py         # transcripción → EstimationQuery → search_text (+ fallback)
│   ├── retriever.py                  # + retrieve(): top-K + threshold + filtros + soft-fail
│   ├── context_assembler.py          # <source> + truncado por presupuesto + reorden en U
│   ├── generator.py                  # generación + validate_citations + reintento único
│   └── store/repository.py           # + search_filtered / search_wide_then_filter / count_candidates
├── api/
│   ├── security.py                   # dos API keys, compare_digest
│   ├── retrieval.py                  # POST /v1/retrieval/search
│   └── estimate_rag.py               # POST /v1/estimate/from-transcript
└── rate_limit.py                     # limiter por API key + handler 429
```

Migración `0003_session9_hnsw.py`: índice HNSW sobre `(embedding::halfvec(1536)) halfvec_cosine_ops`.
Deja de ser demo de directo y pasa a ser precondición del retriever, porque `ChunkStore` ordena por
esa misma expresión — un índice sobre la columna desnuda no lo usaría y caería a sequential scan sin
avisar.

### Endpoints

```
POST /v1/retrieval/search        (X-API-Key: RETRIEVAL_API_KEY · 120/min)
  Input:  {"query_text": "multi-vendor marketplace with vendor payouts",
           "top_k": 10, "distance_threshold": 0.6,
           "sectors": ["ecommerce"], "countries": ["DE"],
           "project_year_min": 2023, "technologies": [...], "chunk_types": [...]}
  Output: {"chunks": [{id, content, chunk_type, distance, sector, project_year, country,
                       budget_id, component_id, main_technology}],
           "low_confidence": false, "total_candidates_considered": 20, "search_time_ms": 1218}
  200 (incluida la lista vacía con low_confidence) · 401 · 422 · 429 · 502 · 503

POST /v1/estimate/from-transcript   (X-API-Key: ESTIMATE_API_KEY · 10/min)
  Input:  {"transcript": "...", "idempotency_key": "uuid-opcional"}
  Output: {"request_id", "estimate": {total_engineer_days, cost_breakdown[], duration_weeks,
                                      sources[], assumptions[], confidence, reasoning,
                                      insufficient_context_explanation},
           "low_confidence", "needs_manual_review", "review_reason", "retrieval": {...}, "cached"}
  Header: X-Request-ID (mismo id que aparece en las cinco etapas del log)
  200 · 401 · 422 · 429 · 502 · 503
```

`POST /search` (S08) y `POST /api/v1/estimate` (S04) siguen intactos: son contrato público.

### Decisiones

- **Responses API en lugar del `LLMWrapper`.** Las dos etapas LLM del flujo usan
  `client.responses.parse` con el modelo Pydantic como `text_format`, no LiteLLM + Instructor. Dos
  razones: `strict: True` hace *imposible* que el modelo emita un campo fuera del esquema (Instructor
  re-pregunta cuando ya ha fallado), y `reasoning.effort` no tiene equivalente en el wrapper. El
  wrapper sigue siendo la vía del camino CAG; conviven sin tocarse.
- **`responses.parse` y no el `schema=Model.model_json_schema()` del enunciado.** Ese JSON Schema no
  es válido para `strict: True` sin post-procesarlo (le falta `additionalProperties: false` y que
  todos los campos sean `required`). El SDK lo deriva correctamente del modelo Pydantic.
- **Filtros sobre `chunks.metadata` (JSONB) y no sobre columnas de `documents`.** El SQL del
  enunciado asume `d.sector` y `d.project_year`, que no existen en este esquema: sector, año,
  tecnología y país viajan con el chunk, ya indexados por GIN. Se filtra sin join y sin migración.
- **`country` añadido a la metadata del chunk.** Estaba en el corpus de origen y no se persistía, así
  que el filtro geográfico no tenía dato que leer. Un campo en `component_metadata()` + re-ingesta
  (60 chunks, ~$0.0003).
- **WHERE construido condicionalmente, no `(:filter IS NULL OR ...)`.** Ese idioma existe para SQL
  crudo con lista fija de parámetros; con un query builder sólo añade ramas OR constantes-falsas que
  el planner tiene que cargar.
- **Derivación conservadora de filtros.** Del `EstimationQuery` sólo se deriva el sector, y sólo si
  pertenece al vocabulario del corpus (`finance`, `ecommerce`, `healthcare`, `industrial`). El
  modelo extrae sectores como *"kitchenware / housewares retail"*, que vaciarían el resultado. País y
  año no se derivan nunca: con 60 chunks son filtros demasiado selectivos. Siguen disponibles para
  quien llame al endpoint de retrieval explícitamente.
- **Soft-fail antes que generar.** Si ningún chunk baja del umbral, el generador **no se llama**: la
  respuesta es 200 con `estimate: null`, `needs_manual_review: true` y la traza que lo explica. Un
  modelo al que se le pide estimar sin contexto produce números indistinguibles de los fundamentados.
- **Sin guardrails de entrada en este endpoint.** `check_input` aplica política `exception` sobre
  PII, y una transcripción real de reunión está llena de datos personales legítimos. Rechazarlas
  haría el endpoint inútil; la pseudonimización se aplica offline, en la ingesta (S06), y este camino
  no persiste la transcripción.
- **API keys opcionales en settings.** Sin clave configurada el router responde 503, en vez de que
  `os.environ[...]` impida arrancar la aplicación sin secretos (rompería tests y desarrollo local).

### Resultados medidos sobre el corpus (17 presupuestos / 60 chunks)

**Reformulación** (`scripts/s09_reformulation_paths.py`, transcripción `02_ambiguous.txt`, top-10;
el presupuesto análogo es BUD-2024-006, *multi-vendor marketplace with vendor payouts*):

| camino | chars embebidos | chunks del análogo | mejor distancia | spread |
|---|---|---|---|---|
| transcripción cruda | 6.618 | **0/10** | 0.6441 | 0.0514 |
| extracción estructurada | 486 | **4/10** (posiciones 1-4) | 0.4201 | 0.1678 |
| HyDE | 732 | 1/10 | **0.3370** | 0.1096 |

HyDE consigue las distancias absolutas más bajas pero recupera lo que su documento hipotético decidió
describir: con un cliente que no ha cerrado el alcance, esa decisión es arbitraria — el suyo habló
sólo de sincronización de inventario y perdió el marketplace. La extracción estructurada recupera el
presupuesto análogo completo y además produce filtros. Por eso es la elegida.

**Calibración del umbral** (`scripts/s09_calibrate_threshold.py`, top-30):

| consulta | mín | p50 | máx |
|---|---|---|---|
| reformulada · 01_clear | 0.3722 | 0.5066 | 0.5683 |
| reformulada · 02_ambiguous | 0.3922 | 0.6033 | 0.6487 |
| reformulada · 03_hard | 0.4967 | 0.6345 | 0.7008 |
| cruda · 01_clear | 0.4923 | 0.6035 | 0.6295 |
| cruda · 02_ambiguous | 0.6441 | 0.7092 | 0.7543 |
| cruda · 03_hard | 0.6027 | 0.6894 | 0.7148 |

Se mantiene **0.6**: deja material a las tres consultas reformuladas (30/14/11 chunks) y hace
soft-fail en dos de las tres transcripciones crudas, que es exactamente el caso que debe rechazarse.
Bajar a 0.5 dejaría `03_hard` con un solo chunk. Con un corpus mayor habría que recalibrar a la baja.

**CAG vs RAG** (`scripts/s09_cag_vs_rag.py`, mismo modelo, mismo prompt, misma transcripción):

| | contexto | tokens | latencia | fuentes citadas |
|---|---|---|---|---|
| CAG (corpus entero) | 60 chunks | 7.900 | 103,8 s | **0** |
| RAG (top-K) | 10 chunks | 1.103 | 91,0 s | **8** |

El dato que importa no es el 7,2× de tokens (a 17 presupuestos es calderilla), sino que con el corpus
entero volcado el modelo no ancló ni una sola cifra en una fuente, y con diez chunks seleccionados
citó ocho. La selección no es sólo ahorro: es lo que hace la respuesta auditable.

**Lost in the middle** (`scripts/s09_lost_in_the_middle.py`, K=5): el chunk crítico se cita en los
tres órdenes (relevancia, crítico-en-medio, patrón U). A esta escala de contexto (~1.100 tokens) no
hay efecto que mitigar, así que `RAG_CONTEXT_REORDER_U` queda en `false`. Habría que volver a medirlo
si `top_k` sube a 15-20.

**Latencia del flujo completo** (`02_ambiguous.txt`, extremo a extremo 88,9 s):

| etapa | duración |
|---|---|
| reformulation | 14,7 s |
| retrieval | 283 ms |
| context_assembly | 2,5 ms |
| generation | **73,4 s** |
| validation | 0,2 ms |

La generación con `gpt-5` y `reasoning.effort=medium` es el 83% del tiempo. Con `idempotency_key`, la
repetición de la misma petición responde en **17 ms**.

### Cómo ejecutarlo

```bash
docker compose up -d                                   # desde la raíz de la sesión
uv run python scripts/query_examples.py                # siembra el corpus (idempotente)

# Trace del estado pre-sesión (respalda arquitectura-actual.md)
uv run python scripts/s09_trace_prework.py --k 5

# Experimentos
uv run python scripts/s09_calibrate_threshold.py       # sólo embeddings, barato
uv run python scripts/s09_reformulation_paths.py       # 2 llamadas gpt-5-mini
uv run python scripts/s09_cag_vs_rag.py                # 2 llamadas gpt-5 (~3 min)
uv run python scripts/s09_lost_in_the_middle.py        # 3 llamadas gpt-5 (~5 min)

# Tests
uv run pytest                                          # 301 unitarios, sin infraestructura
uv run pytest -m integration                           # 8 contra Postgres+pgvector real
```

### Limitaciones conocidas

- **Variabilidad de `confidence`.** La misma transcripción ambigua ha producido `medium` (122
  engineer-days) y `insufficient` en ejecuciones distintas. Es variabilidad del reasoning model, no
  del flujo: el contexto recuperado era el mismo. Con `01_clear.txt` la respuesta es consistentemente
  una estimación (`low`, 74 engineer-days, 4 componentes citados), así que el sistema discrimina; la
  frontera exacta de "insuficiente" no es determinista.
- **El reformulador recoge tecnologías mencionadas de pasada.** En `02_ambiguous.txt` extrae
  `WordPress` porque el cuñado del cliente lo mencionó despectivamente. No contamina el retrieval de
  forma medible, pero es ruido en la query estructurada.
- **`duration_weeks` a veces queda a `null`** aunque haya estimación: el corpus registra horas por
  componente, no calendario, y el modelo se abstiene en lugar de inventarlo.
- **El índice HNSW no se usa todavía.** Con 60 chunks el planner elige sequential scan porque es más
  barato (coste 6.9). El test de integración lo fuerza con `enable_seqscan = off` para verificar que
  la operator class está alineada y el índice es utilizable.

---

> Este proyecto forma parte del **Master en AI Engineering** y es la base sobre la que se construye en directo el resto de la Sesión 04 (output estructurado, guardrails, cache semántico) y de la Sesión 05 (compresión avanzada de memoria con anclas, tier dinámico, patrón Actor-Critic-Boss).
