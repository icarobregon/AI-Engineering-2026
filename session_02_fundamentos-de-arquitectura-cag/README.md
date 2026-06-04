# Sesión 2 — Primeros pasos de arquitectura CAG

## Objetivo de la sesión

Esta sesión marca el salto clave del programa: pasar de una integración puntual con un modelo a la construcción de un sistema real. Aquí empieza el **Proyecto 1**, un sistema de estimación automatizada de software que recibirá transcripciones de reuniones con clientes y generará presupuestos basándose en el historial de la empresa. No es un ejercicio aislado — es el proyecto que evolucionará sesión a sesión hasta convertirse en un producto completo.

El foco deja de estar en la llamada al modelo y pasa a la arquitectura que la rodea: cómo estructurar el sistema, cómo gestionar el contexto y cómo tomar decisiones que impactan directamente en el resultado. En esta sesión se establecen las bases que condicionarán todo lo que vendrá después.

---

## Qué vas a aprender

### 1. 📄 Qué es CAG (Cache Augmented Generation)

Un LLM tiene conocimiento de entrenamiento con fecha de corte y sin información privada de tu empresa. Para resolver esto, existen dos grandes estrategias: **RAG** (Retrieval Augmented Generation) y **CAG** (Cache Augmented Generation).

**RAG** busca los documentos más relevantes en una base de datos vectorial en el momento de la consulta y los incluye en el prompt. Es potente y escalable, pero introduce latencia de búsqueda, errores de selección de documentos y complejidad de infraestructura.

**CAG** propone un enfoque radicalmente más simple: precargar todo el conocimiento necesario directamente en la ventana de contexto del modelo. No hay búsqueda en tiempo real, no hay base de datos vectorial, no hay pipeline de retrieval.

```
# Flujo RAG
Pregunta → Búsqueda vectorial → Selección de fragmentos → Prompt → LLM → Respuesta

# Flujo CAG
Todo el conocimiento (precargado) + Pregunta → Prompt → LLM → Respuesta
```

**Cuándo usar CAG:**

| Criterio                          | CAG ✅                     | RAG ✅                                |
| --------------------------------- | -------------------------- | ------------------------------------- |
| Tamaño de la base de conocimiento | Acotada (cabe en contexto) | Masiva (miles de documentos)          |
| Frecuencia de actualización       | Estática o semestática     | Tiempo real o diaria                  |
| Latencia requerida                | Mínima (sin retrieval)     | Tolerable (retrieval añade latencia)  |
| Complejidad arquitectónica        | Baja (menos componentes)   | Alta (vectorDB, embeddings, pipeline) |
| Coste por token                   | Mayor por llamada          | Menor por llamada (contexto reducido) |

Una arquitectura CAG completa tiene cinco componentes: la **fuente de conocimiento** (datos de referencia), la **capa de preprocesamiento** (selección y formateo), el **constructor de prompts** (system prompt + contexto + mensaje de usuario), el **servicio de llamada al LLM** (gestión de API, errores, rate limits) y el **postprocesamiento** (parseo y validación del output).

**El camino de evolución natural del proyecto:**

```
Módulo 2: CAG
↓ (contexto estático, sin persistencia, todo en el prompt)
↓
Módulos 3-4: RAG
↓ (base de datos vectorial, embeddings, búsqueda semántica)
↓
Módulo 5: Agentes
  (orquestación, razonamiento multi-paso, tools)
```

---

### 2. 📄 Don't do RAG when CAG is all you need (paper)

Paper fundacional de CAG presentado por Chan et al. en la ACM Web Conference 2025. Propone precargar todo el conocimiento relevante mediante KV-cache precomputado, eliminando el retrieval en tiempo real. Los benchmarks en SQuAD y HotPotQA muestran que CAG iguala o supera a RAG en precisión con tiempos de generación notablemente menores.

📎 Referencia: https://arxiv.org/html/2412.15605v1

---

### 3. 📄 Arquitectura escalable en proyectos IA generativa

#### ¿Por qué FastAPI?

Las aplicaciones con LLMs tienen un perfil de ejecución diferente al de las aplicaciones web tradicionales: una llamada a un LLM puede tardar entre 2 y 30 segundos. Un framework síncrono bloquea un thread completo durante todo ese tiempo. FastAPI, construido sobre ASGI con soporte nativo de async/await, libera el event loop mientras espera la respuesta del LLM, permitiendo manejar decenas de peticiones concurrentes con el mismo consumo de memoria.

#### La estructura del proyecto

```
estimador-cag/
├ app/
│ ├ main.py             ← Punto de entrada
│ ├ config.py           ← Configuración centralizada
│ ├ routers/
│ │ └ estimations.py   ← Endpoints HTTP (capa de transporte)
│ ├ services/
│ │ └ llm_service.py   ← Lógica de negocio (capa inteligente)
│ ├ schemas/
│ │ └ estimation.py    ← Contratos de datos (request/response)
│ └ context/
│   └ examples.py       ← Datos de referencia para CAG
├ .env
├ .env.example
├ .gitignore
└ pyproject.toml
```

Cada capa tiene una responsabilidad única. Los **routers** son delgados: reciben, delegan y devuelven. La **lógica** de prompts y llamadas al LLM vive en los **services**. Los **schemas** Pydantic definen los contratos de la API y validan datos. La capa **context** es el punto de sustitución entre CAG y RAG: hoy son datos estáticos, mañana será un servicio de búsqueda semántica.

#### Configuración con Pydantic BaseSettings

```python
# config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "DEBUG"

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

@lru_cache carga la configuración una sola vez. Si OPENAI_API_KEY no está definida, la aplicación falla al arrancar, no cuando el primer usuario hace una petición. **Fallar rápido es una ventaja.**

#### El router: delgado por diseño

```python
# routers/estimations.py
from fastapi import APIRouter
from app.schemas.estimation import EstimationRequest, EstimationResponse
from app.services.llm_service import generate_estimation

router = APIRouter(prefix="/api/v1", tags=["estimations"])

@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest):
    result = await generate_estimation(request.transcription)
    return result
```

#### El servicio: donde vive la inteligencia

```python
# services/llm_service.py
from openai import OpenAI
from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES

settings = get_settings()
client = OpenAI(api_key=settings.OPENAI_API_KEY)

def build_system_prompt() -> str:
    examples_text = format_examples(ESTIMATION_EXAMPLES)
    return f"""Eres un experto en estimación de proyectos de software.

Utiliza los siguientes presupuestos históricos como referencia:

{examples_text}

Genera una estimación detallada para el proyecto descrito."""

async def generate_estimation(transcription: str) -> dict:
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user",   "content": transcription}
        ]
    )
    return {
        "estimation": response.choices[0].message.content,
        "model": settings.LLM_MODEL,
        "provider": settings.LLM_PROVIDER,
    }
```

#### Gestión de dependencias con uv

```bash
# Instalar dependencias
uv sync

# Añadir una nueva dependencia
uv add httpx

# Arrancar la aplicación
uv run uvicorn app.main:app --reload
```

---

### 4. 📄 Gestión efectiva de contexto en arquitectura CAG

La ventana de contexto es el recurso más valioso y la limitación más dura de una arquitectura CAG. Todo lo que el modelo necesita saber debe caber en esa ventana: instrucciones del system prompt, datos de referencia, la consulta del usuario y el espacio para la respuesta.

#### Anatomía de la ventana de contexto

| VENTANA DE CONTEXTO  | CONTENIDO                  | ej: 128K tokens                             |
| -------------------- | -------------------------- | ------------------------------------------- |
| System prompt        | instrucciones + rol        | ~500-1.500 tokens                           |
| Contexto inyectado   | estimaciones de referencia | ~2.000-40.000 tokens según volumen de datos |
| Mensaje del usuario  | transcripción de reunión   | ~500-5.000 tokens                           |
| Respuesta del modelo | estimación generada        | ~1.000-3.000 tokens                         |

Hay un matiz crítico: aunque todo quepa, los modelos prestan más atención al contenido al principio y al final del contexto. La información enterrada en el medio tiende a perderse — fenómeno conocido como **"lost in the middle"**.

#### Principios para gestionar el contexto

**Menos es más.** El objetivo no es llenar la ventana sino incluir la información mínima necesaria con la máxima calidad. Cada token adicional tiene coste económico y coste atencional.

**El formato importa tanto como el contenido.** Usar separadores claros entre ejemplos de referencia y mantener datos normalizados y coherentes produce respuestas significativamente mejores que un volcado en crudo.

**La posición es una decisión de ingeniería:**

1. System prompt con instrucciones claras → AL PRINCIPIO (máxima atención)
2. Estimaciones de referencia (las más relevantes primero) → en el medio
3. Restricciones y reglas específicas → cerca del final
4. Transcripción de la reunión (mensaje del usuario) → AL FINAL (máxima atención)

#### El system prompt efectivo

```
# Débil — produce respuestas genéricas:
"Eres un asistente que ayuda con estimaciones de software."

# Efectivo — define rol, tarea, uso del contexto y formato del output:
"""
Eres un consultor senior de software con 15 años de experiencia en estimación
de proyectos. Analiza transcripciones de reuniones con clientes y genera
estimaciones detalladas usando los ejemplos históricos como referencia de
precios, granularidad de tareas y estructura del presupuesto.

Tu estimación debe incluir:
1. Resumen del proyecto (2-3 frases)
2. Desglose de tareas con horas estimadas y coste
3. Equipo recomendado
4. Duración total estimada
5. Riesgos o supuestos clave

Usa EUR como moneda. Redondea las horas a múltiplos de 5.
"""
```

#### Cuántos ejemplos de referencia incluir

| Número de ejemplos | Situación                                             |
| ------------------ | ----------------------------------------------------- |
| 2-3 ejemplos       | Mínimo viable para CAG funcional                      |
| 5-7 ejemplos       | Punto óptimo — diversidad sin ruido                   |
| +10 ejemplos       | Rendimientos decrecientes, considerar migración a RAG |

#### Formato de los ejemplos: Markdown como estándar

```markdown
===== ESTIMACIÓN DE REFERENCIA 1 =====

**Proyecto:** Plataforma de gestión de inventario
**Tareas:**

- Diseño UI/UX: 40 horas a 400 EUR/h → 16.000 EUR
- Backend API REST: 60 horas a 500 EUR/h → 30.000 EUR
- Autenticación y roles: 20 horas a 500 EUR/h → 10.000 EUR

**Total:** 120 horas — 56.000 EUR
**Equipo:** 2 developers full-stack, 1 diseñador UX (part-time)
**Duración:** 6-8 semanas

===== FIN DE ESTIMACIÓN 1 =====
```

#### Ciclo de iteración en CAG

Una ventaja clave de CAG es la velocidad de iteración: los datos de referencia están en código, por lo que ajustar un ejemplo o el system prompt es inmediato — sin re-indexar bases de datos ni recalcular embeddings.

```
1. Ejecutar estimación con transcripción de prueba
2. Evaluar la calidad del resultado
3. Identificar el problema:
   ¿Formato inadecuado?       → Ajustar system prompt
   ¿Precios descalibrados?    → Mejorar ejemplos de referencia
   ¿Desglose demasiado vago?  → Añadir más detalle a los ejemplos
4. Modificar el contexto
5. Volver al paso 1
```

---

### 5. 📄 Arquitectura de conversaciones con modelos

#### La realidad técnica: stateless por diseño

Cada llamada a un LLM es stateless. El modelo no recuerda nada entre llamadas. En cada petición, la aplicación empaqueta toda la conversación completa como un array de mensajes y lo envía al modelo, que lo procesa de principio a fin y genera una respuesta.

```python
messages = [
    {"role": "system",    "content": "Instrucciones para el modelo..."},
    {"role": "user",      "content": "Primera pregunta del usuario"},
    {"role": "assistant", "content": "Primera respuesta del modelo"},
    {"role": "user",      "content": "Segunda pregunta del usuario"},
    # → el modelo genera la respuesta a esta última entrada
]
```

#### Los tres roles

| Rol       | Función                                                    | Particularidades                                             |
| --------- | ---------------------------------------------------------- | ------------------------------------------------------------ |
| system    | Define comportamiento global. Instrucciones, rol, formato  | Se envía en cada llamada. En Anthropic es parámetro separado |
| user      | Mensajes del ser humano. En nuestro caso: la transcripción | Cada turno añade un nuevo mensaje                            |
| assistant | Respuestas previas del modelo                              | El desarrollador es responsable de guardarlas e incluirlas   |

#### Single-turn vs. Multi-turn

**Single-turn** (transaccional): una transcripción entra, una estimación sale. Sin historial que gestionar. Ideal para empezar y para casos de uso donde no se necesita refinamiento iterativo.

```python
messages = [
    {"role": "system", "content": system_prompt_con_contexto},
    {"role": "user",   "content": transcripcion_de_reunion}
]
```

**Multi-turn** (conversacional): el usuario puede refinar la estimación en un diálogo natural. El historial crece con cada turno y hay que gestionarlo explícitamente.

```python
conversation = [
    {"role": "system",    "content": system_prompt},
    {"role": "user",      "content": "Estima este proyecto: [transcripción]"},
    {"role": "assistant", "content": "## Estimación: ...\n1. Diseño: 40h..."},
    {"role": "user",      "content": "Sube diseño a 60 horas y añade testing"},
    # → modelo responde con contexto completo
]
```

#### Gestión del historial en memoria

```python
class ConversationManager:
    def __init__(self, system_prompt: str):
        self.messages = [{"role": "system", "content": system_prompt}]

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list:
        return self.messages.copy()
```

#### Estrategias de truncamiento cuando el historial crece

**Ventana deslizante** (recomendada para esta fase): conservar siempre el system prompt y solo los últimos N turnos.

```python
def get_messages_windowed(self, max_turns: int = 10) -> list:
    system = [self.messages[0]]
    history = self.messages[1:]

    if len(history) > max_turns * 2:
        history = history[-(max_turns * 2):]

    return system + history
```

**Resumen acumulativo**: cuando el historial alcanza cierto tamaño, usar el propio LLM para resumir los turnos antiguos y reemplazarlos por ese resumen compacto.

**Estrategia híbrida**: combinar ventana deslizante con "turnos ancla" (decisiones clave que nunca se descartan) para conversaciones largas en producción.

#### El flujo completo de una petición

```python
async def generate_estimation(
    transcription: str,
    conversation_history: list | None = None
) -> dict:

    system_prompt = build_system_prompt()

    if conversation_history:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": transcription})
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": transcription}
        ]

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages
    )

    return {
        "estimation": response.choices[0].message.content,
        "model": settings.LLM_MODEL,
        "usage": {
            "input_tokens":  response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens
        }
    }
```

#### Diferencias entre proveedores que afectan al código

| Aspecto              | OpenAI                              | Anthropic                           |
| -------------------- | ----------------------------------- | ----------------------------------- |
| System prompt        | Mensaje dentro del array messages   | Parámetro separado system="..."     |
| Campo de respuesta   | response.choices[0].message.content | response.content[0].text            |
| Alternancia de roles | Flexible                            | Alternancia estricta user/assistant |

---

## Ejercicios prácticos

### ✍️ Ejercicio — Scaffolding del proyecto FastAPI

**Objetivo:** Construir la estructura base del Proyecto 1: una aplicación FastAPI con un endpoint que reciba el texto de una transcripción de reunión y devuelva una estimación de software generada por un LLM, utilizando arquitectura CAG (contexto estático inyectado en el prompt).

**Formato:** Proyecto local en Python. Entrega funcional: el servidor debe arrancar y responder a peticiones.

#### Paso 1 — Inicializar el proyecto con uv

Crea la estructura de directorios y configura el proyecto:

```
estimador-cag/
├ app/
│ ├ __init__.py
│ ├ main.py
│ ├ config.py
│ ├ routers/
│ │ ├ __init__.py
│ │ └ estimations.py
│ ├ services/
│ │ ├ __init__.py
│ │ └ llm_service.py
│ └ context/
│   ├ __init__.py
│   └ examples.py
├ .env
├ .env.example
├ .gitignore
├ pyproject.toml
└ README.md
```

```
uv init
uv add anthropic fastapi openai pydantic-settings python-dotenv structlog "uvicorn[standard]"
uv add --dev httpx2 pytest
```

#### Paso 2 — Configuración con variables de entorno

Implementa config.py con Pydantic BaseSettings para cargar OPENAI_API_KEY, LLM_PROVIDER, LLM_MODEL y APP_ENV desde .env. Crea .env.example con las variables sin valores y asegúrate de que .env está en .gitignore.

#### Paso 3 — Datos de contexto estático

En context/examples.py, define al menos dos estimaciones históricas ficticias con resumen de la reunión y desglose de tareas con horas y costes. Estos son los "few-shot examples" del sistema.

```python
ESTIMATION_EXAMPLES = [
    {
        "meeting_summary": "El cliente necesita una plataforma web de gestión de inventario...",
        "estimation": """
## Estimación: Plataforma de Gestión de Inventario

### Desglose de tareas:
1. Diseño UI/UX: 40 horas — 16.000 EUR
2. Backend API REST: 60 horas — 30.000 EUR
3. Autenticación y roles: 20 horas — 10.000 EUR
4. Testing y QA: 25 horas — 12.500 EUR

**Total: 145 horas — 68.500 EUR**
**Equipo: 2 developers full-stack + 1 diseñador UX (part-time)**
**Duración: 6-8 semanas**
"""
    },
    # ... segundo ejemplo
]
```

Para obtener un resultado consistente con lo que veremos en la sesión, he copiado el fichero del repositorio de ejemplo: https://github.com/LIDR-academy/ai-engineering/blob/session_2/estimator/app/context/examples.py

#### Paso 4 — Servicio de llamada al LLM

En services/llm_service.py, implementa una función que construya el system prompt (con instrucciones + ejemplos inyectados como contexto CAG), envíe la transcripción del usuario y devuelva la estimación generada. Usa gpt-4o-mini (OpenAI) o claude-haiku-4-5 (Anthropic) para este ejercicio.

#### Paso 5 — Endpoint de estimación

En routers/estimations.py, crea POST /api/v1/estimate con schemas Pydantic de request y response:

```json
// Request
{ "transcription": "En la reunión con el cliente se discutió..." }

// Response
{
  "estimation": "## Estimación: ...\n\n### Desglose...",
  "model": "gpt-4o-mini",
  "provider": "openai"
}
```

#### Paso 6 — Punto de entrada y verificación

Configura main.py con el router incluido y un endpoint GET /health. Arranca y verifica:

```bash
# Arrancar el servidor
uv run uvicorn app.main:app --reload

# Probar el endpoint
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "El cliente necesita una landing page con formulario
    de contacto, integración con HubSpot y un blog con editor WYSIWYG.
    Plazo ideal: 4 semanas. El diseño ya existe en Figma."
  }'
```

La documentación Swagger está disponible en http://localhost:8000/docs.

#### Entregable

Proyecto funcional capaz de recibir una transcripción y devolver una estimación generada por un LLM con arquitectura CAG. No se espera que la calidad de las estimaciones sea perfecta en este punto — el refinamiento del prompt y los ejemplos de contexto se trabajará en la sesión en vivo.

> ⚠️ Resolución de referencia (solo si estás completamente bloqueado): https://github.com/LIDR-academy/ai-engineering/tree/main/estimator

---

### Documentación de referencia

- FastAPI — Documentación oficial: https://fastapi.tiangolo.com/
- Pydantic BaseSettings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- uv — Gestor de paquetes: https://docs.astral.sh/uv/
- OpenAI Python SDK: https://platform.openai.com/docs/libraries/python-library
- Anthropic Python SDK: https://docs.anthropic.com/en/api/client-sdks
- Paper CAG — Chan et al. 2025: https://arxiv.org/html/2412.15605v1

---

## Checklist antes de la siguiente sesión

- [ ] El proyecto arranca sin errores con `uv run uvicorn app.main:app --reload`
- [ ] Las API keys se cargan desde .env y no aparecen en ningún archivo de código
- [ ] El endpoint GET /health responde con status 200
- [ ] El endpoint POST /api/v1/estimate recibe una transcripción y devuelve una estimación
- [ ] La estimación se inspira en los ejemplos de contexto inyectados (arquitectura CAG funcional)
- [ ] La documentación Swagger es accesible en /docs
- [ ] El archivo .env está en .gitignore
- [ ] Entiendes la diferencia entre CAG y RAG y cuándo usar cada uno
- [ ] Entiendes qué es la ventana de contexto y cómo se reparte entre los distintos bloques del prompt
- [ ] Entiendes el array de mensajes system/user/assistant como la interfaz real con el LLM
