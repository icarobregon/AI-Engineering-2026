# Sesión 9 — Fundamentos de RAG y técnicas de recuperación

## Objetivo de la sesión

Al cierre del Módulo 3 el servicio IA tiene el corpus de presupuestos históricos vectorizado en pgvector, los embeddings calculados y los chunks bien estructurados. Lo que todavía no puede hacer es lo que el proyecto persigue desde el primer día: recibir la transcripción de una reunión y devolver una estimación fundamentada en esos presupuestos. Los datos por sí solos no estiman nada.

La Sesión 9 abre el Módulo 4 (Arquitectura RAG) construyendo las dos capas que faltan para convertir esos datos en respuestas útiles: el **retrieval** que recupera el material relevante y la **generación** que produce la respuesta a partir de él. El proyecto sigue siendo el estimador automático de software a partir de transcripciones de reuniones, el mismo que durante las próximas tres semanas se convierte en un servicio RAG operable en producción.

Al final de la sesión, el servicio IA implementa el flujo RAG canónico completo (Query → Retrieval → Augmentation → Generation) sobre dos módulos nuevos —`retrieval/` y `generation/`— sin tocar los existentes (`ingest/` de la Sesión 06, `embedding_pipeline/` de la Sesión 07, `storage/` de la Sesión 08), y lo expone como un servicio operable: dos routers FastAPI con contratos y credenciales separados, rate limiting diferenciado, idempotencia, logging estructurado por etapa y un cliente Ruby robusto desde el backend de negocio.

Lo que **no** entra en esta sesión y se trabaja en la siguiente: reranking con cross-encoders, búsqueda híbrida, expansión y descomposición de consultas, multi-índice y routing (todo ello, Sesión 10).

## Qué vas a aprender

### 1. 📋 Del CAG estático al flujo RAG: las cuatro etapas y por qué el retrieval domina — 25 min

Parte del techo real del sistema cerrado en la Sesión 05: el conocimiento del CAG está congelado en el momento en que se montó el system prompt. Mientras la transcripción describa proyectos parecidos a los presupuestos que se metieron en contexto, el modelo estima decentemente; en cuanto el cliente menciona algo que el prompt no cubre, el modelo o inventa apoyándose en su conocimiento paramétrico o produce un número razonable sin fundamento real en datos de la empresa. La pregunta arquitectónica cambia de *"qué presupuestos meto en el prompt"* a *"cómo encuentro, en el momento de la petición, los presupuestos más relevantes para esta transcripción"*.

El artículo desmonta las **cuatro etapas canónicas** del patrón RAG (nomenclatura de Lewis et al., 2020, que ha aguantado sin cambios significativos pese a variantes como Agentic RAG, GraphRAG o Self-RAG, todas ellas sofisticaciones de alguna de las cuatro, no reorganizaciones del flujo):

- **Query** — convierte la entrada en algo que la búsqueda pueda usar. En un RAG de manual es embeber la pregunta tal cual; con transcripciones de miles de tokens con ruido conversacional, anáforas y temas mezclados, la etapa hace trabajo real: extraer requisitos, descomponer sub-temas, generar consultas optimizadas.
- **Retrieval** — recibe la query optimizada y devuelve los chunks más relevantes. La versión naive de la Sesión 08 es top-K por coseno sin filtros ni umbral; en producción combina similitud vectorial con filtros estructurales, umbrales de calidad y eventualmente reranking.
- **Augmentation** — ensambla los chunks en un bloque de contexto que el LLM pueda usar bien: orden (mitigando *lost in the middle*), delimitadores, truncamiento y metadata para permitir citación.
- **Generation** — llamada al LLM con grounding explícito, política de contexto insuficiente, formato de salida estructurado y validación posterior de citaciones.

El orquestador del flujo, en código, son cinco líneas —cada una un punto de fallo y una decisión de diseño:

```python
async def estimate_from_transcript(transcript: str) -> EstimateResponse:
    structured_query = await query_reformulator.reformulate(transcript)
    chunks = await retriever.search(
        query=structured_query,
        top_k=10,
        threshold=0.65,
        filters=structured_query.metadata_filters,
    )
    context = context_assembler.assemble(chunks, max_tokens=4000)
    estimate = await generator.generate(
        transcript=transcript,
        context=context,
        schema=EstimateSchema,
    )
    return estimate
```

**Las cinco diferencias operativas entre CAG y RAG** que importan (más allá del "tamaño del contexto"): *frescura del conocimiento* (añadir un presupuesto pasa de editar prompt + redesplegar a un `POST /v1/retrieval/insert`); *techo del corpus* (CAG está limitado por la ventana del modelo — 800 proyectos × 3.000 tokens son 2,4 M de tokens; RAG no tiene ese techo); *latencia y coste por petición* (aquí RAG pierde: cuatro llamadas frente a una con prompt caching, coste 3-4× superior); *trazabilidad y auditoría* (RAG puede responder exactamente qué presupuestos se recuperaron y qué contexto se montó); y *resistencia a la alucinación* (RAG con prompt de grounding reduce la tasa de forma medible, no la elimina).

Matiz importante que la literatura industrial cuenta mal: **RAG no es "mejor" que CAG, es distinto**. El paper *"Don't Do RAG: When Cache-Augmented Generation is All You Need for Knowledge Tasks"* (Chan et al., 2024) demuestra empíricamente que con corpus pequeño y estable CAG es más simple y produce mejores respuestas en métricas estándar de QA — el modelo "ve" todo el corpus en una atención completa en lugar de un subconjunto elegido por un retriever falible. CAG sigue siendo respetable para corpus de menos de ~100.000 tokens efectivos, estables, donde el coste por petición importa y la trazabilidad no es crítica. También existe la vía híbrida (contexto base estable por CAG, contexto variable por RAG), mencionada como dirección futura pero fuera del alcance del módulo.

Cierra con el mantra operativo que estructura todo el módulo: **"no amount of prompt engineering fixes bad retrieval"**. El techo de calidad del sistema entero está fijado por la calidad del retrieval; las otras tres etapas pueden empujar hacia ese techo, no por encima. De ahí el orden de prioridades ante un fallo: ¿recupero los chunks correctos? → ¿ensamblo bien el contexto? → ¿el prompt fuerza grounding? → y solo en último lugar, ¿el modelo es suficientemente capaz?

### 2. 📋 Reformulación de queries — 25 min

Explica por qué embeber la transcripción cruda y pasarla al endpoint de búsqueda de la Sesión 08 no basta, con tres causas concretas y mundanas: **la longitud disuelve la señal** (el embedding de 2.000 tokens con cinco temas mezclados es el centroide de cinco regiones, cerca de ninguna; las distancias coseno se comprimen alrededor de un valor medio mediocre), **el ruido conversacional ahoga las keywords técnicas** (el embedder no sabe que "marketplace", "KYC", "BaFin" o "SAP" son las siete palabras que importan entre los conectores coloquiales) y **las anáforas no significan nada para el modelo de embeddings** ("lo que hablábamos el otro día", "lo nuestro" contaminan el vector con señal que no remite a nada).

Recorre las **cinco familias de reformulación** con su precio respectivo:

- **Query rewriting** — el LLM reformula la entrada como consulta técnica concisa. Funciona con entradas cortas mal formuladas, mal con entradas largas multi-tema por la compresión arbitraria.
- **Sub-query decomposition** — el LLM produce N sub-queries por sub-tema, cada una se ejecuta contra el retriever y los resultados se fusionan (típicamente con Reciprocal Rank Fusion). Mejora el recall notablemente; cuadruplica búsquedas, embeddings y complejidad.
- **Step-back prompting** — sube un nivel de abstracción antes de buscar. Brilla en QA sobre conocimiento estructurado, rinde peor en dominios *narrow* como estimación de software donde el "concepto general" es difuso.
- **HyDE (Hypothetical Document Embeddings)** — el LLM genera una respuesta hipotética y se embebe ese documento sintético, porque un documento se parece más a otros documentos en el espacio vectorial que una pregunta corta. Funciona muy bien con dominios estables y conocidos por el modelo; peor cuando alucina tecnologías que la empresa nunca ha usado.
- **Extracción estructurada** — el LLM devuelve un JSON validable contra un esquema explícito (función, tecnologías, sector, escala, geografía, regulaciones, restricciones). **Es la elección por defecto del programa.**

La razón de la elección no es que sea la más sofisticada —HyDE produce vectores ligeramente mejores en benchmarks académicos puros— sino el balance en las cuatro dimensiones que importan en producción: *coste y latencia* (una sola llamada, output de 50-100 tokens frente a los 200-400 de HyDE), *debugabilidad* (es la única que produce un artefacto inspectable: puedes mirar el JSON intermedio y ver si el reformulador entendió mal el sector o se le escapó una tecnología clave) y sobre todo *utilidad downstream* (sus campos categóricos alimentan directamente los filtros de metadata del retriever — información que las otras cuatro técnicas pierden).

El artículo detalla el esquema Pydantic canónico del proyecto, la llamada con la Responses API de OpenAI en modo `json_schema` estricto, la función `compose_search_text()` que compone el texto sintético que efectivamente se embebe, y el **patrón de fallback**: cuando la validación del JSON falla, el sistema cae a query rewriting puro, y ese fallback debe activarse y registrarse (si nunca se activa, el reformulador es demasiado tolerante; si se activa más del 5%, hay un problema sistemático con el prompt o el esquema). La mejora de recall frente a la transcripción cruda es típicamente de 2× a 5× según el corpus.

Cierra con dos ideas operativas. **Cuándo subir a algo más sofisticado**: HyDE si el corpus es muy descriptivo y el modelo conoce bien el dominio; sub-query si las transcripciones son consistentemente multi-tema con temas ortogonales; híbrido (extracción para filtros + HyDE para búsqueda semántica) como evolución natural tras semanas de uso — nunca como elección inicial, porque complicar antes de medir produce sistemas difíciles de depurar cuyas mejoras marginales ni siquiera son medibles al no haber baseline. Y: **la reformulación no es un detalle de implementación del retriever, es una capa con vida propia** que merece prompt versionado, esquema versionado, instrumentación y test suite propios; la mayor parte de las regresiones de calidad en producción vienen de aquí.

### 3. 📋 Retrieval que no es solo cosine: top-K, threshold y filtros sobre pgvector — 30 min

Parte de las dos sorpresas que aparecen la primera vez que se pasa la salida del reformulador por el retriever de la Sesión 08. **Los resultados clónicos**: pides diez chunks y ocho pertenecen al mismo presupuesto histórico, porque solo hay un proyecto realmente similar y top-K=10 exige rellenar las diez posiciones. **Las distancias comprimidas**: pides diez y te dan diez, pero todas las distancias están alrededor de 0.7-0.8 — ninguno es realmente similar, todos son mediocres, y la estimación resultante será una alucinación apoyada en presupuestos genéricamente parecidos.

Causa común: el retriever usa una sola palanca (top-K) y le faltan dos disciplinas — **calidad mínima** y **filtrado estructural**.

**Top-K y sus tres costes.** El reflejo de subir K ante resultados pobres tiene consecuencias medibles: el coste del prompt de generación se multiplica casi linealmente (cada chunk son 200-400 tokens; de K=10 a K=30 son 4.000-8.000 tokens extra, de 0,50 € a 1,50 € por petición); el ruido degrada la respuesta por *lost in the middle*; y subir K **oculta el problema real** — el sistema está diciendo "tu corpus no tiene más material relevante" y disfrazarlo con resultados de baja calidad destruye esa señal. Regla del programa: K moderado y estable (10 para el proyecto) y que el threshold decida cuántos entran realmente. El número de chunks por petición es un emergente, no un parámetro: a veces diez, a veces tres, **a veces cero — y cero es información válida, no un fallo**.

**Threshold.** En pgvector el operador `<=>` produce cosine distance entre 0 y 2; el rango típico para embeddings de OpenAI está entre 0.5 y 0.7. El número no se decide por intuición: se toman 20-30 transcripciones representativas, se pasan por el reformulador, se busca con K=50 sin threshold y se grafica la distribución. Aparecen dos grupos —los genuinamente relevantes (0.3-0.5) y el ruido (0.7-0.9)— y el threshold se coloca en el valle, que para `text-embedding-3-small` sobre corpus especializado suele caer en **0.6-0.65**.

```sql
SELECT c.id, c.content, c.metadata,
       c.embedding <=> :query_embedding AS distance
FROM chunks c
WHERE c.embedding <=> :query_embedding < :distance_threshold
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

Detalle operativo: mantener alineados el *operator class* del índice HNSW (`vector_cosine_ops`) y el operador de la query (`<=>`) es condición previa para que cualquier ajuste tenga el comportamiento esperado — el antipatrón silencioso de la Sesión 08. Y el comportamiento cuando nada supera el threshold merece decisión explícita: el programa adopta **soft-fail** (lista vacía + `low_confidence: true`), y el orquestador no llama al generador con contexto vacío sino que responde "no hay evidencia suficiente en el corpus histórico; revisar manualmente". Relajar el threshold dinámicamente es una alternativa válida pero introduce no-determinismo y dificulta el debug; queda como mejora opcional.

**Filtros de metadata: tres estrategias en pgvector.** *Pre-filtering* (WHERE estructural antes de la búsqueda vectorial) es correcto con filtros de alta selectividad; la vieja advertencia de que destruía el índice HNSW ha cambiado desde pgvector 0.7 gracias a los *iterative scans* sobre HNSW filtrado, razonables por debajo del 20% de selectividad — el programa lo adopta como estrategia por defecto. *Post-filtering* (buscar con `wide_k = top_k × 3` y filtrar después) es correcto con baja selectividad, a riesgo de perder recall si el filtro resulta muy selectivo y no hay instrumentación que lo detecte. *In-query filtering* es la fusión moderna: se escribe como pre-filtering y el planner decide internamente. Los cuatro filtros que merece exponer la API son `sectors`, `project_year_range`, `tech_stack` (vía operador JSONB `@>`) y `chunk_types`, todos con el patrón `(:filter IS NULL OR ...)` para que sean opcionales y encadenen directamente con los campos nullable del esquema Pydantic del reformulador.

**Cuatro anti-patrones** a reconocer: subir K para arreglar la calidad; confiar en el LLM como filtro final (el modelo no compara sistemáticamente chunks entre sí ni rechaza lo irrelevante con disciplina — el filtrado se hace en el retriever, el LLM sintetiza); omitir el threshold porque "casi siempre hay algo en el corpus"; y mezclar `chunk_types` sin filtrar cuando el reformulador da pistas claras.

Cierra con el trade-off de fondo: **recall vs precision**. En RAG didáctico la convención es priorizar recall; en producción, cuando el LLM sintetiza una respuesta con consecuencias económicas, la posición correcta es priorizar **precision**, porque la asimetría entre los dos errores es brutal — una alucinación apoyada en chunks parcialmente relevantes es más peligrosa que un "no lo sé" honesto. Una estimación de 250.000 € sin evidencia sólida crea una expectativa que nadie puede honrar; un "revisa esto manualmente" preserva la confianza en las estimaciones que sí se producen.

### 4. 📋 Augmentation: ensamblar contexto para que el LLM lo use bien — 32 min

Empieza desmontando la tentación del `"\n\n".join(...)` que enseña la mitad de los tutoriales de RAG. El código funciona —no lanza excepciones, devuelve algo que parece una estimación— y produce con regularidad incómoda tres fallos: **citas inventadas** (identificadores que parecen razonables de proyectos que no estaban entre los chunks), **mezclas cruzadas** (información de chunks distintos combinada como si fuera un único proyecto) y **respuesta sin contexto** (el modelo ignora silenciosamente los chunks y responde desde su conocimiento entrenado, dejando la falsa impresión de que el retrieval funcionó). Causa común: el modelo no ha recibido instrucciones sobre cómo tratar ese bloque de texto. La augmentation no es "meter chunks en el prompt"; son cinco decisiones de diseño.

**Delimitadores XML.** Los modelos modernos reconocen `<source>`, `<context>` o `<document>` como límites semánticamente significativos. El ensamblador (`generation/context_assembler.py`) envuelve cada chunk como `<source id="142" sector="..." project_year="..." chunk_type="..." distance="0.412">…</source>`, con tres decisiones deliberadas: la metadata va como atributos XML y no embebida en prosa (permite citar con precisión sin reparsear); se incluye la `distance` (posición debatible — el programa la expone porque da al modelo una señal explícita de relevancia); y la etiqueta es `<source>` en singular por su connotación de unidad atribuible de información. La alternativa de *JSON delimited context* funciona pero falla en silencio: los modelos tienden a leer estructuras JSON como datos a interpretar, no como contexto autoritativo.

**Orden de los chunks: *lost in the middle* es real y predecible.** El paper de referencia es *"Lost in the Middle: How Language Models Use Long Contexts"* (Liu et al., 2023): la curva de precisión tiene forma de U — el modelo recupera bien la información al principio y al final del contexto, y la pierde con regularidad en el medio, con caídas de hasta veinte puntos porcentuales. El efecto se ha replicado en GPT-4, Claude y modelos posteriores; no es artefacto de una arquitectura. El programa adopta *most-relevant-first* sin más artificio para K=5-10 (los chunks más relevantes ya caen en las posiciones privilegiadas) y deja `reorder_u_pattern()` como opción configurable, desactivada por defecto, para cuando K sube a 15-20.

**Truncamiento defensivo.** El antipatrón es cortar por caracteres o palabras al llegar al límite: el chunk truncado pierde coherencia, cualquier cita a su id es estructuralmente inválida y sus tokens aportan menos que cero. Regla del programa: **si el chunk no cabe entero, no entra**. Dos detalles clave — contar los tokens del chunk *ya envuelto* con sus delimitadores y metadata (30-50 tokens por chunk que, ignorados, dejan el budget consistentemente optimista) y reservar margen para la salida (heurística: 15% del budget total para output y 5% para overhead de prompt).

**El prompt de generación.** La diferencia entre un prompt mediocre y uno disciplinado son cuatro elementos: restricción de fuentes (`ONLY` en mayúsculas — el contraste tipográfico es una señal que los modelos reconocen como énfasis), obligación de citar cada afirmación cuantitativa con su `source id`, prohibición explícita de inventar ids con un camino alternativo ("surface as assumption") que reduce la presión para alucinar, y política de insuficiencia (`confidence="insufficient"` en lugar de forzar una estimación). El user prompt reactiva la instrucción crítica al final, porque los modelos atienden de forma especialmente fuerte al cierre del prompt.

**Structured output como contrato.** La misma mecánica de Responses API + `json_schema` strict que el reformulador, con un esquema que captura la estimación y sus metadatos de trazabilidad: `total_engineer_days` y `duration_weeks` como `int | None` (a `None` cuando `confidence == "insufficient"`), `CostComponent` con su propia lista de `sources` para trazabilidad fina por componente, `Assumption` separando qué se asume de por qué, y `insufficient_context_explanation` como camino de soft-fail simétrico al del retriever. Modelo `gpt-5` (no `gpt-5-mini`: sintetizar evidencia de múltiples fuentes y decidir cuándo no estimar es genuinamente complejo) con `reasoning.effort="medium"` — la palanca que en los reasoning models sustituye a `temperature`, ya no válido en gpt-5.

**Validación post-generación.** El structured output garantiza la forma, no la coherencia semántica con los chunks recuperados. La verificación crítica es de citaciones: comparar los `source_id` citados contra los ids realmente recuperados. Si hay ids inválidos, tres opciones — reintentar con "your previous response cited invalid source ids: …" (opción por defecto, máximo un reintento), degradar la confianza automáticamente, o rechazar y devolver "requiere revisión manual" (fallback si el reintento también falla). Además: coherencia de `confidence` (decir "insufficient" pero rellenar números es respuesta malformada) y sanidad numérica (marcar para revisión sin bloquear).

Cierra con trade-offs honestos sobre el control de la "creatividad" (con prompt bien estructurado y schema strict la variabilidad inter-llamadas ya es muy baja sin tocar parámetros), instrucción estricta vs flexible (severo es mejor que cómplice cuando el output influye en presupuestos) y el coste de las citaciones obligatorias (+10-20% de tokens de salida, justificado porque distingue una estimación "que el sistema produjo" de una "que el sistema puede defender").

### 5. 📋 La capa de datos como servicio: aislar y securizar el retriever — 32 min

Plantea el escenario realista del segundo o tercer mes en producción: el equipo comercial quiere buscar proyectos similares desde el CRM sin generar estimación. Las dos salidas fáciles —añadir `?retrieval_only=true` al endpoint existente, o duplicarlo— crean tres problemas que no se ven hasta meses después. **Blast radius**: cuando la Sesión 10 introduzca reranking, cualquier cambio toca el endpoint de estimación aunque la generación no varíe. **Rate limiting**: estimate necesita un régimen severo (euros y segundos por llamada), retrieval puede ser permisivo (milisegundos y céntimos); el mismo límite o estrangula al barato o desprotege al caro. **Granularidad de credenciales**: dar la misma API key para un script de análisis implica dar permiso para gastar el presupuesto de LLM.

Conclusión: retriever y generador son dos servicios lógicos distintos que casualmente comparten codebase. El artículo aplica el patrón inverso — **dos `APIRouter` de FastAPI, dos contratos públicos, dos regímenes de seguridad** — montados con prefijos distintos (`/v1/retrieval`, `/v1/estimate`). La asimetría entre contratos es deliberada: retrieval expone palancas operativas (`top_k`, `distance_threshold`, filtros) porque sus consumidores pueden querer ajustar comportamiento; estimate expone solo la transcripción, porque el backend de negocio no debería saber qué `top_k` se usa internamente.

**API Keys y constant-time comparison.** El consumidor es siempre otro servicio interno, así que API Key es lo correcto: simple, sin estado, sin OAuth ni servidor de identidad. Dos claves separadas (`RETRIEVAL_API_KEY`, `ESTIMATE_API_KEY`) y comparación con `secrets.compare_digest` en lugar de `==`: la comparación nativa de strings es *non-constant-time* y termina en el primer carácter distinto, creando un canal lateral medible (timing attack) que sobre red local con muchas peticiones es explotable. El coste de la versión segura es cero. Se menciona la rotación *graceful* (aceptar `KEY` y `KEY_PREVIOUS` simultáneamente durante la ventana de migración), que se cubre en S15.

**Rate limiting diferenciado con slowapi.** Montado como middleware de Starlette, con `key_func` por API key en lugar de por IP — crítico porque el backend de negocio puede compartir IP tras un NAT o proxy y el límite por IP sería trivial de saturar bloqueando a usuarios legítimos. Los regímenes: **120/minuto para retrieval** (un milisegundo de latencia, nada significativo de infraestructura) y **10/minuto para estimate** (5-15 segundos y 0,20-1 € en tokens por petición; 600/hora es suficiente para un equipo comercial y protege contra *runaway costs*). La respuesta 429 debe ser informativa: header estándar `Retry-After` más `retry_after_seconds` en el body.

**Idempotencia.** Si el backend reintenta porque su HTTP client cortó el socket, no debe generarse una segunda estimación con coste duplicado y resultado distinto. El cliente envía un `idempotency_key` (UUID que él genera), el servicio cachea `key → estimate` con TTL de 24 h (suficiente para reintentos legítimos, sin convertir la caché en repositorio implícito de estimaciones históricas). Sutileza conocida: si llega la misma key con transcripción distinta, lo correcto es hashear la transcripción y devolver 409 Conflict — mejora opcional fuera del scope.

**Logging estructurado por etapa.** `structlog` con salida JSON y un context manager `log_stage()` que envuelve las cinco etapas internas (reformulación, retrieval, ensamblado, generación, validación). El `request_id` es lo que ata todas las líneas de una petición en una traza coherente y viaja de vuelta como header `X-Request-ID` para que el backend correlacione sus logs con los del servicio. Cada etapa registra `duration_ms` más un campo específico de debug (`sectors` en retrieval, `chunks` en assembly, `confidence` en validation).

**El cliente Ruby.** Faraday con timeouts diferenciados (`open_timeout` 5 s para detectar rápido que el servicio está caído, `timeout` total 30 s para cubrir el peor caso del LLM), retry policy restringido a 502/503/504 (reintentar un 400 o 401 no tiene sentido; un 500 puro es ambiguo) y generación por defecto del `idempotency_key` con `SecureRandom.uuid`, de forma que si Faraday reintenta, la misma clave viaja al servicio y la idempotencia se activa sin que el programador tenga que pensarlo.

Cierra con trade-offs: **API Key vs JWT vs mTLS** (API Key no lleva identidad más allá de "alguien que tiene esta clave" y es explotable si se filtra; JWT mitiga lo primero, mTLS ambas a costa de gestión de certificados y CA — para un servicio interno con un consumidor controlado, API Key es el mejor coste/beneficio; con múltiples consumidores externos, JWT; con service mesh, mTLS casi gratis), el **OWASP API Security Top 10** como lectura complementaria y reflejo a revisar cada vez que se añade un endpoint, y el **rate limiting in-memory vs distribuido** (slowapi cuenta en memoria del proceso: con varios workers el límite efectivo se multiplica; Redis como backend llega en S15 y es cambio de configuración, no de código).

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Diagnóstico arquitectónico del sistema RAG actual

**Fecha límite indicada por el programa:** domingo 19 de julio, final del día.
**Tiempo estimado:** entre 1 h y 1 h 30 min. Si supera las dos horas, se está bajando a un nivel de detalle que esta fase no necesita.
**Repositorio de referencia del programa:** https://github.com/LIDR-academy/ai-engineering/tree/session_09

**Objetivo.** Producir un único documento de diagnóstico arquitectónico que (a) describa el estado actual del servicio IA tras las Sesiones 06-08, (b) registre el comportamiento observable del sistema cuando se le pasa una transcripción cruda, (c) identifique los fallos concretos del comportamiento actual y (d) proponga, a nivel de cajas y flechas, cómo debe evolucionar la arquitectura para cerrar el bucle hasta la estimación generada.

Este ejercicio **no pide código nuevo**: pide ejecutar lo que ya existe contra una transcripción realista, observar qué pasa y razonar sobre los gaps, para llegar al directo con un mapa mental del propio sistema y preguntas formuladas desde la evidencia, no desde la intuición.

**Material de partida.** El repositorio del proyecto `estimator` en el estado en que quedó al cierre de la Sesión 08: servicio IA con `ingest/`, `embedding_pipeline/` y `storage/` operativos, PostgreSQL + pgvector inicializado con el seed de presupuestos históricos, y los endpoints HTTP construidos hasta ahora (encode de embeddings y búsqueda semántica). Más tres transcripciones de ejemplo en `examples/transcripts/`:

- `01_clear.txt` — el cliente describe con claridad lo que necesita y menciona explícitamente tecnologías y sector.
- `02_ambiguous.txt` — el cliente divaga, mezcla temas y solo en un par de frases da pistas concretas. **Es la transcripción que se usa para el trace.**
- `03_hard.txt` — el cliente menciona varias features posibles, cambia de opinión a mitad de conversación y termina sin cerrar el alcance.

Y un fichero `TEMPLATE.md` con la estructura del entregable y los headers de las cuatro secciones obligatorias.

#### Sección 1 — Diagrama de la arquitectura actual

Dibujar la arquitectura de tres capas (frontend, backend de negocio, servicio IA) con los módulos del servicio IA que existen al cierre de la Sesión 08. Para el servicio IA, bajar un nivel: mostrar `ingest/`, `embedding_pipeline/`, `storage/` y los endpoints HTTP expuestos hoy. Marcar con sombreado, color o anotación dónde acaba lo implementado. **No dibujar lo que falta** — eso es trabajo de la sección 4.

Formato libre: ASCII, Mermaid en un bloque de código Markdown, captura de un boceto a mano o imagen exportada. Lo que importa es que se entienda qué módulo habla con cuál, qué dato fluye entre ellos, y en qué punto el flujo se queda corto si llegara una transcripción.

#### Sección 2 — Trace anotado de una transcripción

Coger `02_ambiguous.txt` y hacer un trace manual a través del sistema tal como está. Cada paso con la llamada ejecutada, la respuesta cruda y un comentario propio de una o dos frases:

1. **Embeber la transcripción completa** contra el endpoint o módulo de embeddings. Pegar la primera y última componente del vector resultante, su norma o dimensionalidad, y comentar qué representa ese vector dado el contenido de la transcripción.
2. **Llamar al endpoint de búsqueda semántica** con ese vector (o con la transcripción, según cómo se implementara en S08) pidiendo los 5 chunks más similares. Pegar la respuesta cruda con los chunks y sus distancias o similitudes.
3. **Comentar cada chunk devuelto**: a qué presupuesto histórico pertenece, de qué sector es, y si parece relevante para lo que el cliente pide. Ser honesto: si el resultado es bueno, decirlo; si no lo es, también.

Usar `curl`, HTTPie, un script corto en Python o una colección de Postman. Pegar los comandos exactos para que el resultado sea reproducible. **El código de las llamadas, los payloads y los nombres de campo van en inglés; las observaciones van en español.**

#### Sección 3 — Diagnóstico: cinco fallos identificados

A partir del trace y del conocimiento del estado actual, enumerar **cinco fallos** que hoy impiden que la transcripción se convierta en una estimación de calidad. Para cada uno, tres líneas:

- **Problema observado** — qué se ve que pasa, referenciando idealmente el trace.
- **Causa probable** — qué decisión arquitectónica o ausencia de pieza lo provoca.
- **Propuesta de solución** — qué pieza, etapa o cambio lo resolvería, sin entrar en cómo implementarlo.

Los fallos deben ser concretos y verificables. *"El sistema no es bueno"* no es un fallo. *"Cuando embebo una transcripción de 4.000 tokens y comparo con chunks de 300 tokens, las distancias coseno comprimen mucho y todos los chunks devuelven scores parecidos"* sí lo es. Si se encuentran más de cinco, escoger los cinco más relevantes y dejar el resto en una sección de "otros".

#### Sección 4 — Propuesta de evolución arquitectónica

Dibujar un segundo diagrama de la misma arquitectura de tres capas, ahora con las cajas y módulos que se añadirían al servicio IA para completar el flujo desde la transcripción hasta la estimación generada. No es una propuesta de implementación: son cajas, flechas y nombres. **Marcar claramente cuáles son nuevas** respecto al diagrama de la sección 1.

Acompañar de un párrafo breve (máximo diez líneas) que responda a tres preguntas: ¿cuál es la responsabilidad de cada módulo nuevo?, ¿qué dato fluye entre ellos?, y ¿qué pieza es la más crítica — la que se atacaría primero si solo se pudiera construir una?

#### Entregable y criterios de aceptación

Un único archivo `arquitectura-actual.md` en la raíz del repositorio con las cuatro secciones. Subirlo en una rama nueva `session-09/pre-work` y abrir PR contra `main` (convención usada desde la Sesión 02). No hace falta que el PR se mergee antes del directo; el branch basta.

El entregable está completo si las cuatro secciones existen, el trace de la sección 2 incluye comandos ejecutables y respuestas reales del sistema, los cinco fallos de la sección 3 referencian observaciones del trace y no afirmaciones genéricas, y los dos diagramas son distinguibles entre sí y muestran claramente qué cambia entre el estado actual y el propuesto.

#### Qué NO hay que hacer

- No implementar reformulación de queries, ni reranking, ni un nuevo retriever, ni modificar el endpoint de búsqueda actual.
- No escribir el módulo de generación ni crear nuevos endpoints.
- Si en algún momento se está escribiendo Python que va más allá de un script cliente para las llamadas del trace, **parar** — eso es trabajo para el directo y las próximas sesiones.
- No buscar en internet la arquitectura RAG canónica para copiarla en la sección 4. Si la sección 4 acaba siendo "Query → Retrieval → Augmentation → Generation" sin más, no se está haciendo el ejercicio: se está repitiendo terminología.

#### Cómo entregar

Además de subir la rama y abrir el PR, enviar por mail a `george@lidr.co` el enlace completo a la rama (URL de GitHub) hasta dos días antes de la sesión en vivo. El plazo es estricto: el equipo necesita margen para revisar las entregas y preparar el material del directo según los problemas reales encontrados. La rama debe ser accesible: repositorio público o, si es privado, con permisos para el revisor indicado en el canal del programa.

---

### 🛠️ Contexto técnico para la implementación

Todo lo que sigue son las decisiones y contratos que la sesión fija para construir el flujo RAG completo sobre el servicio IA. Es el material de referencia para implementar con Claude Code CLI.

#### Estructura de módulos objetivo

Dos carpetas nuevas; los módulos existentes (`ingest/` de S06, `embedding_pipeline/` de S07, `storage/` de S08) **no se tocan** y quedan como dependencias estables. Esa separación permite que S10 evolucione el retriever con reranking sin tocar generación, y al revés.

```
src/estimator/
├── api/
│   ├── main.py
│   ├── security.py
│   └── routers/
│       ├── retrieval.py
│       └── estimate.py
├── retrieval/
│   ├── query_reformulator.py
│   └── retriever.py
└── generation/
    ├── context_assembler.py
    ├── prompt_builder.py
    └── estimator.py          # orquestador del flujo
```

#### Etapa Query — `retrieval/query_reformulator.py`

Esquema Pydantic canónico del proyecto:

```python
from pydantic import BaseModel, Field
from typing import Literal

class EstimationQuery(BaseModel):
    function: str = Field(description="Primary product function in 3-7 words")
    technologies: list[str] = Field(
        default_factory=list,
        description="Specific technologies, services, or integrations mentioned"
    )
    sector: str | None = Field(
        default=None,
        description="Industry or vertical if explicitly mentioned"
    )
    scale: Literal["pilot", "small", "medium", "large"] | None = Field(
        default=None,
        description="Project scale if inferable from the conversation"
    )
    country: str | None = Field(
        default=None,
        description="Geographic scope if mentioned"
    )
    regulations: list[str] = Field(
        default_factory=list,
        description="Regulatory frameworks mentioned (GDPR, BaFin, HIPAA, etc.)"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Non-negotiable requirements or hard constraints"
    )
```

Llamada con Responses API y `strict: True` para que el modelo no se desvíe del esquema:

```python
async def reformulate(transcript: str) -> EstimationQuery:
    response = await client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": REFORMULATION_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "EstimationQuery",
                "schema": EstimationQuery.model_json_schema(),
                "strict": True,
            }
        },
    )
    return EstimationQuery.model_validate_json(response.output_text)
```

El system prompt debe instruir al modelo a extraer **solo lo explícitamente mencionado o inequívocamente inferible**, y a dejar campos opcionales en `null` cuando no haya evidencia. La tentación de "rellenar" con sentido común (inferir GDPR porque hay datos personales, Stripe porque hay pagos) es la fuente principal de errores en producción y hay que reprimirla explícitamente en el prompt.

Composición del texto sintético que efectivamente se embebe:

```python
def compose_search_text(q: EstimationQuery) -> str:
    parts = [q.function]
    if q.technologies:
        parts.append(f"with {', '.join(q.technologies)}")
    if q.sector:
        parts.append(f"for the {q.sector} sector")
    if q.country:
        parts.append(f"in {q.country}")
    if q.regulations:
        parts.append(f"compliant with {', '.join(q.regulations)}")
    if q.constraints:
        parts.append(f"requiring {', '.join(q.constraints)}")
    return ". ".join(parts) + "."
```

**Fallback obligatorio:** si la validación del JSON falla, caer a query rewriting puro (texto reformulado libre). Debe activarse *y registrarse*: si nunca se activa, el reformulador es demasiado tolerante con sus salidas; si se activa en más del 5% de los casos, hay un problema sistemático con el prompt o el esquema.

#### Etapa Retrieval — `retrieval/retriever.py`

Parámetros por defecto del programa: `top_k = 10`, `distance_threshold = 0.6` (calibrar en el rango 0.6-0.65 sobre el corpus propio), estrategia **pre-filtering** con `(:filter IS NULL OR ...)` para filtros opcionales.

```sql
SELECT
    c.id,
    c.content,
    c.chunk_type,
    c.metadata,
    c.embedding <=> :query_embedding AS distance
FROM chunks c
JOIN documents d ON c.document_id = d.id
WHERE (:sectors      IS NULL OR d.sector = ANY(:sectors))
  AND (:year_min     IS NULL OR d.project_year >= :year_min)
  AND (:year_max     IS NULL OR d.project_year <= :year_max)
  AND (:tech_filter  IS NULL OR c.metadata @> :tech_filter::jsonb)
  AND (:chunk_types  IS NULL OR c.chunk_type = ANY(:chunk_types))
  AND c.embedding <=> :query_embedding < :distance_threshold
ORDER BY c.embedding <=> :query_embedding
LIMIT :top_k;
```

Variante post-filtering (cuando el filtro tiene baja selectividad), con `wide_k = top_k × 3`:

```sql
WITH top_candidates AS (
    SELECT c.id, c.content, c.metadata, c.document_id,
           c.embedding <=> :query_embedding AS distance
    FROM chunks c
    WHERE c.embedding <=> :query_embedding < :distance_threshold
    ORDER BY c.embedding <=> :query_embedding
    LIMIT :wide_k
)
SELECT t.*
FROM top_candidates t
JOIN documents d ON t.document_id = d.id
WHERE d.sector = ANY(:sectors)
ORDER BY t.distance
LIMIT :top_k;
```

**Soft-fail:** si ningún chunk supera el threshold, devolver lista vacía y `low_confidence: true`. El orquestador **no** debe llamar al generador con contexto vacío; debe responder al backend de negocio que no hay evidencia suficiente y que el caso requiere revisión manual.

Precondición: el índice HNSW debe estar creado con `vector_cosine_ops` para alinearse con el operador `<=>` de la query. Un desalineamiento hace que PostgreSQL caiga a sequential scan sin emitir error; se detecta con `EXPLAIN ANALYZE` buscando `Index Scan` frente a `Seq Scan`.

#### Etapa Augmentation — `generation/context_assembler.py`

```python
def build_context_block(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for chunk in chunks:
        meta = [
            f'id="{chunk.id}"',
            f'sector="{chunk.sector}"',
            f'project_year="{chunk.project_year}"',
            f'chunk_type="{chunk.chunk_type}"',
            f'distance="{chunk.distance:.3f}"',
        ]
        attrs = " ".join(meta)
        blocks.append(f"<source {attrs}>\n{chunk.content.strip()}\n</source>")
    return "\n\n".join(blocks)
```

Truncamiento a nivel de chunk completo, contando el chunk **ya envuelto**:

```python
def truncate_to_token_budget(
    chunks: list[RetrievedChunk],
    max_context_tokens: int,
    encoder,
) -> list[RetrievedChunk]:
    selected = []
    used_tokens = 0
    for chunk in chunks:              # already sorted by relevance
        wrapped_size = len(encoder.encode(_wrap_chunk(chunk)))
        if used_tokens + wrapped_size > max_context_tokens:
            break
        selected.append(chunk)
        used_tokens += wrapped_size
    return selected
```

Reordenación en U, **configurable y desactivada por defecto** (activar solo si K sube a 15-20 y se observa degradación):

```python
def reorder_u_pattern(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    front, back = [], []
    for i, chunk in enumerate(chunks):
        (front if i % 2 == 0 else back).append(chunk)
    return front + list(reversed(back))
```

Presupuesto de tokens: reservar el **15%** del total para la salida y un **5%** para overhead de prompt (system message, instrucciones, query estructurada).

#### Etapa Generation — `generation/prompt_builder.py` y `generation/estimator.py`

```python
ESTIMATOR_SYSTEM_PROMPT = """You are a senior software estimation assistant.
Your job is to produce structured budget estimates for new software projects
based on historical reference projects.

Rules you must follow:

1. Base every estimate ONLY on the information contained in <source> blocks.
   Do not rely on general knowledge or training data to set numbers.

2. Cite every quantitative claim with the source id it comes from. Example:
   "Backend implementation: 45 engineer-days (source 142, source 387)".

3. Never invent source ids. If no source supports a claim, surface it as an
   assumption with explicit impact level instead.

4. If the provided context is insufficient to estimate the new project,
   set confidence to "insufficient" and list what additional information
   would be needed. Do not force an estimate.

5. Distinguish evidence-backed components from assumptions you must make
   to bridge gaps in the historical data.

Output must conform to the provided JSON schema."""
```

```python
def build_user_prompt(context_block: str, structured_query: EstimationQuery) -> str:
    return f"""Historical reference projects:

{context_block}

New project to estimate:

{structured_query.model_dump_json(indent=2)}

Generate a structured estimate. Cite sources for every quantitative component.
If the historical context does not cover this kind of project sufficiently,
return confidence="insufficient" and explain what is missing."""
```

Esquema de salida:

```python
from typing import Literal
from pydantic import BaseModel, Field

class SourceCitation(BaseModel):
    source_id: int
    relevance: Literal["primary", "supporting", "tangential"]
    used_for: str = Field(description="Which component this source informed")

class Assumption(BaseModel):
    description: str
    impact: Literal["high", "medium", "low"]
    rationale: str

class CostComponent(BaseModel):
    name: str
    engineer_days: int
    sources: list[int] = Field(description="Source ids that support this component")

class Estimate(BaseModel):
    total_engineer_days: int | None
    cost_breakdown: list[CostComponent]
    duration_weeks: int | None
    sources: list[SourceCitation]
    assumptions: list[Assumption]
    confidence: Literal["high", "medium", "low", "insufficient"]
    reasoning: str
    insufficient_context_explanation: str | None = Field(
        default=None,
        description="If confidence is 'insufficient', explain what is missing"
    )
```

Llamada al modelo (nótese: `gpt-5` para generación, `reasoning.effort` en lugar de `temperature`, que ya no es válido en reasoning models):

```python
response = client.responses.create(
    model="gpt-5",
    input=[
        {"role": "system", "content": ESTIMATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
    text={
        "format": {
            "type": "json_schema",
            "name": "Estimate",
            "schema": Estimate.model_json_schema(),
            "strict": True,
        }
    },
    reasoning={"effort": "medium"},
)
estimate = Estimate.model_validate_json(response.output_text)
```

Validación post-generación de citaciones (no opcional):

```python
def validate_citations(estimate: Estimate, retrieved_chunks: list[RetrievedChunk]) -> list[int]:
    valid_ids = {c.id for c in retrieved_chunks}
    cited_ids = set()
    cited_ids.update(c.source_id for c in estimate.sources)
    for component in estimate.cost_breakdown:
        cited_ids.update(component.sources)
    return sorted(cited_ids - valid_ids)
```

Política ante ids inválidos: reintentar una vez con un mensaje adicional del tipo *"your previous response cited invalid source ids: …"*; si el segundo intento también falla, devolver al backend "estimación no fiable, requiere revisión manual". Validar además la coherencia de `confidence` (si es `"insufficient"`, `insufficient_context_explanation` debe estar presente y los campos numéricos a `None`) y la sanidad numérica (marcar para revisión sin bloquear).

#### Capa de servicio — routers, seguridad y rate limiting

```python
from fastapi import FastAPI
from estimator.api.routers import retrieval, estimate

app = FastAPI(title="Estimator AI Service", version="0.9.0")

app.include_router(retrieval.router, prefix="/v1/retrieval", tags=["retrieval"])
app.include_router(estimate.router, prefix="/v1/estimate", tags=["estimate"])
```

Contrato de retrieval (`POST /v1/retrieval/search`):

```python
class SearchRequest(BaseModel):
    query_text: str = Field(min_length=10, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=30)
    distance_threshold: float = Field(default=0.6, ge=0.0, le=2.0)
    sectors: list[str] | None = None
    project_year_min: int | None = Field(default=None, ge=2010, le=2100)
    chunk_types: list[str] | None = None

class SearchResponseChunk(BaseModel):
    id: int
    content: str
    sector: str
    project_year: int
    chunk_type: str
    distance: float

class SearchResponse(BaseModel):
    chunks: list[SearchResponseChunk]
    low_confidence: bool
    total_candidates_considered: int
```

Contrato de estimate (`POST /v1/estimate/from-transcript`), deliberadamente mínimo:

```python
class EstimateRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=50000)
    idempotency_key: str | None = Field(default=None, max_length=128)
```

Autenticación con dos claves separadas y comparación constant-time:

```python
import os
import secrets
from fastapi import Header, HTTPException, status

RETRIEVAL_API_KEY = os.environ["RETRIEVAL_API_KEY"]
ESTIMATE_API_KEY = os.environ["ESTIMATE_API_KEY"]

def require_retrieval_key(x_api_key: str = Header(...)) -> str:
    if not secrets.compare_digest(x_api_key, RETRIEVAL_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key")
    return x_api_key

def require_estimate_key(x_api_key: str = Header(...)) -> str:
    if not secrets.compare_digest(x_api_key, ESTIMATE_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key")
    return x_api_key
```

Rate limiting con slowapi, por API key (no por IP) y diferenciado por endpoint:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

def get_api_key(request) -> str:
    return request.headers.get("x-api-key", get_remote_address(request))

limiter = Limiter(key_func=get_api_key)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)
```

```python
@router.post("/search", response_model=SearchResponse)
@limiter.limit("120/minute")
def search(request, req: SearchRequest, _: str = Depends(require_retrieval_key)):
    ...

@router.post("/from-transcript", response_model=Estimate)
@limiter.limit("10/minute")
def estimate(request, req: EstimateRequest, _: str = Depends(require_estimate_key)):
    ...
```

Respuesta 429 informativa, con header estándar y campo amigable en el body:

```python
def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "limit": str(exc.detail),
            "retry_after_seconds": 60,
        },
        headers={"Retry-After": "60"},
    )
```

Idempotencia con TTL de 24 h:

```python
def estimate_from_transcript(transcript: str, idempotency_key: str | None = None) -> Estimate:
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key)
        if cached:
            return Estimate.model_validate_json(cached)

    structured_query = reformulate_query(transcript)
    retrieved = search_chunks(...)
    context_block = build_context_block(retrieved.chunks)
    estimate = generate_estimate(context_block, structured_query)

    if idempotency_key:
        idempotency_store.set(
            idempotency_key,
            estimate.model_dump_json(),
            ttl_seconds=86400,
        )
    return estimate
```

Logging estructurado por etapa con `structlog`, `request_id` propagado como header `X-Request-ID`:

```python
@contextmanager
def log_stage(stage: str, request_id: str, **context):
    start = time.perf_counter()
    log = logger.bind(stage=stage, request_id=request_id, **context)
    log.info("stage.started")
    try:
        yield log
        duration_ms = (time.perf_counter() - start) * 1000
        log.info("stage.completed", duration_ms=round(duration_ms, 2))
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        log.exception("stage.failed", duration_ms=round(duration_ms, 2), error=str(exc))
        raise
```

Las cinco etapas a instrumentar: `reformulation`, `retrieval` (con `sectors`), `context_assembly` (con `chunks`), `generation`, `validation` (con `confidence`). Todas con `duration_ms`.

#### Cliente Ruby desde el backend de negocio

```ruby
require "faraday"
require "faraday/retry"
require "securerandom"

class EstimatorClient
  ESTIMATE_TIMEOUT = 30 # seconds
  RETRY_OPTIONS = {
    max: 2,
    interval: 1.5,
    backoff_factor: 2,
    retry_statuses: [502, 503, 504],
    methods: [:post],
  }.freeze

  def initialize(base_url:, api_key:)
    @conn = Faraday.new(url: base_url) do |f|
      f.request :json
      f.request :retry, RETRY_OPTIONS
      f.response :json, content_type: /\bjson$/
      f.options.timeout = ESTIMATE_TIMEOUT
      f.options.open_timeout = 5
      f.headers["X-API-Key"] = api_key
    end
  end

  def estimate_from_transcript(transcript:, idempotency_key: SecureRandom.uuid)
    response = @conn.post("/v1/estimate/from-transcript") do |req|
      req.body = {
        transcript: transcript,
        idempotency_key: idempotency_key,
      }
    end
    raise EstimationError, response.body["detail"] if response.status >= 400
    response.body
  end
end
```

#### Bloques hands-on de la sesión en vivo

Lo que se itera en el directo, útil como batería de experimentos a reproducir:

1. **CAG vs RAG sobre la misma transcripción ambigua** — medir respuesta producida, latencia total, coste en tokens y trazabilidad.
2. **Tres caminos de reformulación** — embedding directo de la transcripción cruda (baseline naive), extracción estructurada y HyDE. Medir cuántos de los chunks recuperados pertenecen al sector y geografía correctos.
3. **Iteración sobre parámetros del retriever** — `top_k` entre 3 y 30, `threshold` entre 0.5 y 0.8, y efecto de los filtros estructurales. Métricas observables: número de chunks devueltos efectivamente, porcentaje de chunks del sector correcto, latencia mediana.
4. **Iteración sobre el prompt de generación** — partir del prompt mínimo y añadir restricciones de una en una: delimitadores XML → grounding explícito (`ONLY`) → obligación de citar → política de insuficiencia, observando el cambio en la salida en cada paso.
5. **Demo de *lost in the middle*** — mismo set de cinco chunks, dos órdenes distintos (most-relevant-first vs. chunk crítico en posición tres), comparar las estimaciones resultantes.
6. **Rate limit e idempotencia** — poner el límite de estimate en 2/minuto, lanzar tres peticiones desde el cliente Ruby, observar el 429 y el `Retry-After`, y ver la respuesta cacheada volver en milisegundos gracias al `idempotency_key`.
7. **Incidente de seguridad simulado** — filtrar deliberadamente la API key de retrieval en un commit y ejecutar el procedimiento de respuesta: rotación inmediata, deploy de la nueva clave, retirada de la antigua.

---

## 🧩 Implementación realizada

Documentación técnica completa en [`estimator/README.md`](estimator/README.md#sesión-9--flujo-rag-completo-y-capa-de-servicio);
diagnóstico previo (con el trace real que motiva cada decisión) en
[`arquitectura-actual.md`](arquitectura-actual.md).

**Lo construido**, sobre la aplicación tal como la dejó la Sesión 08:

| Etapa | Módulo | Qué hace |
|---|---|---|
| Query | `generation/rag/query_reformulator.py` | Extracción estructurada a `EstimationQuery` (Responses API, `strict`) + `compose_search_text()` + fallback a rewriting registrado |
| Retrieval | `generation/rag/retriever.py` · `store/repository.py` | top-K + umbral de distancia + filtros JSONB (pre y post-filtering) + soft-fail `low_confidence` |
| Augmentation | `generation/rag/context_assembler.py` | Bloques `<source>` con metadata, truncado por presupuesto de tokens contando el wrapper, reorden en U configurable |
| Generation | `generation/rag/generator.py` | Generación fundamentada + `validate_citations()` + reintento único + chequeos de coherencia |
| Orquestación | `domain/estimation_service.py` | `estimate_from_transcript()`: las cuatro etapas componen en el conductor, con las cinco etapas instrumentadas e idempotencia en Redis |
| Servicio | `api/retrieval.py` · `api/estimate_rag.py` · `api/security.py` · `rate_limit.py` | Dos routers con claves y límites independientes, 429 informativo, `X-Request-ID` |

Migración `0003_session9_hnsw.py` (índice HNSW halfvec como precondición del retriever), `country`
añadido a la metadata del chunk, y tres transcripciones de ejemplo en `estimator/examples/transcripts/`.

**Dónde nos separamos del enunciado, y por qué** (detalle en el README del estimator):

- La estructura `src/estimator/{retrieval,generation}` se mapea sobre las capas que ya rigen el
  proyecto (`ARCHITECTURE.md` §3): las cuatro etapas viven en `generation/rag/` y **componen sólo en
  el conductor**, nunca importándose entre sí.
- Los filtros van sobre `chunks.metadata` (JSONB con índice GIN), no sobre `documents.sector` /
  `documents.project_year`, que no existen en este esquema.
- El esquema estricto se deriva con `responses.parse(text_format=...)`: el
  `schema=Model.model_json_schema()` del enunciado no es válido para `strict: True` sin
  post-procesarlo.
- Los contratos previos (`POST /search`, `POST /api/v1/estimate`) quedan intactos; los endpoints
  nuevos conviven con ellos.
- El cliente Ruby del enunciado no se implementa: el frontend de referencia se eliminó del repo y
  construiremos el nuestro más adelante.

**Tres resultados medidos** sobre el corpus propio (17 presupuestos / 60 chunks):

1. **La reformulación es la pieza crítica, y se puede cuantificar.** Con la transcripción ambigua
   embebida en crudo, el presupuesto análogo (`BUD-2024-006`, marketplace multi-vendedor) aparece
   **0 veces** en el top-10 y las distancias se comprimen en un rango de 0.025. Con extracción
   estructurada, sus cuatro componentes ocupan **las cuatro primeras posiciones** (mejor distancia
   0.42 frente a 0.64).
2. **HyDE gana en distancia y pierde en cobertura.** Consigue el mejor valor absoluto (0.3370) pero
   recupera sólo 1 de los 4 chunks análogos: su documento hipotético eligió una de las dos
   capacidades que el cliente mencionó, y buscó sólo esa.
3. **RAG no es sólo más barato que CAG, es auditable.** Con el corpus entero en el prompt el modelo
   citó **0 fuentes**; con los 10 chunks recuperados citó **8**. Mismo modelo, mismo prompt, misma
   transcripción.

```bash
docker compose up -d                                # desde esta carpeta
cd estimator
uv run python scripts/query_examples.py             # siembra el corpus
uv run pytest && uv run pytest -m integration       # 301 unitarios + 8 de integración
uv run python scripts/s09_calibrate_threshold.py    # calibración del umbral (barato)
```

## Checklist antes de la siguiente sesión

- [ ] Sabes enumerar las cuatro etapas del flujo RAG (Query, Retrieval, Augmentation, Generation) y qué responsabilidad concreta tiene cada una.
- [ ] Puedes argumentar las cinco diferencias operativas entre CAG y RAG (frescura, techo del corpus, latencia/coste, trazabilidad, resistencia a la alucinación) y en qué casos CAG sigue siendo la respuesta correcta.
- [ ] Entiendes por qué "el retrieval domina" y sabes aplicar el orden de diagnóstico correcto cuando un sistema RAG falla.
- [ ] Conoces las cinco familias de reformulación de queries y sabes justificar por qué el programa elige extracción estructurada.
- [ ] Tienes `retrieval/query_reformulator.py` devolviendo un `EstimationQuery` validado con `strict: True`, con su fallback registrado.
- [ ] Sabes por qué embeber una transcripción cruda degrada el recall (longitud, ruido conversacional, anáforas) y puedes cuantificar la mejora sobre tu propio corpus.
- [ ] Has calibrado empíricamente el `distance_threshold` mirando la distribución de distancias sobre transcripciones reales, no por intuición.
- [ ] Tu retriever aplica top-K + threshold + filtros estructurales opcionales, y hace soft-fail explícito (`low_confidence`) cuando nada supera el umbral.
- [ ] Conoces las tres estrategias de filtrado en pgvector (pre, post, in-query) y cuándo aplica cada una según la selectividad del filtro.
- [ ] Puedes explicar el trade-off recall vs precision y por qué en estimación la asimetría de errores justifica priorizar precision.
- [ ] Tu `context_assembler.py` envuelve chunks en `<source>` con metadata como atributos y trunca a nivel de chunk completo contando los wrappers.
- [ ] Entiendes el fenómeno *lost in the middle* y sabes cuándo activar la reordenación en U.
- [ ] Tu prompt de generación fuerza grounding explícito, citación obligatoria y política de `confidence="insufficient"`.
- [ ] Validas las citaciones post-generación contra los ids realmente recuperados y tienes definida la política de reintento.
- [ ] Sabes por qué `reasoning.effort` sustituye a `temperature` en los reasoning models y qué valor usa el proyecto para generación.
- [ ] Tienes los dos routers separados (`/v1/retrieval`, `/v1/estimate`) con contratos, claves y rate limits distintos.
- [ ] Usas `secrets.compare_digest` para comparar API keys y sabes explicar el timing attack que evita.
- [ ] Tu endpoint de estimate soporta `idempotency_key` con TTL de 24 h.
- [ ] Tienes logging estructurado por etapa con `request_id` propagado y `duration_ms` en cada una.
- [ ] El cliente que invoca el servicio IA tiene timeouts diferenciados y retry policy restringido a 502/503/504.

## Documentación de referencia

**Papers**

- Lewis et al. (2020) — *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*: https://arxiv.org/abs/2005.11401
- Liu et al. (2023) — *Lost in the Middle: How Language Models Use Long Contexts*: https://arxiv.org/abs/2307.03172
- Chan et al. (2024) — *Don't Do RAG: When Cache-Augmented Generation is All You Need for Knowledge Tasks*: https://arxiv.org/abs/2412.15605
- Gao et al. (2022) — *HyDE: Precise Zero-Shot Dense Retrieval without Relevance Labels*: https://arxiv.org/abs/2212.10496
- Zheng et al. (2023) — *Take a Step Back: Evoking Reasoning via Abstraction in LLMs*: https://arxiv.org/abs/2310.06117

**Retrieval y base de datos**

- pgvector (extensión oficial): https://github.com/pgvector/pgvector
- pgvector — filtrado e iterative scans: https://github.com/pgvector/pgvector#filtering
- PostgreSQL — EXPLAIN: https://www.postgresql.org/docs/current/using-explain.html
- PostgreSQL — funciones y operadores JSONB: https://www.postgresql.org/docs/current/functions-json.html

**Modelos y APIs**

- OpenAI — Responses API: https://platform.openai.com/docs/api-reference/responses
- OpenAI — Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- OpenAI — Reasoning models (y parámetros deprecados): https://platform.openai.com/docs/guides/reasoning
- OpenAI — Embeddings API: https://platform.openai.com/docs/guides/embeddings
- Pydantic v2: https://docs.pydantic.dev/latest/

**Servicio, seguridad y observabilidad**

- FastAPI — Bigger Applications / APIRouter: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- FastAPI — Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- Python — módulo `secrets`: https://docs.python.org/3/library/secrets.html
- slowapi: https://github.com/laurentS/slowapi
- structlog: https://www.structlog.org/
- OWASP API Security Top 10: https://owasp.org/API-Security/
- Faraday (Ruby HTTP client): https://lostisland.github.io/faraday/
- faraday-retry: https://github.com/lostisland/faraday-retry
