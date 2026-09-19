# Arquitectura del estimador

Este documento es el **contrato de arquitectura** del servicio. El código de cada sesión
nueva debe respetarlo. Si una pieza no encaja en ninguna capa, primero se decide dónde vive
(y se actualiza este documento), no se crea otra carpeta suelta en la raíz.

## 1. Las tres arquitecturas de IA (y por qué componen)

El estimador no es un único patrón de generación: a lo largo del máster apila tres,
**de forma aditiva**, sobre una base común:

- **CAG — Cache-Augmented Generation** (`app/generation/cag/`). Responde sin tocar el LLM
  cuando ya hay una respuesta equivalente: primero un acierto exacto (SHA-256), luego un
  acierto por similitud vectorial.
- **RAG — Retrieval-Augmented Generation** (`app/generation/rag/`). Convierte un corpus
  (presupuestos históricos) en chunks + embeddings y —a partir de la Sesión 8— los persiste
  y los recupera para enriquecer el prompt con conocimiento citable.
- **Agéntica** (`app/generation/agentic/`). Un bucle Actor-Crítico-Boss que itera y audita la
  estimación antes de aceptarla, apoyado en la conversación multi-turno
  (`app/generation/conversation/`).

**Tesis central**: estas tres capas no se conocen entre sí. **Componen únicamente a través del
conductor** (`app/domain/estimation_service.py`). Esa es la regla que evita que el proyecto
vuelva a degenerar en una sucesión de carpetas acopladas.

## 2. El pastel de capas

```
app/
├── main.py                 # factory FastAPI + lifespan
├── config.py               # settings singleton (get_settings, @lru_cache) + AVAILABLE_MODELS
├── dependencies.py         # composition root: wiring de singletons
│
├── foundation/             # plomería sin opinión de arquitectura AI
│   ├── llm/                #   LLMWrapper (LiteLLM + Instructor) + runtime_config.py (overrides de modelo en Redis) + MODEL_COSTS
│   ├── prompts/            #   loader Jinja2 + plantillas versionadas (estimation/v1..v3, …)
│   ├── guardrails/         #   input (moderación+injection+PII) / output (filter de scope)
│   ├── attachments/        #   extracción de texto de PDF/DOCX subidos
│   └── persistence/        #   engine SQLAlchemy + repositories (jobs, mappings)
│
├── domain/                 # contrato + conductores
│   ├── schemas/            #   EstimationRequest/Result/Response (contrato HTTP)
│   ├── graph/              #   sistema multi-agente (LangGraph): state, supervisor, agents, hitl, build
│   ├── security/           #   sandboxing de aplicación: grants (privilegio) + guard (argumentos) + audit
│   └── estimation_service.py  # EstimationService — conductor del camino CAG/RAG/ACB
│
├── generation/             # las 3 arquitecturas que componen + substrato conversacional
│   ├── cag/                #   exact.py + semantic.py
│   ├── rag/                #   chunking/ + embedding/ + analysis/ + store/ + ingest_service.py + retriever.py
│   ├── agentic/            #   boss.py + critic.py
│   └── conversation/       #   models, store, metadata_extractor, tier_resolver, compression/
│
├── ingestion/              # pipeline batch (offline) que alimenta RAG
│   └── catalog/ loaders/ parsers/ cleaning/ pii/ documents/ orchestrator.py architecture.py
│
└── api/                    # transporte: routers finos, sin lógica de negocio
    ├── estimations.py      #   POST /api/v1/estimate
    ├── sessions.py         #   /sessions/*
    ├── ingestion.py        #   /api/v1/ingestion/*
    ├── embeddings.py       #   POST /embeddings/ingest (persiste desde S8) + /embeddings/compare
    ├── search.py           #   POST /search (búsqueda semántica, S8)
    └── config.py           #   GET/PUT /api/v1/config/models (modelos en runtime)
```

## 3. Reglas de dependencias (MUST / MUST NOT)

De más-importado a menos. Cada capa **solo** puede importar de las que tiene por encima:

| Capa | PUEDE importar | NO PUEDE importar |
|---|---|---|
| `config.py` | (nada interno) | — |
| `foundation/*` | `config` | `domain`, `generation`, `ingestion`, `api` |
| `domain/schemas/*` | `config`, `foundation` | `generation`, `api` |
| `generation/<x>/*` | `config`, `foundation`, `domain/schemas` | `api`, `dependencies`, **otro hermano de `generation`** |
| `domain/estimation_service.py` (CONDUCTOR) | todos los hermanos de `generation` + `foundation` + `schemas` | `api`, `dependencies` |
| `domain/security/*` | `config`, `foundation`, `domain/schemas` | `generation`, `api`, `dependencies`, `domain/graph` |
| `domain/graph/*` (CONDUCTOR) | todos los hermanos de `generation` + `foundation` + `schemas` + `domain/security` | `api`, `dependencies` |
| `ingestion/*` | `config`, `foundation`, `domain/schemas`, `generation/rag` | `api`, el conductor |
| `api/*` | `dependencies`, `domain` (schemas + conductor), excepciones de `foundation` | lógica de negocio |
| `dependencies.py` (COMPOSITION ROOT) | cualquier cosa | (lo importan solo `api/` y los tests) |
| `main.py` | `api`, `config` | — |

**Cuatro aristas especiales, explícitas:**
1. `agentic` **puede** importar `conversation` (lo agéntico se construye sobre el multi-turno).
   La inversa está **prohibida**.
2. Los hermanos de `generation` se encuentran **solo** en un conductor. Si dos capas necesitan
   colaborar, el método que las une va en `EstimationService` o en `domain/graph/`, nunca un
   import cruzado.
3. `domain/security` es una hoja: la usan los agentes del grafo, y no importa a nadie.
   `execute_guarded` recibe la tool como argumento precisamente para no tener que
   importar `generation/agentic` desde aquí.
4. `api/config.py` **puede** leer del catálogo de modelos en `foundation/llm/wrapper`
   (`MODEL_COSTS`, `_provider_from_model`). Es la excepción más incómoda de las cuatro
   y conviene mirarla de frente: ese catálogo **es** el cuerpo de la respuesta de
   `GET /api/v1/config/models`, no una decisión que el endpoint tome con él. Hacerlo
   pasar por el conductor sería ceremonia: `EstimationService` no gana nada
   reenviando una tabla de precios. La regla que sigue en pie es la de siempre —
   `api/` lee DATO de `foundation`, nunca conducta: en cuanto haya que decidir algo
   con ese catálogo, la decisión baja a `domain/`.

   **El catálogo vive partido en dos capas y van en lockstep**: `AVAILABLE_MODELS`
   (`config.py`, lo seleccionable) y `MODEL_COSTS` (`foundation/llm/wrapper.py`, lo
   que cuesta). Un modelo añadido sólo al primero es seleccionable y se factura a
   cero en silencio, porque `_estimate_cost` cae a `{"input": 0.0, "output": 0.0}`
   por defecto. Tocar uno sin el otro es el error que esta separación invita a
   cometer.

**Hay dos conductores, no uno.** `estimation_service.py` conduce el camino CAG/RAG/ACB de las
Sesiones 4-11; `domain/graph/` conduce el sistema multi-agente de las Sesiones 13-14. Ocupan la
misma capa y valen las mismas reglas: ninguno de los dos importa `dependencies`, y por eso los
dos reciben sus colaboradores desde una factory que el composition root rellena.

## 4. El conductor

`app/domain/estimation_service.py::EstimationService` es el único sitio donde se cablean las
capas. Sus tres entradas y qué tocan:

- `estimate()` — guardrails(in) → **cag** (exacto + semántico) → prompts → **llm** → guardrails(out) → cag.store
- `estimate_conversational()` — **conversation** (historial+metadata+compresión) → prompts → llm → guardrails(out)
- `estimate_with_acb()` — **agentic** (Boss orquesta Actor+Critic sobre la conversación)

Cuando RAG entre en el camino de petición (S8+), el paso de retrieval se añade **aquí**, como
un step más del conductor, no dentro de otra capa.

## 5. Composition root

`dependencies.py` y `config.py` viven en la **raíz**, por encima de las capas, a propósito: el
composition root tiene permiso para alcanzar cualquier capa (es su trabajo cablear), así que no
puede pertenecer a ninguna. Toda fábrica de singletons (`get_llm_wrapper`, `get_cache`,
`get_semantic_cache`, `get_session_store`, los chunkers, `get_estimation_service`) está aquí.

## 6. Camino de la petición principal

```
POST /api/v1/estimate
  └→ app/api/estimations.py                         (HTTP fino, mapeo de errores)
       └→ app/domain/estimation_service.py::estimate()
            1. app/foundation/guardrails/input.py     (moderación + injection + PII)
            2. app/generation/cag/exact.py            (acierto exacto SHA-256)
            3. app/generation/cag/semantic.py         (similitud vectorial redisvl)
            4. app/foundation/prompts/loader.py       (Jinja2 versionado)
            5. app/foundation/llm/wrapper.py          (Instructor + validators + re-prompt)
            6. app/foundation/guardrails/output.py    (filter de scope)
            7. cag.exact.set() + cag.semantic.store()
            8. return EstimationResponse(result, prompt_version, cached)
```

## 7. ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Backend LLM, plantilla de prompt, guardrail nuevo | `foundation/` |
| Retrieval, chunking, vector store, embeddings | `generation/rag/` |
| Rol de agente o paso de orquestación | `generation/agentic/` |
| Agente, regla de enrutado o puerta humana del grafo | `domain/graph/` + factory en `dependencies.py` |
| Privilegio de tool, validación de argumentos o auditoría | `domain/security/` |
| Estrategia de cache | `generation/cag/` |
| Lógica de memoria conversacional | `generation/conversation/` |
| Modelo nuevo seleccionable | `AVAILABLE_MODELS` (`config.py`) **y** `MODEL_COSTS` (`foundation/llm/wrapper.py`), en el mismo commit |
| Endpoint HTTP | `api/` (fino) + factory en `dependencies.py` |
| Composición entre capas | método en `EstimationService` (`domain/`), **nunca** import cruzado |
| Fuente de datos / parser / limpieza offline | `ingestion/` |

## 8. Contratos públicos que NO se rompen

- **Rutas HTTP**: `/api/v1/estimate`, `/sessions/*`, `/api/v1/ingestion/*`, `/embeddings/ingest`,
  `/search`, `/api/v1/config/models`.
  Cualquier cliente del servicio depende de ellas y de la forma JSON de
  `EstimationResponse` / `ACBResponse`.
- **`EstimationResult`** (`domain/schemas/estimation.py`): `total_cost_eur` es un
  `computed_field` — se deriva de las fases, no se le pide al modelo, así que el presupuesto
  cuadra por construcción y no por reintento. El único `model_validator` que dispara re-prompt
  es `low_confidence_requires_out_of_scope_prefix`, que es una regla de FORMATO y por tanto de
  las que un re-prompt sí arregla. El orden de campos sigue importando para Instructor
  (`phases` antes que `total_duration_weeks`).

## 9. Roadmap (slots reservados)

- `generation/rag/store/` — persistencia pgvector. **Implementado en el previo de la Sesión 8**
  (modelos `documents`/`chunks` + repositorio async). El índice HNSW se añade en el directo.
- `generation/rag/retriever.py` — recuperación semántica. **Implementado en el previo de la
  Sesión 8** (k-NN por distancia coseno). El filtrado por metadatos/acceso se añade en el directo.
- `generation/rag/ingest_service.py` — orquestación chunk → embed → persist en una transacción
  (composición intra-RAG: chunker + embedder + store, permitida dentro del sibling).
- Integración del retriever en `EstimationService.estimate()` (RAG en el pipeline de
  estimación) — sesiones posteriores; la composición irá en el conductor, como manda la §7.

## Apéndice — Mapa de migración de rutas (vieja → nueva)

| Antes | Ahora |
|---|---|
| `app/services/estimation.py` | `app/domain/estimation_service.py` |
| `app/services/llm_wrapper.py` | `app/foundation/llm/wrapper.py` |
| `app/services/cache.py` | `app/generation/cag/exact.py` |
| `app/cache/semantic.py` | `app/generation/cag/semantic.py` |
| `app/services/boss.py` | `app/generation/agentic/boss.py` |
| `app/services/critic.py` | `app/generation/agentic/critic.py` |
| `app/guardrails/*` | `app/foundation/guardrails/*` |
| `app/prompts/*` | `app/foundation/prompts/*` |
| `app/attachments/*` | `app/foundation/attachments/*` |
| `app/persistence/*` | `app/foundation/persistence/*` |
| `app/schemas/*` | `app/domain/schemas/*` |
| `app/sessions/*` | `app/generation/conversation/*` |
| `app/embedding_pipeline/base.py` | `app/generation/rag/chunking/base.py` |
| `app/embedding_pipeline/chunker.py` | `app/generation/rag/chunking/structural.py` |
| `app/embedding_pipeline/strategies/*` | `app/generation/rag/chunking/strategies/*` |
| `app/embedding_pipeline/embedder.py` | `app/generation/rag/embedding/embedder.py` |
| `app/embedding_pipeline/{similarity,comparison}.py` | `app/generation/rag/analysis/*` |
| `app/embedding_pipeline/schemas.py` | `app/generation/rag/schemas.py` |
| `app/embedding_pipeline/router.py` | `app/api/embeddings.py` |
| `app/routers/*` | `app/api/*` |
