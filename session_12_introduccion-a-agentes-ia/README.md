# Sesión 12 — Introducción a agentes de IA

## Objetivo de la sesión

Al cierre de la Sesión 11 el sistema de estimación funciona de extremo a extremo como **pipeline fijo**: reformula la consulta, recupera presupuestos históricos comparables, genera una estimación estructurada y controla su calidad. Tres pasos, siempre los mismos, siempre en el mismo orden. Predecible, barato, testeable — y suficiente para la mayoría de las transcripciones que entran al sistema.

La Sesión 12 abre el **Módulo 5: Orquestación de agentes** y ataca el punto exacto donde ese pipeline se rompe: la transcripción cuyo **árbol de decisión no puedes pre-mapear**. Un proyecto que mezcla un backend de negocio, una integración con el ERP del cliente, una app móvil y una migración de datos legacy no tiene una forma conocida de antemano: no sabes cuántas búsquedas harás, ni sobre qué, ni en qué orden. Lo que falta no es más recuperación ni mejor generación, sino **capacidad de decisión en tiempo de ejecución**.

El eje de la sesión no es "construir un agente" sino **decidir si lo necesitas y pagar su precio con los ojos abiertos**. Un agente no es una mejora gratuita del pipeline: es una decisión arquitectónica que se cobra en latencia, coste, no-determinismo, composición de errores y deuda de observabilidad. La postura del programa es explícita: **el pipeline es el estado por defecto; el agente entra cuando la forma del problema te obliga**.

Al final de la sesión tienes un agente construido **a mano, sin framework** — bucle manual sobre la Responses API de OpenAI — que descompone una transcripción en componentes, invoca sus tools (`search_budgets`, `calculate_estimate`, opcionalmente `validate_estimate`), itera hasta converger y devuelve una estimación estructurada **junto a una traza legible de su razonamiento paso a paso**. La pieza clave no es el bucle (son cincuenta líneas), sino entender qué automatiza un framework antes de adoptarlo, y tener instrumentado el coste para poder defender la decisión con números.

Un detalle de arquitectura que atraviesa los seis artículos: **todo esto vive dentro del servicio IA**. El backend de negocio sigue enviando una transcripción y recibiendo una estimación estructurada por el mismo contrato de siempre. La agencia es un detalle de implementación del servicio IA, no un cambio de arquitectura del producto — y esa frontera es lo que te permite introducir el agente sin tocar la capa de negocio, y quitarlo mañana si el coste no compensa.

> **Nota sobre el material de la plataforma.** La descripción publicada en la página raíz de la Sesión 12 en LIDR Training está **duplicada de la Sesión 10** (habla de reranking con cross-encoders, full-text en PostgreSQL y Reciprocal Rank Fusion, contenidos que no pertenecen a esta sesión). El resumen de arriba se ha reconstruido a partir del contenido real de los seis artículos y del enunciado del ejercicio.

## Qué vas a aprender

### 1. 📄 De pipeline a agente: cuándo tu sistema RAG necesita una capa de decisión — 23 min

Empieza defendiendo lo que el marketing de agentes hace olvidar: **un pipeline fijo es muy bueno**. El control de flujo lo escribes tú, el modelo solo rellena huecos, y de esa única propiedad se derivan cuatro virtudes concretas — es predecible (misma entrada, mismo camino; si falla, sabes en qué paso), es barato (sabes cuántas llamadas al LLM haces por petición), es testeable (cada paso por separado con aserciones deterministas) y es rápido (sin negociación con el modelo sobre qué hacer después). Para una parte enorme de los problemas reales eso es todo lo que se necesita, y añadir agencia ahí es meter no-determinismo, latencia y coste a cambio de nada.

**Dónde se rompe.** Dos transcripciones lo enseñan. Una landing con formulario de contacto: un componente, una búsqueda, una estimación — el pipeline la clava porque la forma del problema es fija y tú ya la codificaste. Una reunión de kickoff con portal de clientes, integración con el ERP vía API, app móvil y migración de un legacy que "nadie sabe muy bien cómo está montado": aquí no sabes cuántos componentes hay hasta leer la transcripción, ni cuántas búsquedas necesitas, ni sobre qué, ni en qué orden. Las dos salidas disponibles dentro del paradigma son malas: **una búsqueda gigante** que devuelve un revoltijo de presupuestos incomparables y hunde la calidad, o un **árbol de decisiones codificado a mano** que hay que mantener para cada forma de proyecto que aparezca — y cada cliente trae una combinación nueva.

**La escala de tres niveles** (Anthropic / Barry Zhang) da el vocabulario para decidir: **tarea** (una única llamada al modelo: resume, clasifica, extrae), **workflow** (varias llamadas encadenadas en un flujo de control que tú defines — aquí vive la mayor parte de un sistema RAG bien hecho, y está bien que así sea) y **agente** (el modelo dirige su propio proceso: decide la siguiente acción a partir de lo que observa y sigue hasta considerar que ha terminado; tú posees el objetivo y las barreras, no cada rama del camino). La síntesis de Zhang: con un workflow la fontanería la controlas tú, con un agente la controla el modelo — y todo lo demás (coste, latencia, testabilidad, observabilidad) se deriva de esa única diferencia estructural.

Visto desde el código, la novedad está **acotada a una línea**. El workflow es una secuencia escrita; el agente es un bucle donde `model.decide(...)` elige el siguiente paso en cada vuelta en función de lo que acaba de observar. El bucle en sí no tiene nada de novedoso: es control de flujo de cualquier programa que hayas escrito.

**Qué compras y qué no.** Compras exactamente una cosa: **orquestación adaptativa** — la capacidad de resolver problemas cuyo árbol de decisión no puedes pre-mapear. No compras mejor recuperación (el agente busca con las mismas herramientas), ni mejor generación (consolida con el mismo modelo), ni inteligencia nueva. Si tu problema tiene forma fija, no hay nada aquí para ti.

**El precio de la autonomía**, dicho sin adornos: *latencia* (cada vuelta es una ida y vuelta al modelo; de dos llamadas a ocho, de dos segundos a veinte), *coste* (la exploración cuesta tokens; como regla mental, ~0,10 USD por tarea equivalen a 30.000-50.000 tokens, y a escala de un millón de peticiones al mes gastar cinco veces lo necesario quema del orden de un millón y medio de dólares al año de más), *no-determinismo* (la misma transcripción puede recorrer caminos distintos, y reproducir un bug pasa a ser un ejercicio de paciencia), **composición de errores** (en un pipeline una recuperación mala produce un fallo acotado; en un agente puede convertirse en tres pasos más construidos sobre esa base podrida — la autonomía amplifica aciertos y errores por igual) y *deuda de observabilidad* (ya no basta loguear entradas y salidas: hay que trazar decisiones).

**Los cinco criterios de decisión**, formulados como preguntas que puedes hacerte delante de un problema concreto: ¿puedes pre-mapear el árbol de decisión? (si puedes enumerar pasos y ramas, hazlo workflow — que puedas mapearlo es la señal más fuerte de que no necesitas agencia); ¿el problema tiene forma variable?; ¿el valor justifica el gasto? (alto volumen y bajo valor unitario → workflow; bajo volumen y alto valor, como estimar un proyecto de seis cifras → puede justificar el sobrecoste); ¿cuál es el coste del error y **puedes verificarlo**? (tools de solo lectura, validación automática de la salida y humano en el bucle en los puntos críticos; un agente con acciones reversibles y verificables es mucho menos arriesgado); ¿el modelo es lo bastante bueno en tu dominio? (la agencia sobre un modelo que no domina el dominio solo produce fallos más elaborados). El caso canónico que cumple las cuatro condiciones son los **agentes de código**: problema ambiguo, valor obvio, modelos buenos en ello y — clave — **resultado verificable con tests**.

**Cómo se aplica al sistema de estimación**, sin diplomacia: el pipeline **sigue siendo el camino por defecto** para las transcripciones simples, que son la mayoría. El agente entra como **capa de decisión por encima**, no como sustituto, y el detalle que lo hace limpio en lugar de un rediseño es que **los pasos del pipeline se promocionan a tools del agente**: la recuperación pasa a ser `search_budgets`, el cálculo a `calculate_estimate`, la validación a `validate_estimate`. No se reimplementa nada. De ahí sale la **arquitectura de dos vías con enrutado barato al principio**: un clasificador ligero decide si la transcripción es simple (pipeline) o compleja (agente), y así pagas la autonomía solo cuando el problema la exige.

Cierre honesto y deliberadamente decepcionante: un agente **no es un paradigma nuevo que jubila tu ingeniería de software**, es una decisión de control de flujo. Lo difícil no es construirlo — el bucle son veinte líneas — sino **decidir si de verdad necesitabas uno** y resistir la tentación de meterlo donde un workflow habría hecho el trabajo mejor, más barato y con menos sorpresas.

### 2. 📄 Anatomía de un agente: qué ocurre dentro del bucle — 22 min

"Un agente es un bucle" es cierto pero no dice nada sobre lo que pasa **dentro de cada vuelta**, y ahí es donde se gana o se pierde el control del sistema. El artículo le pone nombre a los órganos porque **no puedes depurar lo que no sabes nombrar**: un agente sin anatomía es una caja negra que "a veces da mal la estimación".

**El esqueleto: reason → act → observe → repeat.** La formulación canónica viene de **ReAct** (Yao et al., ICLR 2023): entrelazar trazas de razonamiento y acciones, porque el razonamiento sin acción se queda sin datos frescos y alucina, y la acción sin razonamiento no sabe qué hacer con lo que trae. En su forma original era una técnica de *prompting* con formato explícito `Thought / Action / Observation` en bucle hasta una respuesta final. Y el esqueleto necesita, además, **condición de parada**: o el modelo da la respuesta final, o se alcanza un máximo de pasos, o se agota un presupuesto de error. Un bucle de agente sin guarda es un bug esperando a pasar; la parada **es parte del esqueleto**, no un detalle.

**Razonamiento — decidir qué hacer.** Aquí está el matiz que separa el modelo mental de la implementación actual: con los modelos de razonamiento de hoy, **el `Thought` ya no lo escribes tú en el prompt; se muda dentro del modelo** y se paga en tokens internos que no ves. La consecuencia es doble: ya no tienes que enseñarle a razonar con ejemplos, y a cambio **pierdes el control fino sobre esa traza**. Si necesitas auditabilidad estricta, tienes que capturar deliberadamente los *reasoning summaries* que el proveedor expone, porque por defecto el razonamiento es opaco.

**Planificación — descomponer el problema.** Si el razonamiento decide el siguiente paso, la planificación decide **la forma del conjunto**. Dos momentos posibles: el **plan por adelantado** (más auditable — lo tienes escrito antes de gastar — pero rígido ante sorpresas) y la **planificación continua** (se adapta a lo observado, pero es más difícil de anticipar y presupuestar). Con modelos capaces tiende a ser **emergente**, y eso suele bastar; nombrarla como componente te da la palanca de **forzar un plan explícito** cuando necesites justificar ante un cliente por qué la estimación salió como salió. Es una decisión de diseño, no un detalle del modelo.

**Acción — tocar el mundo.** El único punto donde el agente afecta a algo fuera de sí mismo. Mecánicamente es *function calling*, y su contrato es el de una interfaz tipada de toda la vida. **El modelo nunca ejecuta nada**: emite una intención y tú decides qué hacer con ella. Esa mediación es donde vive la seguridad del agente y **no conviene regalarla**: `search_budgets` es de solo lectura (reversible, barata de equivocarse, segura de conceder); una acción que escribe en producción, envía correo o mueve dinero es otra cosa. Principio de **mínimo privilegio**: las acciones que necesita y ni una más, y las irreversibles pasan por una comprobación — o por un humano — antes de ejecutarse.

**Observación — leer la respuesta del entorno.** Es la forma en que el agente obtiene *ground truth* en cada paso; sin ella, el modelo razona sobre su propia imaginación. Se subestima **hasta qué punto la calidad de la observación gobierna la calidad de la siguiente decisión**: una observación estructurada y concreta alimenta buen razonamiento; doscientos ítems en crudo cuando bastaban cinco desperdicia contexto y confunde. Devolver **identificadores estables y semánticos** y solo los campos necesarios para decidir no es cosmética: es lo que mantiene el bucle enfocado. Y **los errores son el caso especial más importante**: "1 coincidencia débil, baja confianza para migración legacy" permite al agente razonar y reformular; un genérico `error` — o peor, un error oculto — lo deja ciego y dando tumbos.

**Handover — saber cuándo apartarse.** Dos direcciones. Hacia un **humano** (*human in the loop*): el agente se detiene en un punto de control cuando su confianza es baja o la siguiente acción es cara e irreversible. En el sistema de estimación: si la migración legacy no tiene ninguna referencia histórica fiable, el agente estima el resto con solvencia y marca esa pieza como **necesitada de revisión** en lugar de inventarse un número con falsa precisión — eso no es un fallo, es un agente bien diseñado reconociendo el límite de lo que puede verificar. Hacia **otro agente**: delegar a un especialista, base de las arquitecturas multi-agente. En ambos casos el handover necesita **contrato explícito** — qué estado se transfiere, quién pasa a ser dueño de la decisión y cómo vuelve el control — porque un handover sin contrato es una pelota lanzada al aire sin que nadie sepa que tiene que recogerla. Traducido a arquitectura: el servicio IA devuelve un `status` (`needs_review`) con lo que sí pudo calcular y la razón, y el backend de negocio lo enruta con un `case`. Software normal.

**El estado que engorda.** El bucle no es memoria pura del modelo: es una estructura que tú mantienes y que crece en cada vuelta con la decisión y su observación. Ese estado acumulado **es la traza** — lo que puedes loguear, inspeccionar y usar para depurar — y también la contrapartida directa de la anatomía: cada llamada es más cara que la anterior porque arrastra todo lo observado. Un agente que da ocho vueltas está pagando, en la octava, por reenviar las siete observaciones previas. Reconocerlo desde el principio (resumir observaciones antiguas, descartar las que ya no informan, quedarse con el identificador en lugar del contenido) **no es optimización prematura: es la consecuencia estructural de un bucle que acumula**.

Cierre: nombra las partes y el agente deja de ser un misterio. El razonamiento es lógica de decisión que ahora vive dentro del modelo en lugar de en tus `if/else`; la planificación es descomposición de problemas; la acción es una llamada a función con efectos; la observación es un valor de retorno que reinyectas; el handover es escalado y delegación; y el bucle es control de flujo con una guarda. **Un agente cuyos órganos sabes nombrar es un sistema que puedes operar; uno cuyos órganos no distingues es una caja negra a la que solo puedes rezarle.**

### 3. 📄 Function calling en la práctica: tools, schemas y contrato con el modelo — 21 min

Arranca matando el malentendido que contamina todo lo demás: **el modelo no ejecuta tu código. Nunca.** No consulta tu base de datos, no corre tu función de cálculo, no toca nada. Emite una petición estructurada — "quiero llamar a `search_budgets` con estos argumentos" — y **tu código decide qué hacer con ella**. Function calling no es el modelo ejecutando funciones; es el modelo **pidiéndote que las ejecutes tú**.

**El contrato tiene cuatro tiempos:** tú declaras las tools disponibles; el modelo emite una petición estructurada si decide que necesita una; tu código ejecuta la operación real; devuelves el resultado y el modelo continúa razonando con ese dato en la mano. Visto así no es exótico: es una interfaz tipada de manual, y la única diferencia con cualquier API que hayas integrado es **quién está al otro lado pidiendo** — un modelo que elige la función según la conversación en lugar de un cliente con un flujo fijo.

**Anatomía de una tool — cuatro piezas**, y conviene tratarlas con respeto porque el modelo **solo ve esto**, nunca tu implementación: *nombre* (identificador único; con biblioteca grande, conviene *namespace* que desambigüe — `budgets_search`, `estimate_calculate`), *descripción* (lo que el modelo lee para decidir cuándo y cómo usarla — **la pieza de mayor apalancamiento**), *parámetros* (JSON Schema: tipos, requeridos, *enums*, y una descripción por parámetro) y *schema estricto* (`strict: true` ciñe los argumentos generados exactamente al esquema declarado).

Lo importante del ejemplo canónico es **cuánta intención cabe en la descripción y en los enums**. No están para documentar: están para **dirigir el comportamiento**. El enum de `component_type` restringe lo que el modelo puede pasar; la instrucción de "una llamada por componente" dentro de la descripción es lo que evita que meta la integración con el ERP y la migración legacy en una sola búsqueda y reciba un revoltijo inútil. **El schema no solo valida: enseña.**

**El ida y vuelta en la Responses API**, con tres cosas que no conviene pasar por alto: la salida **no es texto**, es una **lista de items tipados** — hay que recorrer `response.output` e inspeccionar cada item por su `type`, no asumir que el primero es la respuesta; cada `function_call` trae un **`call_id`** que debes referenciar al devolver el `function_call_output` (emparejar mal o olvidarlo es **el error más común al empezar**); y el estado se encadena con **`previous_response_id`**, de modo que el modelo mantiene contexto sin reenviarlo todo a mano.

Aviso concreto que ahorra una hora de depuración: en la Responses API **el schema de la tool es plano** — `type`, `name`, `description` y `parameters` al mismo nivel. En Chat Completions va anidado bajo una clave `function`. Copiar el formato de una a otra devuelve un error de parámetro que no siempre es obvio.

**Llamadas en paralelo.** Una misma respuesta puede contener **varias** `function_call`, y es habitual y deseable: ante cuatro componentes independientes, el modelo puede pedir cuatro `search_budgets` de golpe. El matiz de implementación importa: **no contestas una y vuelves a llamar por cada una** — recoges todas las llamadas de la respuesta, las ejecutas concurrentemente (`asyncio.gather`, ya que las tools del servicio IA son asíncronas) y devuelves **todos** los `function_call_output`, cada uno con su `call_id`, en una única petición de continuación. Asumir que siempre hay exactamente una es un bug clásico: funciona con transcripciones simples y **se rompe con la primera reunión compleja**.

**El mismo contrato en otro proveedor.** En la API de Anthropic la tool se declara con `input_schema` en lugar de `parameters`, el modelo devuelve bloques `tool_use` (no items `function_call`), la respuesta llega con `stop_reason: "tool_use"` y contestas con un bloque `tool_result`. **Los nombres cambian; el contrato es idéntico.** La consecuencia arquitectónica que merece la pena aprovechar: aísla esas diferencias de transporte en una capa fina o delégalas en un agregador, y mantén la lógica de tus tools completamente independiente del proveedor. Tus funciones no cambian; solo cambia el adaptador.

**Dónde vive todo esto.** En el servicio IA, en Python. Las tools **no son operaciones nuevas**: son la exposición como funciones invocables de capacidades que el servicio ya tenía. Declarar una tool es, en la práctica, escribir su schema y conectar su ejecución a una función que ya existía. El backend de negocio **no participa en nada de esto**: no declara tools, no ve `function_call` ni `tool_use`, no gestiona `call_id`.

**Diseñar tools que el modelo use bien** — la mecánica es fácil, aquí está el trabajo real, y casi todo se reduce a dos superficies. **La descripción es la interfaz**: si el modelo escoge mal o inventa argumentos raros, la causa casi nunca es el modelo, es una descripción vaga; un enum bien puesto o una restricción explícita hacen más por la fiabilidad que cualquier ajuste de temperatura. **Los resultados deben ser de alto valor**: solo lo necesario para decidir el siguiente paso, con identificadores estables, porque un resultado inflado desperdicia contexto — **que además reenvías en cada vuelta**. **Los errores también son resultados**, y de los importantes. **Valida los argumentos antes de ejecutar lo que duele**: `strict: true` garantiza que los argumentos tienen la *forma* del schema, **no que tengan sentido** — el schema es una guarda de tipos, no un sustituto del criterio. Y **cuida la granularidad**: demasiadas tools con contornos solapados confunden al modelo, muy pocas y genéricas le obligan a hacer malabares con los argumentos; el punto dulce es **una tool por operación con límites nítidos**. Señal de alarma: *si te descubres explicando en la descripción cuándo NO usar una tool, quizá esa tool está haciendo demasiadas cosas.*

Cierre: function calling se revela como **una interfaz tipada cuyo cliente resulta ser un modelo**. La disciplina es la de siempre — contratos claros, validación de entradas, errores informativos, respuestas de alto valor. Lo único genuinamente nuevo es que quien elige la función y rellena sus argumentos lo hace a partir de una descripción en lenguaje natural. Y ahí está la palanca: **la fiabilidad de tus tools no vive en un modelo mejor, vive en descripciones y resultados mejores.** Eso es ingeniería de interfaces, no aprendizaje automático.

### 4. 📄 El bucle agéntico paso a paso — 18 min

El artículo constructivo: montar el agente **a mano, sin LangChain ni ningún framework de orquestación**. No porque los frameworks sean malos, sino porque montar el bucle en crudo es **la única forma de entender qué hacen por ti cuando los uses**, y de poder tomar el control cuando lo necesites. Un agente de estimación funcional cabe en unas **cincuenta líneas**.

**Cuatro piezas, ni una más.** Las **tools** (capacidades ejecutables que envuelven lo que el servicio IA ya sabe hacer; el agente no reimplementa nada, solo orquesta), el **modelo** como orquestador (`gpt-5` con esfuerzo de razonamiento `medium`), el **bucle** como esqueleto y el **estado** que se acumula vuelta a vuelta y que es también la traza inspeccionable.

**El registro de tools** es el patrón que se paga solo: un diccionario que mapea nombre → función asíncrona, con un despachador que devuelve `{"error": ...}` cuando la tool no existe o revienta. Desacopla dos cosas que no deberían conocerse — **qué tools existen** y **cómo funciona el bucle**: añadir una tool nueva es añadir un schema y una entrada al registro, y **el bucle no cambia ni una línea**. El `try/except` del despacho no es defensivo por capricho: **una tool que falla no debe reventar el agente**; devuelve el error como observación para que el modelo pueda leerlo, razonar sobre él y reformular.

**El bucle**, recorrido decisión a decisión: la primera llamada arranca **fuera** del bucle con la transcripción como entrada; cada iteración empieza recogiendo todos los items `function_call` de la salida; si no hay ninguno, el modelo ha producido su respuesta final y se sale con `break`; si hay llamadas se ejecutan **todas en paralelo** con `asyncio.gather`; las observaciones se devuelven **juntas**, cada una con su `call_id`, en una única llamada de continuación encadenada con `previous_response_id` — reenviando eso sí las `instructions`, porque **`previous_response_id` no arrastra el system prompt**; cada acción con su observación se guarda en la traza; y todo vive dentro de la guarda `range(MAX_STEPS)`, con el `else` del `for` capturando el caso en que el agente no converge y cortando con un estado explícito de error. **Un bucle de agente sin límite de pasos es una factura esperando a dispararse.**

**El agente en marcha** — la traza de una ejecución real es donde la teoría cobra sentido. Ante una transcripción con integración de ERP y migración legacy: paso 1, búsqueda de la integración (4 coincidencias, mediana 120 h); paso 2, búsqueda de la migración (**1 coincidencia débil, baja confianza**); paso 3, **reformulación** de la consulta de migración con otros términos (3 coincidencias, mediana 90 h); paso 4, cálculo; paso 5, validación. **Lo interesante es el paso 3**: el agente no calculó sobre un dato pobre — leyó la observación, reformuló y volvió a buscar antes de seguir. Eso es exactamente lo que un pipeline fijo no puede hacer, **no lo programaste tú**, y es el agente ganándose su sitio de forma visible en la traza.

**La salida final estructurada.** Cuando el modelo deja de pedir tools, no queremos texto libre: todas las llamadas pasan un `text_format` (modelo Pydantic) al que la respuesta final debe ceñirse, y `response.output_parsed` ya es un objeto validado. Este es **el punto clave para la estabilidad del sistema**: el agente puede recorrer un camino distinto en cada ejecución, pero **la forma de lo que devuelve es siempre la misma**. La no-determinación vive dentro del bucle; **el contrato de salida es determinista**.

**El agente detrás de un endpoint.** Unas pocas líneas de FastAPI, y desde el backend de negocio una llamada HTTP corriente que hace `case` sobre el `status` (`done` → guardar; `max_steps_exceeded` → marcar para estimación manual). El backend **no ve el bucle, ni las `function_call`, ni los `call_id`, ni cuántas vueltas dio el agente**.

**Qué te enseña construirlo a mano.** Primero: **el manejo de errores es tuyo, y es donde se juega la robustez** — el `try/except` convierte un fallo de tool en observación recuperable, la guarda `MAX_STEPS` impide el bucle infinito, el `status` de salida distingue éxito de agotamiento; ninguna de estas defensas es opcional en producción y todas son visibles y ajustables porque las escribiste tú. Segundo: **la observabilidad no viene gratis** — la traza es tu instrumento de depuración y en un sistema real querrás enriquecerla con tiempos por paso, tokens consumidos y el resumen de razonamiento. Tercero: **ahora entiendes lo que un framework haría por ti** — en buena medida este mismo bucle, más gestión de estado, reintentos, instrumentación y, en los más elaborados, orquestación como grafo. Puede que lo quieras; puede que no. La diferencia es que **ahora es una decisión informada, no un acto de fe**.

Cierre: un bucle, un registro de tools, un system prompt y un esquema de salida. **Eso es el agente entero.** No hay una capa oculta donde ocurra algo que no puedas explicar: el razonamiento lo pone el modelo, el control de flujo lo pones tú. Mirar algo que suena a autonomía inteligente y reconocer debajo **un `while` bien escrito con condición de parada**.

### 5. 📄 Patrones de agentes y diseño de tools de calidad — 21 min

**"Agente" no es una cosa.** Bajo esa palabra caben formas muy distintas de resolver un problema, con costes, riesgos y modos de fallo diferentes. El artículo tiene dos mitades que se necesitan: **la forma del agente** y **la palanca que dirige su comportamiento dentro de esa forma** — el diseño de las tools.

**Eje 1: un solo paso o iterativo.** El agente de un solo paso hace una llamada, quizá usa una tool y termina — casi un pipeline con una decisión; para una landing con formulario basta y sobra. El **iterativo** repite decidir/actuar/observar hasta converger, y es lo que exige una transcripción con cuatro componentes. La decisión **no es filosófica, es de coste contra necesidad**: si puedes resolverlo en un paso, hazlo en un paso. La iteración es una herramienta para problemas cuya forma no conoces de antemano, **no un valor por defecto**.

**Eje 2: reactivo o proactivo.** El **reactivo** decide a la luz de lo que acaba de observar, sin plan hacia adelante: simple y sorprendentemente robusto — como no se compromete con un plan, no se rompe cuando la realidad no encaja; su debilidad es la miopía (decisiones localmente buenas que no componen un buen conjunto). El **proactivo** anticipa y actúa hacia el objetivo: más eficiente cuando el camino es predecible, más frágil cuando no lo es, porque un plan formado demasiado pronto puede quedar desmentido por la primera observación. Para transcripciones, **la reactividad suele ganar** — traen sorpresas, como un componente que resulta ser dos o una migración sin referencias — aunque una pizca de proactividad (descomponer en componentes al principio) ahorra vueltas sin comprometerte con un camino rígido.

**Eje 3: plan fijo o planificación dinámica.** El **plan fijo** gana en auditabilidad — lo tienes escrito antes de gastar un token, y poder mostrar "el agente decidió estimar estos cuatro componentes, en este orden, por estas razones" tiene valor real ante un cliente. La **planificación dinámica** gana en adaptabilidad lo que pierde en previsibilidad.

Apunte honesto: **los tres ejes no son ortogonales** — un agente proactivo tiende al plan fijo, uno reactivo a la planificación dinámica. No son tipos de catálogo, son **tres lentes para pensar la misma decisión de diseño**. Lo útil no es clasificar tu agente en una casilla, sino **ser consciente de dónde lo estás colocando y por qué**.

**La elección del programa, mojándose:** el agente de estimación es **iterativo, mayoritariamente reactivo, con planificación ligera y dinámica** — una descomposición inicial floja en componentes, revisada sobre la marcha cuando una observación lo pide. Absorbe la variabilidad de las transcripciones sin pagar el coste de un bucle innecesario ni la fragilidad de un plan rígido. No es la única elección defendible, **pero saber articular por qué es media batalla**.

**Enrutar la forma según el caso** — la decisión que precede a todas las anteriores y que se pasa por alto: **no tienes que elegir una sola forma para todas las entradas**. En producción la mayoría de las transcripciones son simples; comprometerte con el iterativo para todas significa pagar su coste también donde un solo paso resolvería mejor. La pregunta deja de ser "qué forma tiene mi agente" y pasa a ser **"qué forma merece cada entrada"**. Es ingeniería corriente: mides la distribución real de tus entradas, diseñas para el caso común y dejas una vía para el caso difícil. **La forma del agente no tiene por qué ser una constante del sistema; puede ser una decisión que se toma por petición.**

**Las tools son la interfaz que dirige al agente.** Fijada la forma, lo que determina que el agente decida bien es, casi por completo, cuáles tools existen y **cómo las describes**. El modelo no lee tu código ni tu intención: **lee esas frases**. De aquí sale el principio que ahorra muchísimo tiempo de depuración: cuando el agente se comporta mal — elige la tool equivocada, inventa argumentos, mete cuatro componentes en una búsqueda que debía ser de uno, llama a las cosas en orden absurdo — el instinto es culpar al modelo o retocar el bucle, y **casi siempre es un error**. El fallo suele estar en la descripción o en el conjunto de tools, y ahí está también el arreglo. **El modelo hizo lo que tus descripciones le dijeron; si te sorprende lo que hizo, es que decían algo distinto de lo que creías.**

**La descripción es un prompt que se itera**: se escribe, se prueba, se observan los resultados y se ajusta. Una versión ingenua ("Searches historical budgets.") no le da al modelo forma de saber que debe buscar **un componente cada vez**, y ante una transcripción con integración y migración lanzará una única búsqueda mezclada con resultados incomparables — **no es culpa del modelo, la descripción no le dijo otra cosa**. La versión que arregla el comportamiento lleva dentro **la restricción, el contraejemplo y la razón**: buscar UN componente a la vez, llamar por separado para cada uno, nunca combinar componentes no relacionados (por ejemplo una integración con ERP y una migración de datos) **porque los resultados mezclados no se pueden comparar**, y qué se recibe de vuelta. La diferencia entre las dos versiones **no es cosmética: es la diferencia entre un agente que estima bien y uno que produce números sin sentido, y vive enteramente en un campo de texto**.

**El conjunto de tools, no solo cada tool.** El modelo elige **entre todas** las que le ofreces. Demasiadas con fronteras solapadas confunden; muy pocas y genéricas fuerzan malabares con los argumentos. El punto dulce es **un conjunto pequeño con fronteras nítidas**, y cuando crece, los *namespaces* ayudan a agrupar y desambiguar. Señal de alarma: **si te descubres explicando en una descripción cuándo no usar esa tool en favor de otra, las fronteras están mal trazadas** — y el arreglo no es una descripción más larga, sino un conjunto mejor delimitado.

**Optimizar es mirar las trazas.** El método es directo y empírico: un puñado de transcripciones representativas (simples, complejas, casos raros), ejecutar el agente y **leer las trazas** — qué tool eligió, con qué argumentos, en qué orden, dónde se atascó. Cada anomalía se rastrea hasta una descripción vaga, una frontera mal puesta, un resultado con demasiado ruido o un error mudo que dejó al agente ciego. El ejemplo del artículo es perfecto: el agente llama a `calculate_estimate` **antes** de haber buscado presupuestos para todos los componentes; el instinto dice que "se precipita", pero la causa es que la descripción **no declara su precondición**. Añades `"only call this after budgets have been searched for every component"` y el comportamiento se corrige. **No tocaste el modelo ni el bucle; ajustaste una frase — y la mayoría de los arreglos tienen exactamente esa forma.**

Implicación de diseño: **la calidad de tus trazas determina tu capacidad de optimizar**. Un agente que registra acción, argumentos y observación en cada paso es un agente que puedes mejorar; uno que solo devuelve el resultado final es una caja negra a la que solo puedes cambiarle el modelo y rezar.

Cierre: no hay aquí aprendizaje automático ni un modelo secreto que entrenar. Hay **elecciones de diseño y un bucle de mejora empírico**. **No consigues un agente mejor esperando un modelo mejor; lo consigues eligiendo la forma adecuada y afinando las tools hasta que las trazas tienen el aspecto que deben tener.**

### 6. 📄 Cuánto cuesta un agente — 18 min

Un agente hace el mismo trabajo que un pipeline y puede costar varias veces más. **No es un defecto de implementación: es el precio estructural de la autonomía.** El problema es que "el agente es más caro" no es un número con el que puedas presupuestar.

**De dónde sale el sobrecoste — cuatro sumandos.** *Más llamadas al modelo* (una por vuelta del bucle: ocho vueltas donde el pipeline hacía dos ya es un factor de cuatro en número de llamadas). **El contexto crece en cada vuelta, y es el factor dominante** — el que la gente subestima: en cada iteración se reenvía todo lo acumulado (transcripción, decisiones previas, cada observación de cada tool), así que **la octava llamada cuesta como la primera más siete rondas de observaciones arrastradas**; los tokens de entrada, que son los que más se facturan en volumen, **crecen vuelta a vuelta**, y el coste **no es lineal en el número de pasos: engorda con cada uno**. *Tokens de razonamiento* (los modelos de razonamiento deliberan internamente y eso se factura **en cada vuelta**, no una sola vez). *Exploración y reintentos* (reformular una búsqueda pobre es correcto — es el agente adaptándose — pero cuesta tokens que un pipeline no gasta).

**La cuenta del 5x, con números ilustrativos.** Pipeline: dos llamadas, contexto acotado y estable, ~8.000 tokens en total. Agente sobre la misma transcripción compleja: ocho vueltas cuya entrada **no es constante** — 2.000 tokens la primera (solo la transcripción), luego 4.000, luego 6.000, y ~9.000 en la octava porque arrastra todo lo visto; promediando, del orden de **40.000 tokens de entrada** más ~8.000 de salida y razonamiento: **~48.000 frente a 8.000**. Ahí está el factor de seis, y el detalle importante es que **casi todo el sobrecoste está en los tokens de entrada que crecen vuelta a vuelta, no en las respuestas del modelo**. El número exacto variará; **la forma es siempre la misma**. Traducido a dinero con la regla mental del ecosistema (~0,10 USD por tarea ≈ 30.000-50.000 tokens), y a escala: un millón de tareas al mes gastando cinco veces lo necesario quema del orden de **un millón y medio de dólares al año de más**.

**Cómo medirlo.** Buena noticia: es de los problemas **más medibles** que tiene un agente, porque cada respuesta de la API devuelve exactamente cuántos tokens consumió. Un pequeño **libro de cuentas** (`CostLedger`) que acumule `usage` a lo largo del bucle da visibilidad total, y conectarlo es **una línea por vuelta**. Detalle que conviene no equivocar: **los tokens de razonamiento se facturan como tokens de salida y ya están contados dentro de `output_tokens`** — no los sumes aparte, duplicarías el coste; se llevan por separado solo **para ver qué fracción de tu gasto es deliberación**, y a veces descubres que la mitad de la factura es el modelo pensando, que es una señal accionable.

**Tres cosas que medir más allá del total.** El **coste por paso**, porque revela el crecimiento del contexto: si la última llamada cuesta cinco veces la primera, ya sabes dónde está tu dinero. **La distribución, no la media** — los agentes tienen **cola larga**: la mayoría de ejecuciones son razonables, pero **un agente confundido que itera hasta el límite de pasos es tu peor caso y el que te arruina el presupuesto medio**; mide el **percentil 95**. Y la **comparación con el pipeline sobre las mismas entradas**, porque el número que importa no es el coste absoluto sino **el sobrecoste frente a la alternativa más barata** que resolvería el caso.

Y una atribución que paga con creces: **qué tool infla el contexto**. Registrando el tamaño de la observación de cada tool descubres si el coste creciente viene de payloads enormes que luego se arrastran. Atribuir el gasto a su origen es lo que convierte "el agente es caro" en **"el 60% del coste es el arrastre de resultados de búsqueda sin adelgazar"**, que ya es un problema con solución.

**Cómo controlarlo — palancas ordenadas por impacto.** **Enruta**: la palanca más grande no está dentro del agente sino **antes** — no mandes al agente lo que un pipeline resolvería; la mayoría de tus entradas probablemente no exigen autonomía. **Adelgaza el contexto**: como su crecimiento domina el coste por ejecución, recortarlo es la mayor palanca dentro del bucle — resumir observaciones antiguas, descartar irrelevantes, guardar identificadores en lugar de payloads completos; que `search_budgets` devuelva cinco referencias limpias en vez de doscientas filas **no solo mejora las decisiones: reduce lo que reenvías en cada vuelta a partir de entonces**. **Acota la cola**: `MAX_STEPS` pone techo al peor caso, y conviene completarlo con un **presupuesto por ejecución** (si supera un umbral de tokens o coste, cortar y tratarlo como caso para revisión). **Ajusta el modelo y el razonamiento al trabajo**: no toda decisión necesita el máximo esfuerzo ni el modelo más caro — **el nivel de razonamiento es un dial de coste directo**. **Cachea lo determinista**: donde aplica, es dinero gratis.

Cierre y marco de decisión: el coste de un agente **no es un problema oscuro de la IA** — es medible hasta el token, atribuible por paso y controlable con ingeniería corriente. Lo único particular es que la unidad de facturación son tokens sobre un bucle no determinista. Y de ahí sale la pregunta correcta: **un agente no es "mejor" que un pipeline, es un intercambio distinto entre coste y capacidad**. La pregunta no es si el agente funciona — casi siempre funciona — sino **si el valor que aporta en tu caso justifica el multiplicador que acabas de medir**. Si una estimación vale lo suficiente, cinco veces el coste de un pipeline es una ganga. Si no, **el pipeline te estaba sirviendo mejor**.

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Introducción a agentes de IA

**Fecha límite indicada por el programa:** domingo 30 de agosto, al final del día (y en todo caso **hasta dos días antes de la sesión en vivo**).
**Repositorio de referencia:** https://github.com/LIDR-academy/ai-engineering
**Punto de partida:** tu propio proyecto tal como quedó tras la **Sesión 11**.

> **Verificaciones y correcciones sobre el enunciado publicado.** El enunciado de la plataforma remite al "material de la rama `session_12`". Comprobado en el repositorio oficial:
>
> 1. **La rama `session_12` existe**, pero está **26 commits por detrás de `main`** y su carpeta `examples/` solo contiene material de la Sesión 9 (`examples/transcripts/` y `trace_s09.py`). **El kit del ejercicio no está ahí.**
> 2. **El kit real vive en `ai-service/exercises/session-12/` en la rama `main`**, con su propio `README.md`: `sample_transcript_simple.txt`, `sample_transcript_complex.txt`, `reference_retrieval.py`, `calculate_estimate_skeleton.py` y `example_trace_complex.txt` (una traza de ejemplo ya generada).
> 3. **El servicio IA se llama `ai-service/` en `main`** (era `estimator/` en las ramas de sesiones anteriores), aunque **el servicio de `docker-compose` sigue llamándose `estimator`**, que es el nombre que hay que usar en `docker compose exec`.
> 4. **La solución de referencia ya está integrada en `main`** — no la mires antes de intentarlo: `app/generation/agentic/agent_schemas.py`, `app/generation/agentic/agent_tools.py`, `app/generation/agentic/agent_loop.py` y `scripts/run_agent_s12.py`.
> 5. **Discrepancia de nombres documentada en el propio repo (`CLAUDE.md`):** el enunciado llama `calculate_estimate` a la tool de cálculo, pero **en el repo la herramienta aritmética real es `derive_task_hours`** (consenso ponderado por distancia sobre análogos históricos, sin LLM). `calculate_estimate` **solo existió como esqueleto para el alumno**. Para la entrega, mantener el vocabulario del enunciado (`calculate_estimate`) es correcto y es lo que se pide.

**Contexto.** El sistema de estimación funciona bien con un pipeline fijo: reformulas, recuperas, generas. Pero una transcripción real que mezcla un backend de negocio, una integración con un ERP y una app móvil obliga a **buscar presupuestos históricos por separado para cada componente**, calcular parciales y consolidar. **No sabes de antemano cuántas búsquedas harás ni en qué orden: depende de lo que diga la transcripción.**

**Objetivo.** Construir esa capa agéntica **a mano, sin framework**, para ver exactamente de qué está hecha. La idea central: un agente no es magia — **es un bucle que llama a un LLM que decide, ejecuta tools y para cuando ha terminado**.

**Qué vas a construir.** Un agente que:

1. Recibe una **transcripción de reunión**.
2. **Descompone el problema**: identifica los componentes a estimar.
3. Usa **dos tools** para actuar: `search_budgets` (busca presupuestos históricos por componente) y `calculate_estimate` (calcula el coste a partir de los componentes y sus referencias).
4. **Itera en un bucle manual** (razona → actúa → observa → repite) hasta producir una estimación estructurada.
5. Devuelve, junto a la estimación, **una traza que muestra su razonamiento en cada decisión**.

El agente vive en el **servicio IA** (Python + FastAPI). Las tools **envuelven infraestructura que ya tienes**: `search_budgets` reutiliza tu pipeline de recuperación de S9–S10, y `calculate_estimate` es una función determinista de Python. **El backend de negocio no ve el bucle**: sigue enviando la transcripción y recibiendo la estimación estructurada, igual que en S9.

**Lectura previa imprescindible.** Los artículos 1 a 4 de la sesión (de pipeline a agente, anatomía, function calling y el bucle paso a paso). Los artículos 5 y 6 (patrones/diseño de tools y coste) preparan la sesión en vivo y afinan la implementación.

#### Antes de empezar

- **Punto de partida:** tu proyecto tras la Sesión 11. Añades el agente **dentro del servicio IA**.
- **Stack:** Python 3.11+, **Responses API de OpenAI** (`client.responses.create`) con **`gpt-5`** y **esfuerzo de razonamiento `medium`**.
- **Idioma del código: inglés sin excepción** — variables, funciones, descripciones de tools, docstrings y logs. (La documentación de entrega puede ir en español.)

**Kit de partida** (`ai-service/exercises/session-12/` en `main`):

| Fichero | Para qué |
|---|---|
| `sample_transcript_simple.txt` | Un único componente. Para depurar el bucle barato con `gpt-5-mini`. |
| `sample_transcript_complex.txt` | **Cuatro componentes distintos.** La transcripción de los criterios de aceptación. |
| `reference_retrieval.py` | Red de seguridad: stub de recuperación con presupuestos enlatados, **sin base de datos**. Úsalo solo si tu pipeline no está listo; lo ideal es envolver el tuyo. |
| `calculate_estimate_skeleton.py` | Esqueleto del cálculo determinista, con `TODO`s, para no perder tiempo en el modelo de costes. Incluye un `CONTINGENCY_FACTOR = 0.15`. |
| `example_trace_complex.txt` | Traza de referencia de una ejecución real sobre la transcripción compleja. |

#### Las dos tools (+ una opcional)

Defínelas con **JSON Schema y `strict: true`**. Nombres, descripciones y parámetros **en inglés**. En la Responses API **el schema es plano**: `{"type": "function", "name": ..., "description": ..., "parameters": {...}}` — a diferencia de Chat Completions, donde va anidado bajo `function`.

**`search_budgets`**
- *Propósito:* recuperar presupuestos históricos relevantes para **un componente o requisito concreto**.
- *Parámetros:* `query` (string, obligatorio), `filters` (object, opcional: p. ej. `component_type`, `date_range`).
- *Devuelve:* lista de ítems históricos con su importe y metadatos (+ señal de confianza).
- *Implementación:* **envuelve tu retrieval híbrido + reranking de S9–S10. No lo reimplementes**: el agente solo lo invoca.

**`calculate_estimate`**
- *Propósito:* calcular la estimación (parcial o total) a partir de un conjunto de componentes y sus importes de referencia.
- *Parámetros:* `components` (array de objetos, cada uno con `name` y `reference_amounts`).
- *Devuelve:* estructura con el **desglose por componente** y el **total**.
- *Implementación:* **función determinista de Python. No llama al LLM.**

**`validate_estimate` (opcional, recomendada)**
- *Propósito:* guardrails de verificación al estilo S4 sobre la estimación final: **rangos razonables, componentes sin presupuesto de referencia, totales incoherentes**.
- *Parámetros:* `components`, `total_hours`.
- Que el agente la invoque **como último paso antes de devolver el resultado**. Se trabaja en el directo, así que **tenerla explorada da ventaja**.

> **La calidad de las descripciones importa**: son lo único que el modelo lee para decidir cuándo usar cada tool. Escríbelas pensando en un modelo que **no ve tu código, solo el schema**. En el directo se optimiza precisamente esto.

#### Paso a paso

1. **Define las tools** como una lista de schemas planos para la Responses API.
2. **Escribe el system prompt del agente.** Rol claro y **método**: descomponer la transcripción en componentes, buscar presupuestos por cada uno, calcular estimaciones parciales y consolidar. Que sepa que dispone de las dos tools.
3. **Arranca el bucle.** `client.responses.create(...)` con el system prompt (`instructions`), la transcripción como `input`, las `tools` y `reasoning={"effort": "medium"}`.
4. **Conduce el bucle tú mismo.** Al usar tus propias function tools, la API devuelve items `function_call` (con `call_id`, `name`, `arguments`) y **se detiene esperándote**. Ese ida-y-vuelta es el bucle:
   - Recorre `response.output` buscando items `function_call`.
   - Ejecuta la función correspondiente con los `arguments` (parseados desde JSON).
   - Devuelve el resultado como item `function_call_output` **con el mismo `call_id`**.
   - Vuelve a llamar a la API encadenando con `previous_response_id` (o reenviando los items tú mismo).
   - **Repite mientras haya `function_call`.** Sal cuando el modelo devuelva la respuesta final sin más llamadas. **Pon un máximo de iteraciones como salvaguarda.**
5. **No delegues el encadenamiento** al comportamiento agéntico interno de la Responses API. **Conducir el bucle a mano es la única forma de capturar y mostrar cada paso, que es medio ejercicio.**
6. **Captura la traza.** En cada iteración registra: el **razonamiento** del modelo (los *reasoning summaries* de la Responses API son útiles aquí), la **tool invocada con sus argumentos** y la **observación** (el resultado). Guárdalo en una lista ordenada.
7. **Devuelve** la estimación estructurada final **y** la traza.

#### Requisito de traza

La salida debe **dejar ver el razonamiento paso a paso**. Formato mínimo aceptable por iteración:

```
STEP 1
reasoning: <qué decidió el agente y por qué>
action: search_budgets(query="...", filters={...})
observation: <resumen de los ítems devueltos>
```

**No hace falta UI**: una traza legible por consola o en un fichero es suficiente para la entrega.

#### Criterios de aceptación

Con `sample_transcript_complex.txt`, el agente está listo cuando:

- [ ] **Identifica más de un componente** y hace **más de una llamada** a `search_budgets`. *(Si lo resuelve en una sola búsqueda, o el prompt es demasiado directivo, o la transcripción no es lo bastante compleja.)*
- [ ] **Llama a `calculate_estimate`** con los componentes y sus referencias.
- [ ] **Termina por sí solo** — ni bucle infinito ni corte a mitad.
- [ ] Produce una **estimación estructurada coherente**.
- [ ] La traza muestra, **para cada paso, razonamiento + acción + observación**.

#### Entregable y cómo entregar

1. Sube la rama **`session-12/pre-work`** con tu agente implementado dentro del servicio IA.
2. Envía por mail a **`george@lidr.co`** (y a Lia, antes del directo) **hasta dos días antes de la sesión en vivo**:
   - El **enlace completo a la rama/repositorio** en GitHub (URL de tu repo, no del oficial).
   - La **traza de ejecución** para `sample_transcript_complex.txt`.

La rama debe **ejecutar sin errores**, **contener el código del agente** y ser **accesible** (repositorio público o con permisos para el revisor).

**Trae tu agente al directo:** se comparará su comportamiento con el del pipeline fijo sobre la misma transcripción y se analizará su razonamiento.

#### Pitfalls comunes

- **Confundir el schema de Responses con el de Chat Completions.** En Responses, `type`/`name` van al mismo nivel; **no anides bajo una clave `function`**.
- **Olvidar el `call_id`** al devolver el resultado. Cada `function_call_output` debe referenciar el `call_id` de su `function_call`.
- **No poner condición de parada.** Define un **máximo de iteraciones** como salvaguarda, además de la salida natural del bucle.
- **Descripciones de tools vagas.** Si el agente elige mal la tool o inventa argumentos, **casi siempre es la descripción, no el modelo**.
- **Reimplementar la recuperación.** `search_budgets` **envuelve** tu pipeline; no lo reconstruyas.
- **Asumir una sola `function_call` por vuelta.** Puede haber varias: recógelas todas, ejecútalas en paralelo y devuelve todos los `function_call_output` juntos.
- **Olvidar reenviar `instructions`** al encadenar con `previous_response_id`: no arrastra el system prompt.

#### Nota de coste de API

**Depura primero la mecánica del bucle con `gpt-5-mini` y la transcripción simple**: es más barato y rápido para verificar que el ida-y-vuelta funciona. Cuando el bucle sea sólido, cambia a **`gpt-5` con esfuerzo `medium`** para la ejecución real sobre la transcripción compleja. Iterar así mantiene el gasto **por debajo de un par de dólares**.

---

### 🛠️ Contexto técnico para la implementación

Material de referencia consolidado de los seis artículos y del kit oficial, con todo lo necesario para implementar el agente con **Claude Code CLI**. Todo el código, nombres, docstrings y logs **en inglés**.

#### Estructura de módulos

La capa agéntica vive en el servicio IA, junto a la de generación, y **reutiliza** la de recuperación de S9–S11:

```
ai-service/                          # el servicio IA (se llamaba estimator/ en ramas previas)
├── app/
│   ├── generation/
│   │   ├── agentic/
│   │   │   ├── __init__.py
│   │   │   ├── agent_schemas.py     # Pydantic: traza, resultado, argumentos de tools
│   │   │   ├── agent_tools.py       # schemas planos strict:true + implementaciones
│   │   │   └── agent_loop.py        # el bucle manual sobre client.responses.create
│   │   └── rag/
│   │       └── retrieval/           # S9-S11: hybrid_search, reranker, pipeline...
│   └── api/
│       └── routes/estimate.py       # POST /estimate -> run_agent
├── scripts/
│   ├── run_agent_s12.py             # CLI: ejecuta el agente e imprime/guarda la traza
│   └── build_task_corpus.py         # --ingest: corpus de tareas históricas
└── exercises/session-12/            # kit de partida (transcripciones, stub, esqueleto)
```

> **Requisito de datos verificado:** en la implementación de referencia `search_budgets` filtra por `chunk_type='historical_task'`, por lo que el retrieval real necesita el corpus de tareas ingerido:
> `docker compose exec estimator python scripts/build_task_corpus.py --ingest`

#### Schemas de las tools (Responses API — schema **plano**, `strict: true`)

```python
# app/generation/agentic/agent_tools.py

TOOLS = [
    {
        "type": "function",
        "name": "search_budgets",
        "description": (
            "Search historical project budgets for items comparable to ONE software "
            "component. Call this separately for each component in the project; never "
            "combine unrelated components (for example, an ERP integration and a data "
            "migration) in a single query, because mixed results cannot be compared. "
            "Returns comparable historical task items with their recorded hours and a "
            "confidence signal."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A focused description of one component to price.",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional narrowing filters for the search.",
                    "properties": {
                        "component_type": {
                            "type": "string",
                            "enum": [
                                "integration",
                                "migration",
                                "frontend",
                                "backend",
                                "mobile",
                            ],
                        },
                        "date_range": {
                            "type": "string",
                            "description": "ISO date range, e.g. '2022-01-01/2025-12-31'.",
                        },
                    },
                    "required": ["component_type", "date_range"],
                    "additionalProperties": False,
                },
            },
            "required": ["query", "filters"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "calculate_estimate",
        "description": (
            "Compute the effort breakdown and the total from a set of components and "
            "their historical reference amounts. Deterministic arithmetic, no LLM. "
            "Only call this after budgets have been searched for EVERY component."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "Recorded hours of comparable historical tasks.",
                            },
                        },
                        "required": ["name", "reference_amounts"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["components"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "validate_estimate",
        "description": (
            "Run verification guardrails over a candidate estimate: implausible ranges, "
            "components with no reference budget, and inconsistent totals. Call this as "
            "the last step before producing the final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "hours": {"type": "number"},
                        },
                        "required": ["name", "hours"],
                        "additionalProperties": False,
                    },
                },
                "total_hours": {"type": "number"},
            },
            "required": ["components", "total_hours"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]
```

> ⚠️ Con `strict: true` **todas** las propiedades declaradas deben estar en `required` y `additionalProperties` debe ser `false` en cada objeto. Para hacer un campo "opcional" en la práctica, decláralo `required` y admite un valor vacío/nulo por unión de tipos, o documenta en la descripción cuándo debe ignorarse.

#### Registro y despacho de tools

```python
# app/generation/agentic/agent_tools.py (cont.)

from typing import Any, Awaitable, Callable

ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

TOOL_REGISTRY: dict[str, ToolFn] = {
    "search_budgets": search_budgets,
    "calculate_estimate": calculate_estimate,
    "validate_estimate": validate_estimate,
}


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call; never let a failing tool crash the agent loop."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return await fn(args)
    except Exception as exc:  # a failing tool is an observation, not a crash
        logger.warning("tool_failed", tool=name, error=str(exc))
        return {"error": str(exc)}
```

El registro **desacopla qué tools existen de cómo funciona el bucle**: añadir una tool es añadir un schema a `TOOLS` y una entrada al registro; **el bucle no cambia**.

#### Esquemas de traza y resultado

```python
# app/generation/agentic/agent_schemas.py

from typing import Any, Literal

from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    """One iteration of the agent loop: reasoning, action and observation."""

    step: int
    reasoning: str | None = Field(default=None, description="Model reasoning summary")
    action: str
    arguments: dict[str, Any]
    observation: dict[str, Any]


class ComponentEstimate(BaseModel):
    name: str
    hours: float
    reference_task_ids: list[str] = Field(default_factory=list)


class Estimate(BaseModel):
    """Deterministic output contract, regardless of the path the agent took."""

    components: list[ComponentEstimate]
    total_hours: float
    notes: str


class AgentResult(BaseModel):
    status: Literal["done", "needs_review", "max_steps_exceeded"]
    estimate: Estimate | None = None
    reason: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
```

**La no-determinación vive dentro del bucle; el contrato de salida es determinista.**

#### El bucle manual (pieza central del ejercicio)

```python
# app/generation/agentic/agent_loop.py

import asyncio
import json

from openai import AsyncOpenAI

client = AsyncOpenAI()

MAX_STEPS = 8
MODEL = "gpt-5"
REASONING_EFFORT = "medium"

SYSTEM_PROMPT = (
    "You are a software estimation agent. Given a meeting transcript:\n"
    "1. Identify the distinct components that must be estimated separately.\n"
    "2. Call search_budgets ONCE PER COMPONENT to retrieve comparable historical "
    "tasks. Never combine unrelated components in a single query.\n"
    "3. If a search returns weak or low-confidence matches, reformulate the query "
    "with different wording before computing anything.\n"
    "4. Once every component has references, call calculate_estimate with all of "
    "them, then call validate_estimate.\n"
    "5. Produce the final structured estimate. If a component has no reliable "
    "historical reference, say so explicitly in the notes instead of inventing a "
    "number with false precision."
)


async def run_agent(transcript: str) -> AgentResult:
    """Manual reason-act-observe loop over the OpenAI Responses API."""
    trace: list[TraceStep] = []
    step_number = 0

    response = await client.responses.parse(
        model=MODEL,
        reasoning={"effort": REASONING_EFFORT, "summary": "auto"},
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": transcript}],
        tools=TOOLS,
        text_format=Estimate,
    )

    for _ in range(MAX_STEPS):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break  # no tool calls: the model has produced its final answer

        summary = _extract_reasoning_summary(response)

        results = await asyncio.gather(
            *(execute_tool(call.name, json.loads(call.arguments)) for call in calls)
        )

        tool_outputs = []
        for call, result in zip(calls, results):
            step_number += 1
            trace.append(
                TraceStep(
                    step=step_number,
                    reasoning=summary,
                    action=call.name,
                    arguments=json.loads(call.arguments),
                    observation=result,
                )
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,  # MUST match the originating call
                    "output": json.dumps(result),
                }
            )

        response = await client.responses.parse(
            model=MODEL,
            previous_response_id=response.id,
            instructions=SYSTEM_PROMPT,  # not carried over by previous_response_id
            input=tool_outputs,
            tools=TOOLS,
            text_format=Estimate,
        )
    else:
        return AgentResult(status="max_steps_exceeded", trace=trace)

    return AgentResult(
        status="done",
        estimate=response.output_parsed,
        trace=trace,
    )


def _extract_reasoning_summary(response) -> str | None:
    """Pick up the reasoning summary items the Responses API may emit."""
    for item in response.output:
        if item.type == "reasoning" and getattr(item, "summary", None):
            return " ".join(part.text for part in item.summary)
    return None
```

**Decisiones que no son opcionales en producción:** la primera llamada **fuera** del bucle; recoger **todas** las `function_call` de cada vuelta y ejecutarlas con `asyncio.gather`; emparejar cada `function_call_output` con su `call_id`; reenviar `instructions` al encadenar con `previous_response_id`; acumular la traza en cada vuelta; y la guarda `range(MAX_STEPS)` con su `else` para el caso de no convergencia.

#### Formato de traza para la entrega

```python
# scripts/run_agent_s12.py (fragment)

def render_trace(result: AgentResult) -> str:
    """Render the agent trace in the format required by the exercise."""
    lines: list[str] = []
    for step in result.trace:
        lines.append(f"STEP {step.step}")
        lines.append(f"reasoning: {step.reasoning or '(no summary emitted)'}")
        lines.append(f"action: {step.action}({json.dumps(step.arguments)})")
        lines.append(f"observation: {summarize(step.observation)}")
        lines.append("")
    lines.append(f"status: {result.status}")
    if result.estimate is not None:
        lines.append(f"total_hours: {result.estimate.total_hours}")
    return "\n".join(lines)
```

Traza esperada sobre `sample_transcript_complex.txt` (forma, no valores literales):

```
STEP 1  action: search_budgets(query="business backend with orders/routes/tracking API", filters={"component_type":"backend"})   observation: 4 matches, median 120h
STEP 2  action: search_budgets(query="ERP integration via REST API", filters={"component_type":"integration"})                   observation: 3 matches, median 96h
STEP 3  action: search_budgets(query="legacy data migration, undocumented schema", filters={"component_type":"migration"})       observation: 1 weak match, low confidence
STEP 4  action: search_budgets(query="data migration effort, mid-size dataset", filters={"component_type":"migration"})          observation: 3 matches, median 90h
STEP 5  action: search_budgets(query="mobile app consuming customer portal API", filters={"component_type":"mobile"})            observation: 5 matches, median 150h
STEP 6  action: calculate_estimate(components=[...])                                                                             observation: total 456h across 4 components
STEP 7  action: validate_estimate(components=[...], total_hours=456)                                                             observation: ok, no issues found
status: done
```

**El paso 4 es la prueba de que el agente se gana su sitio**: no calculó sobre la coincidencia débil del paso 3 — leyó la observación, reformuló y volvió a buscar. Ese comportamiento **no está programado**; emerge de que el modelo ve el resultado de su propia acción.

#### Cálculo determinista (esqueleto del kit)

```python
# calculate_estimate_skeleton.py (shape of the deliverable)

from statistics import median
from typing import Any

CONTINGENCY_FACTOR = 0.15


def calculate_estimate(args: dict[str, Any]) -> dict[str, Any]:
    """Cost each component from its historical reference amounts, then total."""
    components = args["components"]
    breakdown: list[dict[str, Any]] = []

    for component in components:
        amounts = component["reference_amounts"]
        base_hours = median(amounts) if amounts else 0.0
        hours = round(base_hours * (1 + CONTINGENCY_FACTOR), 1)
        breakdown.append(
            {
                "name": component["name"],
                "base_hours": base_hours,
                "hours": hours,
                "reference_count": len(amounts),
                "has_reference": bool(amounts),
            }
        )

    return {
        "breakdown": breakdown,
        "total_hours": round(sum(item["hours"] for item in breakdown), 1),
        "contingency_factor": CONTINGENCY_FACTOR,
    }
```

**Sin LLM, sin efectos secundarios, testeable con aserciones deterministas.** Los componentes sin referencia (`has_reference: False`) son exactamente el caso que `validate_estimate` debe señalar y que justifica un `status="needs_review"` en lugar de un número inventado.

#### El agente detrás del endpoint (frontera con el backend de negocio)

```python
# app/api/routes/estimate.py

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class EstimateRequest(BaseModel):
    transcript: str


@router.post("/estimate")
async def estimate(request: EstimateRequest) -> dict:
    result = await run_agent(request.transcript)
    return result.model_dump()
```

```ruby
# backend de negocio (Rails): routing the AI service response.
# El patrón es independiente del stack: cualquier cliente HTTP sirve.
response = HTTP.post("#{AI_SERVICE_URL}/estimate", json: { transcript: transcript })
result = JSON.parse(response.body)

case result["status"]
when "done"
  save_estimate(result["estimate"])
when "needs_review"
  enqueue_for_human_review(result["estimate"], result["reason"])
when "max_steps_exceeded"
  flag_for_manual_estimation(result["trace"])
end
```

El backend de negocio **no ve el bucle, ni las `function_call`, ni los `call_id`, ni cuántas vueltas dio el agente**. Envía una transcripción y recibe `status` + estimación estructurada. Esa frontera es lo que permite reescribir el agente sin tocar la capa de negocio.

#### Instrumentación de coste

```python
# app/generation/agentic/agent_cost.py

from dataclasses import dataclass


@dataclass
class Pricing:
    input_per_1k: float
    output_per_1k: float  # reasoning tokens are billed as output tokens


@dataclass
class CostLedger:
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # visibility only: already inside output_tokens

    def add(self, usage) -> None:
        self.steps += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.reasoning_tokens += usage.output_tokens_details.reasoning_tokens

    def cost(self, pricing: Pricing) -> float:
        return (
            self.input_tokens / 1000 * pricing.input_per_1k
            + self.output_tokens / 1000 * pricing.output_per_1k
        )
```

Conectarlo es **una línea por vuelta** (`ledger.add(response.usage)` tras cada llamada). **No sumes los tokens de razonamiento aparte: ya están dentro de `output_tokens`.** Mide además el **coste por paso** (revela el crecimiento del contexto), el **percentil 95** (la cola larga es donde se pierde el dinero) y el **ratio frente al pipeline** sobre las mismas entradas.

#### Comandos de referencia

```bash
# Kit del ejercicio (rama main del repo oficial)
git clone https://github.com/LIDR-academy/ai-engineering.git
ls ai-engineering/ai-service/exercises/session-12/

# Levantar el stack e ingerir el corpus de tareas históricas
docker compose up -d
docker compose exec estimator python scripts/build_task_corpus.py --ingest

# 1) Depuración barata del bucle (retrieval real)
docker compose exec estimator python scripts/run_agent_s12.py \
  exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --effort minimal

# 2) Depuración offline con el stub (sin base de datos)
uv run python scripts/run_agent_s12.py \
  exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --stub

# 3) Ejecución real (entregable) sobre la transcripción compleja
docker compose exec estimator python scripts/run_agent_s12.py \
  exercises/session-12/sample_transcript_complex.txt --model gpt-5 --effort medium \
  --out exercises/session-12/example_trace_complex.txt
```

#### Parámetros de referencia del programa

| Parámetro | Valor de partida | Nota |
|---|---|---|
| Modelo de orquestación | `gpt-5`, `reasoning.effort = "medium"` | Ejecución real y entregable |
| Modelo de depuración | `gpt-5-mini`, `effort = "minimal"` | Para verificar la mecánica del bucle, barato |
| `MAX_STEPS` | `8` | Salvaguarda obligatoria contra el bucle infinito |
| Schema de tools | `strict: true`, **plano** | `type`/`name`/`description`/`parameters` al mismo nivel |
| Encadenado de estado | `previous_response_id` | **No arrastra `instructions`**: reenvíalas cada vuelta |
| Llamadas por vuelta | **puede haber varias** | Recogerlas todas y ejecutar con `asyncio.gather` |
| Tools obligatorias | `search_budgets`, `calculate_estimate` | `validate_estimate` opcional recomendada |
| Granularidad de búsqueda | **1 llamada por componente** | Nunca mezclar componentes en una query |
| Filtro del corpus | `chunk_type='historical_task'` | Requiere `build_task_corpus.py --ingest` |
| Factor de contingencia | `0.15` | Del esqueleto oficial de `calculate_estimate` |
| Presupuesto del ejercicio | **< 2 USD** | Depurar con mini, ejecutar con gpt-5 |
| Heurística de coste | ~0,10 USD ≈ 30k-50k tokens | Regla mental de Barry Zhang (Anthropic) |
| Sobrecoste esperado agente/pipeline | **~5x-6x** | Dominado por los tokens de **entrada** que crecen por vuelta |
| Idioma del código | **inglés** | Variables, funciones, descripciones, docstrings, logs |

#### Orden de trabajo sugerido con Claude Code CLI

1. **Schemas primero.** `agent_schemas.py` (traza, resultado, estimación) y `agent_tools.py` (los tres schemas planos `strict:true`). Sin bucle todavía.
2. **Implementaciones de tools.** `search_budgets` **envolviendo** el `retrieve()` de S9–S11 (filtro `chunk_type='historical_task'`); `calculate_estimate` determinista a partir del esqueleto; `validate_estimate` con los guardrails de S4.
3. **Registro y despacho** con `try/except` que convierte el fallo en observación informativa.
4. **El bucle**, con `MAX_STEPS`, `asyncio.gather`, `call_id` y `instructions` reenviadas.
5. **La traza** y el `render_trace` con el formato `STEP / reasoning / action / observation`.
6. **CLI `run_agent_s12.py`** con `--model`, `--effort`, `--stub` y `--out`.
7. **Endpoint `POST /estimate`** devolviendo `status` + estimación + traza.
8. **Cost ledger** y logging estructurado por paso.
9. **Iterar mirando las trazas**: si el agente elige mal o mezcla componentes, **corrige la descripción de la tool, no el bucle**.

## Checklist antes de la siguiente sesión

- [ ] Sabes distinguir **tarea / workflow / agente** y explicar que la única diferencia estructural es **quién elige el siguiente paso**.
- [ ] Puedes defender que **el pipeline es el estado por defecto** y enumerar sus cuatro virtudes (predecible, barato, testeable, rápido).
- [ ] Identificas la señal que justifica un agente: **un árbol de decisión que no puedes pre-mapear**.
- [ ] Sabes que lo único que compras es **orquestación adaptativa** — no mejor recuperación, ni mejor generación, ni inteligencia nueva.
- [ ] Puedes recitar los cinco criterios de decisión, incluido el de **verificabilidad del error**.
- [ ] Entiendes por qué los **agentes de código** son el caso canónico que funciona (resultado verificable con tests).
- [ ] Sabes nombrar los órganos del bucle: **razonamiento, planificación, acción, observación, handover, estado y condición de parada**.
- [ ] Tienes claro que el `Thought` de ReAct **se ha mudado dentro del modelo** y que la auditabilidad exige capturar *reasoning summaries* deliberadamente.
- [ ] Puedes explicar por qué **la calidad de la observación gobierna la calidad de la siguiente decisión**, y por qué un error mudo ciega al agente.
- [ ] Aplicas **mínimo privilegio** a las tools y sabes qué acciones exigen validación o humano antes de ejecutarse.
- [ ] Sabes diseñar un **handover** con contrato explícito (`status="needs_review"` + razón + parcial calculado).
- [ ] Has interiorizado que **el modelo nunca ejecuta tu código**: emite una intención y tú decides.
- [ ] Declaras tools con **schema plano y `strict: true`** y no confundes el formato de Responses con el de Chat Completions.
- [ ] Emparejas siempre `function_call_output` con su **`call_id`**.
- [ ] Encadenas con **`previous_response_id`** y **reenvías las `instructions`**.
- [ ] Manejas **varias `function_call` por vuelta** y las ejecutas en paralelo con `asyncio.gather`.
- [ ] Sabes traducir el mismo contrato a Anthropic (`input_schema` / `tool_use` / `tool_result`) y por qué conviene aislar el transporte en un adaptador.
- [ ] Tu bucle tiene **condición de parada doble**: respuesta final del modelo **y** `MAX_STEPS`.
- [ ] Una tool que falla **devuelve una observación, no revienta el agente**.
- [ ] Tu salida final está ceñida a un **esquema Pydantic**: camino no determinista, **contrato de salida determinista**.
- [ ] Puedes situar tu agente en los tres ejes (iterativo/un paso, reactivo/proactivo, plan fijo/dinámico) **y justificar por qué**.
- [ ] Sabes que **la forma del agente puede decidirse por petición** mediante un enrutado barato al principio.
- [ ] Cuando el agente se comporta mal, **sospechas de la descripción de la tool antes que del modelo**.
- [ ] Reconoces la señal de fronteras mal trazadas: explicar en una descripción cuándo **no** usar esa tool.
- [ ] Optimizas **leyendo trazas** con un conjunto de transcripciones representativas, no adivinando.
- [ ] Sabes de dónde sale el sobrecoste de un agente y que **el factor dominante es el contexto que crece vuelta a vuelta**.
- [ ] Tienes un `CostLedger` conectado y **no sumas dos veces** los tokens de razonamiento.
- [ ] Mides **coste por paso, percentil 95 y ratio frente al pipeline**, no solo la media.
- [ ] Conoces las cinco palancas de control de coste, y que la mayor (**enrutar**) está **fuera** del bucle.
- [ ] Tu agente cumple los cinco criterios de aceptación sobre `sample_transcript_complex.txt` y su traza lo demuestra.
- [ ] Todo el código, nombres, descripciones, docstrings y logs están **en inglés**.

## Documentación de referencia

**Agentes: cuándo y cómo**

- Anthropic, *Building Effective Agents* — distinción workflow/agente, *ground truth* del entorno y la recomendación de empezar por lo más simple: https://www.anthropic.com/research/building-effective-agents
- Barry Zhang (Anthropic), *How We Build Effective Agents* — taxonomía tarea/workflow/agente y la aritmética de coste: https://shellypalmer.com/2026/04/how-anthropic-thinks-about-agents-workflows-and-tasks/
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (ICLR 2023), arXiv 2210.03629: https://arxiv.org/abs/2210.03629

**Function calling y tools**

- OpenAI, *Function calling (Responses API)* — schema plano, items `function_call` / `function_call_output`, `call_id` y `strict`: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI, *Migrate to the Responses API* — diferencias de forma respecto a Chat Completions: https://platform.openai.com/docs/guides/migrate-to-responses
- OpenAI, *Structured outputs* — salida ceñida a un schema con `text.format` / `parse`: https://platform.openai.com/docs/guides/structured-outputs
- OpenAI, *Production best practices* — el campo `usage` con tokens de entrada, salida y razonamiento: https://platform.openai.com/docs/guides/production-best-practices
- Anthropic, *How tool use works* — el contrato como interfaz tipada y los bloques `tool_use` / `tool_result`: https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works
- Anthropic, *Implement tool use / Define tools* — descripciones efectivas, *namespacing* y resultados de alto valor: https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use
- Anthropic, *Writing effective tools for agents* — el diseño de tools como superficie que se itera empíricamente: https://www.anthropic.com/engineering/writing-tools-for-agents

**Servicio y ejecución**

- FastAPI — Lifespan events: https://fastapi.tiangolo.com/advanced/events/
- Pydantic v2 — Fields y validación: https://docs.pydantic.dev/latest/concepts/fields/
- Python — `asyncio.gather`: https://docs.python.org/3/library/asyncio-task.html#asyncio.gather
- structlog: https://www.structlog.org/

**Material del programa**

- Repositorio oficial: https://github.com/LIDR-academy/ai-engineering
- Kit del ejercicio (rama `main`): https://github.com/LIDR-academy/ai-engineering/tree/main/ai-service/exercises/session-12
- Rama `session_12` (26 commits por detrás de `main`; **no contiene el kit**): https://github.com/LIDR-academy/ai-engineering/tree/session_12

---

## Índice de páginas de origen (LIDR Training — Sesión 12)

| # | Página | Duración |
|---|---|---|
| 0 | Sesión 12: Introducción a agentes de IA (raíz) | 123 min |
| 1 | ✍️ Ejercicio: Introducción a agentes de IA | — |
| 2 | 📄 De pipeline a agente: cuándo tu sistema RAG necesita una capa de decisión | 23 min |
| 3 | 📄 Anatomía de un agente: qué ocurre dentro del bucle | 22 min |
| 4 | 📄 Function calling en la práctica: tools, schemas y contrato con el modelo | 21 min |
| 5 | 📄 El bucle agéntico paso a paso | 18 min |
| 6 | 📄 Patrones de agentes y diseño de tools de calidad | 21 min |
| 7 | 📄 Cuánto cuesta un agente | 18 min |
| 8 | 🆙 Evalúa el contenido de este Módulo (encuesta 1-5, sin contenido formativo) | — |

*Autor del material original: Antonio Pérez — AI Engineering 2026/05, LIDR Academy. Documento de estudio y contexto de implementación elaborado a partir de las páginas de la Sesión 12 y verificado contra el repositorio oficial del programa.*
