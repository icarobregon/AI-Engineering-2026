# Sesión 00: Introducción al Desarrollo de IA y Panorama Actual

## 📋 Descripción

Sesión inaugural del Máster AI Engineering. Esta sesión proporciona el contexto estratégico, las motivaciones del programa y una visión general del panorama actual de la Inteligencia Artificial en productos reales.

**Temas clave:**
- Panorama actual de la IA: evolución de LLMs y su impacto en la industria
- ¿Por qué ahora es el momento para construir productos con IA?
- Diferencia entre experimentar con LLMs vs. construir productos robustos
- Estructura del máster y ruta de aprendizaje
- Configurar del entorno local de desarrollo
- Configurar Google Colab
- Conocer las principales APIs y modelos que se usarán durante el curso

## 🎯 Objetivos de aprendizaje

Al finalizar esta sesión serás capaz de:

- [ ] Entender el estado actual de la tecnología de LLMs y su trajectoria
- [ ] Comprender por qué la industria está en un punto de inflexión para productos con IA
- [ ] Identificar los desafíos clave al construir productos de IA en producción
- [ ] Tener el entorno local y Google Colab configurado para comenzar a trabajar

## 🛠️ Stack Tecnológico

A lo largo del máster utilizaremos las siguientes tecnologías:

### **Backend & Lenguaje**
- **Python 3.11+**: Lenguaje principal para todo el backend de IA. Es el estándar porque los SDKs de OpenAI, Anthropic y otros proveedores están optimizados para Python.
- **FastAPI**: Framework para construir servicios que exponen capacidades de IA (rendimiento asíncrono, validación automática con Pydantic, documentación OpenAPI).
- **uv**: Herramienta rápida para gestionar paquetes y entornos virtuales.

### **Infraestructura**
- **Docker & Docker Compose**: Containerización de servicios para eliminar incompatibilidades entre máquinas.
- **PostgreSQL**: Base de datos con soporte para búsquedas vectoriales.

### **Interfaces & Frameworks**
- **Streamlit**: Para aplicaciones con chat, dashboards, formularios complejos.
- **Gradio**: De Hugging Face, ideal para demos rápidas y prototipos.
- **Chainlit**: Diseñado específicamente para aplicaciones conversacionales con LLMs.

### **APIs de LLMs**
- **OpenAI**: GPT-4o-mini, GPT-4o
- **Anthropic Claude**: Modelos de Anthropic
- **Google Gemini**: Modelos de Google (según progresión)

*El stack se irá completando y refinando conforme avance el máster.*

## 🚀 Configuración del Entorno de Desarrollo

### **1. Docker y Docker Compose**

**¿Qué es?**
Docker es una plataforma que empaqueta aplicaciones y sus dependencias en contenedores aislados (ligeros y que arrancan en segundos). Docker Compose permite levantar múltiples contenedores con un solo comando.

**Instalación en macOS**
1. Descargar Docker Desktop for Mac desde [docker.com/get-started](https://www.docker.com/get-started/) (elegir versión Apple Silicon o Intel según tu procesador)
2. Abrir el archivo `.dmg` y arrastrar Docker a Aplicaciones
3. Abrir Docker Desktop desde Aplicaciones y aceptar términos
4. Esperar a que el icono de la ballena en la barra de menú deje de parpadear — eso indica que Docker está listo

**Verificación:**
```bash
docker --version
docker compose version
docker run hello-world
```

---

### **2. uv — Gestor de Paquetes Python**

**¿Qué es?**
uv es un gestor de paquetes y proyectos Python (escrito en Rust) que es 10-100x más rápido que pip. Reemplaza a pip, virtualenv, poetry y pyenv en una sola herramienta. No necesitas tener Python preinstalado — uv lo instala por ti.

**Instalación en macOS:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Después reinicia tu terminal o ejecuta el comando indicado en la salida del script para actualizar el PATH.

**Verificación:**
```bash
uv --version
```

**Primeros pasos:**
```bash
# Instalar Python 3.11 (versión del programa)
uv python install 3.11

# Crear nuevo proyecto
uv init mi-proyecto
cd mi-proyecto
```

**Ventaja:** `uv init` crea automáticamente estructura del proyecto con `pyproject.toml` y entorno virtual — no necesitas crear ni activar el entorno manualmente.

---

### **3. FastAPI — Framework para Servicios de IA**

**¿Qué es?**
FastAPI es un framework web moderno para construir APIs REST con Python. Genera documentación interactiva (Swagger UI) automáticamente. Se apoya en Starlette (rendimiento asíncrono) y Pydantic (validación de datos).

**Instalación:**
```bash
uv add "fastapi[standard]"
```

La opción `[standard]` incluye Uvicorn (servidor ASGI) y otras dependencias necesarias.

**Ejemplo mínimo:**

Crear archivo `main.py`:
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"mensaje": "¡Hola desde FastAPI!"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}
```

Ejecutar:
```bash
# Con uv
uv run fastapi dev main.py

# O con uvicorn
uvicorn main:app --reload
```

Acceder a:
- **API**: http://127.0.0.1:8000
- **Documentación interactiva**: http://127.0.0.1:8000/docs

---

### **4. Verificación Final del Entorno**

Ejecutar estos comandos para confirmar que todo funciona:

```bash
# Docker
docker --version
docker compose version

# uv y Python
uv --version
uv python list  # Debería mostrar Python 3.11

# FastAPI
uv run fastapi --version
```

Si todos los comandos devuelven versiones sin errores, el entorno está listo para la primera sesión.

---

### **Resumen del Orden de Instalación**
1. **Docker** (primera — todo corre en contenedores)
2. **uv** (gestor de paquetes Python)
3. **FastAPI** (se añade como dependencia con uv)

## 🔗 Recursos

### **Docker**

- **Documentación oficial de Docker:** [docs.docker.com](https://docs.docker.com) — referencia completa de todos los comandos y configuraciones.

- **Guía oficial "Get Started":** [docs.docker.com/get-started](https://docs.docker.com/get-started) — tutorial interactivo paso a paso de Docker.

- **Docker para principiantes (español):** [freeCodeCamp - Guía de Docker para principiantes](https://www.freecodecamp.org/news/docker-tutorial-for-beginners-es/) — tutorial práctico en español para crear tu primera aplicación con Docker.

- **Tutorial Docker en español:** [Imagina Formación - Aprende Docker](https://www.imaginaformacion.com/tutoriales/docker) — guía actualizada con los conceptos principales y primeros pasos.

---

### **uv (Gestor de Paquetes Python)**

- **Documentación oficial de uv:** [docs.astral.sh/uv](https://docs.astral.sh/uv) — referencia completa y guías oficiales.

- **Guía de instalación de Python con uv:** [docs.astral.sh/uv/guides/install-python](https://docs.astral.sh/uv/guides/install-python) — cómo gestionar versiones de Python.

- **"Managing Python Projects With uv" (Real Python):** [realpython.com/python-uv](https://realpython.com/python-uv) — tutorial exhaustivo con ejemplos prácticos paso a paso.

- **"uv: An In-Depth Guide" (SaaS Pegasus):** [saaspegasus.com/guides/uv-deep-dive](https://saaspegasus.com/guides/uv-deep-dive) — guía en profundidad sobre por qué uv es el futuro del empaquetado Python.

- **Tutorial de DataCamp sobre uv:** [datacamp.com/tutorial/python-uv](https://datacamp.com/tutorial/python-uv) — introducción completa con comparativas frente a pip y poetry.

---

### **FastAPI**

- **Documentación oficial de FastAPI:** [fastapi.tiangolo.com](https://fastapi.tiangolo.com) — tutorial completo, guía avanzada y referencia de API.

- **Tutorial oficial en español:** [fastapi.tiangolo.com/es/tutorial](https://fastapi.tiangolo.com/es/tutorial) — la documentación oficial traducida al español.

- **"Get Started With FastAPI" (Real Python):** [realpython.com/get-started-with-fastapi](https://realpython.com/get-started-with-fastapi) — tutorial introductorio bien estructurado.

- **Tutorial de FastAPI (VS Code):** [code.visualstudio.com/docs/python/tutorial-fastapi](https://code.visualstudio.com/docs/python/tutorial-fastapi) — guía oficial de Microsoft para trabajar con FastAPI en VS Code.

- **"FastAPI: la herramienta definitiva" (español):** [cosasdedevs.com/fastapi](https://cosasdedevs.com/fastapi) — colección de tutoriales en español desde cero.

- **Tutorial CRUD con FastAPI (español):** [kinsta.com/es/blog/fastapi](https://kinsta.com/es/blog/fastapi) — guía práctica para construir una aplicación CRUD completa.

## ✅ Ejercicios completados

- `main.py` con el ejemplo de FastAPI definido en la documentación.
- `check_environment.py` que comprueba que todas las dependencias del entorno de desarrollo local están correctamente instaladas.
