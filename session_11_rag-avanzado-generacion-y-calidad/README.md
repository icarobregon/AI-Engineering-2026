# Sesión 11 — RAG Avanzado: Generación y calidad

## Objetivo de la sesión

Al cierre de las sesiones 9 y 10, el pipeline de recuperación del sistema de estimaciones ya funciona con solidez: reformula la consulta, combina búsqueda vectorial y léxica, aplica reranking, expansión, routing multi-índice y filtrado temporal antes de ensamblar el contexto. La Sesión 11 se ocupa de lo que viene después de recuperar: cómo preparar ese contexto para el modelo generador, cómo combinar presupuestos históricos que se contradicen, cómo hacer que cada cifra de la estimación señale de forma verificable a su fuente, cómo detectar y frenar alucinaciones antes de que lleguen al usuario, cómo mantener sano el índice vectorial a largo plazo, y cómo medir con números objetivos si el sistema mejora o empeora con cada cambio.

El hilo que conecta las seis lecciones es la trazabilidad: pasar de un sistema que genera una cifra plausible a uno donde cada cifra puede defenderse, auditarse y, cuando no hay suficiente evidencia, abstenerse de inventar. Al final de la sesión, el servicio de estimación cita a nivel de línea, verifica sus propias afirmaciones contra las fuentes recuperadas, sabe cuándo decir que no dispone de datos suficientes en lugar de mentir con confianza, versiona su índice de embeddings para no degradarse en silencio, y dispone de una batería de métricas RAGAS que convierte una impresión subjetiva en una tabla de números comparables entre versiones.

**Pre-work de la sesión:** citación verificable a nivel de línea + evaluación RAGAS básica sobre un golden set extendido. La tabla de métricas y el informe de verificación de citaciones son el punto de partida del directo.

## Qué vas a aprender

### 1. 📄 Content augmentation: preparar el contexto recuperado antes de generar — 19 min

Aborda la capa que vive entre la recuperación y la generación: convertir fragmentos de presupuestos crudos (con cabeceras, condiciones de pago y secciones irrelevantes) en evidencia destilada y ordenada. Explica por qué el ruido en el contexto resulta caro en tres frentes: tokens de más, atención del modelo mal repartida y mayor riesgo de alucinación. Propone un pipeline componible en tres etapas: compresión (extractiva, sin llamada a modelo y por tanto incapaz de inventar nada; o abstractiva, más flexible pero con el riesgo de introducir un segundo punto de generación), extracción de puntos clave con un esquema estricto que admite un valor vacío honesto en vez de una cifra inventada, y ordenación cargando los extremos del bloque de contexto, porque la atención del modelo no es uniforme. Cierra explicando cuándo la compresión abstractiva sale más cara que barata y por qué cada etapa que descarta información debe dejar constancia de qué descartó.

### 2. 📄 Síntesis de múltiples presupuestos: combinar fuentes que se contradicen — 19 min

Ataca el problema que la augmentation por sí sola no resuelve: varios presupuestos históricos, todos relevantes, que dan cifras distintas para el mismo componente. Descarta las salidas fáciles y poco fiables (promediar sin explicar, quedarse con la primera fuente, inventar un número intermedio) en favor de entender por qué discrepan las fuentes y producir un rango honesto con una razón auditable. Introduce la ponderación de fuentes por relevancia, recencia y similitud con coeficientes que deben poder justificarse en una frase, la separación entre un ancla determinista calculada en código (mediana ponderada, dispersión, señal de contradicción) y el razonamiento del modelo sobre esos agregados, y un formato de salida que obliga a cada componente a llevar un rango, una razón y las fuentes que lo respaldan. Termina señalando que combinar varias fuentes en cada cifra complica todavía más una pregunta clave: de dónde sale exactamente cada número.

### 3. 📄 Citación y atribución verificable — 19 min

Convierte los identificadores de fragmento sueltos en citaciones verificables de verdad, con tres propiedades comprobables: que resuelven a una fuente real, que localizan la línea exacta que respalda la afirmación, y que son trazables hasta el documento original respetando el control de acceso correspondiente. Presenta un modelo de citación con su localizador de línea, una verificación de integridad referencial que detecta citas colgantes en código (nunca confiada al criterio del modelo), y la separación entre estructura de datos y presentación (marcadores en línea, notas al pie, enlaces), con una frontera de responsabilidad clara: el servicio de IA emite identificadores neutros y es la capa de negocio la que resuelve permisos y enlaces reales. Cierra advirtiendo que la integridad referencial confirma que la fuente existe, pero no que diga lo que la estimación afirma que dice: esa alucinación con coartada es el tema del siguiente artículo.

### 4. 📄 Detección y mitigación de alucinaciones — 21 min

Distingue tres formas de alucinar en una estimación: fabricación (una cifra sin ninguna fuente), atribución falsa (una cifra real citando la fuente equivocada) y extrapolación no fundamentada (un salto lógico más allá de lo que las fuentes soportan). Propone detectarlas en capas de coste creciente: anclaje numérico (una comprobación aritmética barata que verifica si una cifra cae dentro del rango combinado de las fuentes citadas, permitiendo interpolación pero marcando la extrapolación), verificación semántica con un modelo juez distinto y más económico que el generador, instruido para dudar a favor de "no soportado", y consistencia por muestreo repetido (cara, reservada a líneas críticas, con la trampa de confundir incertidumbre honesta con invención). La mitigación combina prevención en el prompt, una validación post-generación graduada y la abstención como salida legítima: reconocer que faltan datos suficientes es preferible a inventar una cifra que alguien usará para comprometer presupuesto y plazos.

### 5. 📄 Reindexación y versionado de embeddings — 17 min

Trata el ciclo de vida del índice vectorial como una fuente silenciosa de degradación: la deriva de contenido (un documento se corrige pero su vector sigue representando el texto antiguo) y la mezcla de versiones (comparar vectores de dos modelos de embeddings distintos como si vivieran en el mismo espacio, lo que produce una similitud numérica sin ningún significado real). La solución consiste en versionar cada vector con una clave que combina modelo, dimensión, normalización y configuración de preprocesamiento, garantizando que ninguna consulta cruce versiones. Distingue la reindexación incremental (barata, por documento, detectada mediante hash de contenido) de la migración de versión completa (costosa, con un patrón blue/green: construir el índice nuevo junto al activo, verificarlo, y solo entonces conmutar de forma atómica). Cierra señalando que mantener el índice sano evita una degradación accidental, pero no confirma que un cambio de modelo haya sido realmente una mejora: eso exige medir.

### 6. 📄 Evaluación de calidad con RAGAS — 19 min

Cierra el arco de la sesión con la disciplina de medir el sistema completo, no una respuesta aislada. Presenta las cuatro métricas de RAGAS agrupadas en dos parejas: fidelidad y relevancia de la respuesta miden la generación (si la respuesta se sostiene en el contexto entregado y si de verdad responde a la pregunta), mientras que precisión y exhaustividad del contexto miden la recuperación (si lo recuperado es relevante y si trajo todo lo necesario). Insiste en que el golden set marca el techo de la calidad de las métricas: un conjunto pequeño, sesgado o sin casos de abstención produce números confiados y vacíos de sentido. Distingue la evaluación offline como puerta de regresión antes de desplegar, de la monitorización en producción sobre tráfico real, que solo puede apoyarse en las métricas que no necesitan respuesta de referencia. Cierra con la advertencia de perseguir una sola métrica a costa de las demás: las cuatro deben leerse siempre juntas.

## Ejercicios prácticos

### ✍️ Ejercicio: RAG avanzado — generación y calidad

**Fecha límite:** domingo 23 de agosto, al final del día. Código en inglés (nombres, comentarios, logs, literales, prompts); la prosa de notas y el golden set pueden ir en español.

#### Contexto de partida

Tras las sesiones 9 y 10, el servicio de IA ya reformula la consulta, recupera con búsqueda híbrida, aplica reranking, expansión, routing multi-índice y filtrado temporal, y ensambla el contexto antes de generar. El generador estructurado de la Sesión 9 ya produce una estimación en JSON con citación obligatoria y una política de contexto insuficiente.

El problema que ataca este ejercicio: esa citación es gruesa (a nivel de estimación completa) y no verificable — nada garantiza que la fuente que el modelo dice haber usado exista de verdad en el contexto que se le pasó. Una citación que apunta a un presupuesto que nunca llegó al LLM no es una citación: es una alucinación con apariencia de rigor.

#### Objetivo del ejercicio

1. Que cada línea de la estimación (cada componente, por ejemplo "módulo de pagos" o "autenticación") referencie el presupuesto histórico concreto del que se derivó, de forma verificable a nivel de línea.
2. Detectar y rechazar citaciones colgantes: identificadores que apuntan a fuentes que no estaban en el contexto recuperado.
3. Medir la calidad de la generación con las cuatro métricas de RAGAS sobre un golden set propio.

#### Parte 1 — Citación verificable a nivel de línea

**1.1 Extender el esquema de salida.** El modelo Pydantic v2 de la estimación debe ampliarse para que cada línea transporte sus fuentes. El generador sigue usando la Responses API (`client.responses.parse`) con `text_format` estricto:

```python
class SourceReference(BaseModel):
    chunk_id: str        # id of the retrieved chunk supporting this line
    document_id: str     # historical budget document the chunk belongs to
    evidence: str         # verbatim span or figure from the source backing the line

class EstimateLineItem(BaseModel):
    component: str
    hours: float
    rationale: str
    grounded: bool                     # False => no sufficient source data
    sources: list[SourceReference]     # non-empty iff grounded is True
```

Regla de integridad a implementar (como validador o como verificación posterior): una línea con `grounded=True` debe tener al menos una fuente; una línea con `grounded=False` no puede inventar horas y debe marcarse explícitamente como sin datos suficientes.

**1.2 Forzar la atribución por línea en el prompt.** El prompt de generación debe instruir al modelo para que: atribuya cada línea a uno o más `chunk_id` del contexto que se le ha pasado (los chunks recuperados llegan identificados al ensamblador; hay que propagar esos ids al prompt); copie en `evidence` el fragmento o la cifra concreta que respalda la línea, en vez de parafrasear; y marque `grounded=False` cuando no encuentre soporte, en lugar de estimar a ojo.

**1.3 Verificar las citaciones tras la generación.** Una comprobación post-generación debe recorrer todas las líneas y confirmar que cada `chunk_id` citado existe en el conjunto de chunks recuperados que se entregó al LLM:

```python
def verify_citations(
    estimate: Estimate,
    retrieved_chunk_ids: set[str],
) -> CitationReport:
    """Flag any line whose cited chunk_id was never in the retrieved context."""
```

El informe debe distinguir, como mínimo: líneas correctamente fundamentadas, líneas con citación colgante (id inventado) y líneas marcadas como sin datos suficientes. Registrar el resultado con `structlog`, correlacionado por `request_id`. Una citación colgante es un fallo de calidad, no un detalle cosmético.

#### Parte 2 — Evaluación RAGAS básica

**2.1 Extender el golden set de la Sesión 10.** Partir de las 5 consultas ya construidas en el ejercicio de la Sesión 10. Para cada una, añadir una respuesta de referencia (`ground_truth`): la estimación correcta o esperada para esa transcripción, según el criterio de un experto.

**2.2 Configurar RAGAS.** Montar una evaluación que, para cada consulta, registre las cuatro entradas que RAGAS necesita y calcule las cuatro métricas:

```python
# Per query, RAGAS expects:
#   question     -> the estimation request
#   answer       -> the estimate your pipeline generated (as text)
#   contexts     -> the retrieved chunks passed to the generator
#   ground_truth -> the reference estimate from your extended golden set
#
# Metrics to compute:
#   faithfulness, answer_relevancy, context_precision, context_recall
```

RAGAS usa un LLM como juez y un modelo de embeddings para algunas métricas: configurarlo con la clave de OpenAI, `text-embedding-3-small` para los embeddings y el modelo de chat que se prefiera como juez. El corpus está en español; el juez evalúa en español sin problema.

**2.3 Producir la tabla de métricas.** Generar una tabla con una fila por consulta y una fila de promedio, con las cuatro métricas. Esta tabla es el baseline de calidad de generación que se lleva al directo, donde se extiende midiendo el efecto de la detección de alucinaciones y del pipeline de evaluación completo.

#### Entregables

- Código del schema extendido, el prompt de atribución por línea y la función `verify_citations` (en inglés).
- El golden set extendido con `ground_truth` por consulta.
- El script de evaluación RAGAS y la tabla de métricas (4 métricas × 5 consultas + promedio).
- Una nota breve (2–3 frases) con lo que más llame la atención de los números: ¿la fidelidad baja con citación gruesa?, ¿el context recall es flojo en alguna consulta?

#### Criterios de aceptación

- Cada línea con `grounded=True` cita al menos una fuente real del contexto recuperado.
- La verificación detecta una citación colgante si se introduce a propósito para probarla.
- Las líneas sin soporte se marcan como sin datos suficientes, no se rellenan con cifras inventadas.
- RAGAS devuelve las cuatro métricas para las cinco consultas y un promedio.

#### Qué traer al directo

- La tabla RAGAS (será el baseline que se extiende en vivo).
- El informe de verificación de citaciones sobre al menos una estimación real.
- La nota con los números más llamativos: se trabajará sobre ellos en el bloque de casos avanzados.

#### Nota sobre el stack

Python 3.11+, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, OpenAI Responses API (`client.responses.parse`), `structlog`, RAGAS. La verificación de citaciones es lógica del servicio de IA; si en la implementación de referencia el backend de negocio (Rails) consume la estimación citada, el contrato HTTP no cambia: solo se enriquece el cuerpo de la respuesta con las fuentes por línea.

#### Cómo entregar

Subir la rama `session-11/pre-work`, abrir el PR, y enviar por mail el enlace a la rama (URL completa de GitHub) hasta dos días antes de la sesión en vivo. El plazo es estricto: el equipo necesita margen para revisar las implementaciones, validar los golden sets y preparar el material de la sesión con los números reales obtenidos.

---

### 🛠️ Contexto técnico para la implementación

Material de referencia derivado de las lecciones de la sesión, pensado como contexto para implementar el ejercicio con Claude Code CLI.

#### Estructura de módulos propuesta

```
app/generation/rag/
├── augmentation/
│   ├── compress.py          # extractive / abstractive chunk compression
│   ├── extract.py           # key-point extraction into BudgetEvidence
│   ├── order.py              # edge-loading by relevance + recency
│   └── budget.py             # fit_to_budget (token budget enforcement)
├── synthesis/
│   ├── weighting.py          # combined_weight, source scoring
│   ├── aggregate.py          # weighted_median, contradiction detection
│   └── synthesize.py         # SynthesizedComponent / Estimate generation
├── citation/
│   ├── models.py              # Citation, SourceReference, EstimateLineItem
│   ├── resolve.py             # resolve_citation
│   └── verify_citations.py    # integrity check, no dangling citations
├── verification/
│   ├── numeric_grounding.py   # cheap deterministic anchor check
│   ├── judge.py                # verify_claim (LLM-as-judge)
│   └── gate.py                 # gate_line (grounded / insufficient / rejected)
├── indexing/
│   ├── versioning.py          # EmbeddingVersion, is_stale
│   └── reindex.py              # reindex_incremental, migrate_embedding_version
└── evaluation/
    ├── golden_set.json         # queries + ground_truth, versioned
    └── run_ragas.py             # build_eval_dataset, run_ragas
```
#### Modelos Pydantic clave (contexto acumulado de la sesión)

```python
# Evidence extracted from a retrieved chunk (content augmentation stage)
class BudgetEvidence(BaseModel):
    chunk_id: str
    document_id: str
    component: str
    hours: float | None
    cost_eur: float | None
    sector: str | None
    project_year: int | None
    note: str  # short, grounded justification

# Per-component aggregate computed deterministically before synthesis
class ComponentAggregate(BaseModel):
    component: str
    weighted_estimate: float   # central anchor, in hours
    low: float
    high: float
    contradiction: bool
    sources: list[str]         # chunk_ids contributing to this component

# Synthesized, citable component (output of the synthesis stage)
class SynthesizedComponent(BaseModel):
    component: str
    low_hours: float
    high_hours: float          # equals low_hours when confident
    rationale: str
    source_chunk_ids: list[str]
    contested: bool

# Human-meaningful, verifiable citation (citation stage)
class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    project_year: int
    locator: str                       # exact source line backing the claim
    char_span: tuple[int, int] | None  # offsets, if captured at ingestion

# Verdict from the hallucination judge (verification stage)
class ClaimVerdict(BaseModel):
    component: str
    supported: bool
    reason: str
    confidence: float

# Post-gate line, ready to serve (verification stage)
class VerifiedLine(BaseModel):
    component: str
    low_hours: float | None
    high_hours: float | None
    status: Literal["grounded", "insufficient", "rejected"]
    confidence: float

# Embedding provenance (indexing stage)
class EmbeddingVersion(BaseModel):
    model: str            # "text-embedding-3-small"
    dimensions: int       # 1536
    normalized: bool
    preprocessing_id: str  # id/hash of the chunking + cleaning config

    @property
    def key(self) -> str:
        return f"{self.model}:{self.dimensions}:{self.normalized}:{self.preprocessing_id}"
```

#### Anclaje numérico (verificación barata antes del juez)

```python
def numeric_grounding(
    line: SynthesizedComponent,
    evidence_by_id: dict[str, BudgetEvidence],
) -> bool:
    """Cheap, deterministic check: is the claimed figure traceable to cited sources?

    Interpolation within the cited range is allowed; a figure outside the
    range of every cited source is an unsupported extrapolation.
    """
    cited_hours = [
        evidence_by_id[cid].hours
        for cid in line.source_chunk_ids
        if cid in evidence_by_id and evidence_by_id[cid].hours is not None
    ]
    if not cited_hours:
        return False  # no numeric support at all -> fabrication
    return min(cited_hours) <= line.low_hours and line.high_hours <= max(cited_hours)
```

#### Verificación semántica con juez estricto

```python
VERIFY_INSTRUCTIONS = """
You are a strict verifier of software estimate lines against their cited sources.
A claim is SUPPORTED only if the cited sources actually mention this component
and a figure consistent with the claim. A number present in no cited source is
NOT supported. Attributing a figure to a source that discusses a different
component is NOT supported. Do not be charitable: when in doubt, return supported=false.
"""

def verify_claim(
    line: SynthesizedComponent,
    cited_evidence: list[BudgetEvidence],
) -> ClaimVerdict:
    response = client.responses.parse(
        model=settings.verifier_model,  # cheaper, separate model from the generator
        input=[
            {"role": "system", "content": VERIFY_INSTRUCTIONS},
            {"role": "user", "content": render_verification_input(line, cited_evidence)},
        ],
        text_format=ClaimVerdict,
    )
    return response.output_parsed
```

#### Integridad referencial (ninguna cita colgante)

```python
class CitationIntegrityReport(BaseModel):
    resolved: list[str]
    dangling: list[str]  # cited ids that were never in the retrieved context

def check_citation_integrity(
    estimate: Estimate,
    retrieved_ids: set[str],
) -> CitationIntegrityReport:
    resolved, dangling = [], []
    for component in estimate.components:
        for cid in component.source_chunk_ids:
            (resolved if cid in retrieved_ids else dangling).append(cid)
    if dangling:
        log.warning("dangling_citations", ids=dangling)
    return CitationIntegrityReport(resolved=resolved, dangling=dangling)
```

Política ante una citación colgante, de más a menos estricta: rechazar la estimación entera y reintentar con una instrucción más dura; degradar el componente afectado a "sin fuente verificable" y rebajar su confianza; o, como mínimo, no dejar salir del servicio una estimación con una citación que no resuelve. Nunca ignorarla en silencio.

#### Reindexación incremental y versionado (contexto operativo)

```python
def is_stale(chunk: StoredChunk, source_hash: str, current: EmbeddingVersion) -> bool:
    """A chunk is stale if its source text changed or it belongs to an old version."""
    return chunk.source_hash != source_hash or chunk.embedding_version != current.key

async def reindex_incremental(documents: list[Document], current: EmbeddingVersion) -> None:
    for document in documents:
        source_hash = content_hash(document.text)
        existing = await get_chunks(document.id)
        if existing and not any(is_stale(c, source_hash, current) for c in existing):
            continue  # up to date, skip
        await delete_chunks(document.id)
        chunks = chunk_and_embed(document, current)  # reuses the existing ingestion pipeline
        await insert_chunks(chunks)
        log.info("document_reindexed", document_id=document.id, version=current.key)
```

Toda consulta de recuperación debe filtrar por la versión de embeddings activa:

```sql
-- Retrieval always scopes to the single active embedding version.
SELECT chunk_id, document_id, content
FROM chunks
WHERE embedding_version = :current_version
ORDER BY embedding <=> :query_vector
LIMIT :k;
```

Migración de versión completa: construir el índice nuevo en paralelo (shadow index), verificarlo (recuento de documentos, dimensiones correctas, consultas de prueba con vecinos razonables) y solo entonces promoverlo de forma atómica. Si la verificación falla, se descarta el índice sombra y el servicio sigue con la versión que funcionaba, sin que el usuario note nada.

#### Evaluación RAGAS (esqueleto de implementación)

```python
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

def build_eval_dataset(golden: list[GoldenItem], pipeline) -> Dataset:
    rows = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for item in golden:
        result = pipeline.run(item.transcript)  # real retrieval + generation
        rows["question"].append(item.question)
        rows["answer"].append(result.answer_text)
        rows["contexts"].append([chunk.content for chunk in result.retrieved_chunks])
        rows["ground_truth"].append(item.ground_truth)
    return Dataset.from_dict(rows)

def run_ragas(golden: list[GoldenItem], pipeline) -> dict[str, float]:
    dataset = build_eval_dataset(golden, pipeline)
    scores = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    log.info("ragas_scores", **scores)
    return scores
```

Nota de compatibilidad: la API de RAGAS cambia de forma notable entre versiones (nombres de columnas, clases de dataset). Conviene fijar la versión de RAGAS en el proyecto y comprobar los nombres exactos contra ella antes de dar por bueno el esqueleto anterior.

#### Monitorización en producción (sin ground_truth)

```python
async def monitor_production_sample(estimates: list[ServedEstimate]) -> dict[str, float]:
    """Reference-free quality monitor on sampled live traffic.

    Faithfulness and answer relevancy need no ground_truth, so they work on
    real queries. Context recall does not: there is no reference answer for a
    live request. Alert on downward drift, not on absolute values.
    """
    dataset = Dataset.from_dict({
        "question": [e.question for e in estimates],
        "answer": [e.answer_text for e in estimates],
        "contexts": [[c.content for c in e.retrieved_chunks] for e in estimates],
    })
    return evaluate(dataset, metrics=[faithfulness, answer_relevancy])
```

#### Parámetros de referencia del programa

| Parámetro | Valor de partida | Nota |
|---|---|---|
| Modelo de embeddings | text-embedding-3-small | Usado también por RAGAS para las métricas que lo requieren |
| Modelo de augmentation | modelo barato (p. ej. gpt-5-mini) | Extracción de puntos clave, esquema estricto |
| Modelo de síntesis/generación | modelo de razonamiento medio (p. ej. gpt-5) | Razona sobre agregados, no inventa aritmética |
| Modelo verificador (juez) | distinto y más barato que el generador | Reduce puntos ciegos compartidos |
| Umbral de contradicción | dispersión relativa > 50% entre fuentes fuertes (peso ≥ 0.4) | Punto de partida, no valor sagrado |
| Semivida de recencia / reindexación | coherente con la usada en recuperación (Sesión 10) | Juicio de dominio, no optimización |
| Tamaño del golden set (RAGAS) | 5 consultas + ground_truth | Extiende el golden set de retrieval de la Sesión 10 |

#### Checklist antes de la sesión en vivo

- [ ] El esquema de la estimación incluye `SourceReference` y `sources` por línea, con `grounded` obligatorio.
- [ ] El prompt de generación exige citar `chunk_id` reales del contexto y prohíbe explícitamente inventar cifras.
- [ ] `verify_citations` detecta una citación colgante introducida a propósito como prueba.
- [ ] Las líneas sin soporte quedan marcadas como insuficientes, nunca rellenas con una cifra de relleno.
- [ ] El golden set de la Sesión 10 está extendido con `ground_truth` por consulta.
- [ ] RAGAS se ejecuta contra las cinco consultas y produce las cuatro métricas más el promedio.
- [ ] Existe una nota corta con la lectura honesta de los números (qué falla y por qué, no solo el valor).
- [ ] Sabes explicar la diferencia entre anclaje numérico, verificación semántica y consistencia, y cuándo usar cada una.
- [ ] Entiendes por qué la integridad referencial no es suficiente y qué añade el verificador semántico.
- [ ] Sabes qué es la mezcla de versiones de embeddings y por qué una consulta nunca debe cruzarlas.
- [ ] Distingues cuándo toca reindexación incremental y cuándo una migración de versión completa.
- [ ] Puedes explicar por qué RAGAS separa métricas de generación (faithfulness, answer relevancy) de métricas de recuperación (context precision, context recall).

#### Documentación de referencia

- OpenAI — Responses API: https://platform.openai.com/docs/api-reference/responses
- OpenAI — Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- Pydantic v2 — Validators: https://docs.pydantic.dev/latest/concepts/validators/
- RAGAS — Documentación oficial: https://docs.ragas.io/
- RAGAS — Métricas (faithfulness, answer relevancy, context precision/recall): https://docs.ragas.io/en/stable/concepts/metrics/
- structlog: https://www.structlog.org/
- pgvector: https://github.com/pgvector/pgvector
- PostgreSQL — Columnas generadas: https://www.postgresql.org/docs/current/ddl-generated-columns.html
- FastAPI — Lifespan events: https://fastapi.tiangolo.com/advanced/events/
- SQLAlchemy 2.0 — Asyncio: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

---

*README generado a partir del contenido de la Sesión 11 — RAG Avanzado: Generación y calidad (AI Engineering 2026/05, training.lidr.co), siguiendo la estructura del README de referencia de la Sesión 10 del mismo programa.*
