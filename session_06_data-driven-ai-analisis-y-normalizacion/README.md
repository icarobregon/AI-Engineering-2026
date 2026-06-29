# Sesión 6 — Fundamentos de data driven AI: Análisis, formateo y normalización de datos existentes

## Objetivo de la sesión

Los sistemas RAG no fallan en producción por culpa del modelo de embeddings ni de la base vectorial. Fallan porque los datos que se les dan son basura, están incompletos o no representan lo que el sistema asume que representan. La degradación de calidad es silenciosa: el sistema parece funcionar bien al principio y empieza a romperse cuando el corpus crece o cuando las consultas se alejan de los casos de prueba.

Esta sesión abre el módulo de data-driven AI y aterriza una idea que recorre toda la literatura seria sobre RAG en producción: la calidad del dato es la variable de control más importante de todo el sistema, y también la más ignorada.

El ejercicio pre-sesión lleva a estresar el CAG construido hasta la sesión 5 contra un corpus realista para llegar al directo con un baseline cuantitativo: cuándo el salto de CAG a RAG es una necesidad arquitectónica, no una preferencia. El módulo aborda la auditoría e inventario de datos empresariales, el pipeline de extracción multi-formato, la limpieza y validación con contratos explícitos, y el tratamiento de PII, anonimización y GDPR antes del embedding.

## Qué vas a aprender

### 1. 📄 Calidad del dato y decisiones de arquitectura — 24 min

Los sistemas CAG tienen cuatro restricciones estructurales que los hacen inviables a escala: el context window (límite duro de tokens), el coste por consulta (escala linealmente con el corpus), la latencia (segundos adicionales con contextos largos) y la degradación de atención sobre contextos largos (el fenómeno "lost in the middle"). Cuando el corpus crece, tres de los cuatro ejes del árbol de decisión empujan directamente a RAG.

**Las cuatro restricciones del CAG formalizadas:**

```python
from dataclasses import dataclass

@dataclass
class CAGViability:
    fits_in_context_window: bool
    cost_per_query_acceptable: bool
    latency_acceptable: bool
    attention_quality_acceptable: bool
```

**El árbol de decisión arquitectónica** articula cuatro ejes: tamaño relativo al context window, frecuencia de actualización del corpus, necesidad de trazabilidad (citar fuente concreta), y sensibilidad de los datos. Para el Proyecto 2 (sistema de estimación de proyectos software), tres de los cuatro ejes empujan directamente a RAG: el corpus crece linealmente, la frecuencia de actualización es alta, la trazabilidad es crítica para propuestas comerciales, y la sensibilidad es alta (PII, condiciones comerciales).

**Pipeline RAG como dos pipelines distintos:**

- **Pipeline offline de indexación** (pasos 1-4): ingest → parse → chunk → embed. Se ejecuta en background, sin que haya usuarios esperando.
- **Pipeline online de consulta** (pasos 5-6): retrieve → generate. Se ejecuta síncronamente cuando un usuario hace una pregunta.

Esta separación tiene consecuencias prácticas: el pipeline offline puede usar modelos pesados y estrategias costosas; el online tiene SLA de latencia.

**Trade-offs honestos:** Citar fuentes no es gratis (metadatos por chunk); RAG no es una alternativa más barata a CAG (el coste total incluye indexación, embeddings y vector store); el CAG no muere al introducir RAG, cambia de papel (documentos de referencia inmutables como un rate card siguen siendo mejores como CAG).

### 2. 📄 Auditoría e inventario de datos empresariales — 27 min

La decisión arquitectónica está tomada: RAG con capa residual de CAG. La tentación es empezar a vectorizar los datos que el equipo entregó. Antes hay un paso que la literatura de RAG en producción pone como condición necesaria: auditar lo que hay en la mesa.

**El antipatrón: vectorizar primero, mirar después.** Los tres modos de fallo son: mezcla silenciosa de versiones (el corpus contiene versiones contradictorias del mismo documento), fuentes podridas (una fuente con calidad degradada envenenará todo el índice), y gaps invisibles (el sistema responde con confianza sobre áreas que no están cubiertas).

**Inventario de fuentes — campos mínimos por fuente:**

- `source_id`: identificador estable interno
- `location`: path o URL exacto con sistema de almacenamiento
- `technical_owner`: responsable técnico de accesibilidad
- `business_owner`: responsable del contenido
- `format`: JSON, CSV, PDF, DOCX, TXT, fila de BBDD, respuesta de API
- `volume`: número aproximado de registros y tamaño en disco
- `access_method`: FTP, API, descarga manual, query SQL
- `update_frequency_declared`: cada cuánto cambia oficialmente
- `update_frequency_observed`: cada cuánto cambia realmente

**Evaluación de calidad en cuatro dimensiones** (escala 1-5):

- **Completitud**: porcentaje de registros con todos los campos esperados
- **Consistencia**: el mismo concepto representado de la misma forma (EUR vs eur vs euros)
- **Actualidad**: fecha del último dato relevante y cumplimiento de periodicidad
- **Fiabilidad**: fuente autoritativa vs derivada

La regla de `is_rag_ready` es deliberadamente estricta: una fuente con `completeness=5` y `reliability=1` no es RAG-ready. El mínimo en todas las dimensiones es la condición necesaria.

**Linaje y context erosion.** El linaje de un dato es el rastro de su origen y sus transformaciones. La pérdida progresiva de ese contexto a medida que un documento se copia, renombra o transforma es la "context erosion". Combatirla es la razón fundamental por la que el catálogo es un artefacto necesario.

**El catálogo mínimo viable como YAML versionado** es más que documentación: es un artefacto de software. Cualquier código que toque las fuentes lee el catálogo antes de actuar.

```yaml
# data_catalog.yaml
version: 1
last_audited: "2026-05-15"
sources:
  - name: historical_budgets
    location: "gs://company-data/budgets/"
    format: json
    sensitivity: high
    decision: include
    quality:
      completeness: 4
      consistency: 3
      freshness: 5
      reliability: 4
```

### 3. 📄 Pipeline de extracción multi-formato — 25 min

Con el catálogo cerrado el siguiente paso es convertir cada fuente en texto procesable. El pipeline de extracción tiene un contrato de salida único independientemente del formato de entrada.

**El contrato común: el Document canónico**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class Document(BaseModel):
    content: str
    source_name: str
    source_location: str
    doc_type: str
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
    extra: dict = Field(default_factory=dict)
```

**Arquitectura modular del subsistema `ingest/` en tres capas:**

- **Loaders**: resuelven "cómo llego al fichero". Saben de paths de filesystem, URLs HTTP, autenticación de Drive/S3. Devuelven bytes o un path local temporal.
- **Parsers**: resuelven "qué hay dentro del fichero". Reciben bytes o un path local, eligen la librería adecuada y producen texto + metadatos estructurados.
- **Normalizers**: resuelven "cómo convierto la salida de mi parser al contrato canónico". Es la capa fina que toma la salida del parser y produce un `Document`.

**Estrategias de parsing por formato:**

- **JSON**: renderizar a markdown estructurado para preservar jerarquía
- **TXT** (transcripciones): parsear speaker y timestamp, preservar estructura de quién dijo qué
- **XLSX**: tabla pura → markdown table; estructura compleja → serializar como JSON anidado
- **DOCX**: `python-docx` con headings como metadatos (`section_title`)
- **PDF**: `pypdf` por defecto para digitales; `unstructured` con `hi_res` solo cuando hay tablas o está escaneado

**Propagación de metadatos a través del pipeline** en tres capas:

1. Metadatos del catálogo (conocidos antes de tocar el documento)
2. Metadatos del parser (extraídos del documento concreto)
3. Metadatos del pipeline (`ingested_at`, versión del parser)

**Trade-offs honestos:** parsers nativos vs `unstructured` como navaja suiza (peso de `unstructured[all-docs]`, latencia y coste de `hi_res`); información estructural que no sobrevive al pipeline (aceptable si se documenta).

### 4. 📄 Limpieza, normalización y validación de datos — 28 min

El subsistema `ingest/` produce Documents canónicos que cumplen el contrato Pydantic de forma pero no necesariamente de contenido. Dos Documents pueden cumplir perfectamente el contrato y al mismo tiempo ser radicalmente incompatibles: `client_name: "ACME Corp."` vs `client_name: "Acme Corp"`, `total_amount: -50000`, fechas en formatos distintos.

**Cuatro familias de "suciedad" en datos para RAG:**

1. **Heterogeneidad de formato**: `15/03/2024`, `2024-03-15`, `March 15, 2024`, `15-Mar-24` conviviendo; `EUR`, `eur`, `euros`; `ACME`, `Acme Corp.`, `Acme Corp`
2. **Duplicados con divergencias**: el mismo registro existe dos veces con valores distintos en algún campo
3. **Valores nulos disfrazados**: `"N/A"`, `"-"`, `"unknown"`, `"TBD"`, `"pendiente"`, cadena vacía
4. **Valores fuera de rango**: totales negativos, fechas de finalización anteriores a inicio, porcentajes >100

**Dónde colocar la capa de limpieza**: como módulo separado del pipeline, entre parser y normalizer. La representación intermedia para datos tabulares es un DataFrame, lo que permite usar pandas y Pandera como contrato.

**Pandera como contrato de datos:** librería de validación de dataframes que cumple con pandas el mismo rol que Pydantic cumple con objetos. Valida sobre columnas enteras, detecta qué filas fallaron, en qué columnas y por qué.

```python
import pandera.pandas as pa
from pandera.pandas import DataFrameModel, Field, Check
from pandera.typing import Series

class BudgetSchema(DataFrameModel):
    budget_id: Series[str] = Field(str_matches=r"^BUDGET-\d{4}-\d{4}$")
    client_name: Series[str] = Field(nullable=False)
    total_amount: Series[float] = Field(ge=0, le=10_000_000)
    currency: Series[str] = Field(isin=["EUR", "USD", "GBP"])
    signed_at: Series[pa.DateTime] = Field(nullable=True)

    class Config:
        strict = True
        coerce = False
```

**La estrategia de fallo — tres respuestas posibles:**

- **Reparar automáticamente**: cuando el fallo es recuperable sin pérdida semántica (fecha en formato alternativo, `"euros"` → `"EUR"`)
- **Mandar a cuarentena**: cuando el fallo es grave pero el registro podría ser útil tras revisión humana (no entran al RAG, se preservan)
- **Descartar**: cuando el fallo indica contaminación clara (se eliminan con log detallado)

**Trade-offs honestos:** Pandera vs Great Expectations (Pandera es ligera e integrada en código Python; GE es más ambiciosa con UI y alertas); strict mode desde el primer día (en producción es exactamente lo opuesto a permisividad en desarrollo); normalizar con el bisturí, no con la motosierra.

### 5. 📄 PII, anonimización y GDPR en el pipeline de ingest — 28 min

El corpus ya pasó por inventario, extracción y validación. Los registros son consistentes. Pero contienen datos personales: nombres de clientes, emails de interlocutores, IBANs en presupuestos, nombres de personas mencionadas en transcripciones.

**Tres modos de filtración semántica vía RAG** (que los controles de acceso tradicionales no previenen):

1. **Filtración directa**: el usuario pregunta en lenguaje natural y el RAG devuelve nombres de clientes
2. **Filtración por agregación**: cada query parece inocua pero la combinación reconstruye información privada
3. **Filtración por inferencia**: ocurre incluso después de anonimización ingenua, reduciendo la combinatoria de pistas

**El marco GDPR mínimo aplicado al pipeline:**

- **Datos personales**: cualquier información que pueda identificar directa o indirectamente a una persona física
- **Anonimización vs pseudonimización**: anonimización irreversible (ni el operador puede revertir); pseudonimización (reversible con la mapping table)
- **Derecho al olvido** (Art. 17): arquitectónico, no solo una operación DELETE
- **Minimización**: solo procesar los datos estrictamente necesarios para el propósito

**Microsoft Presidio: detección y anonimización en pipeline.** El analyzer detecta entidades PII en texto y devuelve sus posiciones; el anonymizer las reemplaza según la estrategia elegida. Requiere configuración explícita del modelo spaCy en español (`es_core_news_lg`, no el inglés por defecto).

**Pseudonimización reversible con Faker y una mapping table.** En lugar de reemplazar con tokens opacos (`[PERSON]`, `[EMAIL]`), se generan valores ficticios consistentes vinculados a la entidad original mediante una mapping table persistente:

- La misma cadena siempre se pseudonimiza al mismo valor ficticio (consistencia cross-chunk)
- Los generadores son específicos por tipo de entidad (Faker genera nombres, emails, IBANs realistas)
- La mapping store es un componente separado del pipeline, persistido con `source_name`

**Recognizers custom para el dominio del Proyecto 2:**

- `BUDGET_ID`: patrón `^BUDGET-\d{4}-\d{4}$`
- `CLIENT_CODE`: identificadores internos que mapean uno-a-uno a clientes

**El derecho al olvido en RAG** con esta arquitectura: consultar mapping store por nombre → buscar chunks con esos pseudónimos → eliminar del índice vectorial → eliminar entradas de mapping store → registrar en audit log. Operativamente trivial gracias a la mapping table; sin ella, los pasos son imposibles.

**Trade-offs honestos:** anonimización irreversible vs pseudonimización reversible (la irreversible es más simple pero imposibilita el derecho al olvido y destruye señal para el RAG); falsos positivos de Presidio en español (el modelo `es_core_news_md` es inferior al inglés equivalente); impacto en calidad de embeddings (la pseudonimización consistente preserva la mayor parte de señal semántica).

## Ejercicios prácticos

### ✍️ Ejercicio — Stress test del CAG: Medir donde rompe

**Contexto del ejercicio**

Hasta la sesión 5 se ha construido un sistema CAG (Cache-Augmented Generation): cada turno inyecta en el prompt `[summary] + anchors + ventana_deslizante + ProjectMetadata + tier + transcript + texto_extraído_de_adjuntos`. Todo cabe en el contexto del LLM, por construcción. Eso funciona mientras los proyectos son cortos y los adjuntos modestos.

No se ha puesto a prueba en serio. No se sabe a qué turno empieza a olvidar el nombre del proyecto, ni cuánto cuesta el turno 10 frente al turno 1, ni a qué tamaño de adjunto la latencia P95 supera el SLA del cliente. El módulo 3 (sesión 6 en directo) introduce RAG como respuesta a esas limitaciones, pero el alumno tiene que ver con sus propios datos qué limitación existe antes de aceptar la solución.

Este ejercicio es ese trabajo: instrumentas tu CAG, lo sometes a tres escenarios de carga (multi-turno largo, adjuntos grandes, ráfagas), produces un `REPORT.md` con tres curvas y dos párrafos de lectura. Llegas al directo con un baseline cuantitativo del CAG; sobre él se compara RAG.

**Punto de partida (al final de la sesión 5):**

- Servicio FastAPI con sesiones en memoria, ventana deslizante, anclas heurísticas, summarizer acumulativo, extracción de adjuntos
- Soporte de adjuntos vía `multipart/form-data` con extracción local de texto (camino B)
- Suite de evals con 16 casos golden, tres métricas binarias y runner CLI con modos `--http` y `TestClient`
- Observabilidad: cada llamada devuelve `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `cache_hit`, `model`; tabla de precios en `config.py`
- structlog que expone `cache_hit`, `llm_call_completed`, `history_compressed`, `summarizer_completed`, `session_estimate_received`

**Objetivos de aprendizaje:**

Al terminar deberías poder defender en una conversación técnica:
- La diferencia entre fallo hard (el schema rompe, salta una excepción, el CI avisa) y fallo soft (el recall baja del umbral sin que el sistema lo detecte)
- Cómo extender el framework de evals con métricas nuevas sin reescribirlo: el patrón `MetricResult + MetricRunner` ya está, añadir una métrica es ~15 líneas
- Por qué los presupuestos (token budget, latency budget, cost budget) son contratos de diseño, no banderas a observar
- Las trade-offs de cualquier sistema basado en contexto al escalar: latencia vs tokens, coste acumulado vs turnos, recall vs tamaño de adjunto
- Cuándo "el contexto está lleno" no es un error del LLM sino una señal de diseño: el momento exacto en el que CAG empieza a ser la arquitectura equivocada

**Los cinco bloques del ejercicio:**

**Bloque 1 — Unificar la observación por turno.** Agregar en un único evento `turn_observed` los campos emitidos hoy como logs sueltos. Campos mínimos:

```
turn_index          # 1-based, contado dentro de la sesión
session_id
enriched_transcript_tokens
context_total_tokens
messages_in_window
latency_ms
cost_usd
cache_hit
input_tokens
output_tokens
fact_recall         # placeholder None hasta el Bloque 4
```

Emitirlo con `structlog.get_logger().info("turn_observed", ...)` justo antes del `return` en `EstimationService.estimate_conversational()`.

**Bloque 2 — Escenario sintético multi-turno.** Script `evals/stress/scenarios.py` que genera conversaciones de N turnos (N ∈ {1, 3, 6, 10, 20}) sobre un mismo proyecto. Tres perfiles:
- `growing`: turno a turno se añaden requisitos coherentes (autenticación, multi-tenant, audit log, exporta CSV...)
- `pivot`: el turno 5 cambia el stack (de React a Flutter). Mide si la metadata se actualiza limpiamente
- `contradiction`: el turno 3 dice "presupuesto 30k€", el turno 8 dice "presupuesto 80k€". Mide cuál se preserva, cuál gana

Cada perfil declara un fact-tracker: para cada turno, qué afirmación deberían recordar las llamadas posteriores. Esto alimenta la `MemoryDriftMetric` del Bloque 4.

**Bloque 3 — Escenario de adjuntos grandes.** Script que produce PDFs sintéticos de tamaños calibrados (con `reportlab` o `fpdf2`):

```
0 KB   (no attachment, baseline)
5 KB   (≈ 2 páginas de texto plano)
20 KB  (≈ 8 páginas)
50 KB  (≈ 20 páginas)
100 KB (≈ 40 páginas)
```

Para cada tamaño, ejecutar la misma estimación inicial con el mismo transcript corto y project_type. Mide latencia P95, input_tokens y cost_usd como función del tamaño.

**Bloque 4 — Tres métricas nuevas:**

```python
class LatencyBudgetMetric:
    """1.0 si latency_ms <= budget_ms; 0.0 si no."""
    def __init__(self, budget_ms: int = 3000): ...

class CostBudgetMetric:
    """1.0 si cost_usd <= budget_usd; 0.0 si no."""
    def __init__(self, budget_usd: float = 0.05): ...

class MemoryDriftMetric:
    """Comprueba que el fact_to_remember aparece en la respuesta del LLM."""
    # Determinismo > sofisticacion: match exacto (case-insensitive)
```

Replicar el patrón `MetricResult(name, score, passed, details)` que ya usa `evals/metrics.py`.

**Bloque 5 — Runner + reporte.** Módulo `evals/stress/run.py` que orquesta:

```
uv run python -m evals.stress.run --http http://localhost:8000 \
    --scenarios growing,pivot,contradiction \
    --attachment-sizes 0,5,20,50,100
```

Vuelca un CSV con una fila por turno y todas las columnas del `turn_observed`. Sobre ese CSV escribe `evals/stress/REPORT.md`. Estructura mínima:
- Tabla resumen con P50/P95 de latencia, coste acumulado por escenario, hit rate de ambas caches, recall medio del fact-tracker
- Tres curvas (en tabla ASCII/Markdown): latencia vs tokens, coste acumulado vs turno, recall vs N turnos
- Dos párrafos de lectura: "Dónde empieza a romperse mi CAG y por qué"

**Lo que NO entra** (se construye en el directo): implementar RAG, cambiar `MAX_CONVERSATION_TURNS`, escribir un analizador de `evals/stress/results.csv` con visualizaciones, una `MemoryDriftMetric` con LLM como juez.

**Criterios de "hecho":**
- Cada llamada a `EstimationService.estimate_conversational()` emite un evento `turn_observed` con los 13 campos del Bloque 1
- `evals/stress/run.py` corre end-to-end sin errores y deja un CSV (3 escenarios × 5 tamaños × ≥ 3 repeticiones × N turnos)
- `evals/stress/metrics.py` (o el lugar elegido) expone `LatencyBudgetMetric`, `CostBudgetMetric`, `MemoryDriftMetric` con tests unitarios verdes
- `evals/stress/REPORT.md` contiene la tabla resumen, las tres curvas (en tabla) y los dos párrafos de lectura con al menos una conclusión cuantificada
- Todo está en el repo (no en local). El reporte es el deliverable

**Entrega:**
- Subir los archivos al repositorio del proyecto en una rama `pre-session-06`
- Compartir el link al repositorio o Pull Request por mail a george@lidr.co con al menos dos días de antelación a la sesión en vivo
- No se aceptan entregas por capturas, documentos sueltos o mensajes por chat

## Checklist antes de la siguiente sesión

- [ ] Entiendes las cuatro restricciones estructurales del CAG (context window, coste, latencia, degradación de atención) y cuándo cada una empuja hacia RAG
- [ ] Sabes aplicar el árbol de decisión arquitectónica (CAG vs RAG vs fine-tuning vs híbrido) a un caso real con los cuatro ejes: tamaño del corpus, frecuencia de actualización, necesidad de trazabilidad, sensibilidad de datos
- [ ] Entiendes la separación entre pipeline offline (ingest→parse→chunk→embed) y pipeline online (retrieve→generate) y sus consecuencias operativas
- [ ] Puedes construir un catálogo mínimo viable en YAML con los campos de censo, evaluación de calidad (completitud, consistencia, actualidad, fiabilidad) y decisión de inclusión/exclusión
- [ ] Sabes implementar el Document canónico como contrato de salida del pipeline de extracción, con las tres capas (loaders, parsers, normalizers) y propagación de metadatos
- [ ] Conoces las estrategias de parsing por formato (JSON, TXT, XLSX, DOCX, PDF) y cuándo usar `pypdf` vs `unstructured` con `hi_res`
- [ ] Sabes usar Pandera como contrato de datos sobre DataFrames, con checks de campo, checks cross-column y configuración `strict=True`
- [ ] Entiendes la estrategia de fallo en tres modos: reparar automáticamente, cuarentena, descartar — y los criterios para elegir cada uno
- [ ] Conoces los tres modos de filtración semántica vía RAG (directa, por agregación, por inferencia) y por qué los controles de acceso tradicionales no son suficientes
- [ ] Sabes configurar Microsoft Presidio para español con recognizers custom para el dominio (BUDGET_ID, CLIENT_CODE) y pseudonimización reversible con Faker y mapping table
- [ ] Entiendes el derecho al olvido como problema arquitectónico (no solo como DELETE) y cómo la mapping table lo hace operativamente viable
- [ ] Tienes el REPORT.md del stress test del CAG con baseline cuantitativo para comparar en el directo

## Documentación de referencia

- Pandera — Data validation library for pandas: https://pandera.readthedocs.io/
- Microsoft Presidio — PII detection and anonymization: https://microsoft.github.io/presidio/
- pypdf — PDF extraction: https://pypdf.readthedocs.io/
- PyMuPDF (fitz) — PDF extraction with layout: https://pymupdf.readthedocs.io/
- unstructured — Multi-format document parsing: https://github.com/Unstructured-IO/unstructured
- python-docx — DOCX parsing: https://python-docx.readthedocs.io/
- openpyxl — XLSX parsing: https://openpyxl.readthedocs.io/
- Faker — Synthetic data generation: https://faker.readthedocs.io/
- spaCy — NLP for Presidio (es_core_news_lg): https://spacy.io/models/es
- reportlab — PDF generation for test fixtures: https://www.reportlab.com/docs/
- fpdf2 — PDF generation alternative: https://py-pdf.github.io/fpdf2/
- GDPR — Reglamento General de Protección de Datos: https://gdpr.eu/
- structlog — Structured logging: https://www.structlog.org/
- Pydantic — Data models: https://docs.pydantic.dev/
- FastAPI — File uploads (multipart): https://fastapi.tiangolo.com/tutorial/request-files/
- pandas — Data analysis library: https://pandas.pydata.org/docs/
