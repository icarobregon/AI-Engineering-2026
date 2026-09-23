# Estimator — Servicio IA de estimación de software

Servicio IA en FastAPI que estima proyectos de software. Es la pieza Python del
programa **Master en AI Engineering**: lo consume un backend de negocio, nunca un
usuario final, y desde la Sesión 15 no publica puerto al host.

Hoy estima de **cuatro formas distintas**, y conviven a propósito porque cada una
resuelve un problema que la anterior no:

| Camino | Qué es | Sesiones |
|---|---|---|
| `POST /api/v1/estimate` | Un disparo: formulario tipado → estimación validada. Sin memoria y sin corpus. | 04 |
| `POST /sessions/*` | Lo mismo a varios turnos, con memoria, adjuntos y el modo Actor-Critic-Boss. | 05 |
| `POST /v1/estimate/from-transcript` y `/stages/*` | RAG: una tubería fija que recupera del histórico y cita línea a línea. | 09–11 |
| `POST /v1/estimate/graph` y `/v1/estimate/agent/run` | Agentes que deciden: un grafo multi-agente con puerta humana, y un bucle escrito a mano. | 12–14 |

Tres invariantes valen para los cuatro:

- **Entrada y salida tipadas.** El contrato es Pydantic, no prosa; Instructor
  obliga al modelo a la forma y los `computed_field` derivan lo que no se le pide.
- **El prompt vive fuera del código**, en plantillas Jinja2 versionadas
  (`app/foundation/prompts/<use_case>/<version>/`). Si cambiar el comportamiento
  del modelo obliga a tocar Python, la separación está rota.
- **Los números no los pone el modelo** donde hay con qué calcularlos. En el grafo
  las horas salen de una herramienta determinista y al modelo sólo se le pide la
  prosa; en el camino RAG, una cita que no resuelve se poda antes de servir.

El contrato de capas —quién puede importar a quién— es normativo y vive en
[`ARCHITECTURE.md`](ARCHITECTURE.md).

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

`DATABASE_URL` y `REDIS_URL` no tienen valor por defecto desde la S15, así que hay
que dárselos. Van **delante de la orden** y no en el `.env`, que describe el
despliegue real: una variable de entorno gana al fichero, así que la vía local es
efímera y no deja rastro.

```bash
cd estimator
uv sync
DATABASE_URL=postgresql+psycopg://estimator:estimator@localhost:5433/estimator \
REDIS_URL=redis://localhost:6379 \
uv run uvicorn app.main:app --reload
```

Eso exige que Postgres y Redis sean alcanzables desde el host, que con la frontera
de la S15 ya no lo son. El recetario por caso —depurar, tests, scripts— está en
[`../docs/deployment-local.md`](../docs/deployment-local.md).

### Probar el endpoint

Desde dentro de la red interna, que es de donde se alcanza:

```bash
docker compose exec business-backend curl -sS -X POST http://ai-service:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AI_SERVICE_TOKEN" \
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
uv run pytest        # 687 tests en 82 ficheros, ~6 s
uv run ruff check app tests
```

**Sin red, sin clave y sin base de datos.** `conftest.py` fija `DATABASE_URL`,
`REDIS_URL` y una `OPENAI_API_KEY` falsa **antes** de importar la app. No es
ceremonia: `litellm` llama a `load_dotenv()` al importarse, así que el `.env` del
desarrollador acababa en `os.environ` como efecto colateral y los tests que pasan
`_env_file=None` creyendo aislarse leían el fichero igual. Desde la S15 la suite
pasa con `.env` y sin él, cosa que nunca había hecho.

Cómo está repartida:

| Directorio | Qué fija |
|---|---|
| `tests/` (raíz) | Los contratos de la S03–S05: schemas, render de prompts, wrapper, cachés, guardrails, adjuntos y memoria. |
| `tests/api/` | Los routers como los ve un cliente: códigos, formas JSON, auth y límites de tasa. |
| `tests/generation/rag/` | Troceado, recuperación, fusión, reranking, citación y política de citas. |
| `tests/generation/agentic/` | El bucle del agente, sus tools y el Actor-Critic-Boss. |
| `tests/domain/graph/` | El grafo: el resultado y los invariantes, nunca el camino. |
| `tests/domain/security/` | Privilegios de tool, el guard y la auditoría. |

En el grafo los tests fijan **el resultado y los invariantes, jamás el orden de los
nodos**: el camino es no determinista por diseño, así que un test que fije una
secuencia se rompe cada vez que el supervisor decide distinto y no prueba nada. Y
las tres herramientas de la S12 se usan de verdad —son Python determinista— porque
falsearlas sería testear el falso; sólo se doblan el modelo y el backend de
recuperación.

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
│   │   ├── embeddings.py              #   S07/S08 — troceado, ingest, búsqueda y stats
│   │   ├── search.py                  #   S08 — POST /search, la búsqueda original
│   │   ├── ingestion.py               #   pipeline offline, por HTTP
│   │   ├── config.py                  #   GET/PUT /api/v1/config/{models,retrieval}
│   │   ├── security.py                #   require_estimate_key / require_retrieval_key
│   │   ├── rate_limiting.py           #   slowapi, con una cuota por familia de ruta
│   │   └── routers/                   #   S09-S15
│   │       ├── estimate.py            #     /v1/estimate/from-transcript (RAG citado)
│   │       ├── estimate_stages.py     #     /v1/estimate/stages/* (el asistente, paso a paso)
│   │       ├── estimate_tasks.py      #     /v1/estimate/tasks/hours
│   │       ├── retrieval.py           #     /v1/retrieval/search
│   │       ├── retrieval_advanced.py  #     /v1/retrieval/advanced-search
│   │       ├── agent.py               #     /v1/estimate/agent/run
│   │       ├── estimate_graph.py      #     los siete verbos del grafo
│   │       └── references.py          #     /v1/corpus/references (S15)
│   ├── domain/                        # EL CONTRATO Y LOS CONDUCTORES
│   │   ├── schemas/estimation.py      #   EstimationRequest/Result/Response, TurnObservation
│   │   ├── schemas/graph_estimation.py#   el contrato del grafo y HumanDecision
│   │   ├── estimation_service.py      #   conductor CAG/RAG/ACB (S04-S11)
│   │   ├── proposal.py                #   conductor de la propuesta comercial (S15)
│   │   ├── graph/                     #   conductor multi-agente (S13-S14)
│   │   │   ├── build.py state.py      #     topología y estado tipado
│   │   │   ├── supervisor.py agents.py#     el enrutado y los cinco especialistas
│   │   │   ├── hitl.py band.py        #     la puerta humana y la banda histórica
│   │   │   ├── progress.py            #     el feed, derivado del historial (S15)
│   │   │   └── checkpointer.py        #     AsyncPostgresSaver sobre el mismo Postgres
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
│   │   │   ├── chunking/              #     ocho estrategias comparables (S07)
│   │   │   ├── retrieval/             #     pipeline, fusión, reranker, router (S09-S10)
│   │   │   ├── store/                 #     las tres tablas, stats y references (S08-S15)
│   │   │   ├── validation.py          #     verificar citas / aplicar la política (S11)
│   │   │   └── estimator.py           #     la tubería fija transcripción → estimación
│   │   ├── agentic/                   #   Actor-Critic-Boss y el agente a mano (S12)
│   │   └── conversation/              #   ventana, anclas, resumen, metadata
│   └── ingestion/                     # pipeline offline que alimenta RAG
├── tests/                             # 687 tests, sin red ni clave
├── evals/                             # golden set y el arnés de estrés
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

## El mapa de rutas

Treinta y cuatro operaciones. Las agrupa la sesión que las trajo, no el prefijo,
porque el prefijo no dice nada de para qué sirven.

| Ruta | Qué hace | Clave |
|---|---|---|
| `GET /health` | Liveness. No llama al LLM. | **abierta** |
| `POST /api/v1/estimate` | S04 — un disparo, formulario tipado. | estimate |
| `POST /sessions` · `GET /sessions/{id}` | S05 — abrir sesión y leer su estado. | estimate |
| `POST /sessions/{id}/estimate` · `/estimate-acb` | S05 — un turno, y el mismo turno en Actor-Critic-Boss. | estimate |
| `POST /embeddings/compare` | S07 — las ocho estrategias de troceado, con su coste. | estimate |
| `POST /embeddings/ingest` · `GET /embeddings/index/stats` | S08 — ampliar el índice y la foto del corpus. | estimate |
| `POST /search` | S08 — la búsqueda original. Sustituida por `/v1/retrieval/search`. | retrieval |
| `POST /api/v1/ingestion/runs` · `GET /jobs/{id}` | El pipeline offline, por HTTP. | estimate |
| `POST /v1/retrieval/search` | S09 — k-NN con filtros de metadatos y umbral. | retrieval |
| `POST /v1/retrieval/advanced-search` | S10 — el pipeline multi-índice entero. | retrieval |
| `POST /v1/estimate/from-transcript` | S09–S11 — transcripción → estimación citada. | estimate |
| `POST /v1/estimate/stages/*` | S10–S11 — las cinco etapas por separado. | estimate |
| `POST /v1/estimate/tasks/hours` | S11 — horas por tarea desde el histórico. | estimate |
| `POST /v1/estimate/agent/run` | El bucle de la S12, expuesto en la S15. | estimate |
| `POST /v1/estimate/graph` · `/start` | S13–S14 — el grafo, bloqueante y (S15) en 202. | estimate |
| `GET /v1/estimate/graph/{id}/state` · `/progress` | El checkpoint, y el feed derivado de su historial. | estimate |
| `POST /v1/estimate/graph/{id}/resume` | La decisión humana que libera una pausa. | estimate |
| `POST /v1/estimate/graph/{id}/proposal` | S15 — la propuesta comercial. | estimate |
| `GET /v1/estimate/graph/diagram` | La topología, leída del grafo compilado. | estimate |
| `POST /v1/corpus/references` | S15 — el desglose de una referencia histórica. | estimate |
| `GET/PUT /api/v1/config/models` · `/retrieval` | Modelos y modo de búsqueda, en caliente. | estimate |

**`/health` es la única abierta, y a propósito**: cerrarla mataría el healthcheck
de Docker. `/docs`, `/redoc` y `/openapi.json` también responden sin clave, pero no
salen del contenedor: con la frontera de la S15 sólo el backend de negocio alcanza
este servicio.

## Variables de entorno

| Variable | Default | Notas |
|---|---|---|
| `OPENAI_API_KEY` | — | Requerido al menos uno de los dos |
| `ANTHROPIC_API_KEY` | — | Requerido al menos uno de los dos |
| `PRIMARY_MODEL` | `gpt-4o-mini` | Modelo principal del Router |
| `FALLBACK_MODEL` | `claude-haiku-4-5-20251001` | Se usa si el primario falla |
| `REDIS_URL` | — | **Obligatoria desde la S15**: sin default, porque nombra una máquina. El `.env` lleva el valor del despliegue real (`redis://redis:6379`); para correr fuera de Docker se sobrescribe en la invocación, ver [`docs/deployment-local.md`](../docs/deployment-local.md) |
| `DATABASE_URL` | — | **Obligatoria desde la S15**, por lo mismo, y porque el default traía credenciales en código versionado. Bajo Compose se reconstruye interpolando las credenciales del `.env` de la raíz, que es donde viven |
| `CACHE_TTL` | `86400` | Segundos |
| `APP_ENV` | `development` | Controla el renderer de structlog (JSON en `production`) |
| `LOG_LEVEL` | `DEBUG` | Volumen de logs. **Cableado en la S15**: hasta entonces existía, estaba tipada y no filtraba nada. `DEBUG`/`INFO`/`WARNING`/`ERROR`; cualquier otro valor falla al arrancar |
| `ESTIMATE_API_KEY` | — | **Obligatoria desde la S15.** Token (`X-API-Key`) de todas las rutas de estimación (incluida `POST /api/v1/estimate`), de `/sessions/*`, de `/embeddings/*`, de `/api/v1/config/*` y de `/api/v1/ingestion/*`. En blanco ⇒ 401 en todas. Bajo Compose la inyecta `AI_SERVICE_TOKEN` del `.env` de la raíz de la sesión |
| `RETRIEVAL_API_KEY` | — | Token de `/v1/retrieval/search`, `/v1/retrieval/advanced-search` y de la `POST /search` de la S08, que lleva la misma clave que su sustituta |
| `LLM_TIMEOUT` | `120` | Segundos por llamada. Los 30 de antes se quedaban cortos para un modelo de razonamiento |
| `LLM_RETRIES` | `2` | Reintentos del wrapper antes de caer al fallback |
| `RETRIEVAL_SEARCH_MODE` | `vector` | `vector` o `hybrid`. Default conservador: la rama léxica y la fusión se encienden a propósito. Se sobreescribe en caliente con `PUT /api/v1/config/retrieval` |
| `RERANKER_ENABLED` | `false` | El cross-encoder cuesta, así que se pide. Mismo override en caliente |
| `GRAPH_CONFIDENCE_THRESHOLD` | `0.7` | Por debajo, el grafo se para ante una persona |
| `GRAPH_MAX_ROUTING_STEPS` | `8` | El techo real de despachos, persistido en el estado |
| `GRAPH_RECURSION_LIMIT` | `40` | La red de LangGraph, por detrás del techo anterior |
| `GRAPH_PROPOSAL_MODEL` | `gpt-4o` | Quien redacta la propuesta comercial (S15) |

| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | Dónde responde el servicio, para lo que lo LLAMA. No es un campo de `Settings`: la leen del entorno `streamlit_app.py` y los scripts `query_examples.py` / `build_task_corpus.py`. Sin ella, los scripts sondean `localhost:8000` y `ai-service:8000` |

`get_settings()` es un singleton cacheado con `lru_cache`: cualquier cambio en `.env` requiere reiniciar uvicorn (no basta con `--reload`). **Excepción: los modelos LLM** — ver la sección siguiente.

## Configuración de modelos en runtime

Los knobs de modelo (`PRIMARY_MODEL`, `FALLBACK_MODEL`, `CRITIC_MODEL`, `METADATA_EXTRACTOR_MODEL`, `COMPRESSION_MODEL`, `PROPOSITIONAL_CHUNKER_MODEL`, `CONTEXTUAL_CHUNKER_MODEL`, `GRAPH_SUPERVISOR_MODEL`) se pueden **sobreescribir en caliente** sin tocar `.env` ni recrear contenedores — pensado para cambiar de modelo en mitad de un directo.

```
GET /api/v1/config/models
  → {"models": {KEY: {"effective", "default", "overridden"}},
     "available_models": [...],
     "embedding_model": "...", "embedding_model_note": "...",
     "catalog_generated_at": "2026-09-23T16:00:00+02:00",
     "catalog_sources": ["OpenAI", "Anthropic", "TypeSafe"],
     "model_prices": {MODEL: {"input": 0.15, "output": 0.60}},   # US$ por millón de tokens
     "decision_only_knobs": ["GRAPH_SUPERVISOR_MODEL"],
     "decision_models": ["jev-latest", "jev-1.13.0", "jev-preview"]}

PUT /api/v1/config/models
  Body: {"models": {"PRIMARY_MODEL": "gpt-4o", "CRITIC_MODEL": null}}   # null = reset
  → mismo shape que el GET (snapshot fresco)
  422 key desconocida / modelo fuera de catálogo / modelo de decisión en un knob de texto
  400 modelo sin API key · 503 Redis caído
```

`GRAPH_SUPERVISOR_MODEL` entró en caliente en el **PoC de la Sesión 15**, que es
también lo que trae los modelos de **decisión** al catálogo: devuelven una
elección y una probabilidad en vez de texto, por un endpoint propio, así que sólo
son legales en los knobs que `decision_only_knobs` enumera. El resto de knobs del
grafo (`REFORMULATION_MODEL`, `GENERATION_MODEL`, `GRAPH_PROPOSAL_MODEL`) **siguen
congelándose al arrancar**. Todo el diseño, las alternativas descartadas y lo que
el PoC no resuelve, en [`docs/poc-jev-supervisor.md`](../docs/poc-jev-supervisor.md).

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

## Sesiones 9 y 10 — De la búsqueda a la recuperación

La S08 dejaba una búsqueda semántica cruda. La **S09** le pone contrato: k-NN por
distancia coseno con **filtros estructurales aplicados ANTES del ranking** —sector,
año, tipo de chunk—, un `distance_threshold` que hace de suelo, y un *soft-fail*
que devuelve **200 con `low_confidence=true`** en vez de error.

Ese soft-fail es la decisión que gobierna el resto: recuperar basura con confianza
es peor que no recuperar nada. Cuando nada cruza el umbral, el estimador corta a un
presupuesto «contexto insuficiente» en lugar de fundamentarse en ruido.

La **S10** añade dos capas de relevancia encima sin tocar lo anterior:

- **Búsqueda híbrida.** Una rama densa y una rama léxica (Postgres FTS sobre una
  columna `content_tsv` generada `STORED` — la recalcula Postgres, sin trigger y sin
  deriva posible respecto al texto que indexa), fusionadas por **RRF**. Se fusiona
  por POSICIÓN y no por puntuación porque la distancia coseno y `ts_rank_cd` viven
  en escalas incomparables: sumarlas sería sumar peras y kilómetros.
- **Recall-then-rerank.** Se recupera ancho y barato (50) y se reordena fino y caro
  con un cross-encoder multilingüe hasta 5. El reranker se carga en perezoso bajo un
  `threading.Lock` —dos reranks a la vez no disparan dos descargas— y su
  `import sentence_transformers` vive dentro del método, para que arrancar la app o
  correr los tests no arrastre torch.

La misma sesión parte el corpus en **tres colecciones con tabla propia** —
`budget_chunks`, `transcript_chunks`, `technical_doc_chunks`— porque sus esquemas de
metadatos divergen, y `collections.py` es el único sitio que conoce esa divergencia:
por eso el router, el store y el pipeline avanzado pueden ser agnósticos.

`POST /v1/retrieval/advanced-search` encadena transformación de consulta →
enrutado en cascada → filtros duros → híbrida → fusión → reranking → decaimiento
temporal. **Cada etapa es un interruptor independiente**: el camino completo es el
MÁXIMO, no el obligatorio, y `scripts/eval_retrieval_s10.py` mide ocho
configuraciones nombradas que son DATOS (`StageConfig`), no ramas de código.

Dos detalles que valen por sí solos. El **enrutado va en cascada de coste
creciente** —explícito → reglas de vocabulario → clasificador LLM → todas— y
registra su nivel y su motivo, así que se puede auditar por qué miró donde miró. Y
el **decaimiento temporal** (`0.5 ** (antigüedad/semivida)`) es la contraparte
BLANDA de un filtro de fecha: en vez de excluir lo viejo, multiplica su puntuación
para que la frescura desempate sin silenciar la historia.

La respuesta expone no sólo los chunks sino **cómo** se obtuvieron: el enrutado con
su razón, la técnica, las sub-consultas y la cardinalidad por colección — un 0 ahí
delata un vacío silencioso por filtros, que de otro modo se lee como «no hay nada».

## Sesión 11 — La citación baja a la línea

La citación deja de ser del presupuesto entero y pasa a ser **de cada línea**: un
`TaskItem` lleva sus `sources` —el chunk citado y el span **verbatim** que lo
respalda— y un `grounded` obligatorio. El orden de los campos es deliberado:
`sources` y `grounded` se emiten **antes** que `engineer_days`, para que el modelo
se comprometa con su evidencia antes que con la cifra, en vez de elegir un número y
retro-ajustarle una cita.

Y se separan dos cosas que se confundían:

- **`verify_citations()` REPORTA.** Clasifica cada línea en *grounded* / *dangling* /
  *insufficient* y no toca nada. El informe describe lo que produjo el MODELO, que
  es el artefacto interesante.
- **`enforce_citation_policy()` DECIDE.** Resuelve el documento padre, poda lo que no
  resuelve, degrada a `grounded=False` sin horas lo que se queda sin respaldo y
  recalcula el total. Lo que sirve el SERVICIO.

Así «una estimación nunca sale de aquí con una cita que no resuelve» pasa a ser una
propiedad del código y no una promesa del prompt. Es un chequeo **post-generación y
no un validador de Pydantic** a propósito: un validador haría que Instructor
reintentara en silencio dentro de `complete_structured`, que es justo lo contrario
del requisito, que era poder REGISTRAR el resultado (`log_citation_report`,
correlado por `request_id`).

`document_id` se resuelve en el servidor desde el chunk recuperado y nunca se le
pide al modelo: es derivable, así que pedírselo sólo añadiría una superficie más
sobre la que alucinar.

La calidad se mide, no se supone: `scripts/eval_ragas_s11.py` corre el golden set
por la ruta real y puntúa *faithfulness*, *answer relevancy* y *context precision*.

## Sesión 12 — El agente escrito a mano

Donde la ruta S09–S11 es una tubería **fija** —reformular, recuperar, generar—, el
agente **decide** cuántas búsquedas hace y en qué orden. Eso es lo que necesita una
transcripción con componentes sin relación entre sí: buscar «app móvil de repartos»
y «integración con el ERP» en la misma consulta no recupera ninguna de las dos.

Es la **única excepción deliberada** a la regla de que todo pasa por `LLMWrapper`:
conduce a mano `client.responses.create` / `.parse`, porque ver el bucle **es** el
ejercicio. Llega a la recuperación por un backend **inyectado** que busca tareas y
contesta con módulos, porque el agente estima subsistemas y no tareas.

Sus tres herramientas son esquemas planos con `strict: true` — la Responses API no
anida bajo `function` como Chat Completions — y son Python determinista, no
llamadas a un modelo. La ruta HTTP, eso sí, **no es de la S12**: el bucle se
ejecutaba sólo con `scripts/run_agent_s12.py`, y `POST /v1/estimate/agent/run`
llegó en la S15 para que una consola pudiera gobernarlo.

## Sesiones 13 y 14 — El grafo y la puerta humana

La **S13** reexpresa la estimación como un LangGraph explícito: estado tipado
compartido, una responsabilidad por nodo, un checkpoint tras cada superstep. La
**S14** le quita el control de flujo a las aristas y lo mete en `Command`: hoy sólo
existe una arista declarada, `START → supervisor`, y el camino se decide en
ejecución.

**El supervisor es híbrido, y ésa es la decisión de la sesión.** Siete reglas de
Python resuelven las precondiciones —no puedes buscar presupuestos antes de saber
cuáles son los componentes— y al modelo se le hace **exactamente una** pregunta,
la única sobre la que este dominio tiene opinión: los huecos de evidencia, ¿son un
fallo de recuperación o son reales? Pagarle a un modelo por redescubrir lo obvio en
cada corrida no compra nada y añade un modo de fallo.

**Las horas las pone la herramienta y la prosa el modelo.** `estimate_generator`
llama a `calculate_estimate` —mediana de las referencias × 1,15 de contingencia,
Python puro— y al modelo sólo le pide `rationale` y `notes`. Así el único fallo que
todo este pipeline existe para evitar, que un modelo se invente un número, **no
está disponible**. Mediana y no media porque el corpus mezcla tamaños y un análogo
desproporcionado arrastraría la media.

**La confianza se calcula, no se pregunta.** Un modelo al que se le pide puntuar su
propia salida se pone buena nota, y la puerta humana cuelga de ese número:

```
clamp(0.5·grounded_ratio + 0.3·evidence_density + 0.2·proximity − 0.2·arithmetic_issues)
```

Ponderada y no multiplicada: un producto se hunde a cero con un solo término flojo
y mandaría toda corrida a revisión. Y `arithmetic_issues` resta las líneas no
fundamentadas del total de pegas, porque la herramienta emite una por componente
sin referencia y `grounded_ratio` ya mide eso — contar la lista entera penalizaba
DOS VECES cada componente sin presupuesto: en una corrida real puntuaba 0,36 donde
la evidencia decía 0,66.

**La puerta dispara con cualquiera de tres señales** y devuelve la lista de razones,
no un booleano: confianza bajo umbral, estimación fuera de la banda histórica, o el
buscador ha corrido y no ha encontrado nada. «Confianza 0,31» y «tres componentes
sin precedente» son el mismo booleano y dos informes muy distintos.

**La banda histórica se escala por cobertura**, y sin eso el disparador sería
inalcanzable: `calculate_estimate` pone precio a cada componente desde sus propias
referencias, así que una banda construida con esas mismas referencias contiene el
resultado **por construcción** — un control que se cumple solo. Se suman los mínimos
y los máximos de lo que sí se coteó y se escala por `total / con_precio`.

Cuatro detalles que cuestan caro descubrir por las malas:

- **El techo real es `routing_steps`, no `recursion_limit`.** LangGraph cuenta la
  recursión POR INVOKE, así que una corrida que se pausa y se reanuda estrena
  presupuesto en cada resume. Un contador en el checkpoint no.
- **El nodo de la puerta no hace nada salvo interrumpir**, y su span se abre
  DESPUÉS del `interrupt()`. Al reanudar, LangGraph re-ejecuta el cuerpo desde la
  primera línea y descarta lo que escribió la pasada interrumpida; y como
  `interrupt()` funciona levantando una excepción, un span que lo envolviera se
  exportaría con `status=ERROR` — una pausa es el sistema funcionando.
- **El checkpointer es obligatorio.** `compile(checkpointer=None)` con un
  `interrupt()` NO levanta: la corrida se para en silencio y el fallo aflora mucho
  después. `build_graph` lo rechaza, y si no logra abrirse el servicio arranca con
  los verbos del grafo en 503 y el resto intacto.
- **Una denegación del guard degrada, no mata.** Levantar abortaría el superstep sin
  escribir `status`, y el checkpoint aparcaría el hilo en ese nodo para siempre: cada
  reintento fallaría idéntico sin llegar nunca a la puerta humana, que existe
  exactamente para ese caso.

**Privilegio mínimo, comprobado y no descrito** (`app/domain/security/`).
`AGENT_TOOL_GRANTS` reparte **una** herramienta a cada especialista y **cero** al
supervisor, al extractor, a la puerta y al terminal. `verify_tool_grants` corre en
el `lifespan` antes de abrir el checkpointer y levanta: un agente mal concedido
falla el **despliegue**, no la petición — dejarlo degradar a un 503 lo confundiría
con «Postgres está caído». Toda llamada pasa por `execute_guarded` → `guard_action`
→ structlog, con los argumentos redactados a su FORMA: el cuerpo de una
transcripción es material de cliente y no pinta nada en un agregador de logs.

## Sesión 15 — Puesta en producción

El servicio deja de publicar puerto: sólo el backend de negocio lo alcanza, por la
red interna de Compose, y **todas las rutas exigen `X-API-Key`** salvo `/health`,
que es la que interroga el healthcheck de Docker.

### El grafo deja de bloquear

`POST /v1/estimate/graph/start` contesta **202** y deja el grafo corriendo por
detrás; `GET /v1/estimate/graph/{id}/progress` es lo que se sondea mientras tanto.
Antes la petición HTTP se mantenía abierta los minutos que durase el sistema
multiagente, lo que convertía el timeout del cliente en un techo para la
estimación.

Las duraciones por nodo salen del **historial del checkpointer**, que sella cada
superstep, porque el estado del grafo no lleva ni una fecha. Son *finalizaciones*,
no despachos: `routing_trail` escribe su entrada antes de que el agente corra, así
que un feed montado sobre ella enseñaría al agente como terminado todo el rato que
está trabajando.

### La propuesta comercial

`POST /v1/estimate/graph/{id}/proposal` redacta desde la estimación ya validada
**sin re-ejecutar el grafo**. Es un verbo y no un nodo a propósito: el camino feliz
ya gasta cinco de los ocho despachos de `GRAPH_MAX_ROUTING_STEPS`, así que un nodo
competiría por ese presupuesto con el trabajo que produce la estimación. Sobre un
checkpoint terminado cuesta cero pasos de enrutado y se puede volver a redactar sin
volver a estimar.

### La puerta humana, ahora por componente

`HumanDecision` cambia de forma, y **es un cambio que rompe clientes**: pierde la
acción `adjust` y el campo `adjusted_hours`, y gana `component_hours`, un mapa de
`component_id` a horas. El revisor fija cada línea y el total se deriva de la
suma; un total editable aparte es un número que no cuadra con sus partes, que es
justo lo que nadie puede auditar después. Quedan dos acciones, `approve` y
`reject`, y un `adjust` recibe 422.

Lo que propuso el sistema se conserva: `original_estimated_hours` se sella sólo en
los componentes cuyo valor cambió de verdad —sellarlos todos haría indistinguible
«lo revisé y lo dejé igual» de «no lo toqué»— y `original_total_hours` siempre. Se
aplica igual al aprobar y al rechazar.

### `POST /v1/corpus/references` — de dónde sale cada número

El grafo guarda por componente sus `budget_matches`: un identificador y un total de
horas. Con eso el revisor ve «79 h» y no puede juzgar nada, porque no sabe de qué
proyecto salen, de qué año ni de qué stack. Esta ruta abre ese número.

```bash
curl -s -X POST http://ai-service:8000/v1/corpus/references \
  -H "X-API-Key: $ESTIMATE_API_KEY" -H "Content-Type: application/json" \
  -d '{"references": ["TASK-2022-0032/Authentication & Access"]}'
```

Devuelve el módulo histórico con su contexto —proyecto, sector, año, tecnología— y
el desglose por tareas. **Una referencia es un módulo, no una tarea suelta**: el
identificador tiene la forma `{budget_id}/{module}` y las 79 h del ejemplo son
16 + 27 + 36, las tres tareas de ese módulo. Comprobado sobre las 133 referencias
distintas que citan las ejecuciones guardadas: las 133 resuelven y en las 133 la
suma del desglose coincide con el `amount` que viajó en el match.

Dos detalles del contrato:

- Se piden **en lote** (`references: [...]`, máximo 50). Un componente se respalda
  con cinco y su detalle no debería costar cinco viajes. Va en POST y no en GET por
  eso y porque el identificador lleva dentro una barra y un ampersand, que en un
  segmento de ruta obliga a un doble escapado sin ganancia.
- Lo que el corpus ya no tiene sale en **`missing`**, no como error. El corpus se
  reindexa y una estimación guardada cita lo que había entonces; «el número se
  apoya en algo que ya no está» es precisamente lo que hay que poder enseñar, y un
  hueco silencioso lo haría indistinguible de un fallo de red.

El identificador se parte por la **primera** barra, no por todas: hay un módulo
llamado `Frontend / UX` —115 chunks del corpus— y ningún `budget_id` lleva barras.

### Configuración

`DATABASE_URL` y `REDIS_URL` pasan a ser **obligatorias**, sin valor por defecto: un
default que nombra una máquina, un puerto y unas credenciales es el que produce «en
mi máquina funciona», y estas dos ya habían derivado a puertos que dejaron de
publicarse. Los ~70 knobs restantes conservan el suyo a propósito — para un umbral,
el default **es** la documentación.

La vía de ejecución local sin contenedores está en
[`../docs/deployment-local.md`](../docs/deployment-local.md), y es efímera: se
apoya en que una variable de entorno gana al fichero `.env`, así que no hace falta
tocar ningún fichero para depurar contra la base del Compose.

---

> Este proyecto forma parte del **Master en AI Engineering**. Cada sesión añade una
> capa sobre la anterior sin romperla: la estimación de un disparo de la S04 sigue
> respondiendo igual hoy, con un grafo multi-agente y un corpus de 1.543 tareas
> históricas viviendo en el mismo servicio. Lo que cambia de una sesión a otra no es
> el contrato, es de dónde sale el número.
