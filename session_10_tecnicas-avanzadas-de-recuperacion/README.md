# Sesión 10 — Técnicas de recuperación

## Objetivo de la sesión

Al cierre de la Sesión 9 el pipeline RAG funciona de extremo a extremo: reformula la consulta, recupera presupuestos por similitud vectorial y genera una estimación con ese contexto. El problema es que **"similar" no siempre significa "relevante"**: el sistema recupera el presupuesto de una app de pagos cuando la consulta describe una plataforma de e-commerce. Cercano en el espacio vectorial, inútil para estimar.

La Sesión 10 convierte una recuperación aceptable en una recuperación **precisa**, y lo demuestra con números, no con sensaciones. El eje de la sesión no es acumular técnicas de moda: es incorporar cada una contra una tabla de dos columnas — cuánto gana en relevancia, cuánto cuesta en latencia — y saber decir que no con fundamento cuando la ganancia no paga el peaje de complejidad.

Al final de la sesión, el servicio IA tiene una rama léxica sobre `tsvector` conviviendo con la vectorial en el mismo PostgreSQL, fusión por Reciprocal Rank Fusion, un cross-encoder integrado en un patrón *recall-then-rerank*, y un arnés de medición artesanal con golden set propio que decide qué se queda en el pipeline. Los tres artículos restantes — expansión y descomposición de consultas, multi-índice y routing, y filtrado contextual y temporal — preparan la sesión en vivo, donde el pipeline completo se ensambla en su orden correcto con cada etapa activable por configuración.

## Qué vas a aprender

### 1. 📄 Reranking: cuando el top-k vectorial no es suficiente — 24 min

Parte de la escena que da nombre al problema: una transcripción describe una plataforma de e-commerce (catálogo, carrito, inventario, panel de administración) y el retriever devuelve en primera posición el presupuesto de una app de pagos móviles. No es absurdo — e-commerce y pagos comparten vocabulario, contexto de negocio y tecnologías, y sus embeddings están genuinamente cerca. Pero el grueso del esfuerzo de un e-commerce está en el catálogo y el inventario, no en la pasarela, y estimar con esa referencia sesga el resultado.

El diagnóstico central: **la búsqueda vectorial es excelente encontrando candidatos y mediocre ordenándolos**. La solución no es cambiar de modelo de embeddings ni afinar el chunking, sino añadir una segunda etapa que haga bien lo que la primera hace mal.

El **bi-encoder** codifica cada texto por separado y lo comprime en un vector de dimensión fija. Esa independencia es lo que lo hace viable (los documentos se vectorizan una vez en la ingesta; buscar es comparar contra vectores precalculados), pero la compresión se paga en el ranking fino por dos motivos: *el vector promedia* (un presupuesto de e-commerce con una sección menor sobre pagos produce un embedding que mezcla todo su contenido, y el vector no distingue "habla principalmente de esto" de "lo menciona entre otras diez cosas") y *consulta y documento nunca se miran* (la similitud coseno es geometría sobre dos resúmenes comprimidos, no una lectura conjunta). Resultado práctico: entre los 50 más cercanos los relevantes casi siempre están, pero el orden dentro de esos 50 es poco fiable — y a un pipeline que pasa 5 documentos al LLM le va la vida en ese orden.

El **cross-encoder** concatena consulta y documento en una sola entrada y los procesa juntos: la atención opera sobre los tokens de ambos textos simultáneamente y la salida es directamente una puntuación de relevancia del par. Puede capturar que "plataforma de e-commerce" y "aplicación de pagos" comparten campo semántico pero no intención. El precio es que no hay nada que precalcular: cada par consulta-documento es una inferencia de transformer, así que puntuar todo un corpus por consulta es inviable.

**Recall-then-rerank** encadena ambos — un patrón anterior a los LLMs, que los buscadores web llevan décadas usando. *Etapa de recall*: la búsqueda vectorial recupera un conjunto generoso (top-50); aquí no se pide orden fino, se pide que los relevantes estén dentro. *Etapa de precision*: el cross-encoder puntúa esos 50 pares y reordena, quedándose con el top-5. Los dos números merecen criterio propio: el **conjunto amplio** controla el techo de calidad (el reranking reordena, no recupera — si el presupuesto relevante no entró en el top-50, ningún reranker lo rescata; entre 30 y 75 candidatos suele ser razonable en corpus de empresa), y el **conjunto final** lo dicta el consumidor del contexto, no el reranker (5 presupuestos bien elegidos producen mejores resultados que 15 mediocres: el generador también sufre cuando le entierras la señal en ruido).

**Panorama de modelos.** En local con `sentence-transformers`, la familia clásica `ms-marco-MiniLM` es rápida en CPU pero **monolingüe en inglés** — matiz no opcional con datos en español; las opciones serias son `mmarco-mMiniLMv2` (multilingüe ligero, decenas de milisegundos por lote en CPU) o `BAAI/bge-reranker-v2-m3` (multilingüe nativo, más potente y más pesado, idealmente GPU). A favor: coste marginal cero por consulta, los datos no salen de la infraestructura, latencia sin red. En contra: PyTorch engorda la imagen en cientos de megas y el modelo ocupa memoria permanentemente. Como servicio, **Cohere Rerank** cubre español sin configuración, con mejor calidad y tres líneas de integración, a cambio de coste por consulta, dependencia de red en el camino crítico y documentos viajando a un tercero. **La posición del programa**: para un sistema interno con corpus en español, volumen moderado y datos sensibles, el punto de partida sensato es un cross-encoder multilingüe ligero en local; el salto al hospedado se justifica con números del propio dominio, no con benchmarks genéricos.

Cierra con **la latencia como impuesto** (decenas a pocos cientos de ms en CPU para un modelo ligero; segundos para uno potente sin GPU; 100-500 ms para una API externa, más el arranque en frío que afecta al despliegue y al autoescalado) y con los tres casos en los que **no** hay que rerankear: cuando el ranking vectorial ya es suficiente, cuando el cuello de botella está antes (si los relevantes no entran en el conjunto amplio, el problema es de recall y el reranking pule el orden de los resultados equivocados), y cuando el presupuesto de latencia no da. La señal de que el reranking es la herramienta correcta es precisa: **los documentos relevantes están entre los candidatos, pero no arriba**.

### 2. 📄 Cómo saber si el reranking compensa: medición artesanal de relevancia — 23 min

*"Parece que va mejor" no es un argumento* — ni sobrevive a la pregunta "¿cuánto?", ni a una code review seria, ni al comité de arquitectura, ni al cliente que paga la factura de infraestructura. El artículo convierte esa frase en *"la precisión de recuperación subió de 0,48 a 0,80 a cambio de 250 milisegundos por consulta"*, y lo hace sin framework de evaluación, sin equipo de datos y sin semanas de trabajo: una tarde, criterio de dominio y una hoja de cálculo. A esa práctica la llama **medición artesanal**: deliberadamente pequeña, deliberadamente manual, y suficiente para la decisión que se tiene delante.

**Por qué la intuición engaña midiendo relevancia**, y no por descuido sino por diseño de la atención: *probamos con las consultas equivocadas* (cuando evaluamos a mano se nos ocurren las fáciles, las que nosotros formularíamos bien; los usuarios reales escriben consultas vagas y con terminología de su sector); *recordamos lo memorable, no lo representativo* (si el reranking rescata espectacularmente un presupuesto enterrado, esa anécdota domina la percepción — la memoria pondera por impacto emocional, una métrica pondera por frecuencia); y *comparamos contra una referencia que se mueve* (evaluar a ojo la configuración nueva el martes y la antigua el jueves es comparar contra una vara de medir distinta cada vez). La solución a los tres es la misma: fijar de antemano un conjunto de consultas con sus respuestas correctas conocidas.

**El golden set.** Una colección pequeña de consultas reales del dominio, cada una anotada a mano con los documentos que de verdad son relevantes. Para el sistema de estimación: la consulta es la descripción de un proyecto y la anotación es la lista de presupuestos que un estimador experimentado usaría como referencia — ni los semánticamente parecidos, ni los de la misma tecnología. Tres decisiones definen su calidad, y ninguna es técnica:

- **Qué consultas entran.** Cobertura del uso real, no del cómodo: dos o tres frecuentes y directas, un par de difíciles conocidas (dominios colindantes como e-commerce y pagos), y al menos una con términos exactos que deban respetarse (tecnologías, siglas, productos). Si el sistema procesa transcripciones, alguna consulta debe ser larga y desordenada como lo son las transcripciones.
- **Cuántas.** Menos de las que crees: entre 5 y 20 bien elegidas bastan. El error que invalida la medición no es el tamaño de la muestra, sino que no se parezca al uso real. Ampliar un golden set vivo es trivial; tirar uno grande y mal construido, doloroso.
- **Quién anota y con qué criterio.** Es un juicio de dominio: debe hacerlo quien usaría el resultado, y el criterio se escribe en una frase antes de empezar ("es relevante si serviría como referencia directa de esfuerzo para este proyecto") para evitar el desplazamiento silencioso entre anotaciones. La relevancia se anota **en binario**, resistiendo las escalas de matices: menos expresivo, pero consistente y suficiente.

**La métrica: precision@k.** De los *k* documentos devueltos, qué fracción es relevante según el golden set — con *k* igual a la *k* real del sistema (si pasas 5 presupuestos al LLM, mide precision@5; medir precision@10 responde una pregunta que nadie ha hecho). Tres aciertos entre cinco devueltos = 0,60; se repite por consulta y se promedia. La **exhaustividad (recall@k)** es el complemento gratuito cuando has anotado todos los relevantes de cada consulta — viable en un corpus de empresa — y detecta un fallo que la precisión no ve: el documento valioso que no aparece por ninguna parte. Existen métricas que además premian el orden dentro del top-k, pero para decidir si una técnica entra en el pipeline, precisión y exhaustividad sobre las *k* reales llegan de sobra.

**La otra columna: latencia.** Dos precauciones — *medir en caliente* (la primera consulta tras arrancar paga carga de modelos, conexiones y cachés frías; se descarta) y *quedarse con la mediana* de 3 a 5 ejecuciones, no con la media, que con muestras pequeñas se va con cualquier pico de la máquina.

**El marco de decisión.** Con la tabla delante, cada técnica se sitúa en dos ejes: relevancia ganada y latencia costada. La lectura ingenua ("el reranking multiplica la latencia por ocho") es aritméticamente cierta e irrelevante; la correcta usa el denominador adecuado, el **presupuesto de latencia de la experiencia completa**. En el sistema de estimación, la generación posterior tarda varios segundos: 255 ms añadidos son menos del 5% del total percibido y a cambio dos de cada cinco documentos del contexto pasan de ruido a señal. En un autocompletado con presupuesto de 300 ms, esos mismos 255 ms son el 85%: inasumible aunque la ganancia fuera el doble. **La técnica no es buena ni mala; es cara o barata respecto a un presupuesto, y el presupuesto lo fija el producto.**

El cuadrante deja una **zona traicionera**: ganancia pequeña con coste pequeño. El coste de una técnica nunca es solo su latencia — es el modelo extra que operar, la dependencia que actualizar, el modo de fallo nuevo que diagnosticar a las tres de la mañana. Una mejora de 0,02 en precisión rara vez paga ese peaje, y la tabla es precisamente lo que permite decir "no" con fundamento.

**Lo que esta medición no da**, dicho con honestidad: un golden set de diez consultas no tiene potencia estadística (las diferencias que justifican decisiones son las grandes y consistentes, de 0,48 a 0,80, no las décimas); la anotación arrastra el sesgo de quien anota; y la medición se detiene en la recuperación — dice qué documentos llegan al LLM, no qué hace el LLM con ellos. Una recuperación perfecta no garantiza una estimación correcta, solo la hace posible.

### 3. 📄 Búsqueda híbrida — 23 min

La escena: el proyecto necesita "integración de pagos con Stripe, incluyendo suscripciones y webhooks de facturación". La búsqueda semántica devuelve resultados del campo correcto — pasarelas, cobros recurrentes, integraciones financieras — pero el presupuesto que integró **exactamente Stripe** hace año y medio, con el esfuerzo real de pelearse con esa API concreta, aparece en la posición catorce. Para un modelo de embeddings, "Stripe" es aproximadamente sinónimo de "pasarela de pago": esa generalización es la virtud de los embeddings y aquí es exactamente el problema. **La búsqueda semántica es miope para lo literal.**

**Dos familias, dos puntos ciegos.** La léxica opera sobre términos literales (las palabras raras en el corpus discriminan mucho; las omnipresentes, poco) y **no entiende paráfrasis** — "cobros recurrentes" y "suscripciones de pago" no comparten ni una palabra, y un histórico escrito por personas distintas a lo largo de años está lleno de esas variaciones ("panel de administración" / "backoffice"). La semántica opera sobre significado y **diluye lo literal** — nombres propios, siglas, versiones, códigos internos ("Stripe", "SAP", "ISO 27001", "PostGIS") son los términos con menos masa semántica general y más valor discriminante, la combinación exacta que peor sobrevive a la compresión. En un sistema de estimación conviven ambos tipos de consulta, muy a menudo dentro de la misma consulta: **la conclusión no es elegir mejor, es dejar de elegir**.

**Full-text en PostgreSQL: la pieza que ya tienes.** Resistiendo el instinto de añadir Elasticsearch, si los vectores ya viven en PostgreSQL el propio motor trae full-text maduro: cero infraestructura nueva, cero sincronización entre almacenes, las dos búsquedas a una consulta SQL de distancia. Las piezas son `tsvector` (el texto tokenizado, en minúsculas, sin stopwords y con stemming — la configuración lingüística **no es un detalle**: un corpus en español necesita `'spanish'`, y los términos que el diccionario no reconoce, "Stripe" o "webhook", pasan casi intactos, que es justo lo que queremos), `tsquery` (la consulta con la misma normalización; `websearch_to_tsquery` acepta sintaxis natural y tolera entradas imperfectas), el operador `@@`, el **índice GIN** (un índice invertido, la estructura clásica de los buscadores) y `ts_rank` para puntuar. Se monta con una **columna generada**, que PostgreSQL mantiene sincronizada sin triggers ni código de aplicación.

Dos honestidades: `ts_rank` **no es BM25** y es algo más tosco puntuando (no normaliza por longitud con la misma sofisticación), pero para un corpus de empresa la diferencia es ruido comparada con tener rama léxica frente a no tenerla; y Elasticsearch sigue teniendo su sitio en corpus enormes o con necesidades léxicas avanzadas — la posición no es "Elasticsearch nunca", es **"no añadas un segundo almacén hasta que el primero se te quede pequeño"**, porque cada almacén extra es sincronización, monitorización y modos de fallo nuevos.

**El problema de juntar dos rankings.** Las puntuaciones no son comparables: la similitud coseno vive en un rango acotado con su distribución, `ts_rank` en otra escala sin cota superior intuitiva. Sumarlas es sumar metros con kilogramos. La tentación de normalizar y combinar con pesos **funciona en la demo y se rompe en producción**, porque la distribución cambia con cada consulta (una con términos muy raros produce puntuaciones léxicas altísimas; una conceptual, bajísimas) y la calibración de ayer queda descalibrada hoy.

**Reciprocal Rank Fusion** esquiva el problema ignorando las puntuaciones y usando solo las posiciones: `rrf_score(d) = Σ 1 / (k + rank_i(d))`, con *k* típicamente 60. Un presupuesto 2.º en semántica y 5.º en léxica suma `1/62 + 1/65 ≈ 0,0315`; uno 1.º en semántica que no aparece en léxica, `1/61 ≈ 0,0164`. **RRF es una máquina de premiar el consenso**: aparecer razonablemente arriba en varios rankings vale más que arrasar en uno — el rescate exacto para el presupuesto de Stripe. Sobre la constante *k*: pequeña hace dominar las primeras posiciones, grande aplana las diferencias; el valor 60 viene del paper original, ha demostrado ser robusto en dominios muy distintos, y **empezar tocándolo es optimización prematura**.

**Dónde gana y dónde no.** Gana con claridad en consultas con identificadores exactos — que en estimación no es el caso raro sino el pan de cada día ("Stripe", "Salesforce", "GDPR", "React Native") — y en consultas cortas y específicas. Apenas mueve la aguja en consultas puramente conceptuales bien parafraseadas, donde la semántica ya trabajaba bien; ahí la fusión no estorba (RRF degrada con elegancia) pero tampoco luce. Y hay que vigilarla con **idiomas mezclados** — presupuestos en español plagados de terminología en inglés, como es norma en el sector —: la configuración lingüística procesará bien una parte y dejará la otra sin stemming. No suele ser grave (los términos técnicos en inglés funcionan como identificadores exactos, el caso donde la léxica brilla), pero explica resultados desconcertantes.

### 4. 📄 Expansión y descomposición de consultas — 22 min

Todas las mejoras anteriores actúan **después** de la consulta: mejores índices, mejores rankings, mejores filtros. Este artículo mira al otro lado del mostrador, porque hay un problema que ninguna mejora del lado de los documentos puede arreglar: **la consulta misma**.

Dos problemas distintos. El primero: la entrada habitual no es una consulta limpia de buscador sino una **transcripción de reunión de cuarenta minutos** donde el cliente salta del catálogo a la app móvil, dedica diez minutos a la integración de facturación y entre medias menciona el panel de administración y los informes. Su embedding es el promedio de todos esos temas: un vector moderadamente cerca de todo y genuinamente cerca de nada, que recupera presupuestos "de proyectos grandes con muchas cosas" — la peor categoría posible, porque **la estimación se construye por partidas**: el catálogo se estima con referencias de catálogos, la integración con referencias de integraciones. El segundo, más sutil y presente incluso en consultas de un solo tema: **la lotería de la formulación**. El cliente dice "que los comerciales vean sus números desde el móvil"; el presupuesto relevante decía "dashboard de KPIs con versión responsive". Los embeddings cruzan paráfrasis mejor que cualquier tecnología anterior, pero no son inmunes — y que la calidad dependa de la suerte al redactar es el tipo de fragilidad que un sistema de producción no puede permitirse.

**Dos técnicas que parecen una.** La **expansión (multi-query)** genera varias formulaciones alternativas de la misma intención y busca con todas: un seguro contra la lotería de la formulación — en lugar de un boleto, juegas cuatro. La **descomposición** parte una consulta que mezcla varias intenciones en sub-consultas independientes, una por tema, cada una con un embedding nítido que apunta a su rincón del espacio. La pregunta que las distingue cabe en una línea: **¿la consulta pide una cosa que puede decirse de muchas maneras, o muchas cosas dichas a la vez?** Lo primero se expande, lo segundo se descompone — y aplicar la técnica equivocada no es neutro: expandir una consulta multi-tema produce cuatro variantes igual de mezcladas (cuatro boletos del sorteo equivocado), y descomponer una de un solo tema fabrica sub-temas artificiales que recuperan ruido.

**Generar las variantes: un LLM con la correa corta.** Dos disciplinas separan la versión ingenua de la de producción. *Salida estructurada, no texto libre*: las sub-consultas son entrada de la siguiente etapa, y parsearlas con expresiones regulares es fabricar un punto de rotura. *Instrucciones que acotan, no que inspiran*: el riesgo específico es que el modelo "mejore" demasiado — que invente requisitos no mencionados, que traduzca terminología de dominio a sinónimos genéricos, o que fabrique ocho sub-consultas donde había dos temas. El límite de sub-consultas vive **en dos sitios** (en el esquema, que el modelo no puede violar, y en las instrucciones, que le explican por qué) porque el esquema garantiza y la instrucción orienta. Y el modelo se elige por configuración: no hace falta el más capaz del catálogo, hace falta **el más rápido que haga bien una tarea pequeña y acotada** — esta llamada está en el camino crítico de cada búsqueda.

**Fusionar sin perder de vista para qué se buscaba** — la sutileza que el material introductorio suele pasar por alto: **expansión y descomposición no deben fusionar igual**. En la expansión las N variantes buscaban lo mismo, así que un documento bien posicionado en varias es señal fuerte y la fusión correcta **premia el consenso** (RRF). En la descomposición las N sub-consultas buscaban cosas deliberadamente distintas, y premiar el consenso **sabotea el objetivo**: un presupuesto de catálogo jamás aparecerá en el ranking de la integración de facturación, y con fusión por consenso global el tema con más presupuestos en el histórico inunda el resultado. La fusión correcta **garantiza cobertura por tema**: cuotas por sub-consulta (los dos mejores de cada una) o intercalación en round-robin. Para estimar, esto no es un matiz técnico: es la diferencia entre un contexto con referencias de cada partida y un contexto monotemático. La **deduplicación** no es defensiva por capricho — cuando un presupuesto cubre dos temas aparece en dos rankings y sin deduplicar consumiría dos plazas del contexto contando una sola vez como información.

**El precio.** Estas técnicas meten una generación de LLM en el camino crítico, **antes incluso de empezar a buscar**. *Latencia*: 200 ms a 1 s con un modelo pequeño y salida corta — con diferencia el sumando más caro. *Tokens*: calderilla por consulta, multiplicada por cada consulta del sistema. *Carga*: N búsquedas paralelas son N consultas a la BD y un conjunto de candidatos N veces mayor entrando en las etapas posteriores, que también cobran por volumen. Mitigaciones por orden de rentabilidad: el modelo más pequeño que haga la tarea con fiabilidad (verificándolo con ejemplos reales — "humilde" no es "gratis de verificar"), limitar a tres o cuatro variantes (la ganancia marginal de la quinta es indistinguible de cero), cachear las reformulaciones, y **la mayor de todas: no aplicar la técnica cuando no toca** — una consulta corta, nítida y monotema no necesita reformularse, y el sistema puede decidirlo con una heurística humilde (longitud y estructura) dejando la decisión registrada en los logs.

Una nota de honestidad sobre la medición: estas técnicas **brillan en las consultas difíciles** (largas, mezcladas, mal formuladas), así que si el golden set solo contiene consultas limpias de laboratorio el veredicto saldrá injustamente tibio. La medición vale lo que valga su parecido con el tráfico real.

### 5. 📄 Multi-índice y routing — 19 min

El corpus del sistema ya no es homogéneo: almacena **tres familias** bien distintas — presupuestos (estructurados, telegráficos, llenos de partidas y cifras), transcripciones de reuniones (lenguaje oral, redundante, divagante) y documentación técnica interna (descriptiva, densa, escrita para ser referencia). Ante "¿cuánto costó la integración con SAP en proyectos anteriores?", el documento que responde es un presupuesto, pero el top-5 del índice único viene contaminado con transcripciones donde un cliente habló de SAP largo y tendido y con documentación sobre conectores. **El índice único responde a "¿qué se parece a esta consulta?" cuando la pregunta real era "¿qué presupuesto se parece a esta consulta?"** — y esa diferencia, que un humano resuelve sin pensar, el índice no puede resolverla porque nadie se lo ha dicho.

**El mecanismo de la degradación**, con precisión: las familias tienen *texturas semánticas distintas* (el lenguaje oral produce chunks difusos y temáticamente mezclados; el de presupuesto, densos y monotemáticos — y un chunk de transcripción puede quedar más cerca del embedding de la consulta precisamente por su verbosidad temática, siendo menos útil); *el tipo dominante inunda* (si hay diez veces más chunks de transcripciones — y los habrá: las reuniones generan texto a un ritmo que los presupuestos no pueden seguir — el top-k tendrá la proporción que dicte el volumen, no la utilidad); *cada familia quiere su propio preprocesamiento* (chunking por turnos de palabra, por partidas o por secciones, respectivamente — el índice único empuja a un compromiso mediocre para todos); y *la operación sufre* (reindexar transcripciones no debería tocar presupuestos; en un índice único todo cambio es global).

**Particionar en PostgreSQL: dos opciones.** *(A) Una tabla con columna discriminadora* — menor fricción, un solo modelo de datos, un `WHERE` más; funciona cuando las familias comparten esquema y muchas consultas quieren buscar en todas. *(B) Una tabla por familia* — más piezas y más migraciones, y a cambio cada familia tiene el esquema que su naturaleza pide, cada índice HNSW se construye sobre una población homogénea, y reindexar es una operación local. **La regla de decisión**: si los esquemas de metadatos divergen, tablas separadas; si son variaciones de lo mismo, columna discriminadora. Los metadatos son la confesión involuntaria del diseño — cuando te descubres añadiendo columnas que solo tienen sentido para una familia (`speaker_count` siempre NULL en presupuestos, `total_amount` siempre NULL en transcripciones), la tabla única te está diciendo que son entidades distintas conviviendo a disgusto. En el sistema de estimación los esquemas divergen sin ambigüedad → opción B, con el precio operativo dicho en voz alta: tres migraciones, tres índices que monitorizar, tres pipelines de ingesta.

**El router, en jerarquía de coste creciente** — porque la versión cara y vistosa se ha vuelto el reflejo por defecto y casi nunca es la primera que toca:

- **Nivel cero: el mejor router es no tener router.** Muchas consultas llegan con su destino implícito en el contexto de quien las hace — el flujo de estimación busca presupuestos siempre. La forma correcta de capturar ese conocimiento es el **contrato de la API**: un parámetro explícito de colección, o endpoints distintos por caso de uso. Gratis, determinista, trazable. La pregunta obligada antes de construir cualquier clasificador: *¿de verdad el servicio IA tiene que adivinar algo que el backend de negocio ya sabe?*
- **Nivel uno: reglas deterministas.** Para el buscador libre interno, patrones de vocabulario inequívocos ("¿cuánto costó...?" → presupuestos; "¿qué dijo el cliente...?" → transcripciones). Frágiles ante la creatividad lingüística, pero gratis en latencia y transparentes al depurar.
- **Nivel dos: el LLM como clasificador**, solo para lo que las reglas no resuelven. Esquema cerrado, instrucciones que acotan, y un diseño de salida que contemple la duda honesta.
- **Último peldaño: buscar en todo.** El fallback honesto; su coste en latencia es el de la colección más lenta, no la suma. **La degradación es elegante**: en el peor caso el sistema multi-índice se comporta como el índice único del que veníamos, nunca peor.

Tres decisiones del diseño del router merecen defensa: la salida es una **lista de destinos**, no un destino con confianza — cuando el clasificador duda entre dos colecciones la acción correcta es buscar en ambas, y modelar la salida como lista convierte la duda en comportamiento bien definido en lugar de un umbral arbitrario; el campo `reason` no es decorativo, cuesta una frase de tokens y hace **auditable** cada decisión meses después; y el `StrEnum` **cierra el universo de respuestas**, de modo que el modelo no puede inventarse una colección que no existe.

**Combinar resultados de colecciones distintas** reproduce agravado el problema conocido: las puntuaciones de colecciones distintas no son comparables (cada una tiene su textura, su distribución, su densidad), y fusionar por puntuación cruda hace que la colección de distancias generosas devore a las demás. Salidas sensatas: fusión por posiciones o por cuotas por colección, nunca por puntuación cruda; o, muchas veces mejor, **no fusionar** y presentar agrupado por procedencia ("esto dicen los presupuestos; esto se habló en reuniones"), porque el consumidor final hace cosas distintas con cada familia. Para eso, **cada chunk debe viajar con su etiqueta de procedencia**: es lo que permitirá atribuir, auditar y depurar, y perderla en la fusión es perderla para siempre.

Una observación de arquitectura: el patrón que se acaba de construir — un componente que examina una petición y la delega en el especialista adecuado, con la opción de consultar a varios y combinar — **es el embrión de cómo los sistemas con agentes se reparten el trabajo**. La diferencia es de grado y libertad: este router hace una clasificación acotada con esquema cerrado, sin razonamiento abierto ni herramientas. Esa contención es deliberada, pero el patrón mental se reutilizará ampliado más adelante en el programa.

**Cuándo no particionar** — especialmente tentador de ignorar porque particionar parece arquitectura seria: si el corpus es funcionalmente homogéneo por mucho que los documentos tengan orígenes distintos; si una colección concentraría el 95% de las consultas (el router sería un peaje que casi siempre da la misma respuesta); y "para cuando crezcamos" (tres tablas, tres ingestas y un router son deuda contraída hoy contra una necesidad hipotética). **La señal legítima es observable y concreta: resultados de una familia contaminando consultas dirigidas a otra, de forma recurrente y medible.**

### 6. 📄 Filtrado contextual y temporal — 18 min

La última escena: un portal de cliente con área privada, gestión documental y firma electrónica encuentra un presupuesto **casi calcado** — mismo tipo de cliente, mismo alcance, misma estructura de partidas. Similitud altísima, primera posición indiscutible. El presupuesto es de **2019**: frontend en AngularJS, firma electrónica con un proveedor que ya no existe, tarifas de otra época, prácticas que el estudio abandonó hace tres años. Como referencia de *qué partidas* tiene un portal, todavía orienta; como referencia de *cuánto cuesta hoy*, es directamente peligroso — y el LLM generador no tiene forma de saberlo.

Este es el punto ciego que ninguna técnica de similitud puede cubrir: **el embedding codifica lo que el texto dice, no cuándo se escribió, ni con qué tecnología, ni para qué sector, ni si sigue siendo verdad**. Esas dimensiones viven en los metadatos, y bien usados son la técnica con mejor relación coste-beneficio del arsenal — la única cuyo coste de ejecución es **negativo**, porque filtrar antes de buscar abarata todo lo que viene después.

**Filtros duros.** Condiciones sobre metadatos que excluyen antes de que la similitud opine: un `WHERE` de toda la vida conviviendo con la búsqueda vectorial. La sintaxis es trivial; **la trampa está debajo**: los índices ANN como HNSW no entienden de `WHERE` — el índice navega su grafo buscando los vecinos más cercanos del universo completo y el filtro se aplica *después*. Si pides 50 resultados con un filtro que satisface el 5% del corpus, el índice devuelve sus 50 vecinos, el filtro descarta 48, y la consulta entrega 2 resultados — o cero — **sin ningún error visible**. Mitigaciones: `hnsw.iterative_scan` desde pgvector 0.8 (sigue pidiendo candidatos hasta reunir los solicitados tras el filtro) y el **índice parcial** (un HNSW construido solo sobre las filas que cumplen la condición) para filtros frecuentes y selectivos. La lección de fondo es un hábito: **verifica la cardinalidad de lo que vuelve y déjala en los logs**, porque "el filtro vació el resultado en silencio" es de los modos de fallo más desconcertantes de depurar a posteriori.

Segunda condición que se da por supuesta y no debería: **los metadatos tienen que existir, y existir bien**. La fecha viene gratis; tecnología, sector o tamaño de equipo hay que extraerlos en la ingesta — con reglas cuando el formato lo permite, con extracción estructurada por LLM cuando no — **una vez por documento, nunca por consulta**. La calidad de esa extracción es el techo de todo lo demás: un filtro duro sobre un metadato mal extraído es **peor que ningún filtro**, porque excluye con total confianza al mejor candidato y nadie ve el hueco. Los filtros duros se reservan para metadatos en los que se confía; lo dudoso, como mucho, pondera.

**El tiempo: el metadato que nunca es opcional.** Su efecto sobre la utilidad es universal y direccional — los precios caducan, los stacks rotan, las prácticas cambian. Dos familias de respuesta. La **ventana dura** (solo los últimos N años) es simple de implementar y explicar, con un comportamiento brutal en el borde: el presupuesto de hace 3 años y 11 meses compite en igualdad total, el de 4 años y un mes no existe; da igual con corpus abundante, pero puede dejar fuera la única referencia decente de un proyecto raro cuando el histórico es escaso — y lo es más de lo que se admite. El **decaimiento continuo** trata la edad como penalización progresiva, con un único parámetro de lectura de negocio directa: la **semivida** (cada cuántos días un presupuesto pierde la mitad de su peso). Con semivida de 900 días, un presupuesto de hace un año conserva el 76% de su peso y el de 2019 en torno al 15% — sigue existiendo, correctamente degradado, pero ya no puede ganarle la primera posición a un equivalente reciente. **La semivida no se optimiza con una fórmula**: se elige con juicio de dominio ("¿a partir de cuándo dejarías de fiarte de las cifras de un presupuesto?"). La elección no es ideológica: ventana cuando exista una razón categórica (cumplimiento, política de empresa, un cambio de era que invalide lo anterior); decaimiento para la erosión gradual normal. Y se combinan sin conflicto.

**Ponderación dinámica** — que la importancia de cada metadato dependa de la consulta: la coincidencia tecnológica pesa mucho si la descripción gira alrededor de una tecnología; la experiencia sectorial sube de valor en banca porque arrastra regulación y plazos; y si la consulta no menciona nada de eso, esos metadatos deberían callar. La implementación honesta es prosaica: multiplicadores sobre la ordenación final, definidos en configuración. Y aquí llega **la advertencia más seria del artículo**, porque es donde el exceso de ingeniería acecha con mejor disfraz: cada peso es un número mágico que alguien tendrá que justificar, recalibrar y depurar, y **un sistema con siete boosts contextuales interactuando es un sistema donde nadie sabe ya por qué un documento quedó tercero** — se ha sustituido la opacidad del embedding por una opacidad artesanal, que es peor porque encima parece controlable. La progresión sensata es conservadora: primero filtros duros y decaimiento temporal (que resuelven la mayor parte con dos decisiones explicables), ponderación dinámica después y solo donde haya evidencia medida. *Ejercicio de humildad: si no puedes explicar en una frase por qué un boost vale 1,3 y no 1,5, no estaba listo para producción.*

**Ensamblar el pipeline: el orden es el mensaje.** El principio que ordena todas las piezas y se defiende en cualquier revisión de arquitectura:

> **Lo barato y excluyente, al principio; lo caro y fino, al final; lo blando, al cierre.**

Y la **asimetría deliberada** entre los dos usos de los metadatos, que es la moraleja estructural: los filtros duros van **lo más temprano posible**, las ponderaciones blandas **lo más tarde posible**. El filtro temprano ahorra trabajo a todo lo que sigue; la ponderación tardía ajusta sobre el conjunto pequeño donde equivocarse es barato. Invertir ese orden produce los dos clásicos del pipeline mal montado: **rerankear documentos que un filtro iba a tirar** (dinero quemado) y **ponderar tan pronto que el ajuste blando expulsa candidatos antes de que el reranker pudiera valorarlos** (información destruida). Nota final: no todas las consultas necesitan todas las etapas — el pipeline completo es el camino máximo, y cada etapa debe poder activarse y desactivarse por configuración, tanto para medir su aportación como porque la consulta simple no tiene por qué pagar el peaje de la compleja.

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Técnicas avanzadas de recuperación

**Fecha límite indicada por el programa:** domingo 16 de agosto, final del día.
**Repositorio de referencia:** https://github.com/LIDR-academy/ai-engineering — rama `session_09_live`.

> **Correcciones al enunciado original.** El enunciado publicado citaba la rama
> `session-10` como punto de partida. Se ha corregido por tres motivos comprobados:
>
> 1. **La rama `session-10` no existe**; el repositorio usa guiones bajos (`session_10`).
> 2. **La rama `session_10` contiene ya la solución completa de este ejercicio** — 7
>    ficheros (`retrieval/fusion.py`, `retrieval/pipeline.py`,
>    `alembic/versions/0003_session10_fts.py`, `evals/golden_retrieval.json`,
>    `scripts/eval_retrieval_s10.py` y 2 tests) más 17 ficheros con el cableado hecho.
>    El punto de partida real es **`session_09_live`**, el código de la sesión en vivo
>    anterior: sin paquete `retrieval/`, con solo las migraciones `0001` y `0002` y sin
>    rama léxica en el store.
> 3. `session_09_live` **no incluye el wrapper de cross-encoder** que el enunciado da por
>    construido, así que se ha injertado desde `session_10` únicamente
>    `retrieval/{__init__,reranker,verify_reranker}.py`, el setting `RERANKER_MODEL` y la
>    dependencia `sentence-transformers`. Nada más.
>
> También se ha corregido el nombre del servicio en el comando de verificación
> (`ai-service` → `estimator`, que es como se llama en `docker-compose.yml`).

**Contexto.** El pipeline RAG ya funciona de extremo a extremo: reformula la consulta, recupera presupuestos por similitud vectorial y genera una estimación con ese contexto. El problema es que "similar" no siempre significa "relevante": a veces el sistema recupera el presupuesto de una app de pagos cuando la consulta describe una plataforma de e-commerce. Cercano en el espacio vectorial, inútil para estimar.

**Objetivo.** Atacar ese problema con dos técnicas — **búsqueda híbrida** y **reranking** — y, sobre todo, **medir si compensan**. El objetivo no es solo que la recuperación mejore: es poder demostrar con números cuánto mejora y a qué coste.

**Lectura previa imprescindible.** Los artículos 1, 2 y 3 de la sesión (reranking, medición de relevancia y búsqueda híbrida). El ejercicio se apoya directamente en ellos. Los artículos 4, 5 y 6 preparan la sesión en vivo y pueden leerse después de entregar.

#### Qué necesitas

Si no lo tienes en tu repo personal, haz un fork de `https://github.com/LIDR-academy/ai-engineering`, haz checkout de la rama `session_09_live` y sácalo de ahí. Incluye:

- El pipeline RAG de la sesión anterior, funcionando (desde tu repo personal).
- Un **wrapper de cross-encoder ya construido** en `app/generation/rag/retrieval/` (carga del modelo, scoring de pares consulta-documento). **No hay que implementar el reranker: hay que integrarlo.**
- El dataset de presupuestos históricos ya ingerido y vectorizado.

#### Verificación antes de empezar

```bash
git clone https://github.com/LIDR-academy/ai-engineering.git
cd ai-engineering
git checkout session_09_live
cd estimator
docker compose up -d
docker compose exec estimator python -m app.generation.rag.retrieval.verify_reranker
```

Si este paso falla, **no sigas adelante**: revisa la guía de troubleshooting de la rama `session_10` y, si no se resuelve, llévalo al bloque de resolución de errores de la sesión en vivo (avisando antes por el canal del programa para que quede localizado).

#### Alcance — importante

Este ejercicio cubre **únicamente búsqueda híbrida y reranking**. No implementes expansión de consultas, routing multi-índice ni filtrado por metadatos aunque hayas leído sobre ellos: se construyen juntos en la sesión en vivo sobre lo que traigas hecho.

#### Paso 1 — Búsqueda full-text en PostgreSQL

Crear una migración de Alembic que añada a la tabla de chunks una columna `tsvector` **generada** a partir del contenido, con su índice **GIN**. Los presupuestos del dataset están **en español**: tenerlo en cuenta al elegir la configuración de text search de la columna. Como siempre, **todo el código, nombres, comentarios y mensajes de log van en inglés**.

#### Paso 2 — Rama léxica y fusión RRF

Implementar la búsqueda por palabras clave sobre la nueva columna y combinar sus resultados con los de la búsqueda vectorial existente mediante **Reciprocal Rank Fusion**. El resultado debe ser una función de búsqueda híbrida que devuelva un ranking único fusionado.

*Decisiones libres:* cómo estructuras el módulo, cómo parametrizas la constante de suavizado de RRF, y cómo expones el modo de búsqueda (parámetro del endpoint, configuración o script) — mientras las cuatro configuraciones del paso 4 sean **invocables de forma reproducible**.

#### Paso 3 — Integración del reranker

Conectar el wrapper de cross-encoder al pipeline siguiendo el patrón **recall-then-rerank**: recuperación amplia (**top-50**) y reordenación fina para quedarse con los mejores (**top-5**). El reranking debe poder **activarse y desactivarse sin tocar código**.

#### Paso 4 — Golden set y medición

Construir un **golden set de 5 consultas** representativas del dominio (descripciones de proyectos a estimar) y anotar a mano, para cada una, qué presupuestos del dataset son realmente relevantes. Después, ejecutar las cuatro configuraciones contra el golden set:

| Configuración | Búsqueda   | Reranking |
|---------------|------------|-----------|
| **A**         | Vectorial  | No        |
| **B**         | Híbrida    | No        |
| **C**         | Vectorial  | Sí        |
| **D**         | Híbrida    | Sí        |

Para cada configuración, medir **la precisión sobre los 5 primeros resultados** y **la latencia de la consulta**. Recoger los resultados en una tabla comparativa.

#### Paso 5 — Conclusiones

Cerrar con un párrafo breve respondiendo: ¿qué configuración usarías en el proyecto y por qué? ¿La ganancia de relevancia del reranking justifica su latencia en este caso de uso concreto? **No hay respuesta correcta única: hay respuestas bien y mal argumentadas.**

#### Entregable

Abrir un PR en tu repo personal con rama `session-10/pre-work` y enviar por mail a `george@lidr.co`:

- Enlace completo al PR en GitHub (URL de tu repo, no del oficial).
- Tabla comparativa con las configuraciones A, B, C y D (precisión y latencia).

El plazo es estricto: el equipo necesita margen para revisar las implementaciones, validar los golden sets y preparar el material de la sesión basándose en los números reales. Asegúrate de que el PR es accesible (repo público o permisos para el revisor) y de que el mail incluye enlace + tabla. Si llegas sin haber entregado podrás seguir el directo, pero los bloques de casos avanzados asumirán que ya tuviste cifras de tu setup.

---

### 🛠️ Contexto técnico para la implementación

Material de referencia extraído de los artículos, con todo lo necesario para implementar con Claude Code CLI.

#### Estructura de módulos

Las piezas nuevas viven en la capa de recuperación, junto a la búsqueda vectorial a la que complementan:

```
app/generation/rag/retrieval/
├── reranker.py              # wrapper de cross-encoder (injertado desde la rama session_10)
├── verify_reranker.py       # script de verificación de carga del modelo
├── fulltext_search.py       # rama léxica sobre tsvector
├── fusion.py                # RRF + intercalación round-robin
├── hybrid_search.py         # orquestación de las dos ramas en paralelo
├── query_expansion.py       # expansión / descomposición (sesión en vivo)
├── router.py                # routing multi-índice (sesión en vivo)
├── temporal.py              # decaimiento temporal (sesión en vivo)
└── pipeline.py              # composición de etapas

scripts/
├── golden_set.json          # verdad de referencia, versionada
└── measure_retrieval.py     # arnés de medición artesanal
```

#### Paso 1 — Columna `tsvector` generada e índice GIN

```sql
ALTER TABLE budget_chunks
ADD COLUMN content_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED;

CREATE INDEX ix_budget_chunks_content_tsv
ON budget_chunks USING gin (content_tsv);
```

Búsqueda léxica:

```sql
SELECT chunk_id, ts_rank(content_tsv, query) AS lexical_rank
FROM budget_chunks,
     websearch_to_tsquery('spanish', :query_text) AS query
WHERE content_tsv @@ query
ORDER BY lexical_rank DESC
LIMIT 50;
```

`websearch_to_tsquery` acepta sintaxis natural de buscador (términos sueltos, comillas para frases, `OR`) y tolera entradas imperfectas — la opción sensata cuando la consulta viene de texto libre. La columna generada la mantiene PostgreSQL sincronizada automáticamente: **sin triggers ni código de aplicación**.

#### Paso 2 — Reciprocal Rank Fusion

```python
# app/generation/rag/retrieval/fusion.py

from collections import defaultdict

RRF_SMOOTHING_K = 60

def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = RRF_SMOOTHING_K,
) -> list[str]:
    """Fuse multiple ranked lists of chunk ids into a single ranking."""
    scores: dict[str, float] = defaultdict(float)

    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)

    return [
        chunk_id
        for chunk_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
```

Recibe **una lista de rankings, no exactamente dos**: RRF no sabe ni le importa cuántas fuentes fusiona, y esa generalidad la convierte en la pieza de fusión universal del pipeline.

Fusión alternativa para **descomposición** (garantiza cobertura por tema en lugar de premiar consenso):

```python
def interleave_rankings(
    rankings: list[list[RetrievedChunk]],
    top_k: int,
) -> list[RetrievedChunk]:
    """Round-robin across rankings to guarantee per-topic coverage."""
    fused: list[RetrievedChunk] = []
    seen_ids: set[str] = set()

    for position in range(max(len(ranking) for ranking in rankings)):
        for ranking in rankings:
            if position < len(ranking) and ranking[position].id not in seen_ids:
                fused.append(ranking[position])
                seen_ids.add(ranking[position].id)
                if len(fused) == top_k:
                    return fused
    return fused
```

#### Búsqueda híbrida — las dos ramas en paralelo

```python
# app/generation/rag/retrieval/hybrid_search.py (fragment)

import asyncio

async def hybrid_search(self, query: str, limit: int = 50) -> list[RetrievedChunk]:
    """Run semantic and lexical search in parallel and fuse with RRF."""
    semantic_results, lexical_results = await asyncio.gather(
        self._vector_search.search(query, limit=limit),
        self._fulltext_search.search(query, limit=limit),
    )

    fused_ids = reciprocal_rank_fusion(
        [
            [chunk.id for chunk in semantic_results],
            [chunk.id for chunk in lexical_results],
        ]
    )

    chunks_by_id = {
        chunk.id: chunk
        for chunk in [*semantic_results, *lexical_results]
    }
    return [chunks_by_id[chunk_id] for chunk_id in fused_ids[:limit]]
```

La latencia de la híbrida es la de **la rama más lenta, no la suma**. El contrato es el mismo que el de cualquier otra búsqueda del sistema — entra una consulta, sale una lista ordenada de chunks — y esa uniformidad es una decisión de arquitectura: cambiar de vectorial a híbrida es cambiar una pieza detrás de una configuración, y comparar ambas se convierte en un experimento de un booleano.

#### Paso 3 — Reranker

```python
# app/generation/rag/retrieval/reranker.py

from sentence_transformers import CrossEncoder

from app.foundation.config import settings
from app.foundation.logging import get_logger

logger = get_logger(__name__)

class Reranker:
    """Cross-encoder reranker for retrieved candidates."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.reranker_model_name
        self._model = CrossEncoder(self._model_name)
        logger.info("reranker_loaded", model=self._model_name)

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Score query-candidate pairs jointly and return the top_k best."""
        if not candidates:
            return []

        pairs = [(query, candidate.content) for candidate in candidates]
        scores = self._model.predict(pairs)

        ranked = sorted(
            zip(candidates, scores),
            key=lambda item: item[1],
            reverse=True,
        )

        logger.info(
            "rerank_completed",
            candidates_in=len(candidates),
            candidates_out=min(top_k, len(ranked)),
        )

        return [candidate for candidate, _ in ranked[:top_k]]
```

Tres decisiones que separan un ejemplo de tutorial de un componente de producción:

1. **El modelo se carga una vez, en la construcción.** Cargar un cross-encoder cuesta segundos; hacerlo por consulta sería un desastre. La instancia se crea en el arranque y se comparte entre peticiones (mismo patrón de singleton de ciclo de vida que el cliente del LLM). Consecuencia operativa: el arranque es más lento y más pesado en memoria, y **el healthcheck del contenedor debe esperar a que el modelo esté cargado** antes de declarar el servicio listo.
2. **Recibe y devuelve el mismo tipo.** Entra una lista de chunks, sale una lista de chunks más corta y mejor ordenada — lo que lo convierte en una etapa opcional y componible: activarlo o desactivarlo es decidir si la lista pasa o no por él. Cuando una técnica se enciende con un booleano, comparar su impacto deja de ser una refactorización y pasa a ser un experimento.
3. **El logging registra tamaños de entrada y salida.** Cuando dentro de meses haya que auditar por qué el sistema eligió esos presupuestos, el log estructurado de cada etapa es la diferencia entre diagnosticar en minutos o en días.

Integración en el flujo:

```python
# app/generation/rag/retrieval/pipeline.py (fragment)

async def retrieve(self, query: str) -> list[RetrievedChunk]:
    candidates = await self._vector_search.search(
        query,
        limit=settings.retrieval_candidate_pool_size,   # wide net: e.g. 50
    )

    if not settings.reranking_enabled:
        return candidates[: settings.retrieval_top_k]

    return self._reranker.rerank(
        query,
        candidates,
        top_k=settings.retrieval_top_k,                 # narrow output: e.g. 5
    )
```

⚠️ **Detalle que no aparece en los tutoriales y sí en los incidentes:** la búsqueda vectorial es asíncrona (I/O contra la BD) y el reranking no lo es (cómputo local). En un servicio asyncio, una inferencia de cross-encoder de cientos de milisegundos ejecutada en el event loop **bloquea todas las demás peticiones** mientras dura. Si el reranker local entra en el camino de un endpoint con concurrencia real, la inferencia debe despacharse a un thread pool (`asyncio.to_thread` o el executor del loop).

#### Paso 4 — Golden set y arnés de medición

El golden set es un **archivo de datos versionado junto al código** — cambiarlo debe pasar por revisión, porque cambiar la vara de medir es cambiar el significado de todas las mediciones anteriores:

```json
{
  "annotation_criterion": "Relevant if it would serve as a direct effort reference for estimating this project",
  "queries": [
    {
      "id": "q01",
      "query": "E-commerce platform with product catalog, cart and admin panel",
      "relevant_budget_ids": ["budget-2023-014", "budget-2024-002", "budget-2022-031", "budget-2023-027"]
    },
    {
      "id": "q02",
      "query": "Mobile app with Stripe payment integration and push notifications",
      "relevant_budget_ids": ["budget-2024-011", "budget-2023-019"]
    }
  ]
}
```

```python
# scripts/measure_retrieval.py
"""Artisanal retrieval measurement against a hand-annotated golden set."""

import json
import time
from pathlib import Path
from statistics import median

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
TOP_K = 5
RUNS_PER_QUERY = 3

def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of the top-k retrieved documents that are relevant."""
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    hits = sum(1 for budget_id in top if budget_id in relevant_ids)
    return hits / len(top)

async def measure(pipeline) -> None:
    golden_set = json.loads(GOLDEN_SET_PATH.read_text())
    precisions: list[float] = []
    latencies_ms: list[float] = []

    for entry in golden_set["queries"]:
        relevant_ids = set(entry["relevant_budget_ids"])

        for _ in range(RUNS_PER_QUERY):
            start = time.perf_counter()
            results = await pipeline.retrieve(entry["query"])
            latencies_ms.append((time.perf_counter() - start) * 1000)

        retrieved_ids = [chunk.budget_id for chunk in results]
        precision = precision_at_k(retrieved_ids, relevant_ids, TOP_K)
        precisions.append(precision)
        print(f"{entry['id']}: precision@{TOP_K} = {precision:.2f}")

    print(f"mean precision@{TOP_K}: {sum(precisions) / len(precisions):.2f}")
    print(f"median latency: {median(latencies_ms):.0f} ms")
```

**Decisión de diseño a defender:** esto vive en `scripts/`, **no en las capas de la aplicación**. Un arnés artesanal es una herramienta de decisión puntual, no infraestructura: no necesita endpoint, ni tests propios, ni abstracción para futuros casos de uso. Convertirlo prematuramente en un "módulo de evaluación" es el clásico exceso de ingeniería que después nadie quiere mantener. Cuando el sistema necesite evaluación continua de verdad — automatizada, en CI, con histórico — será otra pieza con otro diseño.

#### Piezas de la sesión en vivo (no entran en el ejercicio)

**Descomposición de consultas** — esquema y correa corta:

```python
# app/generation/rag/retrieval/query_expansion.py

from pydantic import BaseModel, Field

class SubQuery(BaseModel):
    """A self-contained search query targeting a single workstream."""

    topic: str = Field(description="Short workstream label, e.g. 'billing integration'")
    query: str = Field(description="Standalone search query for this workstream")

class QueryDecomposition(BaseModel):
    """Decomposition of a project description into independent sub-queries."""

    sub_queries: list[SubQuery] = Field(min_length=1, max_length=4)
```

```python
DECOMPOSITION_INSTRUCTIONS = """
You split a software project description into independent search queries,
one per distinct workstream, to retrieve similar past project budgets.

Rules:
- Produce at most 4 sub-queries. Fewer is better than fragmented.
- Each sub-query must be self-contained and understandable without the others.
- Preserve the exact domain terms used in the description (product names,
  technologies, acronyms). Never replace them with generic synonyms.
- Never add requirements, features or technologies that the description
  does not mention.
- If the description covers a single topic, return exactly one sub-query
  that rephrases it cleanly.
"""

async def decompose_query(self, raw_query: str) -> list[SubQuery]:
    """Split a multi-topic query into focused sub-queries."""
    response = await self._client.responses.parse(
        model=settings.query_expansion_model,
        instructions=DECOMPOSITION_INSTRUCTIONS,
        input=raw_query,
        text_format=QueryDecomposition,
    )
    sub_queries = response.output_parsed.sub_queries
    logger.info(
        "query_decomposed",
        sub_query_count=len(sub_queries),
        topics=[sub_query.topic for sub_query in sub_queries],
    )
    return sub_queries
```

**Router multi-índice** — esquema cerrado, lista de destinos y razón auditable:

```python
# app/generation/rag/retrieval/router.py

from enum import StrEnum

from pydantic import BaseModel, Field

class SearchTarget(StrEnum):
    BUDGETS = "budgets"
    TRANSCRIPTS = "transcripts"
    TECHNICAL_DOCS = "technical_docs"

class RoutingDecision(BaseModel):
    """Which collections a query should be searched against."""

    targets: list[SearchTarget] = Field(
        min_length=1,
        max_length=3,
        description="Collections to search. Use several only when the query genuinely spans them.",
    )
    reason: str = Field(description="One short sentence explaining the choice")

ROUTING_INSTRUCTIONS = """
You classify search queries for a project estimation system into the
collections they should be searched against.

Collections:
- budgets: historical project budgets, with line items, effort and cost figures.
- transcripts: meeting transcripts between the team and clients.
- technical_docs: internal technical documentation and architecture references.

Rules:
- Choose the single most appropriate collection whenever possible.
- Choose several collections only when the query genuinely needs them.
- Questions about cost, effort or estimates belong to budgets, even if the
  query mentions meetings or documents.
"""
```

**Decaimiento temporal:**

```python
# app/generation/rag/retrieval/temporal.py

from datetime import date

def temporal_weight(document_date: date, half_life_days: int = 900) -> float:
    """Exponential decay: a document loses half its weight every half_life_days."""
    age_days = (date.today() - document_date).days
    return 0.5 ** (max(age_days, 0) / half_life_days)
```

**Filtro duro combinado con búsqueda vectorial:**

```sql
SELECT chunk_id, embedding <=> :query_embedding AS distance
FROM budget_chunks
WHERE project_date >= :min_project_date
  AND technology = ANY(:relevant_technologies)
ORDER BY distance
LIMIT 50;
```

#### Orden canónico del pipeline completo

> **Lo barato y excluyente, al principio; lo caro y fino, al final; lo blando, al cierre.**

1. **Reformulación y routing** — operan sobre la consulta y deciden qué se busca y dónde.
2. **Filtros duros**, empotrados en la propia consulta de búsqueda — reducen el universo antes de que nada caro lo recorra.
3. **Búsqueda** (rama semántica + rama léxica) y **fusión**, sobre el universo ya filtrado → conjunto amplio de candidatos.
4. **Reranking**, al final del tramo caro y solo sobre los supervivientes.
5. **Ponderaciones blandas** (temporal, contextual) como último ajuste sobre la ordenación de los finalistas.

Cada etapa debe poder activarse y desactivarse **por configuración**: tanto para medir su aportación como porque la consulta simple y nítida no tiene por qué pagar el peaje de la compleja.

#### Parámetros de referencia del programa

| Parámetro | Valor de partida | Nota |
|---|---|---|
| Conjunto amplio (recall) | `top-50` | Rango razonable en corpus de empresa: 30-75 |
| Conjunto final (contexto) | `top-5` | Lo dicta el consumidor del contexto, no el reranker |
| Constante RRF | `k = 60` | Del paper original; tocarla primero es optimización prematura |
| Semivida temporal | `900 días` (~2,5 años) | Juicio de dominio, no optimización |
| Modelo de reranking (ES) | `mmarco-mMiniLMv2` o `BAAI/bge-reranker-v2-m3` | Los `ms-marco-MiniLM` clásicos son **monolingües en inglés** |
| Configuración FTS | `'spanish'` | Determina stemming y stopwords |
| Ejecuciones por consulta | 3-5, quedarse con la **mediana** | Medir en caliente, descartar la primera |
| Sub-consultas por descomposición | máx. 4 | Límite en el esquema **y** en las instrucciones |

## Checklist antes de la siguiente sesión

- [ ] Sabes explicar por qué un bi-encoder encuentra bien y ordena mal (el vector promedia; consulta y documento nunca se miran).
- [ ] Entiendes qué hace distinto a un cross-encoder y por qué no puede aplicarse a todo el corpus.
- [ ] Puedes justificar los dos números del patrón recall-then-rerank: el conjunto amplio fija el techo de calidad, el final lo dicta el consumidor del contexto.
- [ ] Sabes que los `ms-marco-MiniLM` clásicos son monolingües en inglés y cuáles son las alternativas multilingües para un corpus en español.
- [ ] Conoces los tres escenarios en los que **no** hay que rerankear, y la señal precisa de que sí toca.
- [ ] Tienes claro por qué el reranker local debe despacharse a un thread pool en un servicio asyncio.
- [ ] Has construido un golden set propio, con criterio de anotación escrito y anotación binaria.
- [ ] Sabes calcular precision@k con la *k* real de tu sistema, y por qué medir con otra *k* responde a una pregunta que nadie hizo.
- [ ] Mides latencia en caliente y con mediana de varias ejecuciones, no con la media de la primera.
- [ ] Puedes situar una técnica en el cuadrante ganancia/coste usando el presupuesto de latencia del producto como denominador.
- [ ] Reconoces la zona traicionera (ganancia pequeña, coste pequeño) y sabes decir que no con la tabla delante.
- [ ] Tienes la columna `tsvector` generada con configuración `'spanish'` y su índice GIN en la tabla de chunks.
- [ ] Sabes por qué normalizar y combinar puntuaciones de dos motores se rompe en producción, y por qué RRF lo esquiva.
- [ ] Puedes explicar qué premia RRF (el consenso) y qué controla su constante `k`.
- [ ] Distingues cuándo expandir y cuándo descomponer una consulta, y por qué **no deben fusionar igual**.
- [ ] Entiendes por qué la descomposición necesita cobertura por tema (cuotas o round-robin) en lugar de consenso.
- [ ] Sabes qué preguntar antes de construir un router: ¿tiene el servicio IA que adivinar algo que el backend ya sabe?
- [ ] Conoces la jerarquía de routing por coste creciente y por qué buscar en todo es un fallback honesto.
- [ ] Puedes decidir entre columna discriminadora y tablas separadas mirando si los esquemas de metadatos divergen.
- [ ] Sabes que un filtro duro sobre HNSW puede vaciar el resultado en silencio, y conoces `hnsw.iterative_scan` y los índices parciales.
- [ ] Distingues ventana dura de decaimiento continuo y sabes elegir semivida con juicio de dominio.
- [ ] Puedes enunciar y defender el orden canónico del pipeline y la asimetría filtros-temprano / ponderaciones-tarde.
- [ ] Tienes las cuatro configuraciones (A/B/C/D) invocables de forma reproducible y su tabla de precisión y latencia.

## Documentación de referencia

**Reranking y cross-encoders**

- sentence-transformers — Cross-Encoders: https://www.sbert.net/examples/applications/cross-encoder/README.html
- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe): https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
- `BAAI/bge-reranker-v2-m3`: https://huggingface.co/BAAI/bge-reranker-v2-m3
- MS MARCO (dataset de pares consulta-pasaje): https://microsoft.github.io/msmarco/
- Cohere Rerank: https://docs.cohere.com/docs/rerank-overview

**Búsqueda híbrida y full-text en PostgreSQL**

- PostgreSQL — Full Text Search: https://www.postgresql.org/docs/current/textsearch.html
- PostgreSQL — Controlling text search (`ts_rank`, `websearch_to_tsquery`): https://www.postgresql.org/docs/current/textsearch-controls.html
- PostgreSQL — Índices GIN: https://www.postgresql.org/docs/current/gin.html
- PostgreSQL — Columnas generadas: https://www.postgresql.org/docs/current/ddl-generated-columns.html
- Reciprocal Rank Fusion (Cormack et al., 2009): https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf

**Vectores, filtrado e índices**

- pgvector: https://github.com/pgvector/pgvector
- pgvector — Filtering e iterative scans: https://github.com/pgvector/pgvector#filtering
- PostgreSQL — Índices parciales: https://www.postgresql.org/docs/current/indexes-partial.html
- PostgreSQL — EXPLAIN: https://www.postgresql.org/docs/current/using-explain.html

**Modelos, API y servicio**

- OpenAI — Responses API: https://platform.openai.com/docs/api-reference/responses
- OpenAI — Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- Pydantic v2 — Fields y validación: https://docs.pydantic.dev/latest/concepts/fields/
- Python — `asyncio.to_thread`: https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread
- FastAPI — Lifespan events: https://fastapi.tiangolo.com/advanced/events/
- Alembic (migraciones): https://alembic.sqlalchemy.org/
- structlog: https://www.structlog.org/
