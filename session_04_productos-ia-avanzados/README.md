# Sesión 4 — Productos IA avanzados

## Objetivo de la sesión

En la sesión anterior convertiste tu sistema en algo que empezaba a parecer un producto: añadiste abstracción, eficiencia y una interfaz utilizable. Ahora toca cuestionar una de las decisiones más extendidas — y menos pensadas — en productos con IA: la interfaz.

Casi todos los productos con IA que llegan a producción comparten una misma decisión inicial: un chat, un textarea y un botón. Ese patrón traslada al usuario el peso de saber promptear, y la calidad del resultado pasa a depender de algo que no controlas. En esta sesión damos la vuelta a esa decisión y transformamos el estimator que venimos construyendo en un producto real, con cinco capas de ingeniería que separan un demo de algo que se despliega con confianza.

→ El chat como antipatrón. Cuándo añadirlo perjudica al producto, qué patrones de UI funcionan mejor cuando el espacio de tareas está acotado, y cómo decidir entre un chat y un formulario tipado.

→ Prompts como artefactos de software. Archivos versionados en el repositorio, separación entre estructura y datos, tests que corren en CI sin coste de API.

→ Las cinco capas que diferencian un demo de un producto. Datos estructurados con schema, guardrails de input y de output, validación semántica del contenido y un cache que entiende intención, no solo strings literales.

En esta sesión transformarás la forma en la que tu sistema interactúa con el usuario y con el modelo. El objetivo no es solo mejorar la interfaz, sino ganar control sobre el comportamiento del sistema: reducir la variabilidad, aumentar la consistencia y hacer que el resultado deje de depender de cómo escribe el usuario. Aquí es donde el modelo deja definitivamente de ser el centro y pasa a ser una pieza dentro de una arquitectura de producto más amplia.

---

## Qué vas a aprender

### 1. 📄 De interfaz conversacional a interfaz de producto

El chat es un default, no una decisión de diseño. Cuando un equipo decide "vamos a meter IA en nuestro producto", la mayoría de las veces lo que aparece es un widget de chat, no porque sea la mejor interfaz para el problema, sino porque es la que vimos en ChatGPT y resultó natural copiar.

La clave está en dónde vive el prompt. En la arquitectura de chat, el prompt vive en el textarea del frontend: el usuario lo escribe y tu backend es básicamente un proxy. En la arquitectura de producto, el prompt vive en el backend. El usuario proporciona parámetros (tipo de proyecto, nivel de detalle, formato de salida) y el backend los inyecta en una plantilla versionada antes de enviarlos al LLM.

Las consecuencias prácticas son enormes: el prompt se puede versionar, testear y optimizar para coste; y le quitas la responsabilidad al usuario de saber qué decirle al modelo.

#### El espectro de interfaces

La trampa es pensar en términos binarios: chat o formulario. La realidad es un espectro con cuatro posiciones:

| Posición            | Ejemplo                              | Cuándo usarla                                 |
| ------------------- | ------------------------------------ | --------------------------------------------- |
| Chat puro           | ChatGPT, Claude.ai                   | Problema genuinamente abierto y exploratorio  |
| Chat con parámetros | Perplexity con selectores, Notion AI | Conversacional pero con modos explícitos      |
| Formulario o acción | Linear AI para issues, Cursor        | Espacio de tareas acotado, salida consistente |
| UI generativa       | Vercel AI SDK 3.0                    | El modelo escoge qué componente renderizar    |

Para el estimator, la respuesta es clara: la salida tiene que ser consistente, los parámetros relevantes son finitos, y pertenece al cuadrante de formulario o acción.

#### El contrato entre frontend y backend

El frontend deja de enviar un mensaje y empieza a enviar un `EstimationRequest` tipado:

```python
from enum import Enum
from pydantic import BaseModel, Field

class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"

class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"

class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"

class EstimationRequest(BaseModel):
    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
```

El backend toma esos parámetros, los inyecta en una plantilla versionada y compone el prompt completo antes de enviarlo al LLM. El modelo recibe siempre la misma estructura, solo cambian los valores.

---

### 2. 📄 Plantillas de prompts y prompting desde backend

La tentación inicial es construir el prompt como un f-string en el endpoint. Funciona para el primer demo, pero en cuanto el producto crece el prompt acaba esparcido entre f-strings y condicionales mezclados con la lógica de Python. Cuando aparecen las preguntas de producción ("¿cómo testeamos esto?", "¿cómo hacemos rollback?", "¿qué prompt está activo en cada caso?") ya no hay respuesta clara.

#### El prompt como artefacto: tres componentes

Un prompt de producción es una composición de tres tipos de contenido con ciclos de vida distintos:

La **estructura fija** es lo que no cambia entre requests: el rol del modelo, las instrucciones generales, el formato de salida, los ejemplos few-shot, las reglas de seguridad. Vive en el repositorio en archivos versionados.

Las **variables** son los datos que llegan en cada request: la descripción del proyecto, los archivos adjuntos, el contexto recuperado por RAG. Vienen en el body del HTTP request.

Los **parámetros** son las selecciones del usuario: nivel de detalle, formato de salida, idioma. Se mapean a campos tipados en el `EstimationRequest`.

#### Organización del servicio IA

```
app/
├── prompts/
│   ├── loader.py
│   └── estimation/
│       └── v1/
│           ├── system.j2
│           ├── user.j2
│           └── examples.j2
```

Los prompts viven en su propio directorio, separados del código que los consume. Cada caso de uso tiene sus propios subdirectorios versionados (`v1/`, `v2/`), lo que permite comparaciones entre versiones, rollback rápido y servicio de versiones distintas a segmentos distintos.

El archivo `system.j2` contiene el rol, instrucciones generales y bloques condicionales según `output_format` y `detail_level`. El `user.j2` es deliberadamente minimal: solo envuelve la descripción del proyecto. El `examples.j2` contiene los few-shot, incluido desde el system mediante `{% include %}`.

#### El loader

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from app.schemas import EstimationRequest

PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)

def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    system = _env.get_template(f"estimation/{version}/system.j2")
    user = _env.get_template(f"estimation/{version}/user.j2")

    context = {
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "description": request.description,
    }

    return system.render(**context), user.render(**context)
```

`StrictUndefined` hace que cualquier variable no definida rompa en tiempo de render, evitando prompts malformados silenciosos. La firma `version: str = "v1"` permite cambiar de versión sin tocar el resto del código.

#### Tests del template

Los tests del template no llaman al LLM: son tests de composición, baratos y rápidos, ejecutables en CI sin coste de API:

```python
def test_estimation_prompt_includes_description_in_user_block():
    request = EstimationRequest(
        description="Mobile app with login, chat and push notifications.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )

    system, user = render_estimation_prompt(request)

    assert "<project_description>" in user
    assert "Mobile app with login" in user
    assert "phases_table" in system
    assert "confidence_pct" in system
```

#### XML tags o Markdown: cuándo usar cada uno

Anthropic recomienda XML tags (`<context>`, `<instructions>`): Claude está entrenado prestando especial atención a esos delimitadores. OpenAI tiende a delimitadores Markdown (`## Context`, `## Instructions`). La consistencia importa más que la convención exacta: si tu proveedor principal es Anthropic, usa XML tags; si es OpenAI, usa Markdown.

---

### 3. 📄 Extracción de datos estructurados

El formulario captura parámetros tipados, pero la salida del LLM sigue siendo texto libre. Si el usuario eligió "tabla por fases", el LLM puede devolver prosa en lugar de los campos estructurados que el frontend necesita para renderizar la tabla. El resultado: o escribes un parser frágil, o pagas una segunda llamada al LLM para extraer los datos, o delegas en el usuario.

La solución correcta es definir el **tipo de retorno** de la llamada al LLM con un JSON Schema, igual que defines el tipo de retorno de cualquier endpoint REST.

#### Pydantic como pieza central

Defines el schema una vez y lo usas tres veces: como contrato con el LLM, como documentación de la API REST que expones al cliente, y como tipo de la variable en el código.

```python
from pydantic import BaseModel, Field, model_validator

class Phase(BaseModel):
    name: str
    duration_weeks: int = Field(ge=1, le=52)
    cost_eur: int = Field(ge=0)
    confidence_pct: int = Field(ge=0, le=100)
    assumptions: list[str]

class EstimationResult(BaseModel):
    summary: str
    total_duration_weeks: int = Field(ge=1)
    total_cost_eur: int = Field(ge=0)
    confidence_pct: int = Field(ge=0, le=100)
    phases: list[Phase]

    @model_validator(mode="after")
    def total_must_match_sum_of_phases(self):
        sum_weeks = sum(p.duration_weeks for p in self.phases)
        sum_cost  = sum(p.cost_eur for p in self.phases)
        if abs(sum_weeks - self.total_duration_weeks) > 1:
            raise ValueError("total_duration_weeks does not match phases")
        if abs(sum_cost - self.total_cost_eur) / self.total_cost_eur > 0.05:
            raise ValueError("total_cost_eur does not match phases")
        return self
```

#### Los tres mecanismos según proveedor

**OpenAI — Structured Outputs:** parámetro `response_format` o `text_format` en la llamada. Adherencia garantizada del 100%.

**Anthropic — tool use forzado:** se define una herramienta cuyo `input_schema` es el shape deseado y se fuerza su llamada con `tool_choice`. La respuesta viene como el input de esa herramienta.

**Instructor** unifica ambos mecanismos: detecta el proveedor y empaqueta la llamada con el mecanismo correcto. La interfaz desde el código es siempre la misma, y la respuesta es siempre una instancia tipada del modelo Pydantic:

```python
import instructor
from openai import OpenAI
from app.schemas import EstimationResult

client = instructor.from_openai(OpenAI())

result = client.chat.completions.create(
    model="gpt-4o-mini",
    response_model=EstimationResult,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ],
)

# result is already an EstimationResult instance, no JSON parsing needed.
print(result.total_cost_eur)
```

Cambiar de proveedor con esta abstracción es una línea: `instructor.from_anthropic(Anthropic())`. Si el LLM devuelve algo que no respeta el schema, Instructor reintenta automáticamente antes de lanzar una excepción.

#### El endpoint refactorizado

```python
from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest, EstimationResponse, EstimationResult

@app.post("/estimate")
def estimate(request: EstimationRequest) -> EstimationResponse:
    system, user = render_estimation_prompt(request)

    result: EstimationResult = client.chat.completions.create(
        model="gpt-4o-mini",
        response_model=EstimationResult,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )

    return EstimationResponse(result=result, prompt_version="v1")
```

El servicio IA siempre devuelve el shape rico, no la presentación. Si mañana añades otro canal (PDF, Slack, email), no tocas el servicio IA. La frontera entre datos y presentación queda limpia.

---

### 4. 📄 Guardrails y validación de outputs

El schema válido no garantiza el contenido. Considera estos escenarios: un usuario inyecta instrucciones maliciosas en la descripción (prompt injection), describe un proyecto fuera de scope (reforma del baño), incluye PII en la descripción, o el modelo alucina una fase absurda. Todos pueden producir un `EstimationResult` perfectamente formado. Eso es lo que significa que la forma no garantiza el contenido.

#### La matriz de validación: cuatro cuadrantes

|            | Sintáctico                                         | Semántico                                        |
| ---------- | -------------------------------------------------- | ------------------------------------------------ |
| **Input**  | Pydantic en `EstimationRequest`                    | Moderation API + heurísticas de prompt injection |
| **Output** | Pydantic en `EstimationResult` + `model_validator` | Validators de negocio + LLM-as-judge             |

#### El pipeline: defensa en profundidad

Las capas sucesivas cubren el espacio sin que ninguna sea responsable de todo:

**Capa 1 — Validación sintáctica del input:** `EstimationRequest` valida tipos, rangos y longitudes antes de que el request llegue al endpoint.

**Capa 2 — Validación semántica del input:** la Moderation API de OpenAI clasifica el texto contra categorías de contenido tóxico (~50-100 ms, gratuita). Las heurísticas custom detectan patrones de prompt injection:

```python
PROMPT_INJECTION_PATTERNS = [
    "ignore previous", "ignore all instructions",
    "you are now", "system prompt", "</project_description>",
]

def validate_input(description: str) -> None:
    moderation = openai_client.moderations.create(input=description)
    if moderation.results[0].flagged:
        raise InputModerationError("Description flagged by moderation API")
    lowered = description.lower()
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern in lowered:
            raise InputModerationError(f"Possible prompt injection: {pattern!r}")
```

**Capa 3 — Robustez del prompt:** instrucciones en `system.j2` que definen el comportamiento cuando la descripción está fuera de scope, forzando al modelo a devolver un resultado explícito con `confidence_pct=0` en lugar de inventar contenido.

**Capa 4 — Validación sintáctica del output:** `EstimationResult` con constraints y `model_validator` que verifica coherencia interna (suma de fases con el total).

**Capa 5 — Validación semántica del output:** validators adicionales de negocio y, para casos críticos, LLM-as-judge.

#### Las tres políticas de fallo

| Política          | Cuándo aplicar                                       | Comportamiento                                                           |
| ----------------- | ---------------------------------------------------- | ------------------------------------------------------------------------ |
| **Exception**     | Violación grave (PII, prompt injection, tóxico)      | Rechaza la petición con 400 y mensaje claro                              |
| **Fix con retry** | Error recuperable (JSON malformado, suma incorrecta) | Instructor reintenta con el error como feedback                          |
| **Filter**        | Fuera de scope, confianza baja                       | Devuelve `EstimationResult` con `confidence_pct=0` y `summary` explícito |

Cada guardrail debe declarar explícitamente cuál de las tres políticas aplica. El error más común en producción es no decidir, y acabar con guardrails que se comportan de forma impredecible.

#### Regla de despliegue: logging primero, bloqueo después

Cuando añades un guardrail nuevo, despliégalo en modo "log only" durante una o dos semanas. Mira las muestras que dispara. Ajusta los thresholds con datos reales. Solo entonces actívalo en modo bloqueante.

---

### 5. 📄 Cacheo semántico de respuestas

El estimator ya es un producto serio, pero también es caro y lento. Un mismo proyecto típico puede estimarse quince veces durante una semana por personas distintas con palabras ligeramente distintas. El cache exact-match de la sesión 03 no captura esa repetición porque está diseñado para string equality. Necesitas una capa que reconozca que dos textos distintos están pidiendo lo mismo.

#### La mecánica del cache semántico

El cache semántico cambia la pregunta: en lugar de comparar strings, compara significados usando **embeddings**, representaciones vectoriales del texto en un espacio de muchas dimensiones. Dos textos que dicen lo mismo producen vectores cercanos; dos textos sin relación producen vectores lejanos.

El flujo:

1. Llega un request → se calcula el embedding del input.
2. Se busca en el cache el vector más cercano mediante similaridad coseno.
3. Si la similaridad supera un threshold (típicamente 0.90-0.93), es un hit → se devuelve la respuesta cacheada.
4. Si no, es un miss → se llama al LLM y se guarda la pareja (embedding, respuesta).

#### El threshold como decisión de producto

Un threshold agresivo (0.85) maximiza hits pero introduce el riesgo de servir una respuesta incorrecta para una pregunta materialmente diferente. Un threshold conservador (0.95) elimina falsos positivos pero reduce los hits. La regla: desplegar en modo log-only primero, calibrar el threshold con datos reales.

#### La cache key compuesta

La cache key combina dos partes para evitar colisiones entre requests con mismos textos pero distintos parámetros:

```python
def build_bucket_key(request: EstimationRequest, version: str = "v1") -> str:
    return ":".join([
        version,
        request.project_type.value,
        request.detail_level.value,
        request.output_format.value,
    ])
```

Incluir `prompt_version` en la clave tiene una ventaja importante: cuando subes a `v2`, los buckets de `v1` quedan automáticamente huérfanos sin necesidad de invalidación manual.

#### Implementación con Redis + redisvl

```python
from redisvl.extensions.llmcache import SemanticCache

cache = SemanticCache(
    name="estimation_cache",
    redis_url="redis://localhost:6379",
    distance_threshold=0.08,  # equivalente a sim ≥ 0.92
    ttl=86400,
)

@app.post("/estimate")
def estimate(request: EstimationRequest) -> EstimationResponse:
    validate_input(request.description)       # input guardrails primero

    cached = cache_lookup(request)
    if cached is not None:
        return EstimationResponse(result=cached, prompt_version="v1", cached=True)

    system, user = render_estimation_prompt(request)
    result = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        response_model=EstimationResult,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )

    cache_write(request, result)   # escribir al cache solo después de guardrails
    return EstimationResponse(result=result, prompt_version="v1", cached=False)
```

#### El orden importa: guardrails antes del cache

Los input guardrails van siempre antes del lookup en cache. Si se saltara la moderación para ahorrar 50 ms, un atacante que sabe que cierto contenido tóxico está en cache podría activar el hit sin pasar por ningún filtro. El cache solo se escribe después de que la respuesta haya pasado todos los guardrails de output.

El campo `cached: bool` en `EstimationResponse` es valioso para el frontend (puede indicar al usuario que la respuesta vino de cache) y para observabilidad (permite medir la tasa real de hits en producción).

---

## Ejercicios prácticos

### ✍️ Ejercicio — Del chat a la interfaz de producto

El estimator que dejamos al final de la sesión 03 es funcional pero tiene dos problemas que nacen de la misma decisión: hemos dejado el prompting en manos del usuario y el prompt vive como un string dentro del código. Antes del directo, vamos a corregir las dos cosas a la vez.

**Punto de partida:** el proyecto de la Sesión 3 — servicio FastAPI con wrapper de proveedores, cliente Streamlit con chat conversacional, caching exact-match, streaming y structlog.

#### Parte 1 — Schemas y formulario en el cliente

Define el contrato entre cliente y servicio IA con Pydantic v2. En `app/schemas.py`, crea las clases `ProjectType`, `DetailLevel`, `OutputFormat`, `EstimationRequest` y `EstimationResponse` tal y como se describe en el Bloque 1.

En el cliente Streamlit, sustituye el chat por un formulario con `st.form`. El envío debe producir un `EstimationRequest` y hacer `POST /estimate` al servicio IA con ese JSON.

#### Parte 2 — Estructura de prompts y loader en el servicio IA

Crea la estructura de directorios `app/prompts/` con el loader y los templates:

- `system.j2`: rol del modelo, instrucciones generales, bloque condicional según `output_format`, bloque condicional según `detail_level`. Incluye `examples.j2` con `{% include %}`.
- `user.j2`: el bloque que envuelve la descripción del proyecto.
- `examples.j2`: dos o tres ejemplos few-shot de estimaciones bien formadas.

El loader debe exponer `render_estimation_prompt(request, version="v1") -> tuple[str, str]` usando `StrictUndefined`, `trim_blocks=True` y `lstrip_blocks=True`.

#### Parte 3 — Refactor del endpoint

Cambia el endpoint `POST /estimate` para que acepte `EstimationRequest`, llame a `render_estimation_prompt(request)` para obtener `(system, user)`, y llame al modelo con los dos roles separados. Mantén el wrapper de proveedor de la sesión 03.

#### Parte 4 — Tests del template (obligatorio)

En `tests/prompts/test_estimation_v1.py` añade al menos tres tests:

- Que `description` aparece dentro del bloque `<project_description>` del user prompt.
- Que con `output_format=phases_table` el system contiene la palabra clave del formato, y que con `narrative` no la contiene.
- Que con `detail_level=detailed` el system incluye la instrucción de listar asunciones, y que con `summary` no aparece.

Estos tests deben correr en milisegundos, sin llamadas a APIs externas.

#### Checklist de verificación

- [ ] El cliente Streamlit muestra un formulario con campos tipados, no un textarea libre
- [ ] `POST /estimate` acepta un body `EstimationRequest` y devuelve `EstimationResponse`
- [ ] El prompt vive en `app/prompts/estimation/v1/`, no en el endpoint
- [ ] `render_estimation_prompt` usa `StrictUndefined` y acepta un parámetro `version`
- [ ] Los tests de template corren sin llamadas a la API
- [ ] La API key no está hardcodeada

#### Bonus opcional

- **Versionado real:** crea un `v2/` con una variación deliberada del prompt y haz que el endpoint acepte `?prompt_version=v2` como query param.
- **Contexto de proyectos similares:** añade `reference_projects: list[ReferenceProject] | None` al schema y recórrelo con `{% for %}` en el template cuando esté presente.
- **Logging del prompt:** añade structlog al loader para emitir un evento con la versión del prompt y un hash del contenido renderizado.

> **Nota:** Tres temas quedan reservados para el directo y no deben adelantarse: forzar JSON estructurado en la salida, guardrails de validación del output, y cacheo semántico. Se introducen con contexto en el directo y la solución de clase puede diferir de una implementación previa.

---

### Entregable

Una rama `pre-session-04` en tu repositorio con todos los cambios, un README breve actualizando cómo se levanta y cómo se ejecutan los tests, y opcionalmente una captura o GIF de la nueva interfaz funcionando.

Envía el enlace a tu rama a George a través de george@lidr.co con al menos dos días de antelación a la sesión en vivo. Las entregas posteriores no se podrán incluir en la revisión grupal del inicio del directo.

---

## Checklist antes de la siguiente sesión

- [ ] El cliente Streamlit muestra un formulario tipado con campos explícitos, no un textarea libre
- [ ] El endpoint `/estimate` acepta un `EstimationRequest` con `project_type`, `detail_level` y `output_format`
- [ ] El prompt vive en `app/prompts/estimation/v1/`, no en un f-string en el código
- [ ] `render_estimation_prompt` usa Jinja2 con `StrictUndefined` y acepta una versión como parámetro
- [ ] Hay tests de template que verifican composición del prompt sin llamar a la API
- [ ] Entiendes la diferencia entre el chat como default y el chat como decisión de diseño, y sabes en qué punto del espectro situar el estimator
- [ ] Entiendes por qué el prompt es un artefacto de software y qué implica versionarlo con `v1/`, `v2/`
- [ ] Entiendes la diferencia entre validación sintáctica y semántica y los cuatro cuadrantes (input/output × sintáctico/semántico)
- [ ] Entiendes las tres políticas de fallo de un guardrail (exception, fix con retry, filter) y cuándo aplica cada una
- [ ] Entiendes por qué el cache semántico necesita una cache key compuesta y por qué los guardrails van antes del lookup
- [ ] Entiendes el threshold del cache semántico como decisión de producto, no técnica, y sabes cómo calibrarlo con datos

---

## Documentación de referencia

- Amelia Wattenberger — Why Chatbots Are Not the Future: https://wattenberger.com/thoughts/boo-chatbots
- Andrej Karpathy — Software Is Changing (Again) (AI Startup School, Y Combinator): https://www.youtube.com/watch?v=LCEmiRjPEtQ
- Vercel — Introducing AI SDK 3.0 with Generative UI support: https://vercel.com/blog/ai-sdk-3-generative-ui
- Anthropic — Prompt engineering overview: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview
- Anthropic — Use prompt templates and variables: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prompt-templates-and-variables
- Anthropic — Use XML tags to structure your prompts: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags
- Jinja2 — Template Designer Documentation: https://jinja.palletsprojects.com/en/stable/templates/
- OpenAI — Structured Outputs (guía técnica): https://platform.openai.com/docs/guides/structured-outputs
- Anthropic — Tool use overview: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Pydantic — Models: https://docs.pydantic.dev/latest/concepts/models/
- Instructor — Documentación oficial: https://python.useinstructor.com/
- Eugene Yan — Patterns for Building LLM-based Systems & Products: https://eugeneyan.com/writing/llm-patterns/
- Guardrails AI — Quickstart: https://www.guardrailsai.com/docs
- OpenAI — Moderation guide: https://platform.openai.com/docs/guides/moderation
- Anthropic — Reduce hallucinations: https://docs.anthropic.com/en/docs/test-and-evaluate/strengthen-guardrails/reduce-hallucinations
- Redis — What is semantic caching?: https://redis.io/blog/what-is-semantic-caching/
- Redis — redisvl Semantic Cache documentation: https://docs.redisvl.com/en/stable/user_guide/llmcache_01.html
