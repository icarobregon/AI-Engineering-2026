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

## Sesión 10 — Búsqueda híbrida y reranking

El pipeline RAG de la Sesión 09 recupera por similitud vectorial, y el problema es que *"similar" no siempre significa "relevante"*: el sistema trae el presupuesto de una app de pagos cuando la consulta describe un e-commerce. Cerca en el espacio vectorial, inútil para estimar. Esta sesión ataca eso con dos técnicas — **búsqueda híbrida** y **reranking** — y, sobre todo, **mide si compensan**.

### Qué se construyó

**Rama léxica sobre `tsvector`.** La migración `0003_session10_fts` añade a `chunks` una columna generada `content_tsv` (`GENERATED ALWAYS ... STORED`) más su índice GIN. Columna generada y no trigger: PostgreSQL recalcula el vector en cada insert/update de `content`, así que el índice léxico no puede desincronizarse del texto que indexa. La columna se declara también en el ORM (`store/models.py`), sin lo cual el próximo `alembic revision --autogenerate` propondría **borrarla**.

La configuración de text search es **`'english'`, no `'spanish'`**. El enunciado dice que el corpus está en español; no lo está: `data/budgets_sample.json` y `data/task_corpus.json` traen nombres y descripciones de componentes en inglés (*"Faceted search"*, *"Order lifecycle"*, *"Product catalog model"*), y solo los nombres de cliente y las transcripciones semilla están en español. Un analizador español sobre texto inglés no eliminaría las stopwords inglesas ni haría stemming correcto, y eso subestimaría la rama léxica justo en la comparación que hay que medir. El literal vive en `TEXT_SEARCH_CONFIG` y la migración guarda su propia copia a propósito (una migración es un registro histórico, no debe cambiar de significado al editar una constante); un test vigila que no divergan.

**Semántica OR, no AND.** `websearch_to_tsquery` —el que sugiere el enunciado— y `plainto_tsquery` unen los términos con AND. Con una consulta real del dominio eso produce:

```
'e-commerc' <-> 'e' <-> 'commerc' & 'platform' & 'product' & 'catalog'
  & 'shop' & 'cart' & 'checkout' & 'admin' & 'panel'
```

Nueve términos obligatorios contra un corpus de empresa: **cero resultados**. Como la entrada real del sistema son descripciones largas de proyecto, la rama léxica habría devuelto lista vacía en casi toda consulta, la híbrida habría degradado en silencio a vectorial, y la tabla comparativa habría "demostrado" que la híbrida no aporta nada — cuando en realidad nunca llegó a ejecutarse. `_or_tsquery()` cambia el operador sobre el tsquery ya normalizado por `plainto_tsquery` y deja que `ts_rank` discrimine, que es la conducta bag-of-words que esta rama debe tener.

**Fusión RRF.** `retrieval/fusion.py` fusiona por posición y no por puntuación, porque las dos ramas producen escalas incomparables: distancia coseno acotada donde menos es mejor, `ts_rank` sin cota donde más es mejor. Normalizar y combinar con pesos funciona en la demo y se rompe en producción, porque la distribución cambia con cada consulta. RRF lo esquiva, y es **una máquina de premiar el consenso**: aparecer razonablemente arriba en varias ramas vale más que arrasar en una. Recibe una *lista* de rankings, no exactamente dos, así que la expansión de consultas y el routing multi-índice reutilizarán la misma pieza.

**Recall-then-rerank.** `retrieval/pipeline.py` expone un único `retrieve()` que compone las cuatro configuraciones detrás de dos interruptores. Cada parámetro resuelve igual: **argumento explícito → settings**. No pasar nada ejecuta lo que el despliegue tenga configurado; pasarlo lo sobreescribe solo para esa llamada. Activar el reranking es un cambio de configuración, y comparar técnicas es un experimento sobre dos booleanos.

Dos detalles que no salen en los tutoriales y sí en los incidentes:

- La búsqueda vectorial es asíncrona (I/O contra la BD) y el cross-encoder no (cómputo local). Unos cientos de milisegundos de inferencia en el event loop **bloquean todas las demás peticiones** mientras duran, así que se despacha con `asyncio.to_thread`. Hay un test de comportamiento, no solo de nombre de hilo: un ticker concurrente debe completar sus 20 ticks mientras un rerank bloqueante de 200 ms está en vuelo.
- Los pesos del modelo (~450 MB) viven en el volumen `hf_cache` con `HF_HOME`. El directorio se crea **en el Dockerfile** con propietario `appuser`, porque Docker inicializa un volumen nuevo desde el directorio de la imagen, propiedad incluida; sin eso el volumen nace de root, el contenedor no-root no puede escribir y el primer rerank muere con `PermissionError`.

### Cómo reproducir la medición

```bash
docker compose up -d

# Gate del enunciado: ¿carga y puntúa el cross-encoder?
docker compose exec estimator python -m app.generation.rag.retrieval.verify_reranker

# Corpus (idempotente: los ya ingeridos responden 409 y se saltan)
docker compose exec estimator python scripts/query_examples.py

# Las cuatro configuraciones contra el golden set
docker compose exec estimator python scripts/measure_retrieval.py
```

Las cuatro configuraciones también son alcanzables por petición, sin reiniciar nada:

```bash
http POST :8000/v1/retrieval/search X-API-Key:$RETRIEVAL_API_KEY \
  query_text="e-commerce platform with product catalog and checkout" \
  search_mode=hybrid rerank:=true
```

### Resultados

Golden set de 5 consultas (`scripts/golden_set.json`), corpus de 17 presupuestos / 60 chunks, `k=5`, conjunto amplio `recall_k=50`, mediana de 5 ejecuciones por consulta, medición en caliente con precalentamiento global de las cuatro configuraciones.

| Configuración | Búsqueda | Reranking | precision@5 | recall@5 | Presupuestos distintos | Latencia |
|---|---|---|---|---|---|---|
| **A** | Vectorial | No | 0,88 | 1,00 | 2,4 / 5 | **2 ms** |
| **B** | Híbrida | No | 0,92 | 1,00 | 2,2 / 5 | **2 ms** |
| **C** | Vectorial | Sí | **0,96** | 1,00 | 2,0 / 5 | **327 ms** |
| **D** | Híbrida | Sí | 0,92 | 1,00 | 2,2 / 5 | **2.383 ms** |

Deltas contra A: `B +0,04 / +0 ms` · `C +0,08 / +325 ms` · `D +0,04 / +2.381 ms`. El embebido de la consulta (159 ms de mediana) queda fuera de la columna de latencia porque es la misma constante en las cuatro filas: incluirlo sumaría lo mismo a todas importando jitter de red a la comparación.

| Query | Qué prueba | A | B | C | D |
|---|---|---|---|---|---|
| Q1 | E-commerce, frecuente y directa | 0,80 | 1,00 | 1,00 | 1,00 |
| Q2 | Pagos, frecuente y directa | 1,00 | 1,00 | 1,00 | 1,00 |
| Q3 | Términos exactos (`HL7/FHIR`) | 0,80 | 0,80 | 0,80 | 0,80 |
| Q4 | Dominios colindantes | 0,80 | 0,80 | 1,00 | 1,00 |
| Q5 | Transcripción larga y desordenada | 1,00 | 1,00 | 1,00 | 0,80 |

Tres ejecuciones independientes dieron la misma precisión: la recuperación es determinista. Las latencias de A y B son estables; C osciló entre 327 y 390 ms y D entre 2.383 y 3.109 ms con la máquina en reposo, y se degradaron a 1.546 y 3.987 ms con la máquina cargada — de ahí que la medición se repitiera con la carga por debajo de 4.

**Dónde se mueve la aguja, con nombre y apellidos.** Las medias esconden lo interesante:

- **Q4 es el fallo que da nombre a la sesión, y lo desactiva el reranker.** Con A, el quinto puesto lo ocupaba `BUD-2024-014` — almacén con AGV: sector industrial, 620 h, vocabulario de operaciones compartido, y **logística en vez de telemetría**. C y D lo sustituyen por un chunk relevante de `BUD-2024-015`. La híbrida sola no lo arregla: cambia un distractor por otro (`BUD-2024-010`, monitorización de pacientes).
- **Q1 la arregla la híbrida.** A colaba `BUD-2024-008` (devoluciones de moda) en cuarta posición; B, C y D lo eliminan.
- **Q3 es el techo, no un fallo.** `BUD-2024-009` es el único presupuesto relevante y tiene 4 componentes, así que 0,80 es el máximo alcanzable. El quinto puesto lo ocupa `BUD-2024-012` en las cuatro configuraciones y ninguna técnica puede mejorarlo.
- **Q5 es la única regresión, y le pasa a la configuración más cara.** D puso `BUD-2024-016` —descomposición de un core bancario monolítico— en **primera** posición para la transcripción de e-commerce. El mecanismo es identificable: la fusión ensancha el pool de 27 a 44 candidatos, mete presupuestos que el umbral vectorial había descartado, y el cross-encoder se equivoca puntuando uno de ellos contra una consulta verbosa y multitema. Más candidatos no es mejor si el reranker tiene que ordenar más ruido.

### Conclusiones — qué configuración usaría y por qué

**Se queda B (híbrida sin reranking), y el reranking espera.**

La razón de quedarse con B no es que gane mucho: es que **gana algo y no cuesta nada**. +0,04 de precisión y +0 ms medibles, porque las dos ramas corren concurrentemente y la léxica se sirve por índice GIN sobre el mismo PostgreSQL — ni un almacén nuevo, ni sincronización entre almacenes, ni un modelo más que operar. No hay tabla de decisión que justifique rechazar una mejora de coste cero, y la rama léxica es además la única que cubre el punto ciego de lo literal, que en estimación no es el caso raro sino el pan de cada día (`Stripe`, `SAP`, `HL7/FHIR`, `React Native`).

La razón de **no** meter el reranking todavía no es su latencia, y esto importa: en este producto la generación posterior tarda varios segundos, así que los 325 ms de C serían menos del 5 % del total percibido — asumibles de sobra. La razón es que **el problema que el reranking resuelve no está presente en este corpus**. `recall@5` sale 1,00 en las cuatro configuraciones: todos los presupuestos relevantes ya entran en el top-5 sin hacer nada. El artículo da la señal precisa de cuándo el reranking es la herramienta correcta — *"los documentos relevantes están entre los candidatos, pero no arriba"* — y aquí ya están arriba, partiendo de 0,88 y no de 0,48.

El `+0,08` de C son **dos chunks en dos consultas**, y una de las dos es la trampa que construimos a propósito. Ese es el retrato exacto de la **zona traicionera** del cuadrante: ganancia pequeña con coste pequeño, donde el coste real nunca es solo la latencia — es el modelo extra que operar, los 450 MB de pesos y los ~6 GB de imagen, la dependencia que actualizar y el modo de fallo nuevo que diagnosticar a las tres de la mañana. Una mejora de dos chunks sobre cinco consultas no paga ese peaje, y la tabla es precisamente lo que permite decir "no" con fundamento en lugar de con desgana.

**D se descarta con datos, no con opinión:** cuesta 7 veces lo que C, puntúa peor que C, y su única regresión es explicable. Es el clásico de acumular técnicas porque están disponibles.

El código de las tres técnicas se queda en el repositorio, apagado por configuración (`RETRIEVAL_SEARCH_MODE=hybrid`, `RERANKER_ENABLED=false`), porque el trabajo caro ya está hecho y encenderlo cuando aparezca la evidencia es cambiar un booleano. Y la evidencia que lo justificaría es observable y concreta: `recall@k` alto con `precision@k` bajo de forma recurrente, es decir, los relevantes entrando en el conjunto amplio pero no en el top-5.

### Limitaciones conocidas

Dicho con honestidad, porque una medición que no declara sus límites invita a sobreinterpretarla:

- **El corpus es demasiado fácil para esta pregunta.** 17 presupuestos en 4 sectores muy separados (finanzas, e-commerce, sanidad, industrial). La búsqueda vectorial casi no falla, así que el techo está demasiado cerca del suelo y la medición no puede discriminar con fuerza. La conclusión de arriba es sobre *este corpus*, no sobre las técnicas.
- **Cinco consultas no tienen potencia estadística.** Un `+0,04` es un chunk en una consulta. Las diferencias que justifican decisiones son las grandes y consistentes, no las centésimas.
- **La anotación arrastra el sesgo de quien anota**, y el caso más discutible está marcado en el propio golden set (`BUD-2024-015` en Q4: el esfuerzo de ingesta de telemetría más modelos transfiere, pero es energía y no manufactura).
- **`precision@5` se mide sobre chunks**, que es lo que el pipeline entrega al generador. Pero el chunker emite un chunk por componente, así que un presupuesto puede ocupar varias plazas legítimamente: 2,0–2,4 presupuestos distintos por top-5. El contexto lleva menos referencias independientes de las que parece. Se descartó una métrica de precisión sobre presupuestos deduplicados porque invierte el significado que dice medir — el denominador se encoge con la duplicación, de modo que premia traer *menos* presupuestos distintos.
- **El `distance_threshold` de 0,6 es el que limita el recall real, no `recall_k`.** La rama vectorial devuelve 12–27 candidatos, nunca los 50 configurados, así que el "conjunto amplio" del patrón no es tan amplio como dice la configuración — y eso abarata artificialmente a C.
- **La medición se detiene en la recuperación.** Dice qué documentos llegan al LLM, no qué hace el LLM con ellos. Una recuperación perfecta no garantiza una estimación correcta; solo la hace posible.

---

> Este proyecto forma parte del **Master en AI Engineering** y es la base sobre la que se construye en directo el resto de la Sesión 04 (output estructurado, guardrails, cache semántico) y de la Sesión 05 (compresión avanzada de memoria con anclas, tier dinámico, patrón Actor-Critic-Boss).
