# Sesión 8 — Bases de datos vectoriales

## Objetivo de la sesión

Al cerrar la Sesión 7 el servicio IA cuenta con un pipeline de embeddings funcional: los presupuestos históricos se dividen en chunks y cada chunk se convierte en un vector de 1536 dimensiones con `text-embedding-3-small`. El problema es que esos vectores viven únicamente en la memoria del proceso: se pierden al reiniciar el contenedor, no hay forma de consultarlos entre réplicas distintas y cualquier búsqueda de similitud implica recorrer a mano, con NumPy, todo el corpus.

La Sesión 8 cierra el Módulo 3 (Data-driven AI) resolviendo exactamente ese hueco: dota al servicio IA de una capa de datos vectorial persistente, concurrente y transaccional, construida sobre PostgreSQL + pgvector. El foco de la sesión no es todavía la recuperación aplicada a RAG (eso se trabaja en las sesiones 9 y 10, dedicadas por completo a retrieval); el foco es entender qué ocurre dentro de la base de datos antes de que cualquier consulta la toque: por qué existe esta categoría de software, qué opciones hay en el mercado en 2026, cómo funcionan por dentro los índices de búsqueda aproximada (ANN), cómo se diseña el esquema relacional que sostiene todo el sistema y qué separa un prototipo de una capa de datos vectorial lista para producción.

Al final de la sesión, el servicio IA persiste cada presupuesto ingerido como un documento con sus chunks asociados en PostgreSQL, y expone un endpoint de búsqueda semántica que resuelve la consulta mediante una query SQL con `ORDER BY embedding <=> :query`, todavía sin índice vectorial (esa pieza se añade en el directo).
## Qué vas a aprender

### 1. 📄 Por qué existen las BBDD vectoriales y cuándo realmente las necesitas — 31 min

Parte del estado real del pipeline de la Sesión 07: los vectores viven en memoria, no hay persistencia entre reinicios y una búsqueda de similitud implica recorrer el corpus entero calculando distancias con NumPy (búsqueda exacta o KNN). Ese enfoque es válido a pequeña escala pero deja de serlo cuando el volumen crece, porque el coste de comparar la consulta contra cada vector almacenado es lineal. La alternativa es la búsqueda aproximada (ANN, *approximate nearest neighbors*): estructuras de datos especializadas (grafos navegables, particiones del espacio, cuantización) que sacrifican una fracción mínima de recall a cambio de pasar de una complejidad lineal a otra logarítmica o casi constante.

El artículo identifica cuatro propiedades que un array en memoria no aporta y que justifican añadir una base de datos vectorial al stack: persistencia, concurrencia entre réplicas, consultas combinadas con datos relacionales (filtros por sector, fecha, importe) y garantías transaccionales (ACID) al ingerir un documento con todos sus chunks. También fija tres umbrales orientativos para decidir *cuándo* dar ese paso: por debajo de unos 10.000 vectores un array en memoria sigue siendo razonable; entre 10.000 y 50 millones una base de datos vectorial es la respuesta correcta (el rango en el que cae el proyecto del programa); por encima de 100 millones entran en juego consideraciones de sharding y almacenamiento en disco que quedan fuera del alcance de esta sesión.

### 2. 📄 Estado del mercado de BBDD vectoriales 2026 — 40 min

Mapea las cinco opciones que dominan los despliegues de producción en 2026 — pgvector, Qdrant, Weaviate, Milvus y Pinecone — y las compara según cuatro ejes operativos: modelo operativo (self-hosted vs. managed), escala práctica soportada, funcionalidades nativas (búsqueda híbrida, filtrado por metadata, soporte multimodal) y modelo de coste real (factura + operación + coste de una futura migración).

La decisión que queda fijada (*locked*) para el proyecto del programa es **pgvector**, por cuatro motivos: alineamiento con el stack de negocio (Ruby on Rails + PostgreSQL), simplicidad de los joins transaccionales entre búsqueda vectorial y datos relacionales, disponibilidad de búsqueda híbrida nativa vía `tsvector`/`ts_rank`, y una escala esperada del proyecto (decenas o cientos de miles de vectores) muy por debajo de cualquier techo plausible de la extensión. El artículo también documenta honestamente cuándo esa misma decisión dejaría de ser correcta: volúmenes sostenidos por encima de 50 millones de vectores, necesidad de match exacto sobre identificadores como eje central del producto, ausencia de experiencia operando PostgreSQL, requisitos de distribución multi-región con SLA estricto, o embeddings multimodales como ciudadanos de primera clase.

### 3. 📄 Anatomía de un índice vectorial: HNSW, IVFFlat y el horizonte de DiskANN — 40 min

Abre la caja negra de los índices ANN que pgvector expone. **IVFFlat** particiona el espacio vectorial en celdas mediante *k-means* (parámetro `lists`) y, en cada consulta, restringe la búsqueda a las celdas más próximas (parámetro `probes`); es rápido de construir y ligero en memoria, pero necesita entrenamiento previo y se degrada de forma silenciosa a medida que se insertan vectores nuevos. **HNSW** construye en su lugar un grafo multicapa navegable —una jerarquía de "autopistas" a "calles locales"— que no necesita entrenamiento, absorbe inserciones de forma incremental y mantiene un recall alto de forma consistente, a costa de un mayor consumo de memoria; se gobierna con tres parámetros: `m` (conexiones por nodo, build-time), `ef_construction` (calidad de construcción, build-time) y `ef_search` (calidad de búsqueda, query-time, el que se tunea empíricamente). **DiskANN** —disponible en PostgreSQL vía la extensión `pgvectorscale`— es el horizonte para escalas que ya no caben en RAM: mantiene una versión comprimida del grafo en memoria y solo lee de SSD los vectores completos cuando hace falta comparar distancias finales.

Para el proyecto del programa, la elección de partida es **HNSW con `m = 16`, `ef_construction = 128` y `ef_search = 40`**. El artículo cierra con una advertencia operativa central que se retoma en el artículo siguiente: el índice se construye con una *operator class* concreta (coseno, L2 o producto interno) y solo acelera las consultas que usan el operador correspondiente; cualquier desalineamiento hace que PostgreSQL caiga a *sequential scan* sin emitir ningún error.

### 4. 📄 Diseño del esquema y búsqueda semántica — 32 min

Aterriza el modelo relacional concreto del proyecto: dos tablas, `documents` y `chunks`, relacionadas uno-a-muchos con `ON DELETE CASCADE`, en lugar de una única tabla que duplicaría la metadata del documento en cada chunk. La metadata estable y consultable de forma estructurada (tipo de documento, tipo de chunk, fechas) vive en columnas tipadas; la metadata variable que el chunker puede enriquecer (sector, tecnologías, scope) vive en una columna `JSONB` con un índice `GIN`. El embedding se tipa como `vector(1536)`, la dimensionalidad de `text-embedding-3-small`, deliberadamente hardcodeada porque cambiarla implicaría reembedear todo el corpus.

Explica las tres métricas de distancia que expone pgvector —coseno (`<=>`), euclídea o L2 (`<->`) e inner product negado (`<#>`)— y por qué, al estar los embeddings de OpenAI normalizados, coseno e inner product son matemáticamente equivalentes en el orden de resultados; el proyecto usa coseno por convención y por robustez ante un futuro cambio de modelo de embeddings. El núcleo operativo del artículo es el antipatrón silencioso: si el índice se construye con `vector_cosine_ops` y la query usa `<->`, PostgreSQL ignora el índice sin avisar y el rendimiento se degrada varios órdenes de magnitud; `EXPLAIN ANALYZE` (buscando `Index Scan` frente a `Seq Scan`) es la herramienta para detectarlo. Cierra con el ejemplo de una query atómica que combina búsqueda vectorial, filtros JSONB y un `JOIN` relacional en una sola sentencia SQL con garantías ACID.

### 5. 📄 Del prototipo a producción: tuning, monitorización y techo de pgvector — 40 min

Cubre lo que separa el ejercicio pre-sesión de un sistema en producción real. La regla central: el rendimiento de un índice HNSW depende sobre todo de si cabe en memoria, lo que lleva a dimensionar `shared_buffers` (~25% de la RAM), `effective_cache_size` (~75% de la RAM) y `work_mem`, y a subir `maintenance_work_mem` (y usar `CREATE INDEX CONCURRENTLY`) al construir índices grandes. Introduce `halfvec`, la cuantización de media precisión (16 bits por dimensión) que reduce a la mitad el almacenamiento del índice manteniendo más del 99% del recall sobre embeddings normalizados, recomendada desde el primer día en cualquier proyecto serio.

Describe la monitorización operativa con `pg_stat_user_indexes` (uso del índice), `pg_stat_statements` (latencia por query) y el ciclo de mantenimiento `VACUUM ANALYZE` / `REINDEX INDEX CONCURRENTLY` / `ANALYZE`. Cierra con tres señales objetivas y medibles para saber cuándo pgvector ha llegado a su techo en un caso concreto: el índice ya no cabe en memoria (>~70% de la RAM disponible), la latencia p99 supera el SLO de forma sostenida a pesar del tuning, o el producto necesita funcionalidades nativas (multimodalidad, sharding multi-región) que pgvector no ofrece.
## Ejercicios prácticos

### ✍️ Ejercicio — Migración a pgvector + endpoint de búsqueda

**Fecha límite indicada por el programa:** martes 12 de julio, final del día.

**Objetivo.** Persistir el pipeline de embeddings construido en la Sesión 07 en PostgreSQL + pgvector y exponer un endpoint de búsqueda semántica funcional sobre los presupuestos históricos. Al terminar, el servicio IA debe: levantar un Postgres con pgvector como dependencia declarada del proyecto; tener un esquema relacional propio (tablas `documents` y `chunks`) gestionado con migraciones Alembic; persistir cada presupuesto ingerido como un `document` con sus chunks correspondientes (cada uno con su embedding) en una sola transacción; y resolver una consulta semántica vía SQL devolviendo los `k` chunks más cercanos por distancia coseno.

**Contexto de partida.** El servicio IA (Python + FastAPI) ya tiene, desde la Sesión 07, un `chunker.py` que parte cada presupuesto JSON en chunks por componente, un `embedder.py` que llama a `text-embedding-3-small` (1536 dimensiones) y un endpoint `POST /embeddings/ingest` que hoy devuelve los vectores en la respuesta HTTP sin persistir nada. Este ejercicio sustituye ese almacenamiento en memoria por PostgreSQL + pgvector.

**Qué SÍ entra en el alcance de este ejercicio:**
- Levantar PostgreSQL con la extensión pgvector vía Docker Compose.
- Esquema relacional con dos tablas (`documents`, `chunks`) gestionado con Alembic (migraciones async).
- Refactor de `POST /embeddings/ingest` para persistir documento + chunks + embeddings en una única transacción.
- Nuevo endpoint `POST /search` que resuelve una búsqueda semántica por distancia coseno.
- Un script `query_examples.py` que ejercita el endpoint de búsqueda con cinco queries representativas.

**Qué NO entra (se trabaja en la sesión en vivo, no adelantarlo):**
- Índices vectoriales (HNSW, IVFFlat). El sequential scan es el baseline contra el que se mide el impacto del índice en directo.
- Filtros por metadata (por ejemplo, filtrar por `chunk_type` o por claves dentro del JSONB `metadata`).
- Búsqueda híbrida (full-text search + vector).
- Tuning de parámetros (`shared_buffers`, `maintenance_work_mem`, `ef_search`); se usan los defaults durante todo el ejercicio.

**Stack y dependencias nuevas** (añadir al `pyproject.toml` del servicio IA):
```toml
sqlalchemy>=2.0
asyncpg>=0.29
pgvector>=0.3
alembic>=1.13
```
`asyncpg` es el driver async recomendado por SQLAlchemy 2.0 para Postgres. El paquete `pgvector` registra el tipo `vector` en SQLAlchemy y expone los operadores de distancia (`l2_distance`, `cosine_distance`, `max_inner_product`) como métodos del ORM.

#### Paso 1 — PostgreSQL con pgvector en `docker-compose.yml`

Usar la imagen oficial `pgvector/pgvector:pg16` (PostgreSQL 16 con la extensión `vector` precompilada):
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: estimator
      POSTGRES_USER: estimator
      POSTGRES_PASSWORD: estimator
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U estimator -d estimator"]
      interval: 5s
      timeout: 5s
      retries: 10

  ai_service:
    # ... configuración existente ...
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://estimator:estimator@postgres:5432/estimator

volumes:
  postgres_data:
```
Verificar antes de continuar:
```bash
docker compose up postgres
docker compose exec postgres psql -U estimator -d estimator -c "SELECT version();"
```
Si esto no funciona, no avanzar al paso siguiente.

#### Paso 2 — Configurar Alembic en el servicio IA

Inicializar Alembic con plantilla async:
```bash
docker compose run --rm ai_service alembic init -t async alembic
```
Configurar `alembic.ini` y `alembic/env.py` para tomar la URL de conexión desde `DATABASE_URL` y para reconocer el tipo `vector` de pgvector (sin esto, `alembic check` no detecta correctamente las columnas `vector`). Dentro de `do_run_migrations`:
```python
import pgvector.sqlalchemy

def do_run_migrations(connection):
    connection.dialect.ischema_names["vector"] = pgvector.sqlalchemy.Vector
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()
```

#### Paso 3 — Esquema de base de datos (migración inicial)

Los nombres de columnas son los que esperan los pasos siguientes; si se cambian, hay que ajustar el resto del código en consecuencia.
```python
# alembic/versions/0001_initial_schema.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", postgresql.JSONB,
                  server_default="{}", nullable=False),
    )
    op.create_index("ix_documents_source_path", "documents", ["source_path"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("document_id", sa.BigInteger,
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", postgresql.JSONB,
                  server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_chunk_type", "chunks", ["chunk_type"])
    op.create_index("ix_chunks_metadata_gin", "chunks", ["metadata"],
                    postgresql_using="gin")
```
Ejecutar la migración:
```bash
docker compose run --rm ai_service alembic upgrade head
```

**Decisiones de schema a justificar en el README del proyecto** (se defenderán en directo):
- **Dos tablas en vez de una.** Un presupuesto produce N chunks; una sola tabla duplicaría la metadata del documento en cada fila y perdería integridad referencial. Con `ON DELETE CASCADE`, eliminar un documento elimina automáticamente sus chunks.
- **`metadata` JSONB en ambas tablas.** La metadata estable (tipo de documento, tipo de chunk, fechas) va en columnas tipadas; la metadata variable o enriquecible por el chunker (tags, scope, tecnologías) va en JSONB con índice GIN, para poder consultar por claves arbitrarias sin migrar el schema cada vez.
- **`vector(1536)`.** Dimensionalidad de `text-embedding-3-small`, hardcodeada deliberadamente porque cambiarla implicaría reembedear todo el corpus.
- **`embedding` nullable.** Permite crear un chunk y rellenar su embedding después si el cálculo fallase (no se usa así en este ejercicio, pero deja la puerta abierta a ingesta asíncrona en sesiones posteriores).
- **Sin índice vectorial.** Deliberado: el directo lo añade y mide su impacto empíricamente.

#### Paso 4 — Refactorizar `POST /embeddings/ingest`

El endpoint pasa de devolver chunks+vectores en la respuesta a persistirlos en una transacción y devolver solo identificadores y métricas de la ingesta.

Request:
```json
{
  "source_path": "data/budgets/budget_2024_q1_fintech.json",
  "document_type": "historical_budget",
  "content": { "...": "JSON completo del presupuesto, tal cual viene del chunker" }
}
```
Response `200 OK`:
```json
{
  "document_id": 42,
  "chunks_created": 17,
  "embedding_dimension": 1536,
  "ingestion_time_ms": 1240
}
```
Response `409 Conflict` si ya existe un documento con ese `source_path`:
```json
{
  "detail": "Document already ingested",
  "document_id": 42
}
```
Implementación, dentro de una sola sesión async de SQLAlchemy: (1) verificar que no existe ya un documento con ese `source_path`; (2) crear la fila en `documents`; (3) ejecutar el chunker estructural sobre el JSON; (4) llamar al embedder por lotes (un único `embeddings.create` con un array de inputs, nunca chunk a chunk); (5) crear todas las filas en `chunks` con `add_all`; (6) commit. La transacción única garantiza que un fallo del embedder no deja documentos huérfanos sin chunks.

#### Paso 5 — Nuevo endpoint `POST /search`

Request:
```json
{
  "query": "REST API with OAuth authentication for fintech sector",
  "k": 5
}
```
Response:
```json
{
  "query": "REST API with OAuth authentication for fintech sector",
  "k": 5,
  "search_time_ms": 87,
  "results": [
    {
      "chunk_id": 156,
      "document_id": 12,
      "chunk_type": "budget_component",
      "content": "Backend service implementation with JWT-based authentication...",
      "distance": 0.231,
      "metadata": { "scope": "backend", "technologies": ["python", "fastapi"] }
    }
  ]
}
```
Implementación: embedear la query con el mismo modelo usado en ingesta (`text-embedding-3-small`) y ejecutar vía SQLAlchemy:
```python
from sqlalchemy import select

stmt = (
    select(
        Chunk.id,
        Chunk.document_id,
        Chunk.chunk_type,
        Chunk.content,
        Chunk.metadata,
        Chunk.embedding.cosine_distance(query_vector).label("distance"),
    )
    .order_by(Chunk.embedding.cosine_distance(query_vector))
    .limit(k)
)
result = await session.execute(stmt)
```
Se usa `cosine_distance` (operador `<=>`) porque los embeddings de OpenAI están normalizados (coseno e inner product serían equivalentes en el orden de resultados) y porque, cuando en el directo se añada el índice HNSW con `vector_cosine_ops`, operador de consulta y operator class del índice quedarán alineados desde el principio. Un desalineamiento entre ambos hace que PostgreSQL ignore el índice silenciosamente y caiga a sequential scan sin avisar.

**Nota de rendimiento.** En esta fase no hay índice vectorial: PostgreSQL hace sequential scan completo. Para el volumen del corpus de ejemplo (decenas de documentos, cientos de chunks) esto es aceptable y el endpoint responde en pocos cientos de milisegundos; observar esa latencia sin índice es justamente uno de los puntos de partida del directo.

#### Paso 6 — Script `query_examples.py`

Reemplaza el `compare.py` de la Sesión 07 (que medía similitud entre pares de textos sueltos) por un script que invoca el endpoint `/search` con cinco queries representativas y formatea los resultados. Las cinco queries deben ejercitar el dataset desde ángulos distintos:

1. **Componente directo conocido** — sanity check con match casi perfecto esperado. Ejemplo: *"REST API development with JWT authentication for financial sector"*.
2. **Reformulación semántica** — misma idea, vocabulario distinto al del corpus. Ejemplo: *"secure backend service with token-based access control for banking applications"*.
3. **Dominio distinto** — algo que no debería estar en el corpus, distancia alta esperada. Ejemplo: *"mobile application for restaurant reservations"*.
4. **Consulta ambigua** — corta y genérica. Ejemplo: *"integration with external system"*.
5. **Consulta muy específica** — vocabulario técnico preciso. Ejemplo: *"migration from monolith to microservices architecture using Kubernetes"*.

Para cada query, imprimir el top-5 de resultados con: `chunk_id`, `distance` (4 decimales), `chunk_type` y los primeros ~120 caracteres del `content`. Formato libre, pero legible en terminal.

#### Entregable

Repositorio que contenga:
- `docker-compose.yml` actualizado con el servicio `postgres`.
- Migración Alembic con la creación del schema (extensión + dos tablas + índices no vectoriales).
- Endpoint `POST /embeddings/ingest` refactorizado para persistir, con manejo del caso de documento duplicado.
- Endpoint `POST /search` nuevo y funcional.
- Script `query_examples.py` ejecutable con `docker compose run --rm ai_service python query_examples.py`.
- Archivo `output_examples.txt` con el output del script ejecutado contra el corpus de ejemplo del programa.
- Sección nueva en el README del proyecto (máximo una página) justificando: (a) por qué dos tablas y no una, (b) por qué `metadata` como JSONB en lugar de columnas, (c) por qué `cosine_distance` y no L2 ni inner product, (d) por qué deliberadamente no hay índice vectorial todavía.

#### Cómo entregar

Enviar por correo a `george@lidr.co` el enlace completo a la rama (GitHub, GitLab o el servicio usado), asegurándose de que sea accesible para el revisor. El plazo es estricto: el equipo del programa necesita margen para revisar las entregas y preparar el material del directo según los problemas reales encontrados. Si no se llega a la sesión con la entrega hecha, se puede seguir el directo igualmente, pero los bloques hands-on asumirán que el pipeline básico ya funciona.

## Checklist antes de la siguiente sesión

- [ ] Entiendes la diferencia entre búsqueda exacta (KNN) y búsqueda aproximada (ANN), y por qué la segunda es necesaria a partir de cierta escala.
- [ ] Sabes justificar, con criterio operativo, cuándo añadir una base de datos vectorial al stack y cuándo es *over-engineering* hacerlo.
- [ ] Conoces el mapa del mercado 2026 (pgvector, Qdrant, Weaviate, Milvus, Pinecone) y puedes argumentar por qué el programa fija pgvector como decisión para este proyecto.
- [ ] Entiendes la intuición geométrica de IVFFlat (particionamiento por clusters) y de HNSW (grafo multicapa navegable), y qué controla cada uno de sus parámetros (`lists`/`probes`, `m`/`ef_construction`/`ef_search`).
- [ ] Sabes diseñar un esquema relacional de dos tablas (`documents`/`chunks`) con metadata tipada + JSONB para un sistema RAG sobre datos empresariales.
- [ ] Conoces las tres métricas de distancia de pgvector (`<=>`, `<->`, `<#>`) y por qué la elección importa incluso cuando los resultados son equivalentes en el ranking.
- [ ] Puedes explicar el antipatrón del desalineamiento operador/operator class y cómo detectarlo con `EXPLAIN ANALYZE`.
- [ ] Entiendes por qué el sizing de memoria (`shared_buffers`, `effective_cache_size`, `maintenance_work_mem`) determina el rendimiento de un índice HNSW más que cualquier otro parámetro.
- [ ] Conoces `halfvec` como técnica de cuantización recomendada por defecto para producción.
- [ ] Sabes qué mirar para monitorizar un índice vectorial en producción (`pg_stat_user_indexes`, `pg_stat_statements`) y el ciclo de mantenimiento (`VACUUM`, `REINDEX`, `ANALYZE`).
- [ ] Tienes tu servicio IA persistiendo documentos y chunks en PostgreSQL + pgvector, con `POST /embeddings/ingest` y `POST /search` funcionando de extremo a extremo.

## Documentación de referencia

- pgvector (extensión oficial): https://github.com/pgvector/pgvector
- pgvectorscale (DiskANN para PostgreSQL): https://github.com/timescale/pgvectorscale
- PostgreSQL — EXPLAIN: https://www.postgresql.org/docs/current/using-explain.html
- PostgreSQL — pg_stat_statements: https://www.postgresql.org/docs/current/pgstatstatements.html
- SQLAlchemy 2.0 (Async ORM): https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic (migraciones): https://alembic.sqlalchemy.org/
- asyncpg: https://magicstack.github.io/asyncpg/
- Qdrant: https://qdrant.tech/documentation/
- Weaviate: https://weaviate.io/developers/weaviate
- Milvus: https://milvus.io/docs
- Pinecone: https://docs.pinecone.io/
- OpenAI Embeddings API: https://platform.openai.com/docs/guides/embeddings
- FastAPI: https://fastapi.tiangolo.com/
- Docker Compose: https://docs.docker.com/compose/