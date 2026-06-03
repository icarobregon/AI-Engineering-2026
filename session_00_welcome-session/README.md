# Sesión 00: Welcome session

## Objetivo de la sesión

Antes de construir sistemas de inteligencia artificial, este módulo de pre-curso tiene un propósito claro: **eliminar cualquier fricción técnica** y garantizar que todos los participantes comprendan el entorno en el que van a trabajar.

---

## Estructura del módulo

### 1. 🗒️ Stack y entorno tecnológico

Presentación del conjunto de herramientas que refleja lo que se utiliza en equipos de ingeniería profesionales.

#### Python + FastAPI

- **Python 3.11+** es el lenguaje base. Los SDKs de OpenAI, Anthropic y prácticamente cualquier proveedor de modelos están diseñados con Python como referencia.
- **FastAPI** es el framework para construir los servicios que exponen las capacidades de IA. Sus ventajas principales son:
  - Rendimiento asíncrono nativo (ideal cuando se espera respuestas de APIs externas como LLMs)
  - Validación automática con Pydantic
  - Documentación OpenAPI generada automáticamente
- **Uvicorn** actúa como servidor ASGI.

#### uv — Gestor de dependencias

Reemplaza a `pip`, `virtualenv`, `poetry` y `pyenv` en una sola herramienta. Es entre 10 y 100 veces más rápido. Comparable a `bundler` en Ruby o `npm` en JavaScript.

#### Docker y Docker Compose

Con un único comando (`docker-compose up`) se levantan todos los servicios:

- Backend FastAPI
- Base de datos PostgreSQL con soporte vectorial
- Frontend

Esto garantiza que todos los participantes trabajen exactamente con el mismo entorno desde el primer día.

#### Frameworks de frontend para IA (prototipado)

| Framework     | Ideal para                                                   | Limitaciones                             |
| ------------- | ------------------------------------------------------------ | ---------------------------------------- |
| **Streamlit** | Dashboards, formularios, multipágina, visualización de datos | No apto para alta concurrencia           |
| **Gradio**    | Demos rápidas, prototipos para stakeholders                  | Menos flexible para interfaces complejas |
| **Chainlit**  | Aplicaciones conversacionales / chatbots                     | Solo interfaces de chat                  |

> En el programa se usará **Streamlit** para la primera interfaz web, separando claramente el backend (FastAPI) del frontend.

---

### 2. 📄 Configuración del entorno en local

Guía paso a paso para instalar y verificar las herramientas base:

#### Docker y Docker Compose

- **macOS**: Instalar Docker Desktop desde [docker.com](https://docker.com/get-started)
- **Windows**: Requiere WSL 2 habilitado + Docker Desktop
- **Linux (Ubuntu/Debian)**: Instalación de Docker Engine directamente via `apt`

Verificación:

```bash
docker --version
docker compose version
docker run hello-world
```

#### uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternativa con pip
pip install uv
```

Primeros pasos:

```bash
uv python install 3.11   # Instalar Python 3.11
uv init mi-proyecto      # Crear proyecto
uv add fastapi           # Añadir dependencias
uv run python main.py    # Ejecutar script
```

#### FastAPI

```bash
uv add "fastapi[standard]"
```

Verificación rápida:

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"mensaje": "¡Hola desde FastAPI!"}
```

```bash
uv run fastapi dev main.py
# Documentación interactiva en: http://127.0.0.1:8000/docs
```

#### Verificación final del entorno

```bash
docker --version
docker compose version
uv --version
uv python list        # Debe mostrar Python 3.11
uv run fastapi --version
```

---

### 3. 📄 Introducción a Google Colab

Google Colab es el entorno estándar para los **ejercicios pre-sesión**. Permite trabajar sin configuración local: Python viene preinstalado y se integra con Google Drive.

**Requisito**: Solo una cuenta de Google.

#### Crear/abrir un notebook

- **Desde el repositorio**: Descargar el `.ipynb` y subirlo en [colab.research.google.com](https://colab.research.google.com)
- **Notebook nuevo**: Directo desde [colab.research.google.com](https://colab.research.google.com) → _Nuevo cuaderno_

#### Instalar librerías

```python
!pip install openai
!pip install anthropic
```

> La instalación es **temporal**: se pierde al desconectarse el entorno.

#### Gestión segura de API Keys con Secrets

**Nunca** escribir la API key directamente en el código. Usar el panel de **Secrets** (icono 🔑 en el panel lateral).

```python
import os
from google.colab import userdata

# OpenAI
os.environ["OPENAI_API_KEY"] = userdata.get("OPENAI_API_KEY")
from openai import OpenAI
client = OpenAI()

# Anthropic
os.environ["ANTHROPIC_API_KEY"] = userdata.get("ANTHROPIC_API_KEY")
from anthropic import Anthropic
client = Anthropic()
```

#### Ciclo de vida del entorno

- El entorno se desconecta tras ~90 minutos de inactividad (versión gratuita)
- Al desconectarse se pierde: librerías, variables y archivos temporales
- El notebook (código y texto) se guarda automáticamente en Google Drive
- Para reiniciar: _Entorno de ejecución → Reiniciar entorno de ejecución_

---

### 4. 🗒️ Principales APIs y modelos que vamos a usar

#### Modelos de Lenguaje (LLMs)

**OpenAI**

| Modelo           | Uso recomendado                                             |
| ---------------- | ----------------------------------------------------------- |
| GPT-5.4          | Tareas complejas, máxima calidad, ventana de 1M tokens      |
| GPT-5.4 mini     | Modelo principal del programa (equilibrio calidad/coste)    |
| GPT-5.4 nano     | Tareas ligeras: clasificación, enrutamiento, autocompletado |
| GPT-4.1 / GPT-4o | Proyectos en producción existentes, optimización de costes  |

Recursos: [Catálogo de modelos](https://developers.openai.com/api/docs/models) | [Precios](https://openai.com/api/pricing)

**Anthropic (Claude)**

| Modelo            | Uso recomendado                                            |
| ----------------- | ---------------------------------------------------------- |
| Claude Sonnet 4.6 | Modelo equilibrado, búsqueda agéntica, extended thinking   |
| Claude Opus 4.6   | Máxima calidad, coding complejo, agentes de larga duración |
| Claude Haiku 4.5  | Alto volumen, baja latencia, moderación y clasificación    |

Recursos: [Modelos Claude](https://platform.claude.ai/docs/en/about-claude/models/overview) | [Anthropic Cookbook](https://github.com/anthropics/anthropic-cookbook)

#### Modelos de Embeddings

Fundamentales para el módulo de **RAG (sesiones 7-11)**. Transforman texto en vectores numéricos para búsqueda semántica.

**OpenAI Embeddings**

| Modelo                   | Dimensiones       | Uso                           |
| ------------------------ | ----------------- | ----------------------------- |
| `text-embedding-3-small` | 1.536 (reducible) | Opción principal, bajo coste  |
| `text-embedding-3-large` | 3.072             | Máxima precisión, multilingüe |

**Sentence Transformers (open-source)**
Librería de Hugging Face para ejecutar embeddings en local, sin API externa. Útil para privacidad de datos o control de costes.

#### Agregador: LiteLLM

Interfaz unificada para llamar a más de 100 modelos de distintos proveedores (OpenAI, Anthropic, Mistral, Groq, Ollama…) con el mismo formato de llamada.

Cambiar de modelo = cambiar un solo string, sin tocar el resto del código.

Funcionalidades clave:

- **Fallback automático** entre proveedores
- **Balanceo de carga** entre deployments
- **Tracking de costes** por llamada

Se usará como librería Python dentro de FastAPI y como **proxy HTTP gateway**.

Recursos: [Documentación LiteLLM](https://docs.litellm.ai) | [GitHub](https://github.com/BerriAI/litellm)

---

## Checklist antes de la primera sesión

- [ ] Docker instalado y funcionando (`docker run hello-world`)
- [ ] `uv` instalado y Python 3.11 disponible (`uv python list`)
- [ ] FastAPI instalado y endpoint básico funcional
- [ ] Entorno Docker del programa levantado en local (`docker-compose up`)
- [ ] Cuenta de Google Colab activa y notebook de prueba creado
- [ ] API keys de OpenAI y/o Anthropic configuradas como Secrets en Colab
- [ ] Revisados los modelos y APIs principales del programa
