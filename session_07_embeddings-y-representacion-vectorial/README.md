# Sesión 7 — Embeddings y representación vectorial

## Objetivo de la sesión

La Sesión 6 dejó los presupuestos históricos limpios, normalizados y documentados en un catálogo de datos. Esta sesión da el paso siguiente y más determinante para la calidad de cualquier sistema RAG: convertir esos documentos en vectores que permitan encontrar información relevante aunque las palabras exactas de una consulta no coincidan con las palabras exactas de los documentos. Cuando un cliente describe un brief nuevo con su propio vocabulario, el sistema debe poder recuperar componentes históricos equivalentes aunque no comparta ni una palabra literal con ellos.

El módulo encadena tres decisiones: qué es un embedding y por qué la geometría que produce sirve para medir similitud semántica; qué modelo de embeddings conviene usar en 2026 según cinco criterios de decisión (dimensionalidad, idioma, dominio, hosting/coste y licencia); y cómo partir los documentos en fragmentos (chunking) antes de vectorizarlos. Los benchmarks recientes (NAACL 2025, Chroma 2025, Vecta 2026) coinciden en un hallazgo incómodo: la estrategia de chunking puede mover la calidad de recuperación tanto como cambiar de modelo de embedding, así que se trata como un tema de primer nivel y no como un detalle de implementación.

El cierre del material aterriza toda la teoría al caso concreto del proyecto: dos chunkers especializados, uno para presupuestos JSON estructurados y otro para transcripciones de reuniones de toma de requisitos, que comparten una interfaz común dentro del servicio IA.

## Qué vas a aprender

### 1. 📄 Embeddings: del texto a la geometría semántica — 21 min

Un embedding es una función que transforma cualquier texto en un vector numérico de dimensión fija (1536 para text-embedding-3-small, 384 para all-MiniLM-L6-v2, 3072 para text-embedding-3-large). Lo relevante no es el número de dimensiones sino la propiedad geométrica que se cumple sobre ellas: textos semánticamente parecidos producen vectores cercanos. Esa geometría emerge durante el entrenamiento mediante aprendizaje contrastivo, en el que el modelo aprende a acercar anclas a sus positivos (parafraseos, traducciones, pares pregunta-respuesta) y a alejarlas de negativos no relacionados.

Para medir cercanía entre vectores hay tres métricas de uso habitual: similitud coseno (mide el ángulo, ignora la magnitud, rango [-1, 1]), producto escalar (sensible a la magnitud, más barato de computar, equivalente al coseno cuando los vectores están normalizados) y distancia euclidiana (sensible a la magnitud, relacionada matemáticamente con el coseno en vectores normalizados). La regla práctica es usar la métrica que recomiende la model card del modelo elegido; para text-embedding-3-small de OpenAI, coseno y producto escalar son intercambiables porque los vectores ya vienen normalizados.

El artículo también marca límites honestos: los embeddings no razonan sobre números, fechas ni identificadores (para eso hacen falta filtros estructurados sobre metadata), son débiles frente a coincidencias exactas de términos raros (ahí gana BM25, de ahí el interés de la búsqueda híbrida en sesiones posteriores) y sufren la maldición de la dimensionalidad, por lo que los umbrales de similitud deben calibrarse sobre el propio dataset y no darse por sentados.

### 2. 📄 Selección de modelos de embeddings: trade-offs en producción — 28 min

No existe un modelo de embeddings universalmente mejor. El artículo recorre el panorama de 2026 (OpenAI text-embedding-3-small/large, Cohere embed-v3 y Voyage voyage-3-large como opciones comerciales; BAAI/bge-m3 y sentence-transformers/all-MiniLM-L6-v2 como opciones open source self-hosted) y advierte sobre las limitaciones del ranking MTEB: mide rendimiento medio sobre datasets públicos genéricos, se ha convertido en un objetivo de optimización en sí mismo, y estudios recientes muestran que la varianza introducida por la estrategia de chunking puede igualar o superar la varianza entre modelos.

Introduce Matryoshka Representation Learning (MRL): modelos entrenados para producir embeddings de calidad a varias dimensionalidades anidadas (256, 512, 1024, 1536, 3072), lo que permite truncar el vector para ahorrar espacio y latencia sin perder demasiada calidad semántica. Se puede pedir la dimensión directamente vía el parámetro dimensions de la API de OpenAI, o truncar manualmente un vector ya almacenado, en cuyo caso hay que renormalizarlo a norma unitaria.

Propone cinco ejes de decisión (dimensionalidad, idioma del corpus, dominio, hosting/coste y licencia) y los aplica al proyecto: la elección fijada es text-embedding-3-small con 1536 dimensiones por defecto, justificada por la integración ya existente desde la Sesión 1, un soporte multilingüe suficiente para briefs en español y descripciones en inglés, un coste despreciable al volumen del proyecto y una licencia aceptable en un contexto académico sin datos sensibles. El artículo documenta también por qué se descartan las alternativas razonables (text-embedding-3-large, bge-m3 self-hosted, voyage-3-large, all-MiniLM-L6-v2 local) para este caso concreto.

### 3. 📄 Estrategias profesionales de chunking — 32 min

Es el artículo más extenso porque el chunking es, según la evidencia citada, la palanca de mayor impacto en la calidad de un sistema RAG. Cataloga doce estrategias agrupadas en cuatro familias: mecánicas (fixed-size, recursive character text splitter, sentence-window retrieval, sliding window), estructurales (document-based sobre Markdown/HTML/JSON, hierarchical / parent-child), semánticas (semantic chunking por embeddings de oraciones, cluster semantic chunking, LLM-based / propositional chunking) y avanzadas/contextuales (late chunking, agentic chunking, query-dependent chunking y Contextual Retrieval de Anthropic).

Para cada estrategia se documentan criterios de cuándo funciona y cuándo no. Las conclusiones operativas más citables: el recursive character text splitter con 400-512 tokens y 10-20% de overlap es el punto de partida razonable y sorprendentemente competitivo; enriquecer cada chunk con metadata estructural del documento padre (contextual chunk headers) puede subir la accuracy de QA entre 15 y 25 puntos según investigación de Microsoft Azure; y Contextual Retrieval de Anthropic, que antepone a cada chunk un resumen de contexto generado por un LLM antes de embederlo e indexarlo, reduce los fallos de recuperación hasta un 35% por sí sola, un 49% combinada con BM25 contextual y hasta un 67% sumando reranking, según los benchmarks publicados por Anthropic.

El mensaje final del artículo es que la mejor estrategia depende del tipo de documento, y que un corpus heterogéneo, como el del proyecto, con presupuestos JSON y transcripciones de texto plano, casi siempre se beneficia de aplicar estrategias distintas a cada tipo de documento en lugar de forzar una única solución genérica.

### 4. 📄 Chunking del proyecto: presupuestos JSON y transcripciones — 26 min

Aterriza el catálogo anterior a los dos tipos de documento reales del proyecto mediante dos chunkers especializados que comparten una interfaz Chunker común: JSONStructuralChunker para presupuestos y TopicSegmentationChunker para transcripciones.

Para los presupuestos JSON, la granularidad correcta es un componente del presupuesto igual a un chunk. Cada chunk combina el texto legible del componente (nombre, descripción, stack, complejidad, horas) con un header contextual que reproduce datos del presupuesto padre (resumen del proyecto, sector del cliente, año, tecnología principal), de modo que un componente de autenticación no compita en el índice con componentes de autenticación de otros sectores irrelevantes. La metadata (budget_id, component_id, client_sector, main_technology, year, complexity, estimated_hours) viaja junto al chunk sin ser embebida, pensada para filtros futuros con pgvector en la Sesión 8.

Para las transcripciones, los splitters de carácter fallan porque cortan en mitad de intervenciones y fragmentan discusiones que se retoman minutos después. La estrategia elegida es topic-based segmentation: se embeben las intervenciones con un modelo local ligero (all-MiniLM-L6-v2, elegido aquí por velocidad y coste, no por ser el modelo final del índice), se mide la similitud entre intervenciones consecutivas y se corta cuando cae por debajo de un umbral (0.55 como punto de partida, a calibrar sobre las transcripciones reales). Cada bloque temático resultante se enriquece con metadata de la reunión (cliente, fecha, fase, hablantes principales).

El artículo cierra con la composición dentro del servicio IA: un IngestRouter que decide qué chunker aplicar según un campo document_type explícito en el payload de entrada (budget o transcript), evitando por ahora la detección automática del tipo de documento, que equivaldría a chunking agentic, con un coste adicional no justificado en este punto del programa.

## Ejercicios prácticos

### ✍️ Ejercicio — Pipeline mínimo de embeddings y chunking

**Objetivo.** Construir, dentro del servicio IA (Python + FastAPI), un pipeline funcional mínimo que reciba presupuestos históricos en JSON, los divida en chunks respetando su estructura, genere embeddings con la API de OpenAI y devuelva los vectores por HTTP. El ejercicio se cierra con un script de línea de comandos que compara la similitud coseno entre pares de textos, a modo de comprobación de que el pipeline discrimina razonablemente entre contenido cercano y lejano semánticamente. La sesión en vivo parte de este pipeline para introducir y comparar otras estrategias de chunking.

**Contexto.** Los presupuestos históricos ya están limpios y normalizados desde la Sesión 6. Este ejercicio no persiste nada en base de datos vectorial todavía (eso llega en la Sesión 8 con PostgreSQL + pgvector): los vectores se generan en memoria y se devuelven en la respuesta HTTP. El código nuevo vive en un módulo embedding_pipeline/ dentro del servicio IA; no se modifica el backend de negocio ni la interfaz visual del proyecto.

**Qué entra en el alcance:**
- Un chunker estructural para presupuestos JSON, con la regla un componente = un chunk.
- Un embedder que llama a text-embedding-3-small de OpenAI.
- Un endpoint POST /embeddings/ingest que recibe presupuestos y devuelve chunks vectorizados.
- Un script compare.py que calcula la similitud coseno entre dos textos dados por línea de comandos.
- La validación manual sobre tres pares de textos de prueba, documentada en un SANITY_CHECK.md.

**Qué NO entra (se trabaja en la sesión en vivo):** ninguna otra estrategia de chunking (recursive, semantic, hierarchical, late chunking, Contextual Retrieval, etc.), comparación entre varios modelos de embeddings, enriquecimiento del chunk con contexto generado por LLM, persistencia en base de datos vectorial, búsqueda semántica (retrieval) y métricas formales de recuperación como recall@k o NDCG.

**Prerrequisitos:**
- Repositorio "estimator" del alumno en el estado de la Sesión 6 (FastAPI, Docker, structlog, pydantic-settings, presupuestos ya normalizados).
- Variable OPENAI_API_KEY configurada en el .env.
- Docker y Docker Compose operativos.
- Python 3.11+ disponible localmente si se quiere ejecutar compare.py fuera del contenedor.

**Datos de entrada.** Se parte de un fichero data/budgets_sample.json con 15 presupuestos históricos normalizados, cubriendo varios sectores (fintech, e-commerce, healthcare, industrial) y stacks tecnológicos distintos. Cada presupuesto sigue este esquema simplificado:

```json
{
  "budget_id": "BUD-2024-014",
  "client_metadata": {
    "name": "FintechCorp",
    "sector": "finance",
    "country": "ES"
  },
  "project_summary": "Mobile banking API with OAuth 2.0 authentication and PSD2 compliance",
  "main_technology": "ruby_on_rails",
  "year": 2024,
  "total_estimated_hours": 480,
  "components": [
    {
      "component_id": "AUTH-001",
      "name": "OAuth 2.0 authentication backend",
      "description": "Implementation of OAuth 2.0 flows with JWT-based session management, multi-tenant token isolation, and rate limiting per client.",
      "tech_stack": ["ruby_on_rails", "postgresql", "redis"],
      "estimated_hours": 120,
      "complexity": "high",
      "dependencies": []
    }
  ]
}
```

Si el alumno dispone de su propio dataset de la Sesión 6 con este mismo esquema, puede usarlo; en caso contrario se trabaja con la muestra proporcionada.

**Pasos de implementación:**

1. **Estructura y dependencias.** Crear dentro del servicio IA el árbol app/embedding_pipeline/ con __init__.py, chunker.py, embedder.py, schemas.py y router.py, además de scripts/compare.py y data/budgets_sample.json. Añadir al pyproject.toml las dependencias openai (>=1.0.0) y tiktoken (>=0.7.0) si no estuvieran ya presentes desde la Sesión 1, y reconstruir el contenedor. No se añaden numpy ni scikit-learn: la similitud coseno se implementa a mano con la biblioteca estándar de Python.

2. **Modelos Pydantic (schemas.py).** Definir, siguiendo el estilo Pydantic v2 usado en sesiones anteriores: BudgetComponent (con todos los campos del componente), Budget (con client_metadata, project_summary, main_technology, year, total_estimated_hours y su lista de componentes), Chunk (chunk_id, text, metadata, token_count), EmbeddedChunk (Chunk más el campo embedding como lista de floats), IngestRequest (una lista de Budget) e IngestResponse (una lista de EmbeddedChunk más un diccionario stats con total_budgets, total_chunks, total_tokens y estimated_cost_usd). Nombres en inglés, con validadores explícitos donde aporten valor, por ejemplo sector como Literal cerrado si el universo de valores es conocido.

3. **Chunker estructural (chunker.py).** Clase JSONStructuralChunker con un único método público chunk(budgets) que devuelve una lista de Chunk. Reglas: granularidad de un componente por chunk; el texto embebible combina un header de contexto del presupuesto padre (resumen del proyecto, sector, año, tecnología principal) con los campos propios del componente (nombre, descripción, stack, complejidad, horas estimadas); la metadata no embebida incluye como mínimo budget_id, component_id, client_sector, main_technology, year, complexity y estimated_hours; el chunk_id sigue el formato {budget_id}::{component_id}; el token_count se calcula con tiktoken.encoding_for_model usando "text-embedding-3-small". No se implementa overlap ni fixed-size splitting de descripciones largas: se confía en que un componente cabe como chunk individual, y cualquier descripción anormalmente larga se deja como dato a discutir en la sesión en vivo.

4. **Embedder (embedder.py).** Clase OpenAIEmbedder con dos métodos públicos: embed_one(text) que devuelve un vector, y embed_many(chunks) que devuelve una lista de EmbeddedChunk. Usa text-embedding-3-small con la dimensión por defecto (1536; la discusión sobre Matryoshka queda para el directo). embed_many debe agrupar los chunks en lotes de referencia de 100 elementos por llamada en lugar de llamar a la API una vez por chunk. Debe manejar el error de rate limit con reintento exponencial simple (tres reintentos con esperas de 1, 2 y 4 segundos) y propagar el resto de errores. Cada lote procesado se registra con structlog (número de chunks, tokens totales, latencia). El coste estimado se calcula como una constante de módulo claramente etiquetada: 0.02 dólares por millón de tokens de entrada para text-embedding-3-small, precio de referencia de mayo de 2026 sujeto a cambios.

5. **Endpoint FastAPI (router.py).** POST /embeddings/ingest recibe un IngestRequest y devuelve un IngestResponse. El handler orquesta chunker.chunk(budgets), luego embedder.embed_many(chunks), y por último construye la respuesta con sus estadísticas agregadas. Códigos de estado: 200 en éxito, 422 en fallo de validación Pydantic (gestionado automáticamente por FastAPI), 500 con mensaje genérico al cliente y detalle en logs si falla la llamada a la API de embeddings. El router se registra en el main.py del servicio IA bajo el prefijo /embeddings, y debe quedar visible e invocable desde /docs (Swagger UI).

6. **Script CLI (scripts/compare.py).** Recibe dos textos por línea de comandos (--text-a y --text-b), los embebe reutilizando OpenAIEmbedder, calcula la similitud coseno a mano (producto escalar dividido por el producto de las normas, sin numpy) e imprime ambos textos junto al valor de similitud. Debe poder ejecutarse tanto dentro del contenedor como fuera de él cargando el .env. Documentar ambas formas de ejecución en el README del servicio.

7. **Validación con tres pares de texto (embedding_pipeline/SANITY_CHECK.md).** Ejecutar compare.py sobre exactamente estos tres pares y documentar los resultados:
   - Par A, textos cercanos, similitud esperada orientativamente mayor a 0.6: "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" frente a "Authorization service using JSON Web Tokens for a banking application".
   - Par B, textos no relacionados, similitud esperada orientativamente menor a 0.4: "OAuth 2.0 authentication backend with JWT tokens for fintech mobile app" frente a "Database migration from MySQL to PostgreSQL with zero downtime".
   - Par C, textos genéricos y ambiguos, sin expectativa fija, para comentar el resultado: "Backend services" frente a "API development".

   El SANITY_CHECK.md debe incluir los tres valores numéricos obtenidos y un comentario breve (3 a 5 líneas) sobre si el resultado coincide con la intuición y qué llama la atención. No es una validación formal de calidad de retrieval, sino la comprobación mínima de que el pipeline funciona de extremo a extremo.

**Entregable.** Una rama nueva llamada session-07/pre-exercise en el repositorio "estimator" del alumno, que contenga: el módulo embedding_pipeline/ completo (chunker.py, embedder.py, schemas.py, router.py, __init__.py), el script scripts/compare.py funcional, el endpoint POST /embeddings/ingest registrado y visible en /docs, el fichero embedding_pipeline/SANITY_CHECK.md con los tres resultados y su comentario, el README del servicio actualizado con las instrucciones de ejecución del endpoint y de compare.py dentro y fuera de contenedor, y el pyproject.toml actualizado con las dependencias nuevas. No se exigen tests automatizados en esta entrega.

**Cómo entregar.** Enviar por correo el enlace completo a la rama (GitHub, GitLab o el servicio usado) con al menos dos días de antelación a la sesión en vivo, asegurándose de que el repositorio sea accesible para el revisor. No se aceptan entregas por capturas, documentos sueltos ni mensajes de chat.

## Checklist antes de la siguiente sesión

- Entiendes qué es un embedding, cómo emerge su geometría semántica del entrenamiento contrastivo, y qué mide cada una de las tres métricas de similitud (coseno, producto escalar, distancia euclidiana).
- Sabes aplicar los cinco criterios de selección de modelo de embeddings (dimensionalidad, idioma, dominio, hosting/coste, licencia) a un caso real, y puedes argumentar por qué text-embedding-3-small es la elección del proyecto.
- Entiendes qué es Matryoshka Representation Learning y cuándo truncar dimensiones aporta valor frente a cuándo es prematuro.
- Conoces las doce estrategias de chunking organizadas en las cuatro familias (mecánicas, estructurales, semánticas, avanzadas/contextuales) y tienes un criterio para elegir cada una según el tipo de documento.
- Entiendes por qué los contextual chunk headers y Contextual Retrieval son las palancas de mayor impacto documentado sobre la calidad de recuperación.
- Sabes diseñar un chunker estructural específico para JSON jerárquico (presupuestos) y un segmentador por temas para texto conversacional sin estructura (transcripciones).
- Tienes claro qué información va en el texto embebido de un chunk y cuál va en su metadata no embebida, y por qué a veces la misma información debe ir en ambos sitios.
- Tienes tu pipeline mínimo de embeddings y chunking funcionando de extremo a extremo, con su SANITY_CHECK.md completado sobre los tres pares de validación.

## Documentación de referencia

- OpenAI Embeddings API: https://platform.openai.com/docs/guides/embeddings
- tiktoken: https://github.com/openai/tiktoken
- Sentence Transformers: https://www.sbert.net/
- LangChain Text Splitters: https://python.langchain.com/docs/how_to/#text-splitters
- LlamaIndex Node Parsers: https://docs.llamaindex.ai/
- MTEB Leaderboard: https://huggingface.co/spaces/mteb/leaderboard
- Anthropic — Contextual Retrieval: https://www.anthropic.com/news/contextual-retrieval
- Jina AI — Late Chunking: https://jina.ai/news/late-chunking-in-long-context-embedding-models/
- Cohere Embed: https://docs.cohere.com/docs/embeddings
- Voyage AI: https://docs.voyageai.com/
- BAAI/bge-m3: https://huggingface.co/BAAI/bge-m3
- pgvector: https://github.com/pgvector/pgvector
- Pydantic: https://docs.pydantic.dev/
- FastAPI: https://fastapi.tiangolo.com/
- structlog: https://www.structlog.org/
