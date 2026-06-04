# Sesión 3 — Patrones de diseño para wrappers de modelos

## Objetivo de la sesión

En la sesión anterior construiste la primera versión funcional del sistema: un endpoint FastAPI que responde con estimaciones de software usando arquitectura CAG. En esta sesión damos el siguiente paso: convertir ese backend en un sistema que empieza a comportarse como un producto real.

El foco ya no está en que "responda", sino en **cómo responde, cómo escala y cómo se integra en un contexto de uso real**. Los patrones de esta sesión — abstracción de proveedores, cacheo, streaming y observabilidad — son los que separan un script de demo de un sistema preparado para producción, y los aplicarás en cualquier proyecto con LLMs.

---

## Qué vas a aprender

### 1. 📄 Interfaces conversacionales, frameworks y librerías

Tienes un endpoint que recibe texto y devuelve respuestas de un LLM. Pero la única forma de probarlo es con curl, Postman o Swagger. Para que alguien no técnico lo use — o para tener una experiencia de chat decente durante el desarrollo — necesitas una interfaz web. Los frameworks de interfaz para aplicaciones de IA permiten crear una UI funcional en Python puro, sin JavaScript, en menos de 50 líneas de código.

#### Los tres frameworks principales

**Streamlit** es el más generalista. Nació como herramienta para dashboards de datos y con el tiempo incorporó elementos de chat (`st.chat_message`, `st.chat_input`). Su modelo de ejecución clave: cada interacción del usuario re-ejecuta todo el script de arriba a abajo, por lo que necesitas `st.session_state` para persistir el historial de la conversación.

```python
import streamlit as st
from openai import OpenAI

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Escribe tu mensaje"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=st.session_state.messages,
            stream=True,
        )
        response = st.write_stream(stream)
    st.session_state.messages.append({"role": "assistant", "content": response})
```

25 líneas: chat con historial, streaming y gestión de estado. `st.write_stream` acepta directamente el stream del SDK y lo renderiza token a token.

**Gradio** nació para envolver funciones Python en UIs de demo de modelos ML. Su `gr.ChatInterface` simplifica la creación de chatbots y su comando `demo.launch(share=True)` genera una URL pública temporal (72 horas) sin necesidad de deployment — ideal para compartir prototipos con stakeholders.

**Chainlit** es el más especializado: diseñado exclusivamente para interfaces conversacionales con LLMs. Ofrece de serie observabilidad del razonamiento del agente, threading de mensajes, autenticación y persistencia de historial. Está construido sobre asyncio desde su base, lo que hace el streaming natural y eficiente. Se revisará en profundidad en los módulos de agentes.

#### Cuándo usar cada uno

| Framework     | Cuándo usarlo                                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Streamlit** | Tu app necesita más que chat: sidebars, gráficos, tablas, formularios. Prototipado rápido. **Ejercicio de esta sesión.** |
| **Gradio**    | Demos rápidas de modelos, especialmente multimodales (imagen, audio). Compartir prototipos vía share link.               |
| **Chainlit**  | Chat serio con agentes: observabilidad del razonamiento, autenticación, persistencia, threading. Módulos 4-5.            |

---

### 2. 📄 Abstracción de proveedores y estrategias de fallback

El código del Proyecto 1 tiene un problema serio: está acoplado a un único proveedor. Si usas el SDK de OpenAI, cambiar a Anthropic implica reescribir la llamada, adaptar el parseo de la respuesta, manejar errores diferentes y ajustar la gestión de tokens. En producción, esta rigidez tiene consecuencias directas: si el proveedor se cae, si sube precios, o si aparece un modelo mejor, no puedes reaccionar sin tocar código de negocio.

La solución es una **capa de abstracción**: una interfaz unificada entre tu lógica de negocio y los proveedores de LLMs. Tu código habla un solo idioma; el wrapper traduce a cada proveedor.

```python
# Acoplado a OpenAI
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
estimation = response.choices[0].message.content

# Desacoplado con LiteLLM
from litellm import completion
response = completion(model="gpt-4o-mini", messages=[...])  # cambiar modelo = 0 cambios en lógica
estimation = response.choices[0].message.content
```

Cambiar de proveedor pasa a ser un cambio de configuración, no de código.

#### LiteLLM — la herramienta que usaremos

LiteLLM es una librería Python open source con interfaz unificada para más de 100 modelos de más de 10 proveedores. Más allá de la abstracción pura, ofrece router con fallback automático, tracking de costes por llamada, rate limiting y modo proxy.

```python
from litellm import Router

router = Router(
    model_list=[
        {
            "model_name": "estimator",          # nombre lógico en tu código
            "litellm_params": {
                "model": "gpt-4o-mini",
                "api_key": "sk-...",
            },
        },
        {
            "model_name": "estimator",          # mismo nombre = fallback automático
            "litellm_params": {
                "model": "claude-haiku-4-5",
                "api_key": "sk-ant-...",
            },
        },
    ],
    num_retries=2,
)

# Tu endpoint solo conoce "estimator" — no sabe si respondió OpenAI o Anthropic
response = router.completion(model="estimator", messages=[...])
```

> ⚠️ **Nota de seguridad:** En marzo de 2026, las versiones 1.82.7 y 1.82.8 de LiteLLM en PyPI fueron comprometidas con código malicioso. El incidente fue resuelto, pero es un recordatorio de buenas prácticas: fija versiones en `pyproject.toml` y verifica hashes.

#### Estrategias de fallback

**Fallback secuencial** (la más común): lista ordenada de proveedores. Si el primero falla, rota al segundo. Es lo que configura el Router de LiteLLM.

**Fallback por tipo de error**: no todos los errores merecen fallback. Un error de autenticación no se resuelve rotando de proveedor. Un timeout o un rate limit 429 sí justifican rotación.

```python
# Lógica de fallback granular por tipo de error
for provider in providers:
    try:
        return provider.call(messages)
    except AuthenticationError:
        raise                # No tiene sentido rotar
    except RateLimitError:
        continue             # Rotar al siguiente
    except TimeoutError:
        if provider.retries_left > 0:
            provider.retry_with_backoff()
        else:
            continue
    except ServerError:
        continue
```

#### La arquitectura del wrapper en el proyecto

```
Interfaz Streamlit
       │
Endpoint FastAPI
       │
   LLM Wrapper         ← abstracción + fallback + cacheo + logging
   ┌───┴───┐
OpenAI  Anthropic
```

---

### 3. 📄 Cacheo inteligente de respuestas de LLMs

Si un usuario envía la misma transcripción dos veces, sin cacheo el sistema hace dos llamadas al LLM, paga dos veces los tokens y el usuario espera dos veces la latencia. En aplicaciones reales con LLMs, los patrones de uso muestran repetición constante. Según datos de producción de 2026, el cacheo semántico puede alcanzar tasas de acierto del 40-70%, con impacto directo en coste y latencia.

El cacheo de respuestas LLM tiene tres beneficios: **latencia** (microsegundos vs segundos), **coste** (cada cache hit es una llamada que no pagas) y **fiabilidad** (las respuestas cacheadas no dependen de la disponibilidad del proveedor).

#### Las tres capas de cacheo

| Nivel                            | Mecanismo                     | Velocidad                               | Qué captura                                |
| -------------------------------- | ----------------------------- | --------------------------------------- | ------------------------------------------ |
| **L1 — Exact match**             | Hash SHA-256 del input        | Microsegundos                           | Inputs idénticos byte a byte               |
| **L2 — Semántico**               | Embeddings + similitud coseno | Milisegundos                            | Reformulaciones del mismo significado      |
| **Prompt caching del proveedor** | Nativo (Anthropic, OpenAI)    | Reducción de coste en tokens de entrada | Porción repetida del prompt entre llamadas |

#### Implementación: exact match con Redis

```python
import hashlib, json, redis
from openai import OpenAI

class LLMCache:
    def __init__(self, redis_url="redis://localhost:6379", ttl=86400):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.client = OpenAI()
        self.ttl = ttl  # 24 horas por defecto

    def _cache_key(self, prompt: str, model: str, system_prompt: str) -> str:
        raw = json.dumps(
            {"prompt": prompt, "model": model, "system_prompt": system_prompt},
            sort_keys=True
        )
        return f"llm:{hashlib.sha256(raw.encode()).hexdigest()}"

    def completion(self, prompt: str, model: str, system_prompt: str) -> dict:
        key = self._cache_key(prompt, model, system_prompt)

        cached = self.redis.get(key)
        if cached:
            result = json.loads(cached)
            result["cache_hit"] = True
            return result

        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt},
            ],
        )
        result = {
            "content": response.choices[0].message.content,
            "model": model,
            "tokens_in": response.usage.prompt_tokens,
            "tokens_out": response.usage.completion_tokens,
            "cache_hit": False,
        }
        self.redis.setex(key, self.ttl, json.dumps(result))
        return result
```

El `system_prompt` forma parte de la clave: si cambias los ejemplos CAG, las claves cambian automáticamente y las entradas antiguas expiran por TTL — **invalidación implícita sin borrado manual**.

#### Cacheo semántico: capturar reformulaciones

```python
import numpy as np

class SemanticCache:
    def __init__(self, similarity_threshold=0.95):
        self.client = OpenAI()
        self.entries = []  # (embedding, response)
        self.threshold = similarity_threshold

    def _embed(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(
            model="text-embedding-3-small", input=text
        )
        return resp.data[0].embedding

    def _cosine_sim(self, a, b) -> float:
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def lookup(self, query: str):
        query_vec = self._embed(query)
        best_score, best_response = 0.0, None
        for vec, response in self.entries:
            score = self._cosine_sim(query_vec, vec)
            if score > best_score:
                best_score, best_response = score, response
        if best_score >= self.threshold:
            return best_response, True
        return None, False

    def store(self, query: str, response: str):
        self.entries.append((self._embed(query), response))
```

El umbral de similitud (0.95 como punto de partida) es el parámetro crítico: muy alto = pocos hits, muy bajo = respuestas incorrectas para queries diferentes.

#### Cacheo multi-nivel combinado

```python
class MultiLevelCache:
    def __init__(self):
        self.exact = LLMCache()       # L1: exact match con Redis
        self.semantic = SemanticCache()  # L2: semántico con embeddings

    def completion(self, prompt, model, system_prompt):
        # L1: exact match
        result = self.exact.completion(prompt, model, system_prompt)
        if result["cache_hit"]:
            return result

        # L2: semántico
        cached_response, is_hit = self.semantic.lookup(prompt)
        if is_hit:
            return {"content": cached_response, "cache_hit": True, "cache_level": "semantic"}

        # Miss en ambas: guardar en semántico para futuras queries similares
        self.semantic.store(prompt, result["content"])
        return result
```

#### Cuándo cachear y cuándo no

Cachea cuando los inputs se repiten, la respuesta no necesita ser única, y los datos subyacentes son estables. **No cachees** cuando se espera creatividad y variabilidad, los datos cambian en tiempo real, o la temperatura es alta (>0.7).

---

### 4. 📄 Streaming y manejo de respuestas largas

Sin streaming, el usuario espera un spinner durante 5-10 segundos y de golpe aparece un bloque de texto completo. El streaming envía la respuesta fragmento a fragmento a medida que el LLM la genera: el usuario ve el texto "escribiéndose" en tiempo real, como en ChatGPT o Claude. La percepción de velocidad cambia radicalmente aunque el tiempo total de generación sea el mismo.

#### Los tres mecanismos

**StreamingResponse** (nivel más básico): FastAPI envía la respuesta con `Transfer-Encoding: chunked`. Un generador asíncrono yieldea los fragmentos del LLM al cliente.

```python
from fastapi.responses import StreamingResponse

async def generate_estimation(transcription: str):
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": transcription},
        ],
        stream=True,
    )
    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content

@app.post("/estimate")
async def estimate(transcription: str):
    return StreamingResponse(generate_estimation(transcription), media_type="text/plain")
```

**Server-Sent Events (SSE)** (recomendado para FastAPI): envía eventos estructurados con campos `data`, `event`, `id`. El navegador tiene la API nativa `EventSource` para consumirlo con reconexión automática. Desde FastAPI 0.135.0, soporte nativo con `EventSourceResponse`.

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent

@app.post("/estimate/stream", response_class=EventSourceResponse)
async def estimate_stream(transcription: str):
    stream = client.chat.completions.create(
        model="gpt-4o-mini", messages=[...], stream=True
    )
    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield ServerSentEvent(data=content)
```

**WebSockets**: canal bidireccional y persistente. Cada lado puede enviar mensajes en cualquier momento. Adecuado para chat real donde el cliente también envía mensajes activamente. Más complejo de implementar y escalar — se reserva para módulos posteriores.

#### Cuál usar según contexto

| Contexto                                | Mecanismo recomendado                                                        |
| --------------------------------------- | ---------------------------------------------------------------------------- |
| Interfaz Streamlit                      | `st.write_stream()` — Streamlit lo abstrae todo, no hay que implementar nada |
| Endpoint FastAPI para clientes externos | SSE — eventos estructurados + reconexión automática                          |
| Chat bidireccional con agentes          | WebSockets — módulos 4-5                                                     |

#### Streaming con diferentes proveedores

```python
# OpenAI
stream = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, stream=True)
for chunk in stream:
    text = chunk.choices[0].delta.content or ""
    yield text

# Anthropic
with anthropic_client.messages.stream(model="claude-haiku-4-5", messages=msgs, max_tokens=4096) as stream:
    for text in stream.text_stream:
        yield text

# LiteLLM (interfaz uniforme para ambos)
response = completion(model="gpt-4o-mini", messages=msgs, stream=True)
for chunk in response:
    text = chunk.choices[0].delta.content or ""
    yield text
```

Con LiteLLM, el código de streaming no cambia al cambiar de proveedor.

#### Manejo de respuestas truncadas

Configura `max_tokens` explícitamente con margen suficiente (2000-4000 para estimaciones de software). Detecta truncamiento revisando `finish_reason`:

```python
if response.choices[0].finish_reason == "length":
    # La respuesta fue cortada — notificar al usuario o continuar en segunda llamada
    pass
```

---

### 5. 📄 Observabilidad, logging y trazabilidad

El logging web convencional te dice que el endpoint `/estimate` respondió un 200 en 4.2 segundos. Lo que no te dice es qué prompt se envió exactamente, cuántos tokens consumió, cuánto costó esa llamada, qué modelo respondió, si la respuesta vino de caché, o por qué la calidad de la estimación fue baja. Con LLMs — cajas negras probabilísticas — debuggear sin trazabilidad es trabajar a ciegas.

La trazabilidad en aplicaciones con LLMs necesita cubrir tres dimensiones: **qué se envió y recibió** (prompt completo, respuesta literal, parámetros), **cuánto costó** (tokens de entrada/salida, modelo, coste económico) y **qué camino siguió la llamada** (¿caché o LLM?, ¿hubo fallback?, ¿cuánto tardó cada fase?).

#### Structured logging con structlog

En lugar de registrar logs como texto plano, los registramos como objetos estructurados con campos tipados:

```json
{
  "timestamp": "2026-04-02T10:30:15.123Z",
  "level": "info",
  "event": "llm_call_completed",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "tokens_in": 1847,
  "tokens_out": 423,
  "cost_usd": 0.00089,
  "latency_ms": 3215,
  "cache_hit": false,
  "fallback_used": false
}
```

```python
import structlog, logging, os

def configure_logging():
    shared_processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.EventRenamer("msg"),
    ]

    if os.environ.get("ENV") == "production":
        # JSON para ingestión por plataformas de observabilidad
        structlog.configure(
            processors=shared_processors + [structlog.processors.JSONRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        )
    else:
        # Consola coloreada y legible en desarrollo
        structlog.configure(
            processors=shared_processors + [structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        )
```

`bind()` permite vincular contexto común a todas las líneas de un request sin repetirlo:

```python
logger = structlog.get_logger()
request_logger = logger.bind(request_id="req-abc-123", endpoint="/estimate")

request_logger.info("llm_call_started",    model="gpt-4o-mini", tokens_in=1847)
request_logger.info("llm_call_completed",  latency_ms=3215, cache_hit=False)
request_logger.warning("fallback_triggered", original="openai", fallback="anthropic")
```

#### Integración en el wrapper

```python
import time, structlog

logger = structlog.get_logger()

class LLMWrapper:
    def completion(self, messages, model):
        call_logger = logger.bind(model=model)
        call_logger.info("llm_call_started")
        start = time.time()

        try:
            response = self._call_provider(messages, model)
            latency = (time.time() - start) * 1000
            call_logger.info(
                "llm_call_completed",
                latency_ms=round(latency, 1),
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens,
                finish_reason=response.choices[0].finish_reason,
                cache_hit=False,
            )
            return response
        except Exception as e:
            call_logger.error(
                "llm_call_failed",
                error_type=type(e).__name__,
                error_msg=str(e),
                latency_ms=round((time.time() - start) * 1000, 1),
            )
            raise
```

#### Herramientas de observabilidad

| Herramienta          | Tipo                       | Cuándo usarla                                                                                                             |
| -------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **structlog**        | Librería local             | Base de cualquier proyecto. Se implementa en la sesión en vivo.                                                           |
| **Pydantic Logfire** | SaaS / OTel                | Observabilidad visual con trazas unificadas FastAPI + Redis + LLM. Free tier generoso. Opción natural para nuestro stack. |
| **Langfuse**         | Open source auto-hosteable | Requisitos de privacidad de datos o control total. Alternativa sólida sin LangChain.                                      |
| **LangSmith**        | SaaS (LangChain)           | Equipos que usan LangChain/LangGraph. Indispensable para debuggear agentes complejos. Módulos 4-5.                        |
| **Helicone**         | SaaS proxy                 | Setup más rápido posible: cambia la URL base del cliente OpenAI y ya tienes logging.                                      |

**Recomendación para esta fase:** structlog como base (lo que implementamos en el directo) + Logfire si quieres observabilidad visual con el free tier.

---

## Ejercicios prácticos

### ✍️ Ejercicio — Interfaz conversacional con Streamlit para el Proyecto 1

**Objetivo:** Añadir una interfaz conversacional web al Proyecto 1 usando Streamlit. Al finalizar, poder pegar una transcripción de reunión en una interfaz de chat y ver la estimación generada por el LLM en streaming, sin necesidad de usar curl, Postman ni Swagger.

**Punto de partida:** El proyecto de la Sesión 2 — backend FastAPI con endpoint CAG funcional.

**Formato:** Fichero Python (`streamlit_app.py`) en la raíz del proyecto. Se ejecuta con `streamlit run streamlit_app.py`.

#### Nivel 1 — Chat básico (obligatorio)

Crea una aplicación Streamlit con interfaz de chat (`st.chat_message`, `st.chat_input`) que permita escribir o pegar una transcripción de reunión. La aplicación debe enviar ese texto al LLM reutilizando la lógica de llamada del proyecto y mostrar la estimación resultante como mensaje del asistente.

**Requisitos:**

- El historial de la conversación debe mantenerse visible durante la sesión (usa `st.session_state`)
- El system prompt debe ser el mismo que usas en tu endpoint CAG
- La API key no debe estar hardcodeada

#### Nivel 2 — Streaming (obligatorio)

Modifica la aplicación para que la respuesta del LLM se muestre en streaming (token a token) en lugar de aparecer de golpe. Usa `st.write_stream` o el patrón de placeholder + delta que prefieras.

El usuario debe ver la estimación "escribiéndose" en tiempo real.

#### Nivel 3 — Contexto CAG en la interfaz (opcional)

Añade un panel lateral (`st.sidebar`) que muestre:

- El system prompt activo (solo lectura)
- El contexto estático inyectado (estimaciones de ejemplo del CAG)
- Métricas básicas de la última llamada: modelo utilizado, tokens de entrada, tokens de salida, tiempo de respuesta

Esto le da al usuario visibilidad sobre qué información está usando el modelo para generar la estimación.

#### Entregable

Fichero `streamlit_app.py` funcional en tu proyecto.

> **Nota:** El wrapper de abstracción de proveedores, el cacheo inteligente y la capa de logging/trazabilidad se implementarán juntos durante la sesión en vivo. No es necesario prepararlos antes.

---

### Checklist de verificación

- [ ] `streamlit run streamlit_app.py` abre una interfaz de chat en el navegador
- [ ] Puedes pegar una transcripción de reunión y recibes una estimación de software
- [ ] La conversación persiste en pantalla (puedes hacer varias preguntas seguidas)
- [ ] La respuesta se muestra en streaming, no de golpe
- [ ] La API key se lee desde `.env` o `st.secrets`, no está en el código

---

### Documentación de referencia

- Streamlit chat elements: https://docs.streamlit.io/develop/tutorials/chat-and-llm-apps/build-conversational-apps
- Streamlit secrets management: https://docs.streamlit.io/develop/concepts/connections/secrets-management
- LiteLLM — Getting Started: https://docs.litellm.ai/docs/
- LiteLLM — Router y fallback: https://docs.litellm.ai/docs/routing
- FastAPI — Server-Sent Events: https://fastapi.tiangolo.com/advanced/custom-response/
- structlog — Documentación oficial: https://www.structlog.org/en/stable/
- Pydantic Logfire — AI & LLM Observability: https://logfire.pydantic.dev/docs/

---

## Checklist antes de la siguiente sesión

- [ ] `streamlit run streamlit_app.py` funciona y muestra una interfaz de chat
- [ ] La estimación aparece en streaming (nivel 2 completado)
- [ ] La API key se carga desde `.env` o `st.secrets`
- [ ] Entiendes la diferencia entre los tres frameworks (Streamlit, Gradio, Chainlit) y cuándo usar cada uno
- [ ] Entiendes por qué el acoplamiento a un proveedor es un problema y cómo lo resuelve LiteLLM
- [ ] Entiendes los tres niveles de cacheo (exact match, semántico, prompt caching del proveedor)
- [ ] Entiendes la diferencia entre StreamingResponse, SSE y WebSockets y cuándo aplica cada uno
- [ ] Entiendes por qué el logging estándar no es suficiente para aplicaciones con LLMs
- [ ] Sabes qué campos registrar en cada llamada al LLM (modelo, tokens, coste, latencia, cache_hit, fallback)
