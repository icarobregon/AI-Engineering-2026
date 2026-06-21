# Sesión 5 — Funcionalidades avanzadas en productos IA

Extensión del estimador CAG de la sesión 4 hacia un sistema **multi-turno con memoria conversacional y soporte de adjuntos**.

---

## Punto de partida

- **Backend**: solución *live* del profesor (`answers/session_4_live/estimator`) — FastAPI con guardrails de entrada/salida, caché exacta + semántica (Redis Stack), salida estructurada vía Instructor + validadores Pydantic.
- **Frontend**: Streamlit propio, reescrito para consumir los nuevos endpoints conversacionales y renderizar la salida estructurada.

---

## Cómo levantar el sistema

### Con Docker Compose (recomendado)

Requiere Docker con Redis Stack (incluye RediSearch + RedisJSON para la caché semántica).

```bash
cd session_05_funcionalidades-avanzadas-en-productos-ia/estimator

# Copia las variables de entorno (añade tus API keys)
cp .env.example .env

# Levanta backend + Redis
docker compose up --build
```

El backend queda en `http://localhost:8000` (docs en `/docs`).

### Sin Docker (uvicorn local)

Requiere Redis Stack corriendo localmente en `localhost:6379`.

```bash
cd session_05_funcionalidades-avanzadas-en-productos-ia/estimator
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### Streamlit

```bash
# En otro terminal, desde la misma carpeta
uv run streamlit run streamlit_app.py
```

---

## Cómo ejecutar los tests

```bash
cd session_05_funcionalidades-avanzadas-en-productos-ia/estimator
uv sync
uv run pytest
```

La suite completa (66 tests) no requiere Redis ni API keys: las dependencias de LLM y Redis se mockean en tests.

---

## Decisiones de implementación

### Adjuntos — Camino B (extracción local)

Se eligió **Camino B** sobre el Camino A (multimodal Files API) por tres razones:

1. **Sin lock-in de proveedor**: funciona con cualquier modelo via LiteLLM, no sólo Anthropic.
2. **Control fino**: se decide exactamente qué texto entra al contexto; útil para filtrar cabeceras irrelevantes de un PDF antes de enviarlo al LLM.
3. **Preparación para RAG**: el texto extraído localmente es el mismo que el pipeline de chunking de las sesiones 7+ necesita. El Camino A no prepara ese pipeline.

Formatos soportados: **PDF** (`pypdf`) y **DOCX** (`python-docx`). Otros formatos se aceptan pero se omiten con un warning sin abortar la petición.

El texto extraído se concatena al transcript con el separador:
```
--- attachment: <filename> ---
```

Los guardrails de entrada corren sobre el **texto combinado** (transcript + adjuntos). Limitación conocida: PII en un adjunto bloquea la petición con HTTP 400.

### Extracción de ProjectMetadata — LLM extractor

Se eligió el **LLM extractor** sobre la heurística regex por:

- Las transcripciones son texto libre en ES/EN con alta variabilidad → regex sería frágil.
- El modelo recibe `response_model=ProjectMetadata` (Instructor + Pydantic), lo que garantiza un JSON bien formado incluso si el modelo es impreciso.
- El coste es una segunda llamada LLM ligera (~512 tokens, modelo primario) por turno.

La regla del README lo confirma: *"dominio abierto, multilingüe, con variabilidad alta → LLM extractor"*.

La fusión de metadata sigue la política:
- **Escalares** (`project_name`, `assumed_team_size`, `agreed_scope`): sobrescriben el valor previo sólo cuando el extractor devuelve un valor no nulo.
- **Listas** (`mentioned_technologies`, `explicit_constraints`, `rejected_options`): se acumulan (unión sin duplicados, insensible a mayúsculas).

---

## Arquitectura añadida en la sesión 5

```
POST /sessions                    → crea sesión (uuid4), devuelve session_id
POST /sessions/{id}/estimate      → turno conversacional (multipart/form-data)
  └── attachments.py              → extracción local PDF/DOCX
  └── services/conversation.py   → orquestador del turno
      ├── check_input()           → guardrails de entrada (heredado)
      ├── render_estimation_prompt_with_metadata()  → prompt v2 con <project_metadata>
      ├── llm_wrapper.complete_structured(..., history=...)  → estimación
      ├── enforce_scope_response()                 → guardrail de salida (heredado)
      └── _extract_and_merge_metadata()            → LLM extractor + merge
  └── sessions.py                 → ConversationHistory + ProjectMetadata + SessionStore
```

Los endpoints transaccionales (`/api/v1/estimate`) y la caché Redis no se modificaron.

---

## Checklist de verificación (del README de la sesión)

- [x] `POST /sessions` crea una sesión y devuelve `session_id`
- [x] `POST /sessions/{session_id}/estimate` acepta `multipart/form-data` con transcripción y adjuntos opcionales
- [x] Tras varios turnos, el LLM responde con coherencia respecto al proyecto en curso
- [x] El `project_metadata` se actualiza visiblemente entre turnos
- [x] El historial respeta el límite de la ventana deslizante (`MAX_TURNS=6`)
- [x] Los tests del Paso 7 pasan en local

---

## Limitaciones conocidas

- El `SessionStore` es un dict en memoria: un reinicio del servidor pierde todas las sesiones activas. Se persistirá en BBDD en una sesión posterior.
- La extracción de PDF es texto puro; PDFs escaneados sin OCR devuelven texto vacío (el transcript sigue funcionando normalmente).
- Los guardrails de PII pueden bloquear adjuntos que contengan emails o teléfonos de ejemplo en el documento.
