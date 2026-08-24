# Notas para la revisión — Sesión 11

Pre-work de la Sesión 11: **citación verificable a nivel de línea** y **evaluación RAGAS** sobre el
golden set extendido. Este documento recoge el alcance, las decisiones de diseño, las desviaciones
respecto al enunciado y la lectura honesta de los números.

Todo el código va en inglés (nombres, comentarios, logs, prompts), como pide el enunciado; esta prosa
y el `ground_truth` del golden set, en español.

---

## 1. Alcance

El enunciado marca el pre-work con precisión: **Parte 1** (citación por línea) y **Parte 2** (RAGAS
básico). El resto de la sección "Contexto técnico para la implementación" — `augmentation/`,
`synthesis/`, el juez semántico de alucinaciones, el versionado de embeddings y la monitorización en
producción — es material del directo, y no se ha implementado. La estructura de módulos que propone
el README es orientativa; aquí manda la arquitectura real del repo (reglas de capas de
`ARCHITECTURE.md`), así que la funcionalidad se ha extendido **en su sitio** en vez de crear paquetes
nuevos `citation/`, `verification/` y `evaluation/` que duplicarían lo que ya existe.

Punto de partida: `session_10_live`, sin la carpeta `estimator-web/` (el cliente Rails del profesor).

---

## 2. Lo que ya existía y lo que faltaba de verdad

Conviene decirlo porque cambia el tamaño real del ejercicio: **el camino de la Sesión 9 ya citaba por
línea**. `TaskItem.sources` era una `list[int]` de ids de chunk, `validate_citations` ya cruzaba esos
ids contra los chunks recuperados y el orquestador ya hacía un reintento correctivo.

Lo que faltaba —y es exactamente lo que pide el enunciado— era:

| Pieza | Antes | Ahora |
|---|---|---|
| Qué transporta una cita | un `int` | `SourceReference(chunk_id, document_id, evidence)` |
| Evidencia | ninguna | el fragmento **verbatim** que respalda la línea |
| Abstención por línea | no existía | `TaskItem.grounded`, obligatorio |
| Resultado de la verificación | `list[int]` plana de ids inventados | `CitationReport` con veredicto por línea |
| Consecuencia de una cita colgante | bajar la confianza global a `low` | podar la cita y degradar **esa** línea |
| Registro | un `warning` sin ids | evento `citation_report` con contadores e ids, correlacionado por `request_id` |

---

## 3. Decisiones de diseño

### 3.1 La "línea" es `TaskItem`, extendido en su sitio

El enunciado dibuja un `EstimateLineItem(component, hours, rationale, grounded, sources)`. El árbol
real del repo es `Estimate.modules[] → WorkModule.tasks[] → TaskItem`, y `estimate.components` no
existe. Crear un modelo paralelo habría duplicado el contrato para tener que fusionarlo después, así
que la línea del enunciado se mapea sobre `TaskItem`: `component → name`, `hours → engineer_days`
(la unidad del repo son días-ingeniero, no horas), y `rationale` se cubre con la combinación de
`description` (alcance de la tarea) y el `evidence` verbatim de cada fuente, que es más verificable
que una justificación en prosa.

El radio de impacto resultó mínimo: `task.sources` solo se consumía en un punto de `app/`
(`validation.py`) y en dos tests.

### 3.2 `grounded` es obligatorio, sin default

La checklist dice "con `grounded` obligatorio". Declararlo sin default obliga al modelo a decidir por
cada línea si tiene respaldo, en vez de dejar que la omisión signifique `False` por accidente. Coste:
dos fixtures de test que construían tareas sin ese campo.

### 3.3 `document_id` lo resuelve el servicio, no el modelo

`SourceReference` lleva `document_id`, como pide el enunciado, pero **el prompt le dice al modelo que
lo deje vacío**: es un valor 100 % derivable del `chunk_id`, y pedirle que lo repita solo añadiría
una superficie más donde alucinar. `enforce_citation_policy` lo rellena desde el chunk recuperado.

Consecuencia práctica: no hace falta exponer `document_id` en el bloque `<source>`, así que el
ensamblador de contexto no se ha tocado.

### 3.4 La regla de integridad es verificación posterior, no un validador Pydantic

El enunciado admite las dos vías ("como validador o como verificación posterior"). Se ha elegido la
segunda por una razón concreta: un `@model_validator` hace que **Instructor re-promptee en silencio**
hasta seis veces dentro de `complete_structured`, sin `log_stage`, sin control del feedback y sin
dejar rastro. El punto 1.3 pide justo lo contrario: *registrar* el resultado con `structlog`. Además,
todo el camino RAG ya valida así (`check_coherence` es el precedente local; `schemas.py` no tiene ni
un validador).

### 3.5 Verificar e imponer son dos cosas distintas

Esta es la decisión que más código explica:

- `verify_citations(estimate, chunks) -> CitationReport` **informa**: clasifica cada línea en
  `grounded` / `dangling` / `insufficient` y no cambia nada. Es lo que se loguea y lo que se lleva al
  directo, porque describe lo que hizo el **modelo**.
- `enforce_citation_policy(estimate, chunks) -> Estimate` **decide**: resuelve el `document_id`, poda
  las citas que no resuelven, degrada a `grounded=False` sin horas la línea que se queda sin respaldo
  y **re-deriva** `total_engineer_days` a partir de lo que sobrevive. Es lo que el **servicio** sirve.

De las tres políticas que ofrece el enunciado ante una cita colgante irreparable, se ha elegido la
intermedia (degradar la línea afectada) en vez de la más dura (rechazar la estimación entera con un
502). Cumple el mínimo exigido —"no dejar salir del servicio una estimación con una citación que no
resuelve"— sin romper el contrato observable de `POST /v1/estimate/from-transcript` ni tirar a la
basura las líneas que sí estaban bien fundamentadas. Si **ninguna** línea sobrevive fundamentada, la
estimación colapsa entera a la forma canónica de contexto insuficiente, que es la respuesta honesta.

El endpoint de etapa `POST /v1/estimate/stages/generate` **informa pero no impone**: devuelve el
`citation_report` con la salida cruda del modelo. Es coherente con lo que ya hacía (no auto-reintenta
ni repara incoherencias: expone las señales para que el wizard las enseñe). La imposición vive en el
camino servido.

### 3.6 Orden de campos de `TaskItem`

`sources` y `grounded` se declaran **antes** de `engineer_days`. `ARCHITECTURE.md` §8 eleva el orden
de campos a contrato por la razón autorregresiva ya documentada en el repo: el modelo emite en orden,
así que primero enumera su evidencia y declara si la tiene, y solo entonces se compromete con una
cifra — en vez de elegir un número y buscarle una cita después.

---

## 4. Desviaciones del enunciado (todas deliberadas)

1. **`LLMWrapper` (Instructor) en vez de `client.responses.parse`.** El enunciado muestra la Responses
   API cruda con `text_format=`. La regla del repo es que toda llamada LLM pasa por
   `app/foundation/llm/wrapper.py`, y está escrita en el propio docstring del orquestador. El mapeo es
   1:1 (`text_format=<Model>` → `response_model=<Model>`).
2. **RAGAS ejecuta su juez y sus embeddings fuera de `LLMWrapper`.** La regla anterior protege el
   camino de petición del servicio; un arnés de evaluación offline no está en ese camino, y
   reimplementar las cuatro métricas a mano para respetarla sería exactamente el código especulativo
   que `CLAUDE.md` prohíbe.
3. **`chunk_id: int`, no `str`.** El id citable es la PK del chunk en la base de datos, que es lo que
   el modelo ve literalmente en `<source id="...">` y lo que compara toda la cadena. Cambiarlo a `str`
   habría roto la aritmética de conjuntos de la validación y tres aserciones de test, a cambio de nada.
4. **`verify_citations(estimate, retrieved_chunks: list[RetrievedChunk])`**, no
   `(estimate, retrieved_chunk_ids: set[str])`. La política necesita el chunk completo, no solo su id,
   para resolver el `document_id`. La firma del enunciado se conserva en espíritu.
5. **La unidad es `engineer_days`**, no `hours`: es la del esquema de la Sesión 9. El corpus histórico
   sí está en horas, y esa conversión es justo lo que el modelo tiene que razonar a partir del
   `evidence`.
6. **El golden set tiene 8 consultas, no 5.** Q1–Q5 (descripciones de proyecto, budget-only) reciben
   `ground_truth` y se evalúan con RAGAS; Q6–Q8 son preguntas documentales cross-colección ("qué dijo
   el cliente sobre…"), no peticiones de estimación, y se quedan como estaban, solo para retrieval.

---

## 5. Problemas del entorno de partida

1. **`ragas` no se puede instalar sin más.** `ragas 0.4.3` importa en duro
   `langchain_community.chat_models.vertexai`, que la versión 0.4.x de `langchain-community` (ya en
   *sunset*) eliminó: `import ragas` revienta con `ModuleNotFoundError`. La solución es sujetar
   `langchain-community<0.4` en el grupo `dev`, lo que mantiene toda la pila de langchain en 0.3.x —
   dentro de los rangos que el proyecto ya declaraba, y con la suite verde. Queda documentado en
   `pyproject.toml`.
2. **`evaluate()` no acepta las métricas "modernas".** La misma versión expone
   `ragas.metrics.collections.{Faithfulness,…}` y marca como *deprecated* las clásicas, pero
   `evaluate()` rechaza las primeras con `TypeError: All metrics must be initialised metric objects`.
   El arnés usa el esquema moderno de datos (`EvaluationDataset`/`SingleTurnSample`) con los objetos
   de métrica clásicos, que es la combinación que funciona. Es exactamente la trampa que avisa el
   enunciado: verificar la API contra la versión instalada antes de dar por bueno el esqueleto.
3. **El `.env` de partida era el de la Sesión 6.** Le faltaban 16 claves de S09/S10, entre ellas
   `RETRIEVAL_API_KEY` y `ESTIMATE_API_KEY`: vacías significan 401 en todos los routers de RAG. Y su
   `REDIS_URL` apuntaba al hostname de Docker (`redis://redis:6379`), que no resuelve en ejecuciones
   desde el host, al contrario que su `DATABASE_URL`, que sí era host-side.

---

## 5.bis Bugs propios, detectados y corregidos

1. **La reparación de coherencia se saltaba la política de citación.** El paso 7 del orquestador
   regenera la estimación cuando `check_coherence` falla, y esa generación nueva llegaba al cliente
   sin pasar por `enforce_citation_policy` — es decir, podía servir exactamente la cita colgante que
   el paso 6 acababa de impedir. Se aplica la política también sobre la reparación
   (`estimator.py`, paso 7), con test que lo fija.
2. **La re-derivación del total no era una salvaguarda teórica.** En la primera prueba contra un
   modelo real (gpt-4o-mini, esquema nuevo), el modelo devolvió `total_engineer_days=0` con tareas
   que sumaban 55 días. `enforce_citation_policy` lo recalculó a 55. La regla 5 del prompt pide que
   el total cuadre con la suma; el código ya no depende de que el modelo obedezca.

---

## 6. La tabla RAGAS

Generada con `uv run python scripts/eval_ragas_s11.py` sobre las cinco consultas de estimación del
golden set, con el pipeline real (recuperación + generación con `gpt-5`) y `gpt-4o-mini` como juez.

| Query | faithfulness | answer_relevancy | context_precision | context_recall |
| --- | --- | --- | --- | --- |
| Q1 | 0.42 | 0.11 | 1.00 | 0.80 |
| Q2 | 0.26 | 0.08 | 1.00 | 0.50 |
| Q3 | 0.40 | 0.18 | 1.00 | 0.33 |
| Q4 | 0.60 | 0.26 | 1.00 | 0.67 |
| Q5 | 0.36 | 0.13 | 1.00 | 0.67 |
| **Promedio** | **0.41** | **0.15** | **1.00** | **0.59** |

### Informe de verificación de citaciones sobre esas mismas cinco estimaciones

Salida cruda del modelo, antes de aplicar la política:

| Query | líneas | fundamentadas | colgantes | sin datos | ids colgantes |
| --- | --- | --- | --- | --- | --- |
| Q1 | 20 | 16 | 0 | 4 | — |
| Q2 | 25 | 25 | 0 | 0 | — |
| Q3 | 25 | 20 | 0 | 5 | — |
| Q4 | 15 | 15 | 0 | 0 | — |
| Q5 | 18 | 18 | 0 | 0 | — |
| **Total** | **103** | **94** | **0** | **9** | **—** |

Las nueve abstenciones no son ruido, son exactamente el trabajo que ningún presupuesto del corpus
desglosa: las apps móviles iOS/Android y la UX de autenticación reforzada en Q1, y el bloque de QA y
gestión de proyecto en Q3. El modelo las marca `grounded=false` sin horas en vez de rellenarlas.

---

## 7. Lectura de los números

**Citación perfecta y `faithfulness` de 0.41 no se contradicen: esa brecha es el hallazgo.** Las 103
líneas citan fuentes reales y ninguna cuelga, pero la sesión empuja a desglosar un componente
histórico grueso ("OAuth 2.0 authentication backend: 120h") en tareas granulares con cifras
interpoladas ("Authorization Code flow: 5 días"), y esa cifra concreta **no está literalmente en la
fuente**, así que el juez la marca como no soportada. Dicho de otro modo: el sistema es trazable y aun
así puntúa regular en fidelidad, porque `faithfulness` premia parafrasear la fuente y el ejercicio
premia derivar de ella. `context_precision` en 1.00 con `context_recall` en 0.59 dice que lo
recuperado es todo relevante pero no cubre todo lo que la referencia espera — y el peor caso, Q3
(0.33), es el más revelador: la telemedicina necesita cinco bloques (FHIR, agenda, vídeo,
consentimiento, registros clínicos) y el top-10 se los come con los tres primeros.

Dos cautelas honestas sobre la tabla. **`answer_relevancy` (0.15) no mide lo que parece**: esa métrica
comprueba si la respuesta responde a la pregunta, pero nuestras "preguntas" son descripciones de
proyecto y la respuesta es un desglose estructurado en módulos y tareas. Es un desajuste de forma, no
una señal de calidad, y no debería leerse como tal. Y **la varianza entre ejecuciones es alta**:
midiendo dos veces el mismo sistema sin cambiar nada, `faithfulness` en Q1 pasó de 0.00 a 0.42 y en
Q2 de 0.54 a 0.26. Cada ejecución regenera la estimación con `gpt-5` y la vuelve a juzgar, así que
esta tabla es un baseline de orden de magnitud, no una medición fina — y es la razón práctica por la
que la consistencia por muestreo repetido existe como técnica.

---

## 8. Revisión adversarial del propio trabajo

Antes de cerrar, el diff pasó por una revisión con cuatro lentes (correctitud, criterios de
aceptación, alcance y arnés de evaluación) y cada hallazgo se sometió a un intento de refutación
contra el código real: **30 hallazgos en bruto, 11 confirmados**. Los ocho de código y método se
arreglaron:

1. **El más caro, y afectaba a los números.** El texto de un chunk de presupuesto lleva el nombre del
   proyecto y del componente, pero **no su `BUD-2024-xxx`**. El arnés escribía cada línea como
   «derived from BUD-2024-001» y los `ground_truth` estaban redactados con esos ids, así que el juez
   tenía que verificar afirmaciones sobre identificadores que el contexto no contiene: se medía su
   capacidad de resolver ids, no la fundamentación del sistema. Ahora la respuesta cita el `evidence`
   verbatim (que sí está en el contexto) y la referencia se escribe con el vocabulario del corpus.
2. **La reparación de coherencia no estaba cubierta de verdad.** El test que la justificaba pasaba
   sin entrar nunca en esa rama (la política ya dejaba coherente la estimación, así que
   `check_coherence` no fallaba). Reescrito para alcanzarla de verdad, y **verificado por mutación**:
   borrando la línea que protege, el test falla.
3. **El colapso pisaba la explicación del modelo.** Cuando el propio modelo declara contexto
   insuficiente y explica por qué, la rama de colapso reescribía su motivo con uno fijo que en ese
   caso era falso. Ahora la explicación del modelo sobrevive si la hay.
4. **El nivel de log ignoraba un caso.** Se decidía con el contador de líneas `dangling`, así que un
   id fabricado citado solo en el `sources` de nivel superior se registraba como INFO. Ahora mira
   también `dangling_source_ids`.
5. **`validate_citations` quedó sin consumidores** al migrar sus dos llamadas: era código muerto con
   una justificación falsa en su docstring. Eliminada; sus cuatro tests se conservan sobre
   `verify_citations(...).dangling_source_ids`, que es exactamente el mismo contrato.
6. **El arnés no leía los overrides de retrieval en Redis** que sí usa el orquestador, mientras su
   docstring afirmaba reproducir "las mismas llamadas y los mismos settings". Corregido.
7. **`datasets` estaba declarada y no se importa** en ninguna parte (`ragas` ya la arrastra).
   Eliminada del grupo dev.
8. **El round-trip de JSON del golden set expandió todos los arrays de ids**, convirtiendo 6 cambios
   reales en 71 líneas de diff sobre consultas que el ejercicio no toca. Devuelto al formato original.

---

## 9. Los conceptos de la checklist

- **Anclaje numérico vs. verificación semántica vs. consistencia.** Son tres capas de coste creciente.
  El anclaje numérico es aritmética determinista: ¿la cifra cae dentro del rango de las fuentes
  citadas? Es gratis y no puede alucinar, pero solo ve números. La verificación semántica usa un juez
  LLM distinto del generador para preguntar si la fuente citada *dice* lo que la línea afirma; cuesta
  una llamada por línea y detecta la atribución falsa, que la aritmética no ve. La consistencia por
  muestreo repetido genera la misma línea varias veces y mide la dispersión; es la más cara y se
  reserva a líneas críticas, con la trampa de que confunde incertidumbre honesta con invención.
- **Por qué la integridad referencial no basta.** Confirma que la fuente citada existía en el contexto
  entregado; no confirma que diga lo que la línea afirma. Una cifra real atribuida a la fuente
  equivocada pasa la integridad referencial con nota. Eso es lo que añade el verificador semántico —y
  es también la razón de que este pre-work pida copiar el `evidence` verbatim: sin el fragmento, no
  hay nada que un juez pueda contrastar.
- **Mezcla de versiones de embeddings.** Dos vectores producidos por modelos distintos (o por el mismo
  modelo con otra dimensión, normalización o preprocesado) no viven en el mismo espacio: su similitud
  coseno es un número perfectamente calculable y sin ningún significado. Por eso cada vector se
  versiona con una clave que combina esos cuatro factores y **ninguna consulta cruza versiones**.
- **Reindexación incremental vs. migración completa.** La incremental es barata y por documento: se
  detecta por hash del contenido que un documento cambió y se re-embebe solo ese. La migración de
  versión es cara y global: cambia el modelo de embeddings, así que hay que reconstruir el índice
  entero en paralelo (blue/green), verificarlo y solo entonces conmutar de forma atómica, para que un
  fallo no deje el servicio a medias.
- **Por qué RAGAS separa generación de recuperación.** `faithfulness` y `answer_relevancy` miden lo
  que el generador hizo con el contexto que recibió; `context_precision` y `context_recall` miden si
  ese contexto era el adecuado. Sin la separación, una caída de calidad no se puede atribuir: una
  respuesta mala con contexto bueno es un problema de prompt o de modelo; una respuesta mala con
  contexto malo es un problema de recuperación, y tocar el prompt no lo va a arreglar.
