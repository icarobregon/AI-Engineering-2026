# Sesión 1: LLMs y Setup de Entorno de Trabajo

## Objetivo de la sesión

Esta sesión marca el punto de partida del programa. El objetivo es claro: **hacer tu primera llamada real a un modelo de lenguaje desde código** y entender qué está ocurriendo en cada parte de la integración.

A diferencia de usar herramientas como ChatGPT, aquí empiezas a trabajar como en un entorno profesional: integrando modelos directamente vía API y controlando su comportamiento desde tu propio código. El modelo deja de ser una caja negra y pasa a ser una pieza controlable dentro de un sistema más grande.

---

## Qué vas a aprender

La sesión cubre tres bloques fundamentales:

**1. Comunicación con LLMs vía API** — importación de librerías cliente (OpenAI SDK, Anthropic SDK), anatomía de una llamada completa (system prompt, user message, parámetros, estructura de la respuesta), uso de tokens y su impacto en coste, y manejo de errores comunes.

**2. Ecosistema de proveedores** — comparativa de los proveedores principales (OpenAI, Anthropic, Google, Mistral, open source), criterios de selección según caso de uso (coste, latencia, calidad, contexto disponible), y agregadores y routers de modelos.

**3. Análisis de casos reales** — ejemplos de productos que usan LLMs, desglose de su arquitectura a alto nivel e identificación de bloques reutilizables.

---

## Estructura de la sesión

### 1. 🗒️ Estructura de una llamada al API de OpenAI

OpenAI ofrece actualmente dos APIs:

- **Responses API** (`client.responses.create`) — La API más reciente y recomendada para todos los proyectos nuevos (lanzada en marzo 2025). Soporta herramientas integradas, gestión de estado y mejor rendimiento con modelos de razonamiento. **La que se usa en este programa.**
- **Chat Completions API** (`client.chat.completions.create`) — La API anterior, soportada indefinidamente. Su patrón de mensajes con roles es el estándar que siguen la mayoría de proveedores alternativos.

#### Anatomía de una llamada

```python
from openai import OpenAI

client = OpenAI()  # Lee OPENAI_API_KEY del entorno

response = client.responses.create(
    model="gpt-4o-mini",
    instructions="You are a software project estimation expert.",
    input="What factors should I consider when estimating a database migration?",
    temperature=0.7,
    max_output_tokens=500
)

print(response.output_text)
```

Diferencias clave respecto a Chat Completions: las instrucciones van en `instructions` (no como mensaje), la entrada va en `input`, y el texto de la respuesta se accede con `output_text`.

#### Parámetros esenciales

| Parámetro           | Descripción                                                             |
| ------------------- | ----------------------------------------------------------------------- |
| `model`             | Qué modelo usar                                                         |
| `instructions`      | System prompt (fijo, definido por el desarrollador)                     |
| `input`             | Entrada del usuario (string o array de mensajes)                        |
| `temperature`       | Aleatoriedad (0.0 = determinista, 2.0 = muy aleatorio)                  |
| `max_output_tokens` | Techo de tokens de salida                                               |
| `store`             | Si OpenAI almacena la respuesta (necesario para `previous_response_id`) |

#### Conversación multi-turno

Dos opciones para gestionar el contexto:

```python
# Opción A: historial manual en el array input
response_2 = client.responses.create(
    model="gpt-4o-mini",
    instructions="...",
    input=[
        {"role": "user", "content": "Pregunta anterior"},
        {"role": "assistant", "content": response_1.output_text},
        {"role": "user", "content": "Nueva pregunta"}
    ]
)

# Opción B: previous_response_id (exclusivo de Responses API)
response_2 = client.responses.create(
    model="gpt-4o-mini",
    input="Nueva pregunta",
    previous_response_id=response_1.id,
    store=True
)
```

#### Estructura de la respuesta

```python
response.output_text          # Texto de la respuesta (acceso directo)
response.id                   # ID único (útil para trazabilidad y previous_response_id)
response.model                # Snapshot exacto del modelo usado
response.status               # "completed", "incomplete" o "failed"
response.usage.input_tokens   # Tokens de entrada
response.usage.output_tokens  # Tokens de salida
response.usage.total_tokens   # Total
```

#### Errores más frecuentes

| Error                       | Causa                                                      |
| --------------------------- | ---------------------------------------------------------- |
| `AuthenticationError` (401) | API key inválida o no configurada                          |
| `RateLimitError` (429)      | Límite de llamadas o tokens superado, o saldo insuficiente |
| `BadRequestError` (400)     | Modelo incorrecto, parámetro fuera de rango                |
| `APIConnectionError`        | Problema de red                                            |
| `InternalServerError` (500) | Error en el lado de OpenAI                                 |

---

### 2. 🗒️ Estructura de una llamada al API de Anthropic

Anthropic ofrece una única API: la **Messages API** (`client.messages.create`). Sigue un patrón similar a Chat Completions de OpenAI, con diferencias importantes:

- El system prompt va en un parámetro `system` separado
- `max_tokens` es **obligatorio** (Anthropic no asume un valor por defecto)
- El historial siempre es manual (no hay equivalente a `previous_response_id`)
- Los mensajes deben **alternar estrictamente** entre `user` y `assistant`

#### Anatomía de una llamada

```python
from anthropic import Anthropic

client = Anthropic()  # Lee ANTHROPIC_API_KEY del entorno

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    system="You are a software project estimation expert.",
    messages=[
        {"role": "user", "content": "What factors should I consider?"}
    ],
    max_tokens=500,
    temperature=0.7
)

print(response.content[0].text)
```

#### Diferencias clave respecto a OpenAI

| Aspecto             | OpenAI (Responses API) | Anthropic (Messages API)   |
| ------------------- | ---------------------- | -------------------------- |
| System prompt       | `instructions=`        | `system=`                  |
| Entrada usuario     | `input=`               | `messages=[...]`           |
| Texto respuesta     | `response.output_text` | `response.content[0].text` |
| `max_tokens`        | Opcional               | **Obligatorio**            |
| Reintentos SDK      | No automáticos         | Sí, 2 veces por defecto    |
| Rango temperature   | 0.0 – 2.0              | 0.0 – 1.0                  |
| Timestamp respuesta | Sí                     | No                         |

#### Stop reason

```python
response.stop_reason  # "end_turn", "max_tokens", "stop_sequence", "tool_use"

if response.stop_reason == "max_tokens":
    print("⚠️ Respuesta truncada — aumenta max_tokens")
```

#### Reintentos automáticos del SDK

El SDK de Anthropic incluye reintentos automáticos con backoff exponencial para errores transitorios. Configurable al crear el cliente:

```python
client = Anthropic(max_retries=5)  # Por defecto: 2
client = Anthropic(max_retries=0)  # Desactivar reintentos
```

---

### 3. 🗒️ Estructura de una llamada al API de Gemini

Google ofrece acceso a los modelos Gemini a través del SDK `google-genai` (el SDK anterior `google-generativeai` está deprecado). Toda la configuración se agrupa en un único objeto `GenerateContentConfig`.

#### Anatomía de una llamada

```python
from google import genai
from google.genai import types

client = genai.Client()  # Lee GEMINI_API_KEY del entorno

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="What factors should I consider when estimating a migration?",
    config=types.GenerateContentConfig(
        system_instruction="You are a software estimation expert.",
        temperature=0.7,
        max_output_tokens=500
    )
)

print(response.text)
```

#### Diferencias clave respecto a OpenAI y Anthropic

| Aspecto              | Gemini                                                             |
| -------------------- | ------------------------------------------------------------------ |
| System prompt        | Dentro de `config` como `system_instruction`                       |
| Rol del modelo       | `"model"` (no `"assistant"` — usar `"assistant"` produce un error) |
| Acceso al texto      | `response.text`                                                    |
| Configuración        | Todo en `GenerateContentConfig`                                    |
| ID de request        | No existe — hay que generarlo manualmente                          |
| Reintentos SDK       | No automáticos                                                     |
| Contar tokens gratis | ✅ `client.models.count_tokens()`                                  |
| Thinking activado    | Por defecto en Gemini 2.5+                                         |

#### Conteo de tokens gratuito (exclusivo de Gemini)

```python
result = client.models.count_tokens(
    model="gemini-2.5-flash",
    contents="Tu texto aquí..."
)
print(f"Esta llamada consumirá {result.total_tokens} tokens de entrada")
```

#### Finish reason

```python
finish_reason = response.candidates[0].finish_reason.name
# "STOP" = normal, "MAX_TOKENS" = truncado, "SAFETY" = bloqueado
```

---

### 4. 🗒️ Parámetros en modelos de razonamiento

Los modelos de razonamiento (OpenAI o3/o4-mini/GPT-5 series; Anthropic Claude 4/4.5/4.6 con extended thinking) no generan respuestas en una sola pasada. Ejecutan un proceso de pensamiento multi-paso que invalida los parámetros de muestreo tradicionales.

#### Parámetros bloqueados en OpenAI (modelos de razonamiento)

`temperature`, `top_p`, `frequency_penalty`, `presence_penalty`, `logprobs`, `logit_bias` — todos bloqueados o ignorados.

**Nuevos parámetros que los reemplazan:**

```python
response = client.responses.create(
    model="gpt-5-mini",
    instructions="You are a technical analyst.",
    input="Should we use microservices?",
    reasoning={"effort": "medium"},  # "low", "medium", "high"
    text={"verbosity": "low"},       # Controla la longitud de la respuesta
    max_output_tokens=500
)
```

#### Parámetros bloqueados en Anthropic con extended thinking

Con `thinking` activado: `temperature`, `top_k` bloqueados. Sin thinking, en modelos 4.5+: no se pueden especificar `temperature` y `top_p` simultáneamente.

```python
response = client.messages.create(
    model="claude-sonnet-4-6-20250514",
    messages=[{"role": "user", "content": "Design a distributed rate limiter."}],
    max_tokens=16000,
    thinking={
        "type": "enabled",
        "budget_tokens": 10000  # Controla la profundidad del razonamiento
    }
)
```

#### Regla mnemotécnica

> Los modelos de razonamiento **quitan el control del muestreo** y te dan **control sobre el razonamiento**. Pierdes `temperature` y `top_p`. Ganas `reasoning_effort` y `verbosity` (OpenAI) o `thinking.budget_tokens` (Anthropic).

#### Coste del razonamiento

Los `reasoning_tokens` (OpenAI) y `thinking_tokens` (Anthropic) se facturan como tokens de salida aunque no aparezcan en la respuesta visible. Un modelo con `reasoning_effort: "high"` puede consumir 10x más tokens que con `"minimal"` para la misma pregunta.

---

### 5. 🗒️ Tokenización: conceptos avanzados

Los modelos de lenguaje no leen texto — operan sobre secuencias de números enteros. La **tokenización** es el proceso que convierte texto en IDs numéricos que el modelo puede procesar.

#### El algoritmo BPE (Byte Pair Encoding)

Es el estándar de facto para LLMs (GPT, Llama, Mistral, etc.). Parte de un vocabulario de 256 bytes y fusiona iterativamente los pares más frecuentes hasta alcanzar el vocabulario deseado:

| Modelo / Tokenizador           | Vocabulario  |
| ------------------------------ | ------------ |
| GPT-2 (2019)                   | ~50K tokens  |
| GPT-3.5/4 `cl100k_base` (2023) | ~100K tokens |
| GPT-4o `o200k_base` (2024)     | ~200K tokens |

```python
import tiktoken

enc = tiktoken.encoding_for_model("gpt-4o-mini")
tokens = enc.encode("PostgreSQL migration")
# → [5765, 48528, 12507]  →  'Postgre' + 'SQL' + ' migration'
```

#### Patrones críticos para producción

**El español consume más tokens que el inglés.** Entre un 20-40% más para el mismo contenido semántico. Los system prompts en español se reenvían con cada turno: en 20 turnos, la diferencia puede ser de 1.000 tokens de entrada adicionales sin valor añadido. Decisión de diseño: algunos equipos escriben sus system prompts en inglés para reducir costes.

**Los tokens de salida son 3-6x más caros que los de entrada.** Controlar la longitud de las respuestas (con `max_output_tokens` e instrucciones de brevedad) tiene más impacto en coste que optimizar la longitud del prompt.

**El JSON con pretty-print consume más tokens.** Al inyectar datos estructurados como contexto, usar formato compacto (sin indentación) puede reducir un 20-30% los tokens consumidos.

**Los modelos no ven letras ni dígitos individuales.** "Strawberry" puede ser un único token opaco — el modelo no tiene acceso a su composición de caracteres. Nunca delegues aritmética ni manipulación de strings a un LLM; hazlo en tu código.

#### La ventana de contexto y conversaciones multi-turno

La ventana de contexto incluye todo: system prompt + historial + entrada + respuesta. El coste de una conversación crece de forma acumulativa:

```python
# En cada turno se reenvía TODO el historial + system prompt
# Turno 1: system_prompt + mensaje_1
# Turno 2: system_prompt + mensaje_1 + respuesta_1 + mensaje_2
# Turno N: system_prompt × N + historial_completo
```

Estrategias de mitigación: prompt caching (hasta 90% de descuento en Anthropic), truncado de historial, resumen de turnos anteriores, o `previous_response_id` (OpenAI gestiona la caché internamente).

#### Herramientas de tokenización

```python
# tiktoken (OpenAI) — conteo local
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4o-mini")
token_count = len(enc.encode("Tu texto aquí"))

# Gemini — conteo gratuito vía API
result = client.models.count_tokens(model="gemini-2.5-flash", contents="...")
```

---

### 6. 🗒️ Comparación de modelos 2026

> ⚠️ Los precios y modelos cambian con frecuencia. Este contenido refleja el estado a abril de 2026. Consulta siempre las páginas oficiales antes de tomar decisiones en producción.

#### Los cinco grandes proveedores

**OpenAI** — Líder en amplitud de catálogo y ecosistema de desarrolladores. Familia GPT-5.4 con cobertura desde modelos ultra-baratos (Nano) hasta premium con razonamiento avanzado (Pro).

**Anthropic** — Posicionado en calidad y seguridad. Claude Opus 4.6 lidera benchmarks de ingeniería de software (SWE-Bench Verified). Fuerte en prompt caching (90% de descuento en cache hits).

**Google** — Ventaja en integración con su ecosistema. Gemini 2.5 Flash es uno de los modelos más baratos del mercado con calidad competitiva. Soporte nativo multimodal fuerte.

**xAI (Grok)** — Grok 4.1 Fast ofrece la ventana de contexto más grande del mercado (2M tokens). Fuerte en razonamiento científico.

**DeepSeek** — El disruptor de precios. Calidad comparable a modelos 50-100x más caros. Consideración: los datos se procesan en servidores en China.

#### Modelos usados en el programa

| Proveedor | Modelo en ejercicios        | Uso                                         |
| --------- | --------------------------- | ------------------------------------------- |
| OpenAI    | `gpt-4o-mini`               | Modelo principal, equilibrio calidad/coste  |
| Anthropic | `claude-haiku-4-5-20251001` | Comparativas, abstracción de proveedores    |
| Google    | `gemini-2.5-flash`          | Comparativas, arquitecturas multi-proveedor |

#### Precios de referencia (abril 2026)

| Modelo            | Input ($/MTok) | Output ($/MTok) |
| ----------------- | -------------- | --------------- |
| gpt-4o-mini       | $0.15          | $0.60           |
| gpt-5.4 mini      | $0.75          | $4.50           |
| gpt-5.4           | $2.50          | $15.00          |
| claude-haiku-4-5  | $1.00          | $5.00           |
| claude-sonnet-4-6 | $3.00          | $15.00          |
| claude-opus-4-6   | $15.00         | $75.00          |
| gemini-2.5-flash  | $0.15          | $0.60           |
| deepseek-v3-2     | $0.14          | $0.28           |

#### Prompt caching

Todos los proveedores principales ofrecen descuentos por caché. Los tokens del system prompt y el contexto que se repiten entre llamadas se sirven con descuento:

| Proveedor | Descuento en cache hits |
| --------- | ----------------------- |
| Anthropic | 90%                     |
| OpenAI    | hasta 90%               |
| Google    | 90%                     |

#### Tendencias del mercado

Los precios han bajado aproximadamente un **80% en 12 meses** (de 2025 a 2026). Las ventanas de contexto han pasado de 4K tokens (GPT-3.5, 2023) a 1-2M tokens (2026). Las arquitecturas de producción usan cada vez más **múltiples modelos**: un modelo barato para tareas simples, uno mid-tier para el grueso del trabajo, y uno premium para casos difíciles — lo que puede reducir costes entre un 60% y un 80%.

---

## Ejercicios prácticos

### ✍️ Ejercicio 1 — Crear tu cuenta en Anthropic y OpenAI

> ⚠️ Completa este ejercicio antes de abordar los ejercicios de código.

**Objetivo:** Crear una cuenta de desarrollador en OpenAI y/o Anthropic, configurar la facturación en al menos uno de los dos proveedores, y generar una API key funcional que utilizarás durante todo el programa.

**Entregable:** No hay entrega formal. Al finalizar debes tener:

- Cuenta activa en OpenAI Platform con una API key generada
- Cuenta activa en Anthropic Console con una API key generada
- Facturación configurada y crédito disponible en al menos uno de los dos proveedores

#### Parte A — OpenAI

1. Ve a [platform.openai.com](https://platform.openai.com) (es la plataforma de API, separada de chatgpt.com) y haz clic en **Sign up**. Si ya tienes cuenta de ChatGPT, puedes usarla — la facturación de la API es independiente de tu suscripción.
2. En **Settings → Billing**, añade un mínimo de **5 USD** de crédito. OpenAI funciona con crédito prepago; sin saldo las llamadas devuelven error. Configura un límite de gasto mensual en **Usage Limits** para evitar sorpresas.
3. Ve a **API Keys** y haz clic en **Create new secret key**. Dale un nombre descriptivo (p. ej. `master-ai-engineering`). **Copia la key inmediatamente** — solo se muestra una vez y empieza por `sk-`.

**Verificación:**

- [ ] Acceso al dashboard en `platform.openai.com`
- [ ] Saldo en Billing superior a 0 USD
- [ ] API key copiada y guardada (empieza por `sk-`)

#### Parte B — Anthropic

1. Ve a [console.anthropic.com](https://console.anthropic.com) y regístrate. Las cuentas nuevas pueden recibir créditos gratuitos para pruebas iniciales (requiere verificación por SMS).
2. En **Settings → Billing**, selecciona el plan **Build** (pay-as-you-go) y añade un mínimo de **5 USD** en créditos. Configura un límite de gasto mensual.
3. En **API Keys**, haz clic en **Create Key**. Dale un nombre descriptivo. **Copia la key inmediatamente** — solo se muestra una vez y empieza por `sk-ant-`.

**Verificación:**

- [ ] Acceso al dashboard en `console.anthropic.com`
- [ ] Crédito disponible (gratuito o comprado)
- [ ] API key copiada y guardada (empieza por `sk-ant-`)

#### ⚠️ Seguridad de las API keys

Trata tus API keys como contraseñas. Tres reglas básicas:

1. **Nunca las escribas directamente en tu código.** Usa variables de entorno o el gestor de Secrets de Google Colab.
2. **Nunca las subas a un repositorio.** Ni público ni privado. Añade `.env` a tu `.gitignore`.
3. **Si sospechas que una key ha sido expuesta**, revócala inmediatamente desde el dashboard del proveedor y genera una nueva.

---

### ✍️ Ejercicio 2 — Respuesta de modelo vía API

**Objetivo:** Realizar tu primera integración real con un LLM desde código Python: enviar un mensaje, recibir una respuesta y entender cómo cambia el comportamiento del modelo.

**Formato:** Google Colab Notebook

**Proveedor:** A tu elección — OpenAI o Anthropic. El notebook incluye código para ambos.

#### Niveles

**Nivel 1 — obligatorio**

Realiza una llamada básica a la API: envía un mensaje simple, recibe la respuesta e imprímela por pantalla.

> 👉 Si ves una respuesta sin errores, el setup es correcto.

**Nivel 2 — obligatorio**

Añade un system prompt que defina un rol (p. ej. experto en estimación de software). Envía el mismo mensaje que en el nivel 1 y compara la respuesta. Observa las diferencias en tono, nivel de detalle y estructura.

**Nivel 3 — opcional**

Extrae los metadatos de la respuesta: tokens de entrada, tokens de salida y modelo utilizado. Calcula el coste estimado de la llamada usando las tarifas oficiales:

- OpenAI: [platform.openai.com/pricing](https://platform.openai.com/pricing)
- Anthropic: [anthropic.com/pricing](https://www.anthropic.com/pricing)

#### Problemas comunes

Si algo no funciona, revisa: ¿tienes crédito disponible?, ¿la API key está bien configurada?, ¿estás usando el modelo correcto?, ¿has instalado correctamente la librería?

---

### ✍️ Ejercicio 3 — Google Colab inicializado con API keys y una llamada

**Objetivo:** Conectar con la API de un LLM desde código Python en Google Colab y obtener una respuesta exitosa.

**Formato:** Google Colab Notebook

#### Niveles

**Nivel 1 — obligatorio:** Llama básica a la API del proveedor que elijas. Envía un mensaje, recibe la respuesta e imprímela por pantalla.

**Nivel 2 — obligatorio:** Añade un system prompt que dé al modelo un rol concreto (p. ej. experto en estimación de proyectos de software). Envía el mismo mensaje que en el nivel 1 y compara las diferencias en la respuesta.

**Nivel 3 — opcional:** Extrae los metadatos de la respuesta (tokens de entrada, tokens de salida, modelo utilizado) y calcula el coste estimado usando las tarifas publicadas del proveedor.

#### Entregable

No hay entrega formal. Debes llegar a la sesión en vivo con los **niveles 1 y 2 funcionando**. En la sesión se resolverán dudas y se avanzará sobre esta base.

---

### Documentación de referencia

- OpenAI Quickstart: [platform.openai.com/docs/quickstart](https://platform.openai.com/docs/quickstart)
- Anthropic SDK Python: [github.com/anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)

---

## Checklist antes de la siguiente sesión

- [ ] API key de OpenAI operativa y primera llamada exitosa con la Responses API
- [ ] API key de Anthropic operativa y primera llamada exitosa con la Messages API
- [ ] Entendida la diferencia entre `instructions`/`system`/`system_instruction` en los tres proveedores
- [ ] Comprendida la estructura de `response.usage` y cómo calcular el coste de una llamada
- [ ] Entendido por qué `temperature` está bloqueado en modelos de razonamiento
- [ ] Leídas las implicaciones de tokenización para el idioma español y el formato de datos
