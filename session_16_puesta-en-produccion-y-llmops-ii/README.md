# Sesión 16 — Puesta en producción II: Calidad y observabilidad

> 6️⃣ Módulo: Despliegue y puesta en producción · 77 min · 8 lecciones + 1 prueba
> Proyecto 2 — sistema de estimación: backend de negocio (Ruby on Rails) + servicio IA (Python/FastAPI) + base de datos relacional (PostgreSQL) + base de datos vectorial.

## Objetivo de la sesión

Al cierre de la Sesión 15 el sistema de estimación está desplegado: documentado, containerizado, con pipeline de CI/CD y con la frontera público/privado materializada sobre redes reales. El smoke test está en verde, lo que significa que el sistema está **vivo**: `/health` responde y una estimación de prueba recorre el flujo completo y vuelve con la forma correcta. Lo que ningún smoke test puede decir es si esa estimación es **buena**. El sistema puede devolver "250 horas" con toda la seguridad del mundo y no hay forma de saber si es un acierto razonable o una cifra inventada con aplomo. Está vivo, pero opera a ciegas.

La Sesión 16 le quita la venda. El eje es pasar de "el sistema responde" a "el sistema responde bien, de forma segura y a un coste que sé cuánto es". A ese conjunto de prácticas —operar un sistema de IA en producción con los ojos abiertos— se le llama **LLMOps**, y hace falta porque un sistema con un LLM en el corazón rompe la garantía silenciosa de todo el software clásico: que el mismo código se comporta igual. Aquí el comportamiento cambia sin que cambie el código (el proveedor actualiza el modelo, los datos derivan, una palabra del prompt altera casos inesperados) y, cuando falla, **falla en silencio**: no hay crash ni test rojo, solo respuestas peores y una factura mayor.

La sesión responde por orden a las cuatro preguntas que el despliegue deja abiertas: **¿es seguro?** (guardrails, derecho a decir "no lo sé", escalado a humanos y compliance-by-design), **¿es bueno?** (golden test set y evaluation harness), **¿sigue siendo bueno?** (regression testing y KPIs), **¿qué hace en producción?** (observabilidad: señales, dashboard, trazas y feedback loops) y **¿cuánto cuesta?** (modelo por tarea, cacheo, higiene de prompts, A/B testing y la decisión de self-hostear el modelo). El orden no es arbitrario: la seguridad va primero porque es el suelo; sin él, cualquier métrica de calidad da igual.

Un detalle que atraviesa todos los artículos: casi nada es magia de IA. Medir contra una referencia, vigilar señales, poner límites deterministas y controlar el gasto son disciplinas de ingeniería de siempre. Lo único nuevo es aplicarlas a un sistema cuyo comportamiento no vive en el código y que, por tanto, hay que observar como algo vivo. Al final, el sistema no solo está en producción: está **operado** en producción.

## Qué vas a aprender

### 1. 📄 Introducción LLMOps — 11 min

Parte de la pequeña victoria de la sesión anterior (sistema desplegado, smoke test en verde) para señalar su límite: el smoke test dice que el sistema está vivo, no que estime bien. Operar a ciegas es operar un sistema que puede estar perfectamente vivo y ser, a la vez, malo, cada vez peor, inseguro y ruinoso.

**El día que "no ha cambiado el código" deja de valer.** Todo lo que sabéis de operaciones se apoya en una garantía: si nadie toca el repositorio, el sistema de hoy hace lo mismo que el de ayer, y si algo falla, falla ruidosamente. Un LLM la rompe por los dos lados. El mismo código se comporta distinto sin que nadie toque nada: el proveedor actualiza el modelo por debajo, los datos del mundo derivan, una palabra del prompt cambia el comportamiento en casos que ni imaginabais. El diff ya no captura el cambio porque el cambio no está en el diff. Y cuando falla, **falla en silencio**: estimaciones peores, factura de tokens que crece cada semana, más "me inventé un número", sin que salte ninguna alarma. LLMOps existe porque las herramientas de operaciones clásicas dan por supuesta una garantía que aquí no se cumple.

**Cuatro preguntas que el despliegue no responde.** *¿Es bueno?* —de forma medible, no a ojo un martes—. *¿Sigue siendo bueno?* —tras el próximo cambio de prompt, la próxima actualización del proveedor, el próximo mes de deriva—. *¿Es seguro?* —¿reconoce cuándo no tiene datos en vez de inventar, escala a un humano, cumple la regulación?—. *¿Cuánto cuesta?* —¿sabéis el coste de cada respuesta y os enteraríais antes de la factura si se duplica?—. Alrededor del sistema desplegado se sitúan así las cuatro preocupaciones del mapa de LLMOps: **seguridad, evaluación, observabilidad y coste**.

**LLMOps es una disciplina, no una herramienta.** No hay producto que se instale y os deje "hacer LLMOps". Hay herramientas que ayudan (trazado, evaluación, monitorización), pero son medios. LLMOps es la práctica de operar un sistema no determinista de forma **segura, medible, observable y sostenible en coste**, y mantenerlo así en el tiempo. Es la continuación natural de la idea de la Sesión 15: si "producción" era un conjunto de promesas de *estar bien desplegado*, aquí aparecen las de *estar bien operado*.

**Por dónde se empieza.** Lo natural sería lanzarse a medir la calidad, pero hay una pregunta más básica: la **seguridad**. Un sistema que devuelve una cifra con total confianza sin un solo dato que la respalde no es "un poco impreciso": miente con seguridad, y ninguna métrica de acierto lo captura. Lo primero que LLMOps exige a lo desplegado no es una métrica, sino un suelo de comportamiento seguro.

### 2. 📄 Un sistema debe saber decir "No lo sé" — 14 min

El caso que abre el artículo: una transcripción que habla de integrar el producto con un ERP interno sin documentación ni precedentes en la base vectorial. El sistema recupera, razona, genera y devuelve **"180 horas. Confianza: alta."** Es lo peor que puede producir: no porque 180 sea incorrecto, sino porque no tenía base para darlo y lo ha dado con aplomo, y alguien va a comprometer presupuesto, fechas y equipo alrededor de esa cifra.

**El fallo que ninguna métrica de acierto ve.** Las métricas de calidad solo miran los casos en los que **sí** hay respuesta: miden lo cerca que está el número cuando debía haber un número. El caso de las 180 horas no lo ven, porque ahí el problema es que no debería haber número. Por eso la seguridad es un eje distinto de la calidad, y va primero: la calidad es la media (cómo responde cuando responde); la seguridad es el suelo (que no se comporte de forma inaceptable en los casos difíciles, raros o sensibles). Un sistema con calidad media excelente puede ser peligroso, y en producción, tarde o temprano, todo se sale de su terreno.

**Guardrails: dos filtros, no una frase en el prompt.** El **guardrail de entrada** mira lo que llega antes de tocar al modelo: ¿está dentro del alcance (estimar)?, ¿trae instrucciones inyectadas ("ignora tus reglas y…")?, ¿contiene datos sensibles que no deberían acabar en un prompt? Lo que no pasa se rechaza o se marca antes de gastar un token. El **guardrail de salida** mira lo que produce el modelo antes de que llegue al usuario: ¿es un `EstimateResponse` válido con su confianza?, ¿las fuentes citadas existen de verdad?, ¿el número está dentro de límites razonables (nada de 4 horas para migrar una base de datos entera)? La idea que más se malentiende: **un guardrail es código, no una frase en el prompt**. "Por favor, no te inventes las fuentes" es un deseo; un guardrail es una comprobación determinista que se ejecuta siempre y verifica, por ejemplo, que las fuentes citadas existen en la base de datos, bloqueando la respuesta si no. Es el trozo predecible alrededor del trozo impredecible.

**El derecho a decir "no lo sé".** Los guardrails atrapan lo que está claramente mal, pero el caso de las 180 horas tiene la forma correcta: lo que falla es el exceso de confianza. Hace falta un camino explícito para reconocer que no se sabe: cuando la recuperación devuelve precedentes pobres o inexistentes, o la confianza cae por debajo de un umbral, la respuesta correcta es "no tengo datos suficientes para estimar esto con fiabilidad". Eso no es un fallo: es el sistema funcionando bien. Hay tres caminos, y elegir bien entre ellos es el corazón de la seguridad:

- **Responder**, cuando hay base suficiente: estimación con su confianza y sus fuentes.
- **Abstenerse con honestidad** (*safe-completion*): una respuesta parcial y útil que reconoce el límite y dice qué haría falta para superarlo ("necesitaría precedentes de integraciones similares o una descripción más detallada del alcance").
- **Escalar a un humano**, cuando el caso es sensible o de alto impacto (una estimación que mueve mucho dinero). La intervención humana no es un parche: es un estado más del sistema, decidido a propósito.

Esto no es magia de IA, es diseño de producto: decidís en código qué hace el sistema cuando no está seguro.

**Compliance-by-design.** El marco europeo de IA se apoya en principios estables aunque plazos y detalles se sigan moviendo: enfoque basado en el **riesgo** (más impacto, más obligaciones), **transparencia** (el usuario sabe que interactúa con IA y conoce sus límites), **supervisión humana** y **trazabilidad** (poder reconstruir por qué el sistema hizo lo que hizo). Compliance-by-design es construirlos dentro del sistema desde el diseño, no atornillarlos al final. Y casi todo lo que os hace cumplir es lo mismo que os hace seguros: abstenerse es transparencia sobre los límites, escalar es supervisión humana, registrar cada estimación con fuentes y confianza es trazabilidad. Aviso práctico: el detalle regulatorio concreto (qué obligación aplica a qué sistema y desde cuándo) es un blanco en movimiento; hay que contrastarlo con la fuente oficial vigente.

**Seguro no es bueno.** El suelo evita el desastre, pero no garantiza la calidad. Un sistema puede no hacer nunca nada peligroso y dar estimaciones mediocres una tras otra. Y la calidad no se juzga a ojo: hace falta una vara.

### 3. 📄 Evaluación en producción — 13 min

Cambiáis una palabra en el prompt, lanzáis tres o cuatro transcripciones que tenéis a mano, "se ven mejor", desplegáis. Acabáis de tomar una decisión de producto basada en nada: es sesgo de confirmación con pasos intermedios. Para saber si un sistema no determinista es bueno hay que dejar de mirarlo y empezar a medirlo.

**Por qué el ojo no sirve.** Tres motivos estructurales que no se arreglan con buena voluntad. **Probáis los casos que se os ocurren**, que son los representativos, justo los que el sistema domina; los que fallan son, por definición, los que no se os ocurren. **El sistema no es determinista**: la misma transcripción puede dar respuestas distintas; juzgarlo por una tirada es juzgar un dado por un lanzamiento. **No tenéis contra qué comparar**: sin punto de referencia fijo, "mejor" es una sensación relativa a un recuerdo poco fiable. Igual que un laboratorio no pesa a ojo, necesitáis un instrumento.

**El golden test set: vuestra definición de "bueno", escrita.** Un conjunto de casos de referencia en los que vosotros —no el modelo— habéis decidido de antemano cuál es una buena respuesta. Cada caso lleva una entrada (transcripción o descripción de tarea), una estimación esperada y, sobre todo, un **rango aceptable**, porque una estimación es un intervalo razonable: un caso "de 8 puntos" pasa si el sistema responde entre 5 y 13. Dos cosas hacen que valga: que cubra **dificultades distintas** (fácil y frecuente, medio-alto, de borde) y que incluya al menos un **caso de abstención** (sin precedentes, donde la respuesta correcta es "no tengo datos suficientes"). Un sistema que acierta mucho pero nunca sabe abstenerse no es bueno: es un buen adivino. Lo esencial es *cuándo* se decide qué es bueno: **antes**, en frío, no caso a caso en el calor de un despliegue.

**El harness: medir sin opinar.** El **evaluation harness** coge cada caso del set, se lo lanza al servicio IA desplegado, compara la respuesta con lo esperado y agrega el resultado en un puñado de números. La comparación es mecánica: un caso de estimación pasa si cae en el rango; uno de abstención, si el sistema se abstuvo. Enlaza con la Sesión 15: en CI se mockea el modelo porque se testea *vuestro código*; el harness es lo contrario, **llama al modelo real** porque su trabajo es *evaluar al modelo*. Testear (determinista, mockeado, en cada commit) y evaluar (no determinista, real, deliberado) son dos caras de la misma moneda; por eso el harness no corre en cada push. Lo que devuelve cambia la conversación: de "me parece que responde mejor" a "el 72% cae en rango, el error medio es de 3 puntos y abstiene correctamente en los casos sin datos".

**Un golden set es tan bueno como el criterio que hay detrás.** Si los valores esperados son inventados a ojo, tenéis una máquina que mide con precisión contra una vara torcida (*garbage in, garbage out*): basadlos en los datos históricos reales de la base vectorial. Y tratadlo como algo **vivo**: cada fallo en producción que no estaba cubierto se convierte en un caso nuevo, de modo que la vara crece justo por donde el sistema ha demostrado ser débil. Un set pequeño, honesto y creciente vale más que uno grande hecho de una tacada.

**Lo que queda.** Una medida aislada dice cómo está el sistema hoy, no si el próximo cambio lo mejora o lo empeora. El verdadero peligro es tener un sistema bueno y estropearlo sin enteraros.

### 4. 📄 Tratamiento de regresiones — 12 min

Un usuario se queja de que las estimaciones de autenticación se quedan cortas. Ajustáis el prompt para ser más conservador con la autenticación, comprobáis ese caso, arreglado, desplegáis. Lo que no habéis visto es que el mismo ajuste ha empeorado las migraciones de datos, las integraciones y media docena de tipos de tarea que ni tocasteis. Eso es una **regresión silenciosa**, la forma más común y traicionera en que un sistema de IA bueno se estropea.

**Por qué arreglar un caso empeora otros.** En código normal el efecto de un cambio está acotado: la función cambia y lo que no la llama ni se entera; podéis razonar sobre el radio de impacto. Un prompt no es un módulo con una responsabilidad: es una instrucción global que condiciona **todo** lo que el modelo hace. No existe "la parte de autenticación" del prompt; empujarlo desplaza el comportamiento entero. El radio de impacto de un cambio de prompt es el sistema completo. Consecuencia: **"he arreglado el bug" nunca significa "no he creado otros"**.

**Regression testing: no miréis el caso, mirad el conjunto.** Tras cualquier cambio —prompt, modelo nuevo, datos reindexados— se ejecuta el golden set entero y se compara con la ejecución anterior. La pregunta no es "¿arreglé el caso?", sino "¿está el sistema, en su conjunto, mejor o peor que antes?": ¿subió o bajó la tasa de aciertos?, ¿algún caso que pasaba ahora falla? El valor del harness no es dar *una* medición, sino permitir *comparar* mediciones: "antes acertaba el 80%, con tu cambio el 60%". Por eso hay que **guardar el informe de cada ejecución**: sin la línea base, "60%" no significa nada; contra el "80%" de ayer, es una alarma.

> Un cambio no se juzga por el caso que arregla, sino por lo que le hace al conjunto.

**Qué medir: los KPIs del sistema.** La calidad no es un solo número; cada forma de fallar pide su métrica:

- **Acierto** — tasa de estimaciones dentro del rango. La que ya calcula el harness.
- **Tasa de alucinación** — fuentes que no existen, cifras sin apoyo en los datos. Caza el fallo del "número con aplomo y sin base" que la tasa de acierto no ve.
- **Cumplimiento de seguridad** — ¿abstiene y escala cuando debe? Un sistema que empieza a responder donde debería abstenerse se degrada aunque sus aciertos no bajen.
- **Latencia** — un sistema que acierta pero tarda veinte segundos está, para el usuario, roto.

Para la parte de RAG hay atajos: **RAGAS** (visto en la Sesión 11) da métricas hechas de recuperación y generación —fidelidad a las fuentes, relevancia de la respuesta, precisión del contexto—.

**El cambio que mejora una métrica y hunde otra.** Los KPIs se mueven unos contra otros: reducir alucinaciones puede volver al sistema tan cauto que abstiene de más y baja el acierto; un modelo más grande sube la precisión pero también latencia y coste. No existe "el número" del sistema; existe un equilibrio que **vosotros** decidís según lo que necesita el producto. El regression testing sobre todos los KPIs a la vez hace ese intercambio **visible** en lugar de accidental.

**Lo que queda.** Todo esto mide el sistema en el laboratorio, cuando lanzáis la evaluación, con vuestro golden set. En producción hay usuarios reales mandando entradas que nunca imaginasteis, a todas horas. Para eso hace falta observabilidad.

### 5. 📄 Observabilidad — 12 min

El golden set está en verde, los KPIs aguantan, el regression testing no saltó. Y mientras dormís, un usuario pega una transcripción rarísima, el sistema tarda doce segundos, el coste por petición se triplica durante horas porque el modelo razona de más, y una tanda de peticiones parecidas recibe estimaciones malas. Os enteráis tres días después, por la factura o por un cliente enfadado. El laboratorio no mintió: simplemente no estaba mirando la producción.

**Evaluación mira dentro; observabilidad mira fuera.** La **evaluación** es la prueba de laboratorio: vosotros elegís las entradas y la vara, y la lanzáis cuando queréis; responde "¿es bueno *en mis casos*?". La **observabilidad** es el monitor de constantes vitales: las entradas las manda el mundo, no hay vara, está siempre puesta; responde "¿qué hace el sistema *ahora mismo* con el tráfico real?". Son complementarias: la evaluación caza regresiones antes de desplegar (os protege de vuestros cambios); la observabilidad caza lo que la evaluación no pudo imaginar (os protege de la realidad).

**Las señales que se vigilan.** Observar no es registrarlo todo y mirar un mar de logs, sino elegir un puñado de señales que delatan un problema antes que un cliente:

- **Latencia**, y no solo la media (que esconde a la minoría que sufre): el **p95** dice si hay usuarios esperando una eternidad.
- **Coste por petición**: la señal del sube-y-baja silencioso. Una petición que cuesta el triple no rompe nada; solo engorda la factura.
- **Tasa de error**: timeouts, 503, respuestas bloqueadas por el guardrail de salida. La más clásica y la primera que salta.
- **Señales de calidad y de usuario**: la **tasa de abstención** (si sube de golpe, algo ha cambiado, quizá los datos han derivado), los pulgares abajo, los reintentos, los usuarios que reformulan tres veces.

Un dashboard es esas señales juntas y a la vista; las **alertas** son el dashboard avisando cuando cruzan un umbral sin que tengáis que estar mirándolo.

**El trace: por qué una petición tardó lo que tardó.** El dashboard dice **que** la latencia se disparó; no dice **dónde**. En un sistema RAG una petición pasa por varias etapas: embedding de la consulta, búsqueda en la base vectorial y generación del LLM. El **trace** desglosa la petición en tramos, cada uno con su tiempo y su coste, y convierte "las estimaciones van lentas hoy" (una queja) en "la recuperación es el cuello de botella desde que creció la base vectorial" (un diagnóstico). **Langsmith** y **Logfire** (Sesión 13) instrumentan el flujo RAG y las llamadas al LLM y dan las trazas casi sin trabajo, con tiempos, tokens y coste por tramo.

**Feedback loops: lo que se observa vuelve al sistema.** La producción es la mejor fuente de casos nuevos: la entrada rarísima que tardó doce segundos y dio una mala estimación es exactamente un caso que le faltaba al golden set vivo. La subida de la tasa de abstención avisa de una deriva de datos que toca reindexar. Los pulgares abajo señalan un fallo que vuestros casos no cubrían. El bucle consiste en recoger eso y devolverlo a la evaluación y a los datos.

**No confundáis el latido con la vigilancia.** Comprobar que el modelo responde con calidad, medir su coste y vigilar su latencia es trabajo del dashboard y de las trazas, **no del health check**. El `/health` sigue siendo barato y tonto: solo dice "estoy vivo".

**Lo que queda.** Ver el coste por petición y el tiempo de cada tramo hace imposible no notar que son más altos de lo que deberían: el modelo grande contestando preguntas triviales, peticiones que recalculan lo que ya se calculó, prompts inflados. El siguiente paso es bajarlos sin estropear la calidad, y demostrarlo.

### 6. 📄 Coste, latencia y A/B Testing — 13 min

Vuestro sistema manda **todas** las peticiones al modelo más grande: la trivial ("¿esta tarea es backend o frontend?") y la difícil ("estima este proyecto sin precedentes"). Es como poner al arquitecto más senior a contestar el teléfono. Funciona, pero es la forma más cara imaginable de que funcione.

**Modelo por tarea.** Una estimación con RAG y agentes es una cadena de sub-tareas de dificultad muy distinta: clasificar el tipo de tarea, enrutar hacia la estrategia adecuada, recuperar precedentes, generar la estimación razonada, validar el resultado. Clasificar o decidir un routing lo resuelve un modelo pequeño y barato igual de bien; generar una estimación razonada a partir de precedentes ambiguos es donde el modelo grande gana su sueldo. El modelo caro solo donde la calidad lo exige; el barato en todo lo demás. Clasificar con el modelo grande no da una clasificación mejor: da la misma, más cara y más lenta.

**No recalculéis lo que ya sabéis: cacheo multinivel.** En producción muchas entradas se repiten o se parecen. El nivel más claro es el de **embeddings**: son deterministas (mismo texto, mismo vector), así que calcularlos dos veces es tirar tokens y tiempo. Por encima se pueden cachear **resultados de búsqueda** para consultas repetidas y hasta **estimaciones enteras** para peticiones idénticas. A esto se suma la **higiene de prompts**: un prompt inflado paga tokens de más en cada llamada, para siempre. La optimización de tokens es de las pocas cosas que salen gratis: menos texto, misma respuesta, menos coste.

**El peligro de optimizar: abaratar rompiendo.** **Cada optimización es una apuesta a que la calidad sobrevive.** El modelo pequeño puede enrutar mal un tipo de tarea y arruinar la estimación entera; recortar el prompt puede eliminar justo la instrucción que evitaba alucinar fuentes; cachear estimaciones puede servir una respuesta vieja para un proyecto que cambió. Optimizar sin medir es degradar a propósito con la esperanza de que no se note. Cada optimización pasa por el mismo filtro que cualquier cambio: golden set, comparación con la línea base, ¿aguantó la tasa de aciertos? El regression testing no distingue entre "mejoré el prompt" y "abaraté el modelo". Pero algunos efectos solo se ven con tráfico real.

**A/B testing: demostrar que la versión barata sigue siendo buena.** Se manda una fracción del tráfico real —un 10%, por ejemplo— a la versión B (optimizada) y el resto se queda en A (actual). Lo importante es **qué** se compara: no basta con que B sea más barata y rápida (eso ya se sabía al diseñarla); hay que comprobar a la vez que **mantiene la calidad**: que no cae la tasa de aciertos, que no alucina más, que no abstiene de menos. Si B recorta el coste a la mitad con la misma calidad, se adopta con evidencia; si ahorra pero la calidad baja, lo habéis aprendido barato, sobre un 10% del tráfico. Es optimización con red.

**Cierre: de hacer funcionar una demo a operar un producto.** La Sesión 15 desplegó el sistema (documentado, partido por fronteras que compran algo, containerizado, con pipeline y frontera público/privado real): quedó *vivo*. La Sesión 16 le ha puesto **ojos y frenos**: un suelo de seguridad, una vara para medir si es bueno, una red para que no se degrade sin avisar, un monitor para ver qué hace en producción y control de coste y latencia. Las cuatro preguntas del mapa tienen respuesta medible. Y casi nada era magia de IA: son disciplinas de ingeniería de toda la vida aplicadas a un sistema cuyo comportamiento no vive en el código. Lo que sigue, en el Laboratorio 10x Engineer, ya no es sobre este sistema, sino sobre cómo todo esto cambia la forma de construir software.

### 7. 📄 Modelos en local — 14 min

Durante toda la sesión, cuando el servicio IA ha necesitado un modelo, ha llamado a un proveedor (OpenAI, Anthropic…): pagáis por token, confiáis vuestros datos a su sistema y vuestra disponibilidad a la suya. Es el punto de partida sensato, pero es *una* opción. El modelo puede correr en vuestra máquina o en una GPU que controláis: eso es **self-hosting**.

**Tres sitios donde puede vivir el modelo.**

| Opción | Cómo | Para qué | Límite |
| --- | --- | --- | --- |
| **API alojada** | El modelo vive en la infraestructura del proveedor; solo llamáis | Opción por defecto: cero operación, calidad de frontera, pago por uso | Mal sitio si hay un motivo de peso para no estar ahí |
| **Máquina local** | Ollama o llama.cpp con un modelo de pesos abiertos (Llama, Mistral, Qwen), normalmente cuantizado | Desarrollo y prototipo: gratis en el margen, sin rate limits, offline, los datos no salen de la máquina | Modelos más pequeños, poca capacidad de tráfico; no es producción |
| **Instancia cloud con GPU** | GPU alquilada (AWS u otro) con un servidor de inferencia (vLLM o TGI) | Self-hosting de producción: control total, escala con el tráfico | Pagáis la GPU y, sobre todo, lo operáis vosotros |

**Y al servicio IA le da casi igual: es cambiar la URL.** Aquí se recoge lo sembrado en el Módulo 2: el servicio IA **encapsula** la llamada al modelo tras una abstracción, con su capa de proveedores y sus fallbacks. Ollama, vLLM y TGI exponen casi todas una interfaz **compatible con OpenAI**, así que cambiar de proveedor alojado a modelo propio es, en lo esencial, apuntar el cliente a otra `base_url` y elegir otro nombre de modelo. El RAG, los agentes y los guardrails no se enteran. "Dónde corre el modelo" no es una decisión que os ate: es un **backend intercambiable** detrás de la abstracción. Podéis desarrollar contra un modelo local, desplegar contra una API y mañana mover parte del tráfico a una GPU propia sin reescribir el sistema.

**Por qué self-hostear: tres razones de peso.** **Privacidad y cumplimiento**: si por regulación o contrato los datos no pueden salir de vuestra infraestructura, mandar datos a un proveedor externo no es una opción a optimizar, está prohibido; el modelo corre dentro de la red privada y los datos nunca cruzan la frontera. **Control**: un proveedor puede actualizar el modelo por debajo y cambiaros el comportamiento de un día para otro; un modelo de pesos abiertos alojado por vosotros se queda en la versión que fijasteis. **Coste a volumen**: la razón más citada y peor entendida.

**El cruce de costes: "barato" depende del volumen.** La API se paga **por uso** (empieza en cero y crece con el tráfico); la GPU se paga **por tiempo encendida** (coste plano, pero arranca alto y no baja cuando baja el tráfico). Hay un **punto de cruce**: por debajo, la API es más barata porque no pagáis una GPU ociosa; por encima, la GPU propia puede compensar porque su coste fijo se reparte entre muchísimas peticiones. La trampa: **la GPU no es el único coste**. Al self-hostear os convertís en el equipo de operaciones del modelo (parchear, escalar, vigilar disponibilidad, gestionar picos, actualizar el servidor de inferencia). Esas horas de gente no aparecen en la factura de AWS, y desplazan el cruce real más a la derecha de lo que sugiere la GPU sola.

**Lo que perdéis.** Algo de **calidad de frontera** (los modelos abiertos suelen ir un paso por detrás de los mejores alojados; importa en las tareas difíciles). La **red de seguridad del proveedor**: sus capas de safety, sus mejoras continuas, su escalado automático. Y ganáis una **superficie operativa nueva**: GPU, servidor de inferencia y madrugadas. No se hace por prestigio: se hace cuando hay un motivo concreto (regulación, volumen, control).

**Dónde encaja la decisión.** No cambia la arquitectura: solo cambia **qué hay detrás** de la llamada. Y como la costura está aislada, la decisión es reversible y hasta mixta: un modelo pequeño self-hosted para tareas fáciles y de alto volumen (enlaza con el "modelo por tarea") y una API de frontera para las difíciles. Un modelo self-hosted es una pieza más dentro de la **frontera privada**: no se expone a internet, se securiza como la capa de datos y el servicio IA lo alcanza por la red interna.

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Golden set de producción

🚨 **Fecha límite indicada en la plataforma: domingo 27 de septiembre a las 23:59 de tu hora local.** Tiempo estimado del enunciado: 5 min. Punto de partida: el sistema de estimación desplegado en la Sesión 15 (staging o producción), o al menos levantado con `docker compose`. Repositorio de referencia: https://github.com/LIDR-academy/ai-engineering.

#### Contexto

Tras la Sesión 15, el sistema de estimación está desplegado en producción: documentado, containerizado, con pipeline y con la frontera público/privado sobre redes reales. Está *vivo* —el smoke test lo confirma— pero opera a ciegas: no se sabe si estima con acierto, si empezó a alucinar tras el último cambio de prompt ni cuánto cuesta cada respuesta. El smoke test dice que el sistema *responde*; no que responda *bien*.

Este ejercicio pone al sistema bajo medición. Se construyen tres cosas que son la base de toda la sesión: un **conjunto de referencia** contra el que medir la calidad, un **arnés** que ejecute esa medición de forma automática y un **dashboard** que muestre el estado del sistema en producción.

> Recordatorio de la Sesión 15: en CI se mockea el modelo porque CI testea *vuestro código*. Este ejercicio es lo contrario: **evalúa el modelo**, así que sí llama al modelo de verdad. Por eso no corre en cada commit, sino de forma deliberada contra el sistema desplegado. Evaluar y testear son cosas distintas; aquí se está en el lado de evaluar.

Nomenclatura del programa: **servicio IA** es el backend Python/FastAPI (encapsula CAG/RAG y agentes) y **backend de negocio** es la capa Rails (usuarios, sesiones, persistencia, reglas de negocio).

#### Objetivo

Al terminar debe haber:

1. Un **golden test set** con al menos 5 transcripciones de referencia, cada una con su estimación esperada.
2. Un **evaluation harness** que ejecute el set contra el servicio IA desplegado y produzca métricas.
3. Un **dashboard básico de monitorización** con las señales clave del sistema en producción.

#### Requisitos previos

- El sistema de estimación desplegado en la Sesión 15 (staging o producción), o al menos levantado con `docker compose`.
- Acceso al servicio IA a través del backend de negocio, o directamente al endpoint `/v1/estimate` con el token de servicio.
- La clave de LLM disponible: este ejercicio **consume tokens**, porque llama al modelo real. Es un gasto pequeño y deliberado; hay que tenerlo en cuenta.

#### Paso 1 — Construir el golden test set

Un golden test set es un conjunto de casos de referencia: entradas para las que vosotros —no el modelo— habéis decidido cuál es una buena respuesta. Es la vara de medir: sin él, "el sistema estima bien" es una opinión; con él, es un número.

Crear un fichero versionado en el repositorio (`ai-service/eval/golden_set.json`) con **al menos 5 casos**. Cada caso lleva la entrada, la estimación esperada y un rango aceptable, porque una estimación no es una cifra exacta sino un intervalo razonable. Ejemplo del enunciado (3 casos; hay que llegar a 5 como mínimo):

```json
[
  {
    "id": "case-001",
    "task_description": "Add OAuth2 login with Google and GitHub providers",
    "project_id": "proj-crm",
    "expected_points": 8,
    "acceptable_range": [5, 13],
    "expected_sources_include": ["task-142"],
    "notes": "Common auth task with clear historical precedents"
  },
  {
    "id": "case-002",
    "task_description": "Migrate the reporting module from MySQL to PostgreSQL",
    "project_id": "proj-crm",
    "expected_points": 13,
    "acceptable_range": [8, 21],
    "expected_sources_include": [],
    "notes": "Data migration, medium-high effort"
  },
  {
    "id": "case-003",
    "task_description": "Integrate with an in-house ERP that has no public documentation",
    "project_id": "proj-crm",
    "expected_points": null,
    "acceptable_range": null,
    "expect_abstention": true,
    "notes": "No historical precedent -> the system should abstain, not invent a number"
  }
]
```

Recomendaciones para que el set sea útil de verdad:

- **Cubrir dificultades distintas.** Un caso fácil y frecuente (con precedentes claros), uno de esfuerzo medio-alto y al menos uno **de borde**.
- **Incluir un caso de abstención.** `case-003` no tiene precedente histórico: la respuesta correcta no es un número, es que el sistema reconozca que **no tiene datos suficientes**. Medir esto es medir la seguridad del sistema, no solo su acierto, y enlaza con el bloque de safety de la sesión.
- **Fijar los valores esperados con criterio, no a ojo.** Basarlos en los datos históricos reales con los que se ha poblado la base de datos vectorial. El golden set es tan bueno como el criterio que hay detrás.

#### Paso 2 — El evaluation harness

El harness coge el golden set, lo lanza contra el servicio IA desplegado y compara cada respuesta con lo esperado. Va en el servicio IA (`ai-service/eval/run_eval.py`) y llama al sistema **real**, no a un mock.

```python
# ai-service/eval/run_eval.py
import json
import time
from pathlib import Path

import httpx

AI_SERVICE_URL = "<https://ai-service.internal>"  # deployed AI service
SERVICE_TOKEN = "..."  # from the secret manager / env

def load_golden_set(path: str) -> list[dict]:
    return json.loads(Path(path).read_text())

def call_estimate(case: dict) -> dict:
    started = time.perf_counter()
    response = httpx.post(
        f"{AI_SERVICE_URL}/v1/estimate",
        headers={"X-Service-Token": SERVICE_TOKEN},
        json={
            "task_description": case["task_description"],
            "project_id": case["project_id"],
        },
        timeout=30,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    return {"status": response.status_code, "body": response.json(), "latency_ms": latency_ms}

def evaluate_case(case: dict, result: dict) -> dict:
    body = result["body"]

    # Abstention case: the system must recognise it has no data
    if case.get("expect_abstention"):
        abstained = body.get("estimate_points") is None or body.get("confidence", 1) < 0.3
        return {"id": case["id"], "type": "abstention", "passed": abstained}

    # Estimation case: the estimate must fall within the acceptable range
    predicted = body.get("estimate_points")
    low, high = case["acceptable_range"]
    within_range = predicted is not None and low <= predicted <= high
    abs_error = abs(predicted - case["expected_points"]) if predicted is not None else None

    return {
        "id": case["id"],
        "type": "estimation",
        "passed": within_range,
        "predicted": predicted,
        "expected": case["expected_points"],
        "abs_error": abs_error,
    }
```

La lógica de la comparación: un caso de estimación pasa si el resultado cae **dentro del rango aceptable**, no si acierta la cifra exacta. Un caso de abstención pasa si el sistema **reconoce que no sabe** (`estimate_points` nulo o `confidence < 0.3`). Se está codificando la definición de "bueno".

#### Paso 3 — Producir métricas

El harness no termina en pasa/falla por caso: agrega todo en un puñado de métricas que resumen el estado del sistema.

```python
def run() -> dict:
    cases = load_golden_set("ai-service/eval/golden_set.json")
    evaluations = []
    for case in cases:
        result = call_estimate(case)
        evaluation = evaluate_case(case, result)
        evaluation["latency_ms"] = result["latency_ms"]
        evaluations.append(evaluation)

    estimation_cases = [e for e in evaluations if e["type"] == "estimation"]
    within_range = [e for e in estimation_cases if e["passed"]]
    errors = [e["abs_error"] for e in estimation_cases if e["abs_error"] is not None]

    return {
        "within_range_rate": len(within_range) / len(estimation_cases),
        "mean_absolute_error": sum(errors) / len(errors) if errors else None,
        "abstention_correct": all(e["passed"] for e in evaluations if e["type"] == "abstention"),
        "mean_latency_ms": sum(e["latency_ms"] for e in evaluations) / len(evaluations),
        "cases": evaluations,
    }

if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
```

Métricas mínimas que debe devolver el informe:

| Métrica | Qué mide |
| --- | --- |
| `within_range_rate` | Fracción de estimaciones que caen en el rango aceptable. La "tasa de acierto". |
| `mean_absolute_error` | Error medio en puntos frente a lo esperado. Dice *cuánto* falla, no solo *si* falla. |
| `abstention_correct` | Si el sistema se abstuvo correctamente en los casos sin datos. Señal de seguridad. |
| `mean_latency_ms` | Latencia media por petición. |

Guardar la salida de cada ejecución (por ejemplo en `ai-service/eval/reports/`): esa serie de informes es lo que permitirá, en la sesión, detectar si un cambio ha degradado la calidad.

#### Paso 4 — Dashboard básico de monitorización

El golden set mide la calidad *cuando se lanza la evaluación*. El dashboard mide lo que pasa *en producción, todo el rato*. Son complementarios: uno es la prueba de laboratorio; el otro, el monitor de constantes vitales.

Primero hay que **emitir las señales**: instrumentar el servicio IA para que, en cada petición de estimación, registre las métricas clave.

```python
# ai-service/app/observability.py (sketch)
import logging

logger = logging.getLogger("ai-service.metrics")

def record_request_metrics(request_id: str, latency_ms: float,
                           prompt_tokens: int, completion_tokens: int,
                           status: str) -> None:
    # Cost is derived from token counts and the provider's price per token
    estimated_cost = estimate_cost(prompt_tokens, completion_tokens)
    logger.info(
        "estimate_request",
        extra={
            "request_id": request_id,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost": estimated_cost,
            "status": status,
        },
    )
```

Con esas señales saliendo del servicio IA, montar un **dashboard básico** que muestre como mínimo:

- **Latencia** por petición (media y p95).
- **Coste por petición** (derivado del recuento de tokens).
- **Tasa de error** (proporción de respuestas no `200`).

Herramienta: el camino más corto es reutilizar lo visto en la Sesión 13 (**Logfire** o **Langsmith**), que ingieren estas trazas y dan los paneles casi hechos. Si se prefiere algo autocontenido, vale un panel mínimo que lea los logs estructurados y pinte las tres señales. Lo importante no es la herramienta: es tener claro **qué** se vigila y por qué.

> Trampa que se verá en la sesión: el `/health` del servicio IA **no** debe llamar al modelo. Comprobar que el modelo responde con calidad es trabajo del dashboard y del golden set, no del healthcheck.

#### Entregables

Subir al repositorio del Proyecto 2:

- `ai-service/eval/golden_set.json` con al menos 5 casos, incluyendo uno de abstención.
- `ai-service/eval/run_eval.py` (harness ejecutable) y una ejecución de ejemplo en `ai-service/eval/reports/`.
- La instrumentación de métricas en el servicio IA y el **dashboard** (una captura + la configuración o el código del panel).
- Un README corto (`docs/evaluation.md`) explicando cómo se lanza la evaluación y cómo se lee el dashboard.

No subir claves reales ni el token de servicio: van por variable de entorno, como siempre.

#### Cómo llegar preparado al directo

Traer **vuestros números**: la salida del harness sobre vuestro golden set y una captura del dashboard. Y traer anotado **qué casos falla** el sistema y qué señal del dashboard llama la atención (una latencia alta, un coste por petición mayor del esperado, un caso de abstención que no abstiene).

En el directo se ejecutará el test suite completo sobre el entorno desplegado, se hará A/B testing entre dos versiones del sistema para ver cuál mide mejor y se analizarán los costes reales de operación. Todo se apoya en lo montado aquí: sin golden set no hay con qué comparar versiones, y sin dashboard no hay con qué ver el coste. Si hay bloqueo, en el repositorio de la solución hay una versión funcional de referencia: intentarlo primero por cuenta propia y usarla para contrastar.

#### Criterios de aceptación ("hecho")

- `ai-service/eval/golden_set.json` versionado, con ≥ 5 casos que cubren fácil/frecuente, medio-alto, borde y **al menos un caso de abstención** (`expect_abstention: true`, `expected_points: null`, `acceptable_range: null`).
- Los valores esperados y rangos están basados en los datos históricos reales de la base vectorial, no a ojo (justificación en `notes`).
- `python ai-service/eval/run_eval.py` se ejecuta contra el servicio IA **desplegado** (modelo real), con URL y token leídos de variables de entorno, y devuelve como mínimo `within_range_rate`, `mean_absolute_error`, `abstention_correct`, `mean_latency_ms` y el detalle `cases`.
- Cada ejecución deja un informe con marca temporal en `ai-service/eval/reports/` (hay al menos uno de ejemplo versionado).
- El servicio IA emite, por cada petición de estimación, un log estructurado con `request_id`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `estimated_cost` y `status`.
- Existe un dashboard (Logfire, Langsmith o panel propio) con latencia media y p95, coste por petición y tasa de error; hay captura y configuración/código del panel.
- `/health` sigue sin llamar al modelo y sin autenticación.
- `docs/evaluation.md` explica cómo lanzar la evaluación y cómo leer el dashboard.
- Ningún secreto en el repositorio: token de servicio y clave del LLM solo por entorno.

#### Pitfalls comunes

- **Ejecutar el harness en CI en cada commit.** Llama al modelo real: es no determinista, caro y lento. La evaluación es deliberada, contra el sistema desplegado; CI sigue mockeando el LLM.
- **Golden set a ojo.** Una vara torcida medida con precisión sigue siendo una vara torcida. Los valores esperados salen de los datos históricos.
- **Solo casos de manual.** Si todos los casos son los que el sistema ya domina, se vuelve al punto ciego del "se ve bien".
- **Olvidar el caso de abstención.** Sin él no se mide la seguridad, y la tasa de acierto no ve el "número con aplomo sin base".
- **Juzgar por la cifra exacta.** Un caso pasa si cae en el rango aceptable, no si coincide con `expected_points`.
- **No guardar los informes.** Sin línea base no hay regression testing: "60%" solo es alarma frente al "80%" anterior.
- **Mirar solo la latencia media.** Esconde a la minoría que sufre; el p95 es obligatorio.
- **Hardcodear `AI_SERVICE_URL` y `SERVICE_TOKEN`.** El snippet del enunciado usa placeholders; en la implementación se leen del entorno.
- **Exponer el servicio IA para poder evaluarlo.** El harness se ejecuta desde dentro de la red privada (o a través del backend de negocio); la frontera público/privado no se relaja.
- **Healthcheck que llama al LLM.** Gasta tokens en cada comprobación y convierte un hipo del proveedor en reinicios en cascada.
- **Logs `extra` que no salen.** Con el formatter por defecto de `logging`, los campos de `extra` no aparecen en la salida: hace falta un formatter JSON (o Logfire) para que el dashboard pueda leerlos.

### 🛠️ Contexto técnico para la implementación

Material de referencia consolidado de los siete artículos y del enunciado, con todo lo necesario para implementar el ejercicio con Claude Code CLI. Todo el código, nombres, docstrings y logs en inglés. Lo que viene literal del enunciado está en los pasos anteriores; lo que sigue son invariantes y bocetos de implementación coherentes con él.

#### Invariantes de arquitectura (no negociables)

1. **Evaluar ≠ testear.** CI (determinista, LLM mockeado, en cada commit) no cambia. El harness de evaluación llama al modelo real, se lanza a mano o de forma programada y nunca bloquea un push.
2. **Frontera público/privado intacta.** El servicio IA sigue sin puerto público; el harness lo alcanza por red interna (`docker compose exec`, job dentro de la VPC) o a través del backend de negocio.
3. **Contrato estable.** Se evalúa contra `POST /v1/estimate` con cabecera `X-Service-Token` y payload `EstimateRequest` (`task_description`, `project_id`); la respuesta `EstimateResponse` expone al menos `estimate_points` (nullable), `confidence` (0–1) y `sources`.
4. **Abstención como respuesta válida.** `estimate_points = null` (o `confidence < 0.3`) con un mensaje que explica qué faltaría es una respuesta correcta, no un error; no debe devolver 5xx.
5. **`/health` barato.** Ni autenticación ni llamadas al LLM; la calidad se vigila con golden set + dashboard.
6. **Secretos por entorno.** `AI_SERVICE_URL`, `AI_SERVICE_TOKEN`, `LLM_API_KEY` y precios por token vienen del entorno o del gestor de secretos.
7. **Guardrails en código.** Las comprobaciones de entrada/salida son deterministas y se ejecutan siempre; nunca son una instrucción en el prompt.

#### Estructura de módulos objetivo

```
project-2/
├── ai-service/
│   ├── app/
│   │   ├── main.py               # FastAPI app + /health + routers
│   │   ├── security.py           # verify_service_token()
│   │   ├── observability.py      # record_request_metrics(), estimate_cost(), JSON logging
│   │   ├── guardrails.py         # input/output guardrails (deterministic)
│   │   ├── api/routers/          # /v1/estimate (token-protected)
│   │   └── domain/               # CAG/RAG, graph and agents (S12-S14)
│   ├── eval/
│   │   ├── golden_set.json       # >= 5 cases, incl. abstention
│   │   ├── run_eval.py           # harness (real model)
│   │   ├── compare_reports.py    # regression check vs baseline
│   │   └── reports/              # one JSON report per run (timestamped)
│   ├── dashboard/                # optional self-contained panel over structured logs
│   └── tests/                    # CI tests, LLM mocked (unchanged)
├── docs/
│   └── evaluation.md             # how to run the eval and read the dashboard
└── .env.example                  # + LLM price vars, LOGFIRE_TOKEN / LANGSMITH_API_KEY
```

#### Plantilla del golden set (5+ casos)

Los tres primeros casos son los del enunciado. Los dos últimos son **plantillas ilustrativas**: los `task_description`, `expected_points`, rangos y `expected_sources_include` hay que sustituirlos por tareas reales del histórico de la base vectorial.

```json
[
  { "id": "case-001", "...": "see Step 1 (easy, frequent, clear precedents)" },
  { "id": "case-002", "...": "see Step 1 (medium-high effort)" },
  { "id": "case-003", "...": "see Step 1 (abstention)" },
  {
    "id": "case-004",
    "task_description": "<real small task from history, e.g. add a field to an existing form>",
    "project_id": "proj-crm",
    "expected_points": 2,
    "acceptable_range": [1, 3],
    "expected_sources_include": ["<real task id>"],
    "notes": "Easy, frequent, strong precedent"
  },
  {
    "id": "case-005",
    "task_description": "<edge case: vague or multi-part request mixing known and unknown work>",
    "project_id": "proj-crm",
    "expected_points": 21,
    "acceptable_range": [13, 34],
    "expected_sources_include": [],
    "notes": "Edge case: ambiguous scope; checks the system does not collapse to a tiny estimate"
  }
]
```

Campos: `id` (único), `task_description`, `project_id`, `expected_points` (nullable), `acceptable_range` (`[low, high]` o `null`), `expected_sources_include` (IDs de precedentes que deberían aparecer en `sources`), `expect_abstention` (opcional), `notes` (justificación del criterio).

#### Mejoras sobre el harness del enunciado

- Leer `AI_SERVICE_URL` y `AI_SERVICE_TOKEN` con `os.environ[...]`; el path del golden set relativo al propio fichero (`Path(__file__).parent / "golden_set.json"`).
- Tratar respuestas no `200` como caso fallido (con `status` en el informe) en lugar de reventar en `response.json()`; capturar `httpx.TimeoutException`.
- Evitar `ZeroDivisionError` si no hay casos de estimación.
- Añadir `p95_latency_ms`, `error_rate` y, si la respuesta lo incluye, tokens/coste por caso.
- Usar `expected_sources_include` para una **tasa de alucinación/cobertura de fuentes**: fuentes citadas que no existen en la base vectorial (alucinación) y fuentes esperadas que no aparecen.
- Opción `--repeat N` para ejecutar cada caso varias veces (el sistema no es determinista) y reportar la media.
- Guardar el informe con metadatos: timestamp, versión/commit del servicio, modelo y versión de prompt, para poder comparar.

```python
# ai-service/eval/run_eval.py (report persistence, sketch)
import datetime as dt
import os

REPORTS_DIR = Path(__file__).parent / "reports"

def save_report(report: dict) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report["meta"] = {
        "run_at": stamp,
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        "model": os.environ.get("LLM_MODEL", "unknown"),
        "prompt_version": os.environ.get("PROMPT_VERSION", "unknown"),
    }
    path = REPORTS_DIR / f"eval_{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
```

#### Regression testing contra la línea base

```python
# ai-service/eval/compare_reports.py (sketch)
import json
import sys
from pathlib import Path

def compare(baseline_path: str, current_path: str, max_drop: float = 0.05) -> int:
    baseline = json.loads(Path(baseline_path).read_text())
    current = json.loads(Path(current_path).read_text())

    passed_before = {c["id"] for c in baseline["cases"] if c["passed"]}
    failed_now = {c["id"] for c in current["cases"] if not c["passed"]}
    regressions = sorted(passed_before & failed_now)

    drop = baseline["within_range_rate"] - current["within_range_rate"]
    print(f"within_range_rate: {baseline['within_range_rate']:.2f} -> {current['within_range_rate']:.2f}")
    print(f"regressed cases: {regressions or 'none'}")
    if not current["abstention_correct"]:
        print("SAFETY: abstention case no longer abstains")

    return 1 if regressions or drop > max_drop or not current["abstention_correct"] else 0

if __name__ == "__main__":
    sys.exit(compare(sys.argv[1], sys.argv[2]))
```

Un cambio (prompt, modelo, reindexado, optimización) se juzga por lo que le hace al conjunto: casos que pasaban y ahora fallan, caída de la tasa de acierto y pérdida de la abstención.

#### KPIs a vigilar

| KPI | Fuente | Qué fallo caza |
| --- | --- | --- |
| Acierto (`within_range_rate`) y `mean_absolute_error` | Harness | Cifras flojas |
| Tasa de alucinación (fuentes inexistentes, cifras sin apoyo) | Harness + guardrail de salida | Invenciones |
| Cumplimiento de seguridad (`abstention_correct`, escalados) | Harness + logs | Responder donde debía abstenerse |
| Latencia media y p95 | Harness + dashboard | Lentitud |
| Coste por petición | Dashboard (tokens × precio) | Factura silenciosa |
| Tasa de error (no `200`, timeouts, bloqueos del guardrail) | Dashboard | Caídas |
| Tasa de abstención, pulgares abajo, reintentos | Dashboard | Deriva de datos y calidad percibida |

Los KPIs se mueven unos contra otros (menos alucinación ↔ más abstención; modelo mayor ↔ más latencia y coste): el equilibrio se decide a sabiendas, con los números delante. Para métricas específicas de RAG, RAGAS (fidelidad, relevancia de la respuesta, precisión del contexto).

#### Instrumentación: coste y logs estructurados

```python
# ai-service/app/observability.py (sketch, completing the statement)
import json
import logging
import os

PRICE_PER_1K_PROMPT = float(os.environ.get("LLM_PRICE_PER_1K_PROMPT_TOKENS", "0"))
PRICE_PER_1K_COMPLETION = float(os.environ.get("LLM_PRICE_PER_1K_COMPLETION_TOKENS", "0"))

METRIC_FIELDS = ("request_id", "latency_ms", "prompt_tokens",
                 "completion_tokens", "estimated_cost", "status")

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"event": record.getMessage(), "ts": self.formatTime(record)}
        payload.update({k: getattr(record, k) for k in METRIC_FIELDS if hasattr(record, k)})
        return json.dumps(payload)

def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1000) * PRICE_PER_1K_PROMPT + \
           (completion_tokens / 1000) * PRICE_PER_1K_COMPLETION
```

Llamar a `record_request_metrics()` en el router de `/v1/estimate` (también en errores, con `status` distinto de `ok`/`200`), tomando los tokens del objeto `usage` que devuelve el cliente del LLM y generando un `request_id` por petición (propagarlo desde el backend de negocio si ya existe). Con Logfire o Langsmith, además, se obtienen **trazas por tramo** (embedding → recuperación → generación) con tiempo, tokens y coste de cada uno: son las que dicen *dónde* está el cuello de botella.

#### Dashboard mínimo autocontenido (alternativa a Logfire/Langsmith)

Un script o panel que lea el fichero de logs JSON del servicio IA y calcule, por ventana temporal:

- latencia media y **p95** (`statistics.quantiles(latencies, n=20)[18]`),
- coste medio y total por petición (`estimated_cost`),
- tasa de error (`status` distinto de éxito / total),
- opcional: tasa de abstención y umbrales de alerta (p. ej. p95 > X ms, coste por petición > Y, error rate > Z%).

Puede ser un pequeño endpoint interno, un notebook o una página estática generada; lo importante es qué señales se vigilan, no la herramienta.

#### Guardrails y abstención (bloque de safety)

```python
# ai-service/app/guardrails.py (sketch)
from app.domain.models import EstimateResponse

MIN_CONFIDENCE = 0.3
MAX_POINTS = 100

INJECTION_MARKERS = ("ignore your rules", "ignore previous instructions", "system prompt")

def check_input(task_description: str) -> None:
    text = task_description.lower()
    if any(marker in text for marker in INJECTION_MARKERS):
        raise ValueError("input rejected: possible prompt injection")
    # also: scope check (is this an estimation request?), PII scrubbing

def check_output(response: EstimateResponse, known_source_ids: set[str]) -> EstimateResponse:
    # Sources must exist in the vector DB: block invented ones
    if any(src not in known_source_ids for src in response.sources):
        return abstain(response, reason="cited sources not found in history")
    # Numbers within sane bounds
    if response.estimate_points is not None and not (0 < response.estimate_points <= MAX_POINTS):
        return abstain(response, reason="estimate outside sane bounds")
    # Low confidence or no precedents -> honest abstention (safe-completion)
    if response.confidence < MIN_CONFIDENCE or not response.sources:
        return abstain(response, reason="not enough historical data")
    return response
```

`abstain()` devuelve `estimate_points = None`, conserva la confianza y añade un mensaje útil ("no puedo estimar esto de forma fiable; necesitaría precedentes de integraciones similares o más detalle del alcance"). Para casos de alto impacto (p. ej. estimación por encima de un umbral) el sistema marca `needs_human_review = true` en lugar de responder directamente: escalar a un humano es un estado más del sistema. Todo se registra con fuentes y confianza (trazabilidad para compliance).

#### Optimización de coste y latencia (para el directo)

- **Modelo por tarea:** clasificación y routing con un modelo pequeño; generación de la estimación con el modelo grande. Configurable por entorno (`LLM_MODEL_SMALL`, `LLM_MODEL_LARGE`).
- **Cacheo multinivel:** caché de embeddings por hash del texto (deterministas), caché de resultados de búsqueda para consultas repetidas y, con cuidado de invalidación, caché de estimaciones para peticiones idénticas.
- **Higiene de prompts:** recortar lo que no se gana su sitio; medir tokens antes/después.
- **Toda optimización pasa por el golden set** y `compare_reports.py` antes de desplegar.
- **A/B testing:** enrutar un porcentaje del tráfico (p. ej. 10%) a la variante B con una asignación estable (hash del `request_id` o del usuario), registrar `variant` en los logs y comparar calidad (acierto, alucinación, abstención) **y** coste/latencia a la vez antes de decidir.

```python
# variant assignment (sketch)
import hashlib

def assign_variant(key: str, b_share: float = 0.10) -> str:
    bucket = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100
    return "B" if bucket < b_share * 100 else "A"
```

#### Modelos en local (backend intercambiable)

El cliente del LLM ya está encapsulado en el servicio IA; para apuntar a un modelo self-hosted basta con cambiar `base_url` y nombre de modelo, porque Ollama, vLLM y TGI exponen API compatible con OpenAI:

```python
# ai-service/app/llm/client.py (sketch)
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL"),     # e.g. http://ollama:11434/v1 in dev
    api_key=os.environ.get("LLM_API_KEY", "not-needed-for-local"),
)
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
```

Útil para desarrollar y para correr el harness sin coste, pero la evaluación que cuenta es la del modelo que se usa en producción. Un modelo self-hosted vive en la red privada, nunca con puerto público.

#### Comandos de referencia

```bash
# Ejecutar la evaluación desde dentro de la red interna (el servicio IA no es público)
docker compose exec ai-service python eval/run_eval.py

# Ejecutar la evaluación contra staging con variables de entorno
AI_SERVICE_URL=http://ai-service:8000 AI_SERVICE_TOKEN=$AI_SERVICE_TOKEN python ai-service/eval/run_eval.py

# Comparar la última ejecución contra la línea base
python ai-service/eval/compare_reports.py ai-service/eval/reports/<baseline>.json ai-service/eval/reports/<latest>.json

# Ver las métricas emitidas por el servicio IA
docker compose logs --tail=200 ai-service | grep estimate_request

# Comprobar que /health sigue sin llamar al modelo (debe ser instantáneo y sin tokens)
docker compose exec business-backend curl -sS http://ai-service:8000/health

# CI sigue igual: tests deterministas con el LLM mockeado
docker compose exec ai-service pytest -v
```

#### Qué verificar (y qué no)

Verificar que el harness corre contra el sistema desplegado con el modelo real y produce las cuatro métricas mínimas; que el caso de abstención pasa (o, si no, dejarlo anotado para el directo); que cada ejecución deja su informe; que cada petición a `/v1/estimate` emite su log estructurado con tokens y coste; que el dashboard muestra latencia media/p95, coste por petición y tasa de error; y que `/health` sigue sin tocar el modelo. No se trata de que todos los casos pasen: se trata de tener números honestos y saber qué falla.

#### Qué se añade en el directo (fuera del alcance de la pre-sesión)

- Ejecución del test suite completo sobre el entorno desplegado.
- A/B testing entre dos versiones del sistema para ver cuál mide mejor.
- Análisis de los costes reales de operación (tokens, latencia, modelo por tarea, cacheo).
- Revisión de los casos que falla cada sistema y de las señales del dashboard que llaman la atención.

## Checklist antes de la siguiente sesión

- Sabes explicar por qué un sistema con LLM rompe la garantía de "mismo código, mismo comportamiento" y por qué falla en silencio.
- Puedes enumerar las cuatro preguntas que el despliegue no responde (¿es bueno?, ¿sigue siéndolo?, ¿es seguro?, ¿cuánto cuesta?) y las cuatro áreas de LLMOps (seguridad, evaluación, observabilidad, coste).
- Entiendes LLMOps como disciplina, no como herramienta.
- Distingues calidad (la media) de seguridad (el suelo) y sabes por qué la seguridad va primero.
- Tienes guardrails de entrada y de salida implementados como código determinista, no como frases en el prompt.
- Tu sistema tiene un camino explícito para decir "no lo sé": responder, abstenerse con honestidad (safe-completion) o escalar a un humano.
- Conoces los principios estables del marco europeo de IA (riesgo, transparencia, supervisión humana, trazabilidad) y cómo se cubren por diseño.
- Sabes por qué la evaluación a ojo falla (casos elegidos, no determinismo, sin referencia).
- Tienes un golden set versionado con ≥ 5 casos, rangos aceptables, dificultades distintas y al menos un caso de abstención, basado en datos históricos reales.
- Tu harness llama al modelo real, compara de forma mecánica y produce `within_range_rate`, `mean_absolute_error`, `abstention_correct` y `mean_latency_ms`.
- Distingues evaluar (modelo real, deliberado) de testear (mockeado, en cada commit).
- Guardas un informe por ejecución y sabes comparar contra la línea base para detectar regresiones silenciosas.
- Entiendes por qué un cambio de prompt tiene como radio de impacto el sistema completo.
- Vigilas varios KPIs (acierto, alucinación, cumplimiento de seguridad, latencia) y sabes que se mueven unos contra otros.
- Distingues evaluación (laboratorio) de observabilidad (producción) y sabes por qué hacen falta las dos.
- Tu servicio IA emite latencia, tokens, coste y estado por petición, y tienes un dashboard con latencia media/p95, coste por petición y tasa de error.
- Sabes qué es un trace por tramos (embedding, recuperación, generación) y para qué sirve frente al dashboard.
- Cierras el feedback loop: los fallos de producción se convierten en casos del golden set.
- Tu `/health` sigue siendo barato y no llama al modelo.
- Conoces las palancas de coste y latencia (modelo por tarea, cacheo de embeddings/búsquedas/estimaciones, higiene de prompts) y que toda optimización se valida contra el golden set.
- Sabes diseñar un A/B test que compare calidad y coste a la vez sobre una fracción del tráfico.
- Sabes dónde puede vivir el modelo (API, local, GPU cloud), cuándo compensa self-hostear (privacidad, control, volumen) y el coste oculto de operarlo.
- Entregables subidos al repositorio antes del domingo 27 de septiembre a las 23:59: golden set, harness con informe de ejemplo, instrumentación + dashboard (captura y configuración) y `docs/evaluation.md`.
- Llegas al directo con tus números, una captura del dashboard y la lista de casos que falla el sistema.

## Documentación de referencia

**Evaluación y calidad**

- RAGAS — documentación: https://docs.ragas.io/
- LangSmith — evaluación y datasets: https://docs.smith.langchain.com/
- HTTPX — cliente HTTP para Python: https://www.python-httpx.org/
- `statistics` — percentiles (`quantiles`): https://docs.python.org/3/library/statistics.html

**Observabilidad**

- Pydantic Logfire — documentación: https://logfire.pydantic.dev/docs/
- LangSmith — observabilidad y trazas: https://docs.smith.langchain.com/
- Python `logging` — referencia: https://docs.python.org/3/library/logging.html
- OpenTelemetry — conceptos de trazas y métricas: https://opentelemetry.io/docs/
- Google SRE Book — monitorización de sistemas distribuidos: https://sre.google/sre-book/monitoring-distributed-systems/

**Seguridad y cumplimiento**

- Reglamento (UE) 2024/1689 de Inteligencia Artificial (texto oficial): https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- OWASP Top 10 for LLM Applications: https://genai.owasp.org/llm-top-10/
- Pydantic — modelos y validación: https://docs.pydantic.dev/latest/

**Modelos en local y self-hosting**

- Ollama: https://github.com/ollama/ollama
- Ollama — compatibilidad con la API de OpenAI: https://github.com/ollama/ollama/blob/main/docs/openai.md
- llama.cpp: https://github.com/ggml-org/llama.cpp
- vLLM — documentación: https://docs.vllm.ai/
- Hugging Face Text Generation Inference (TGI): https://huggingface.co/docs/text-generation-inference/
- OpenAI Python SDK (`base_url` configurable): https://github.com/openai/openai-python

**Repositorios del programa**

- Repositorio oficial de soluciones: https://github.com/LIDR-academy/ai-engineering
- Sesión anterior (puesta en producción, arquitectura e infra): https://github.com/icarobregon/AI-Engineering-2026/tree/session_15_puesta-en-produccion-y-llmops-i
