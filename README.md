# AI Engineering 2026/05 — Ejercicios del Máster

Repositorio **personal** de ejercicios y proyectos desarrollados durante las sesiones del máster **AI Engineering 2026/05** impartido por [LIDR.co](https://www.lidr.co/ai-engineering/).

> **Objetivo del programa:** Diseñar, construir y desplegar sistemas de inteligencia artificial reales en entornos de producción.

---

## Descripción del programa

AI Engineering es un programa técnico orientado a la construcción de productos de IA completos: desde la integración con modelos de lenguaje hasta el despliegue, evaluación y monitorización en producción. No se trata de teoría ni de demostraciones aisladas, sino de replicar cómo se construyen sistemas con IA en equipos de ingeniería reales.

**Duración:** 17 semanas

**Formato:** 100% online · Sesiones en vivo los miércoles de 17:30 a 19:30 CET

**Carga:** ~8 horas semanales (sesiones en directo + prácticas + contenido bajo demanda)

A lo largo del programa se trabaja sobre un **proyecto principal evolutivo** — un sistema de estimación automatizada de software que recibe transcripciones de reuniones con clientes y genera presupuestos basándose en el historial de la empresa. Este proyecto crece y se complejiza sesión a sesión, incorporando nuevas capas de arquitectura hasta convertirse en un producto listo para producción.

---

## Stack tecnológico

- **Lenguaje:** Python
- **Framework backend:** FastAPI
- **Entorno de desarrollo:** Docker (entorno local reproducible) + Google Colab (experimentación rápida)
- **Interfaz:** Streamlit
- **Proveedores de LLMs:** OpenAI (GPT-4o, o1), Anthropic (Claude), Google (Gemini)
- **SDKs:** OpenAI SDK, Anthropic SDK, Google Gen AI SDK
- **Arquitecturas:** CAG (Cache Augmented Generation), RAG (Retrieval-Augmented Generation)

---

## Estructura del repositorio

Se generará una rama específica para cada sesión, añadiendo todo el contenido dentro de la carpeta correspondiente a la sesión.

Esto permitirá al final del máster hacer un merge de todas las ramas y obtener un repositorio completo de todo el trabajo realizado.

```
/
├── session_00_welcome-session/
├── session_01_llms-y-setup-de-entorno-de-trabajo/
├── session_02_fundamentos-de-arquitectura-cag/
├── session_03_wrappers-de-modelos-y-arquitectura-de-capas/
├── session_04_productos-ia-avanzados/
├── session_05_funcionalidades-avanzadas-en-productos-ia/
├── session_06_data-driven-ai-analisis-y-normalizacion/
├── session_07_embeddings-y-representacion-vectorial/
├── session_08_bases-de-datos-vectoriales/
├── session_09_fundamentos-de-rag/
├── session_10_tecnicas-avanzadas-de-recuperacion/
├── session_11_rag-avanzado-generacion-y-calidad/
├── session_12_introduccion-a-agentes-ia/
├── session_13_orquestacion-de-agentes/
├── session_14_sistemas-multi-agente-avanzados/
├── session_15_puesta-en-produccion-y-llmops-i/
├── session_16_puesta-en-produccion-y-llmops-ii/
└── session_17_laboratorio-10x-engineer/
```

La rama `main` quedará únicamente para elementos comunes y posibles configuraciones compartidas.

---

## Módulos y sesiones

### Welcome Session — Sesión 0

Sesión de presentación del programa, metodología y expectativas. Introducción al rol del AI Engineer, stack tecnológico y visión práctica del curso. Setup inicial y contexto de los proyectos que se desarrollarán durante el máster.

---

### Sesión 1 — LLMs y setup de entorno de trabajo

Introducción práctica a la integración de LLMs vía API en aplicaciones reales.

- Comunicación con modelos y estructura de llamadas
- Gestión de prompts, tokens y respuestas
- Ecosistema de proveedores y criterios de selección
- Análisis de arquitecturas reales y casos prácticos

---

### Sesión 2 — Fundamentos de arquitectura CAG

Inicio de proyecto real con arquitectura Cache Augmented Generation.

- Fundamentos de CAG
- Gestión de contexto, parámetros y costes
- Arquitectura conversacional
- Buenas prácticas en consumo y optimización

---

### Sesión 3 — Wrappers de modelos y arquitectura de capas

Diseño de sistemas robustos para trabajar con múltiples proveedores.

- Interfaces conversacionales (Streamlit y alternativas)
- Abstracción y fallback entre modelos
- Cacheo inteligente, streaming y trazabilidad
- Patrones de diseño para sistemas escalables

---

### Sesión 4 — Productos IA avanzados

Diseño de productos donde la calidad no depende del prompt del usuario.

- Interfaces no conversacionales y UX orientada a negocio
- Prompts estructurados y templates dinámicos
- Extracción de datos estructurados
- Guardrails y validación de outputs

---

### Sesión 5 — Funcionalidades avanzadas en productos IA

Ampliación del sistema con capacidades reales de producción.

- Integración de contexto externo (archivos, web, BBDD)
- Memoria conversacional
- Sistemas adaptativos por permisos
- Testing y evaluación del sistema

---

### Sesión 6 — Data-driven AI: análisis y normalización

Preparación de datos empresariales para sistemas inteligentes.

- Auditoría y selección de datos
- Normalización y limpieza
- Arquitectura según tipo de dato
- Privacidad y cumplimiento normativo

---

### Sesión 7 — Embeddings y representación vectorial

Vectorización e indexación para búsqueda semántica avanzada.

- Chunking y estrategias de procesamiento
- Modelos de embeddings
- Espacios vectoriales y recuperación semántica
- Preparación de datos para entornos productivos

---

### Sesión 8 — Bases de datos vectoriales

Uso profesional de bases vectoriales en sistemas IA.

- Arquitectura y comparativa con BBDD tradicionales
- Indexación y escalabilidad
- Búsqueda semántica en producción
- Consideraciones de rendimiento

---

### Sesión 9 — Fundamentos de RAG

Diseño de sistemas Retrieval-Augmented Generation.

- Flujo de consultas, recuperación y generación
- Estrategias de retrieval
- Integración retriever–generador
- Securización de la capa de datos

---

### Sesión 10 — Técnicas avanzadas de recuperación

Optimización de precisión y relevancia en sistemas RAG.

- Reranking y búsqueda híbrida
- Expansión de consultas
- Routing entre agentes
- Filtrado contextual y temporal

---

### Sesión 11 — RAG avanzado: generación y calidad

Mejora de calidad, reducción de alucinaciones y evaluación.

- Síntesis multi-fuente
- Citación y atribución
- Mitigación de alucinaciones
- Métricas y evaluación (RAGAS)

---

### Sesión 12 — Introducción a agentes IA

Bases técnicas de sistemas agénticos.

- Anatomía de un agente
- Patrones de razonamiento y planificación
- Tools y function calling
- Integración con sistemas RAG

---

### Sesión 13 — Orquestación de agentes

Diseño de arquitecturas multi-agente robustas.

- Frameworks (Langchain, Autogen, Langgraph…)
- Gestión de estado y memoria
- Manejo de errores y observabilidad
- Diseño de grafos de ejecución

---

### Sesión 14 — Sistemas multi-agente avanzados

Arquitecturas colaborativas y supervisadas.

- Comunicación y delegación entre agentes
- Human-in-the-loop
- Seguridad y sandboxing
- Patrones avanzados de supervisión

---

### Sesión 15 — Puesta en producción y LLMOps I

Despliegue real de productos IA en entornos productivos.

- Arquitectura de microservicios
- Monitorización, observabilidad y KPIs

---

### Sesión 16 — Puesta en producción y LLMOps II

Despliegue real de productos IA en entornos productivos.

- Safety y compliance-by-design
- Optimización de latencia y costes
- A/B testing y mejora continua

---

### Sesión 17 — Laboratorio 10x Engineer

Sesión práctica orientada a integrar IA de manera efectiva en el proceso de desarrollo end-to-end.

- Spec-Driven Development
- Agentes
- MCPs
- Skills

Aplicación de lo aprendido en casos de uso reales, desde la planificación de la tarea hasta la code review automatizada.

---

## Buenas prácticas del repositorio

Este repositorio sigue las directrices de la [Política de Gestión de Repositorios](https://training.lidr.co/posts/ai-engineering-202605-%F0%9F%93%9C-politica-de-gestion-de-repositorios) del programa:

- **No se incluyen archivos `.env`** en el repositorio. Usar `.env.example` como referencia de variables necesarias.
- **No se exponen claves API, tokens ni credenciales** en ningún fichero o commit.
- **No se incluyen datos reales** de usuarios ni información personal.
- Los datos de ejemplo son ficticios o anonimizados.
- Cada ejercicio incluye documentación sobre setup, decisiones de diseño y limitaciones.

---

## Recursos

- [Programa oficial AI Engineering](https://www.lidr.co/ai-engineering/)
- [Plataforma del programa](https://training.lidr.co/spaces/23692938)
- [Programa detallado](https://lidr.notion.site/ai-engineering)
- [OpenAI API Documentation](https://platform.openai.com/docs)
- [Anthropic API Documentation](https://docs.anthropic.com)
- [Google Gen AI SDK](https://ai.google.dev/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Streamlit Documentation](https://docs.streamlit.io)
- Repositorios de código con soluciones
  - [Sesión 00 y 01](https://github.com/LIDR-academy/ai-engineering-pre-sessions/tree/main/session_01)
  - [Resto de sesiones](https://github.com/LIDR-academy/ai-engineering)

---

## Autor

**Icaro Bregon**  
Participante del máster AI Engineering 2026/05 — LIDR.co
