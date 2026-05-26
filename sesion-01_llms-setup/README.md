# Sesión 1: LLMs y Setup de Entorno de Trabajo

## 📋 Descripción

Primera sesión práctica del Máster AI Engineering donde sientas las bases para trabajar como ingeniero de IA en entornos profesionales. Esta sesión marca el punto de partida del programa y define cómo trabajarás durante las próximas semanas.

Temas clave:

- Comunicación con LLMs vía API (OpenAI, Anthropic)
- Anatomía de una llamada API: system prompt, user messages, parámetros, respuesta
- Manejo de tokens: impacto en coste y contexto disponible
- Ecosistema de proveedores: criterios de selección según caso de uso
- Comparativa de modelos 2026: precios, latencia, calidad, tamaño de contexto
- Tokenización: conceptos avanzados
- Análisis de casos reales que utilizan LLMs

## 🎯 Objetivos de aprendizaje

Al finalizar esta sesión serás capaz de:

- [ ] Hacer una llamada real a un modelo de lenguaje (LLM) desde código Python
- [ ] Entender la anatomía completa de una llamada API: estructura, parámetros y respuesta
- [ ] Integrar LLMs vía SDK (OpenAI, Anthropic) y controlar su comportamiento desde código
- [ ] Diferenciar entre experimentar con LLMs vs. construir productos robustos
- [ ] Seleccionar el proveedor y modelo adecuado según criterios de coste, latencia y calidad
- [ ] Comprender tokenización y su impacto en coste y rendimiento
- [ ] Analizar la arquitectura de productos reales que usan LLMs

## 🛠️ Stack Tecnológico

### APIs de LLMs

- **OpenAI**: GPT-4o, GPT-4o-mini (modelos más recientes)
- **Anthropic Claude**: Modelos Anthropic (buena relación calidad-coste)

### Entorno de desarrollo

- **Google Colab**: Notebooks Jupyter basado en navegador para prototipos rápidos
- **Python 3.11+**: Lenguaje principal (SDKs optimizados para Python)
- **SDKs cliente**:
  - openai (para OpenAI)
  - anthropic (para Anthropic)

## 🚀 Configuración de Cuentas en Proveedores de API

### 1. OpenAI

**Paso 1: Crear la cuenta**

1. Ve a [platform.openai.com](https://platform.openai.com) — es la plataforma de API (separada de chatgpt.com)
2. Haz clic en **Sign up**
3. Regístrate con tu email, o usa tu cuenta de Google o Microsoft
4. Verifica tu email y completa la verificación por SMS con tu número de teléfono
5. Si ya tienes ChatGPT, puedes usar las mismas credenciales. La facturación de API es independiente de tu suscripción a ChatGPT.

**Paso 2: Configurar la facturación**

1. Una vez dentro, ve a **Settings → Billing** (o accede directamente a [platform.openai.com/settings/organization/billing](https://platform.openai.com/settings/organization/billing))
2. Haz clic en **Add credit**
3. Introduce los datos de tu tarjeta de crédito o débito
4. Añade un mínimo de **5 USD** (suficiente para semanas de uso del programa)
5. **Recomendado**: Configura un límite de gasto mensual en Usage Limits para evitar sorpresas

OpenAI usa un sistema de crédito prepago. Sin saldo, las llamadas devuelven error.

**Paso 3: Generar la API key**

1. Ve a **API Keys** en el menú lateral (o accede a [platform.openai.com/api-keys](https://platform.openai.com/api-keys))
2. Haz clic en **Create new secret key**
3. Dale un nombre descriptivo (ej: `master-ai-engineering`)
4. **Copia la key inmediatamente** y guárdala en un lugar seguro
5. **Importante**: La key solo se muestra una vez. Si cierras sin copiarla, no podrás recuperarla

**Verificación:**

- [ ] Tienes acceso al dashboard en platform.openai.com
- [ ] Tu saldo en Billing es superior a 0 USD
- [ ] Tienes una API key copiada y guardada (empieza por `sk-`)

---

### 2. Anthropic

**Paso 1: Crear la cuenta**

1. Ve a [console.anthropic.com](https://console.anthropic.com)
2. Haz clic en **Sign up** o **Continue with Google**
3. Completa el registro con tu email y verifica tu cuenta
4. Puede que Anthropic pida verificación por SMS
5. Las cuentas nuevas pueden recibir créditos gratuitos iniciales (si los tienes, verifica tu número de teléfono para reclamarlos)

**Paso 2: Configurar la facturación**

1. En el menú lateral, ve a **Settings → Billing** (o accede a [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing))
2. Selecciona el plan **Build** (pay-as-you-go) — es el adecuado para uso individual
3. Introduce los datos de tu tarjeta y compra un mínimo de **5 USD** en créditos
4. **Recomendado**: Configura un límite de gasto mensual

Anthropic usa un sistema de crédito prepago similar a OpenAI. Sin crédito, las llamadas devuelven error.

**Paso 3: Generar la API key**

1. En el menú lateral, haz clic en el icono de llave (🔑) (o navega a [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys))
2. Haz clic en **Create Key**
3. Dale un nombre descriptivo (ej: `master-ai-engineering`)
4. **Copia la key inmediatamente** y guárdala en un lugar seguro
5. **Importante**: La key solo se muestra una vez

**Verificación:**

- [ ] Tienes acceso al dashboard en console.anthropic.com
- [ ] Tienes crédito disponible (gratuito o comprado)
- [ ] Tienes una API key copiada y guardada (empieza por `sk-ant-`)

---

### ⚠️ Seguridad de las API Keys

Trata tus API keys como contraseñas. Cualquier persona con acceso a tu key puede hacer llamadas que se cargarán a tu cuenta.

**Tres reglas básicas:**

1. **Nunca las escribas directamente en tu código**. Usa variables de entorno o el gestor de Secrets de Google Colab
2. **Nunca las subas a un repositorio** (ni público ni privado). Añade `.env` a tu `.gitignore`
3. **Si sospechas exposición, revócala inmediatamente** desde el dashboard del proveedor y genera una nueva

## 🚀 Configuración Google Colab

Google Colab es un entorno de notebooks Jupyter en el navegador. No requiere instalación local, viene con Python preinstalado y se integra automáticamente con Google Drive. Solo necesitas una cuenta de Google.

### Crear y Abrir Notebooks

**Opción 1: Crear uno nuevo**

1. Accede a [colab.research.google.com](https://colab.research.google.com)
2. Haz clic en **Archivo > Cuaderno nuevo en Drive**
3. Se guardará automáticamente en la carpeta "Colab Notebooks" de tu Google Drive

**Opción 2: Cargar uno existente**

1. Accede a [colab.research.google.com](https://colab.research.google.com)
2. Haz clic en **Archivo > Abrir cuaderno**
3. Desde aquí, tienes la posibilidad de cargar desde la pestaña **Google Drive**, **Github** o subir un archivo `.ìpynb` desde la pestaña **Subir**

### Interfaz Básica

Un notebook contiene dos tipos de celdas:

- **Celdas de código**: Escribe y ejecuta Python. Se ejecutan con ▶ o Shift + Enter
- **Celdas de texto**: Documentación en Markdown (solo visualización, sin ejecución)

### Instalación de Librerías

Colab incluye numpy, pandas, matplotlib preinstalados. Para los SDKs de LLMs, instala desde una celda:

```
!pip install openai
!pip install anthropic
```

La instalación es temporal y se pierde cuando el entorno se desconecta.

### Gestión Segura de API Keys con Secrets

**Este es el aspecto crítico: nunca hardcodees tu API key en el notebook.**

Colab proporciona Secrets para almacenar claves de forma segura en tu cuenta Google, no en el notebook.

**Proceso:**

1. Haz clic en el icono de llave (🔑) en el panel izquierdo
2. Añade un nuevo secreto:
   - Nombre: `OPENAI_API_KEY` o `ANTHROPIC_API_KEY`
   - Valor: Tu API key
3. Activa el toggle de **"Acceso al notebook"**
4. Carga la clave en tu código usando `userdata.get()`:

```python
import os
from google.colab import userdata

os.environ["OPENAI_API_KEY"] = userdata.get("OPENAI_API_KEY")

from openai import OpenAI
client = OpenAI()  # Lee la key del entorno automáticamente
```

```python
import os
from google.colab import userdata

os.environ["ANTHROPIC_API_KEY"] = userdata.get("ANTHROPIC_API_KEY")

from anthropic import Anthropic
client = Anthropic()  # Lee la key del entorno automáticamente
```

**Los secrets son personales** (solo tú los ves) y **globales en tu cuenta** (disponibles en cualquier notebook con acceso activado).

### Ciclo de Vida del Entorno de Ejecución (Runtime)

- La máquina virtual se asigna cuando ejecutas la primera celda
- Se desconecta automáticamente tras ~90 minutos de inactividad o ~12 horas de uso continuado (versión gratuita)
- Al desconectarse, se pierde el estado (librerías, variables, archivos temporales)
- **El notebook se guarda automáticamente** — solo se pierde la ejecución
- Puedes reiniciar desde **Entorno de ejecución → Reiniciar**

### Recomendaciones Prácticas

- Ejecuta las celdas secuencialmente de arriba a abajo
- Utiliza siempre Secrets para las API keys — nunca hardcodees
- No te preocupes si el entorno se desconecta; vuelve a ejecutar desde el principio
- La versión gratuita es suficiente para los ejercicios (no requiere GPU para llamadas a APIs)

## ✍️ Ejercicios Prácticos

### Ejercicio 1: Crear tu cuenta en Anthropic y OpenAI

**Objetivo**: Tener cuentas activas y funcionales en al menos dos proveedores.

**Entregables:**

- [ ] Cuenta activa en OpenAI Platform con API key generada
- [ ] Cuenta activa en Anthropic Console con API key generada
- [ ] Facturación configurada y crédito disponible en al menos uno de los proveedores
- [ ] APIs keys guardadas de forma segura

**Completar antes de los siguientes ejercicios.**

---

### Ejercicio 2: Respuesta de modelo vía API

**Objetivo**: Realizar tu primera integración real con un LLM desde código Python.

**Formato**: Google Colab Notebook

**Proveedor**: A tu elección (OpenAI o Anthropic, según el que configuraste)

**Niveles:**

**Nivel 1 (Obligatorio):** Llamada básica a la API

1. Envía un mensaje simple
2. Recibe una respuesta
3. Imprímela por pantalla
4. ✅ Si ves una respuesta sin errores, el setup es correcto

**Nivel 2 (Obligatorio):** Añade un system prompt con rol

1. Define un system prompt que asigne un rol (ej: "Eres un experto en estimación de software")
2. Envía el mismo mensaje que en Nivel 1
3. Compara la respuesta anterior con esta
4. ✅ Observa: tono, nivel de detalle, estructura

**Nivel 3 (Opcional):** Extrae metadatos y calcula costes

1. Extrae de la respuesta:
   - Tokens de entrada
   - Tokens de salida
   - Modelo utilizado
2. Calcula el coste estimado de la llamada
3. Consulta precios oficiales:
   - OpenAI: [platform.openai.com/pricing](https://platform.openai.com/pricing)
   - Anthropic: [anthropic.com/pricing](https://www.anthropic.com/pricing)

**Entrega:**

Debes llegar a la sesión en vivo con Nivel 1 y Nivel 2 funcionando. En la sesión resolveremos dudas y avanzaremos desde aquí.

**Problemas comunes:**

- ¿Tienes crédito disponible en tu cuenta?
- ¿La API key está bien configurada?
- ¿Estás usando el modelo correcto?
- ¿Has instalado correctamente la librería?

**Documentación de referencia:**

- OpenAI: [platform.openai.com/docs/quickstart](https://platform.openai.com/docs/quickstart)
- Anthropic: [github.com/anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)

---

### Ejercicio 3: Google Colab Inicializado con API Keys

**Objetivo**: Tener un notebook de Google Colab completamente funcional con las API keys correctamente configuradas y una llamada a un LLM ejecutada.

**Requisitos:**

- [ ] Notebook en Google Colab con librerías instaladas
- [ ] API keys configuradas con Secrets (no hardcodeadas)
- [ ] Primera llamada a un LLM ejecutada correctamente
- [ ] Respuesta impresa y verificada

## 🔗 Recursos

### OpenAI

- Documentación oficial de OpenAI API: [platform.openai.com/docs](https://platform.openai.com/docs)
- Quickstart de OpenAI: [platform.openai.com/docs/quickstart](https://platform.openai.com/docs/quickstart)
- Precios de OpenAI: [platform.openai.com/pricing](https://platform.openai.com/pricing)
- GitHub SDK Python: [github.com/openai/openai-python](https://github.com/openai/openai-python)

### Anthropic

- Documentación oficial de Anthropic: [docs.anthropic.com](https://docs.anthropic.com)
- GitHub SDK Python: [github.com/anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)
- Precios de Anthropic: [anthropic.com/pricing](https://www.anthropic.com/pricing)
- Guía de API Messages: [docs.anthropic.com/en/api/messages](https://docs.anthropic.com/en/api/messages)

### Google Gemini

- Documentación oficial: [ai.google.dev](https://ai.google.dev)
- Google AI Studio: [aistudio.google.com](https://aistudio.google.com)
- Precios de Gemini: [ai.google.dev/pricing](https://ai.google.dev/pricing)

### Google Colab

- Documentación oficial: [developers.google.com/colab](https://developers.google.com/colab)
- Guía de Secrets: [colab.research.google.com/notebooks/snippets/importing_libraries.ipynb](https://colab.research.google.com/notebooks/snippets/importing_libraries.ipynb)

## ✅ Ejercicios a Completar

- **Sesión_01_Nivel_01_Anthropic.ipynb**
- **Sesión_01_Nivel_01_Openai.ipynb**
- **Sesión_01_Nivel_02_Anthropic.ipynb**
- **Sesión_01_Nivel_02_Openai.ipynb**
- **Sesión_01_Nivel_03_Anthropic.ipynb**
- **Sesión_01_Nivel_03_Openai.ipynb**
