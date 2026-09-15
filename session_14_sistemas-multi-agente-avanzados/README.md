# Sesión 14 — Sistemas multi-agente y patrones avanzados

## Objetivo de la sesión

Al cierre de la **Sesión 13** el servicio IA orquesta la estimación como un grafo explícito de LangGraph: cinco nodos con una responsabilidad cada uno, un `EstimationState` tipado con reducers, un checkpointer `AsyncPostgresSaver` sobre el Postgres del proyecto y un span por nodo. Es determinista, se traza bien y se depura pieza a pieza. Pero hay una pregunta que ese grafo nunca llega a hacerse en tiempo de ejecución: **¿qué toca ahora?** La respuesta está escrita en el fichero; no se decide.

La **Sesión 14** ataca el punto donde eso deja de bastar. El prompt de un nodo empieza a acumular reglas de dominios distintos y tocar una regla rompe un caso que no tenía nada que ver. El conjunto de tools crece dentro de un único espacio de decisión y la tasa de elección incorrecta sube con el número de opciones. Y, sobre todo, el camino óptimo empieza a depender del caso: un CRUD conocido, una integración sin precedente y una migración de datos no piden la misma secuencia. Cuando quien elige el siguiente paso deja de ser el código y pasa a ser el modelo, se ha cruzado la frontera entre un *workflow* y un **sistema agéntico** — y la diferencia no está en el número de nodos, sino en quién es dueño del control flow.

El eje de la sesión es reorganizar ese grafo en una topología **supervisor + agentes especializados** y resolver las cuatro preguntas que la arquitectura deja abiertas: cómo se **enruta** (a mano, con `StateGraph` y `Command`, para que cada bifurcación quede visible en la traza), cómo se **comunican** los agentes (pizarra compartida, handoff directo o mensajes), qué hace el sistema cuando **no debe decidir solo** (`interrupt()` sobre el checkpointer, con la primera extensión real del contrato hacia el backend de negocio) y qué puede **tocar** cada agente (mínimo privilegio, validación de acciones y auditoría).

Un detalle de arquitectura que atraviesa los seis artículos: **no hay infraestructura nueva**. El estado compartido es el mismo estado tipado de la S13, el checkpointer es el mismo sobre el mismo Postgres, y las tools son las de la S12 (`search_budgets`, `calculate_estimate`, `validate_estimate`) — solo se reparten. Un sistema multi-agente, en la forma que sirve en producción, es el grafo que ya tenías reorganizado con un nodo que decide y unos agentes que solo ven sus propias herramientas. La capa genuinamente nueva es pequeña; el resto son principios que ya aplicas desde siempre: separación de responsabilidades, contratos entre capas, no confiar en el cliente y defensa en profundidad.

---

## Qué vas a aprender

### 1. 📄 Cuándo un sistema multi-agente deja de ser "un grafo con más nodos" — 18 min

Arranca desactivando el entusiasmo: si la única diferencia entre tu grafo y tu "sistema multi-agente" es renombrar `search_budgets` a `budget_searcher`, es teatro de arquitectura, y se paga en latencia, en coste por token y en depuración nocturna. La pregunta correcta ante "hay que hacerlo multi-agente" no es *cómo*, sino **por qué**.

**El techo del grafo único.** Un grafo dirigido con nodos-función fija el control flow en el código: las aristas condicionales dan flexibilidad, pero acotada a las ramas que alguien previó. Eso es una ventaja enorme — predecible, barato de trazar, fácil de testear — y para un proceso de negocio con secuencia estable es la respuesta correcta. Empezar por multi-agente cuando el flujo es fijo equivale a montar microservicios para un CRUD de tres tablas. El techo aparece con cuatro síntomas reconocibles: **prompts que acumulan dominios distintos** (acoplamiento, igual que una clase de 800 líneas), **demasiadas tools en un único espacio de decisión** (repartirlas mejora la precisión, no solo la seguridad), **orden desconocido de antemano** (la señal definitiva) y **responsabilidades que evolucionan a ritmos distintos** (ejes de cambio distintos piden componentes distintos).

**Cooperación o competición.** Una vez justificada la decisión, queda otra que suele saltarse y que determina coste y comportamiento. En **cooperación** cada agente aporta una pieza ortogonal y el resultado es la composición: es la topología por defecto para estimar, cuesta una pasada por el flujo y su riesgo es el de las cadenas — un eslabón débil contamina todo lo que viene detrás. En **competición**, varios agentes atacan la misma tarea con criterios distintos y un tercero sintetiza; lo valioso no es que "elija la buena", sino que **la divergencia entre propuestas es información nueva** sobre la incertidumbre del caso. Regla de bolsillo: cooperación para descomponer trabajo, competición para atacar incertidumbre, y no mezclarlas por defecto.

**Lo que cuesta.** Cada salto de enrutado es una llamada al modelo que no produce trabajo útil: una tarea que toque dos especialistas pasa de dos llamadas a cuatro. A eso se suman la **pérdida de contexto en las transiciones** (pasar todo el historial descontrola el contexto; pasar solo un resumen crea un cuello de botella semántico), el **no-determinismo del control flow** (dos ejecuciones sobre la misma transcripción pueden recorrer caminos distintos: testea el resultado y las invariantes, no el camino), una **superficie de fallo mayor** y un coste **cognitivo** que nadie apunta en la factura.

**Cuándo no hacerlo.** Si el flujo es fijo, un supervisor es una arista condicional cara con aleatoriedad de regalo. Si el problema real es un prompt malo, reparte el prompt entre cuatro agentes y tendrás cuatro prompts mediocres más un problema de coordinación. Y si no tienes observabilidad por nodo, no añadas agentes: la instrumentación es la precondición, no un extra posterior.

### 2. 📄 El supervisor: construir el enrutado a mano con StateGraph y Command — 19 min

Un supervisor hace tres cosas — **descomponer**, **delegar** y **consolidar** — y no hace trabajo de dominio. Si tiene tools de negocio en la mano, es un agente más que además enruta, y has reintroducido el nodo sobrecargado que querías eliminar. Aquí es un nodo **sin ninguna tool** cuya única salida es una decisión.

**El digest antes que el enrutado.** La primera decisión no es *cómo* decide, sino **qué ve para decidir**. Pasarle el historial completo de mensajes —el valor por defecto de varias abstracciones del ecosistema— descontrola el contexto y encarece cada iteración. El supervisor no necesita saber qué dijo el buscador de presupuestos: necesita saber **si ya buscó**. Un `build_state_digest()` de cinco líneas da coste constante por decisión, independiente del tamaño de la transcripción.

**La decisión es un tipo, no texto libre.** Un `Literal` con los destinos posibles más un modelo Pydantic (`next_agent` + `reason`) convierte el enrutado en un valor de un conjunto cerrado que rompe ruidosamente si el modelo se sale del guion. El campo `reason` no lo consume ningún componente: lo lees tú en la traza cuando el supervisor enrute a `finalize` sin haber estimado nada.

**`Command` hace dos cosas a la vez:** actualiza el estado (`update`) y mueve el control (`goto`). El tipo de retorno `Command[AgentName]` no es cosmético — LangGraph lo usa para inferir los destinos al construir el grafo, así que el conjunto de destinos y el conjunto de valores que el modelo puede devolver son literalmente el mismo `Literal`.

**Dos invariantes no negociables.** Un **presupuesto de enrutado** (`MAX_ROUTING_STEPS`) desde la primera línea: en un grafo determinista un bucle infinito es un bug evidente, en un grafo enrutado por un modelo es el comportamiento por defecto ante una instrucción ambigua. Y un **span que lleva la decisión**, con `next_agent` y `reason` como atributos: eso es exactamente lo que se pierde cuando el enrutado ocurre dentro de una abstracción de librería.

**El supervisor híbrido, la opción aburrida que suele ganar.** La mayoría de las decisiones de enrutado no necesitan un LLM. Que los requisitos deban extraerse antes de buscar presupuestos no es un juicio matizado: es una **precondición**. Codificarla en un system prompt es cambiar una garantía por una probabilidad, y encima pagando. El patrón que rinde en producción resuelve por reglas lo determinista y llama al modelo solo ante ambigüedad real — y tiene una virtud pedagógica: te obliga a nombrar cuáles son las decisiones difíciles de tu dominio. Si descubres que no hay ninguna, no necesitas un supervisor con modelo: necesitas el grafo que ya tenías.

**Montar el grafo y la panorámica.** Con esta topología solo se declara **una arista** (`START → supervisor`): todas las demás transiciones viven dentro de los nodos, en los `Command`. El grafo ya no describe un flujo, describe un conjunto de capacidades y un enrutador; la forma del recorrido emerge en ejecución. Con cuatro especialistas un supervisor **plano** va sobrado; con quince, su precisión se degrada igual que la de un agente con quince tools y toca agrupar por equipos con **sub-supervisores**, pagando un nivel más de enrutado por salto. Sobre las abstracciones tipo `create_supervisor`: la propia recomendación actual de LangChain para la mayoría de casos es implementar el patrón a mano, con tools y `Command`, precisamente para conservar el control sobre qué contexto recibe cada agente y mantener cada decisión visible en las trazas.

### 3. 📄 Patrones de comunicación entre agentes: estado compartido, handoff y mensajes — 17 min

Hay una decisión en tu arquitectura que probablemente no recuerdas haber tomado, porque vino de regalo con el framework: **cómo se comunican los agentes**. Al declarar un `EstimationState` tipado y poner a cada agente a escribir su parcial en él, elegiste un patrón con nombre propio y cincuenta años de historia. Hay tres, los tres legítimos, y aparecen en producción en este orden.

**1. Estado compartido (blackboard).** La metáfora es literal: especialistas frente a una pizarra. Nadie le habla a nadie; cada uno lee lo escrito, ve si puede aportar y escribe su contribución. El `budget_searcher` no le pasa nada al `estimate_generator`: escribe en `budget_matches` y se va. Están desacoplados entre sí y su único acoplamiento es **al esquema del estado** — el mismo que ya gestionas entre servicios que comparten base de datos o entre un frontend y el contrato de una API. Añadir un agente no obliga a tocar ninguno existente. Su única pregunta difícil son los **reducers**: qué pasa cuando dos agentes escriben la misma clave. En secuencial no ocurre; en cuanto el supervisor lanza dos búsquedas en paralelo, sin política explícita la última gana y la primera desaparece en silencio. Regla de diseño: **para cada campo del estado, decide conscientemente si acumula o sobrescribe**. Un campo que debería acumular y sobrescribe es pérdida silenciosa de datos — el sistema no falla, simplemente estima con menos evidencia de la que buscó. Sus dos límites reales: el estado crece hasta parecer un objeto Dios del que cada agente usa el 15% (mitigación: **proyecciones** por agente) y **todo el mundo lo puede leer todo**, que ya no es un problema de comunicación sino de privilegio.

**2. Handoff directo (swarm).** Con supervisor, el control siempre vuelve al centro, y cada retorno es una llamada cuyo único producto es una decisión de enrutado. El handoff elimina ese viaje: el agente que termina decide quién sigue y pasa el testigo. El mecanismo en LangGraph es una **tool que devuelve un `Command` en lugar de un dato**, con dos detalles críticos: `graph=Command.PARENT` para que el salto escape del subgrafo del agente y aterrice en el grafo padre (el error número uno al implementarlo a mano), y el **`task_brief`**, que es la decisión de diseño de verdad — qué viaja en el testigo. Historial completo: el siguiente hereda todo el contexto, todo el coste y todo el ruido. Solo un brief: contexto limpio pero cuello de botella semántico, porque lo que no esté ahí no existe para quien viene. Ganas llamadas (dos en vez de cuatro para una tarea de dos especialistas); pagas **acoplamiento topológico** (cada agente necesita conocer a sus vecinos: cambias una estrella por una malla) y **trazabilidad** (la decisión deja de estar en un único `routing_trail`).

**3. Mensajes.** Los dos patrones anteriores comparten una premisa no enunciada: todos los agentes viven en el mismo proceso. El patrón de mensajes la rompe — un agente publica un hecho y a quién le llegue no es asunto suyo. Es arquitectura orientada a eventos, con las propiedades que ya conoces (desacoplamiento máximo, escalado independiente, reintentos y colas de fallidos) y los costes que también conoces (consistencia eventual, trazabilidad distribuida con `correlation_id`, complejidad operativa de un bus).

**La postura.** No son alternativas del mismo nivel, son tres escalones, y subir uno sin necesitarlo es la forma más común de arruinar una arquitectura multi-agente. **Estado compartido por defecto** (mejor ratio de trazabilidad por unidad de complejidad; la mayoría de sistemas se quedan aquí y hacen bien). **Handoff** cuando el impuesto de enrutado sea un problema *medido*, no imaginado. **Mensajes** cuando los agentes crucen la frontera del proceso y pasen de funciones a servicios. Y son **combinables**: la pregunta nunca es cuál es el mejor patrón, sino qué patrón corresponde a cada frontera del sistema.

### 4. 📄 Human-in-the-loop: interrupt, pausa y reanudación sobre el checkpointer — 18 min

El sistema devuelve 840 horas para un CRUD de tres entidades cuyo histórico ronda las 120–200. Lo interesante es que el sistema **sabía** que algo iba mal: el validador tenía delante el rango histórico. La pregunta no es cómo evitar el error, sino qué debe hacer el sistema cuando detecta que no está en condiciones de responder solo. La respuesta fácil es un `if` que devuelve error. La correcta es detenerse, enseñárselo a una persona y esperar — y esperar es lo difícil, porque puede tardar tres días: la ejecución tiene que **morir y resucitar** donde estaba, en otro proceso, quizá después de un despliegue. Eso no es una pausa, es **persistencia**. Y ya la tienes montada.

**La pausa vive en el checkpointer.** Si el estado se persiste tras cada nodo, la ejecución en memoria es prescindible: se puede tirar y reconstruir. Y si se puede reconstruir, se puede parar indefinidamente. Un human-in-the-loop es exactamente eso: una parada que dura lo que tarde un humano. `interrupt()` no es un `sleep`: lanza una excepción de control que LangGraph captura, el estado queda escrito en el checkpoint, la ejecución termina y el proceso queda libre. **El payload de `interrupt()` no es un log, es la interfaz**: un revisor al que solo le enseñas `confidence: 0.42` no puede decidir nada; uno al que le enseñas la estimación, el rango histórico con el que choca y los presupuestos análogos encontrados, sí.

**Reanudar es simétrico.** `ainvoke` con un input arranca; `ainvoke` con `Command(resume=...)` continúa. La misma función, porque para LangGraph reanudar no es un caso especial: es lo que hace siempre, partiendo de un checkpoint que resulta no estar vacío. El `thread_id` es la pieza que lo cose todo — usa el `estimation_id` del dominio y no un UUID nuevo, y tendrás un identificador único que atraviesa las tres capas y las trazas.

**Qué debe parar el grafo.** Tres señales legítimas: **confianza baja** (pedida explícitamente con esquema y criterios, no aparecida por arte de magia), **fuera de rango histórico** (una comparación aritmética, ni siquiera necesita modelo) y **sin precedente** (ningún análogo supera el umbral de similitud: el sistema no se equivocó, no tiene base sobre la que acertar). La regla debajo: **una señal de disparo es una condición evaluable sobre el estado**. Si no la puedes escribir como un booleano, no es una señal: es una intuición, y las intuiciones no se testean ni se explican a un cliente.

**Y qué no debe pararlo**, tres antipatrones disfrazados de prudencia. **Un agente ha fallado** no es revisión, es error: se resuelve con reintento, fallback o degradación — el error es que el sistema no pudo hacer su trabajo, la revisión es que lo hizo y el resultado necesita juicio. **Revisar por si acaso**: si el 80% pasa por revisión, el revisor aprueba en bloque sin mirar y has destruido la señal; una puerta que dispara en el 5% vale más que una que dispara en el 60%. **Una regla de negocio dura** (todo presupuesto por encima de 50.000 € lo firma un socio) es un flujo de aprobación y su sitio es el backend de negocio: el gate del servicio IA existe para cuando el sistema de IA sabe que no sabe.

**El contrato cruza las tres capas.** La pausa ocurre en el servicio IA, la persona decide en el frontend y en medio está el backend de negocio, que tiene usuarios, permisos y persistencia. La superficie mínima son dos cosas: un **valor nuevo** en el campo `status` que ya leías (`awaiting_human_review`) y un **endpoint de reanudación**. Eso significa que el backend no necesita una integración nueva, solo una rama nueva: la arquitectura no cambia, se extiende. La autorización, la notificación, la bandeja y el histórico de quién aprobó qué viven en negocio; el servicio IA solo sabe pausar y reanudar. Esa separación no es purismo: es lo que permite cambiar la política de aprobación sin tocar el grafo.

**Lo que muerde.** El **nodo se reejecuta desde el principio al reanudar** — `interrupt()` devuelve entonces el valor en lugar de detener, así que todo lo anterior dentro de ese nodo se ejecuta dos veces; si había una llamada al modelo, se paga dos veces. Regla: **el nodo que interrumpe no hace nada más que interrumpir**. Las **reanudaciones huérfanas** (nadie decide nunca) exigen una política de plazo, escalado o caducidad. La **doble reanudación** (dos revisores aprueban) exige idempotencia o bloqueo: es el doble submit de un formulario, no un problema de IA. Y una recomendación que se paga sola: **guarda la decisión humana desde el primer día**. El par "lo que propuso el sistema / lo que decidió la persona" es material de evaluación y de ajuste de umbrales, gratis ahora e irrecuperable después.

### 5. 📄 Competición y síntesis entre agentes — 18 min

El sistema devuelve 260 horas. ¿Cuánto te fías? No hay forma de saberlo: la cifra se ve igual si venía de un caso trivial que el sistema clavó o de un caso imposible sobre el que el modelo improvisó con aplomo. Esa es la debilidad de fondo de un estimador único: **no produce ninguna medida de su propia fragilidad**. Pedirle al modelo que puntúe su confianza es mejor que nada, pero tiende a confiar en lo que acaba de decir. Hay una forma más honesta: que dos agentes con criterios opuestos ataquen el mismo problema y medir cuánto se separan.

**De cooperar a competir.** Dos estimadores deliberadamente enfrentados — `conservative_estimator`, que asume fricción (integraciones que se tuercen, requisitos que crecen, staging que nadie montó), y `aggressive_estimator`, que asume el mejor caso razonable (equipo competente, alcance estable) — más un `synthesizer` que recibe ambas propuestas. Es exactamente lo que ocurre en cualquier reunión de estimación real: el desacuerdo no es un fallo del proceso, el desacuerdo **es** el proceso.

**Las propuestas tienen esquema.** Si un estimador devuelve un número suelto, el sintetizador solo puede promediar, que es la peor opción. Tiene que devolver su número **y los supuestos que lo sostienen** (`assumptions`, `risks`, `reasoning`). Los supuestos son la carga útil: cuando uno dice 340 horas porque asume que la integración con el ERP legacy no está documentada y el otro dice 190 porque asume documentación y entorno de pruebas, la diferencia no es un número, es **una pregunta concreta que alguien puede ir a resolver**.

**Paralelo, y el fan-in es gratis por el reducer.** Los dos estimadores son independientes, así que salen del mismo punto del grafo y convergen en el sintetizador. El campo `proposals` anotado con `operator.add` concatena las dos escrituras concurrentes; sin anotar, uno de los dos competidores desaparecería en silencio y tendrías un sistema de competición con un solo competidor — el bug más silencioso de todo el módulo.

**La divergencia se calcula, no se opina.** La separación relativa entre dos números es una operación aritmética: pedírsela a un LLM es pagar tokens por una división y aceptar que a veces la haga mal. Una línea de código, cero tokens, y ya tienes la señal que faltaba: 190 frente a 340 da 0,44; 250 frente a 270 da 0,07. Y el significado no es simétrico. **Convergen**: dos criterios opuestos han llegado al mismo sitio, el resultado no depende de los supuestos, el sistema puede cerrar solo con confianza alta. **Divergen**: el resultado depende por completo de qué supuestos se acepten, y eso es un juicio que toma una persona. Es decir, la competición no solo mejora la estimación: **da el criterio para saber cuándo no deberías estar estimando solo**. La divergencia alimenta la confianza, y la confianza alimenta la decisión de parar — aquí encajan las dos mitades de la sesión.

**El sintetizador no promedia.** Hay que instruirlo explícitamente para que no lo haga, porque promediar es el comportamiento por defecto y es justo lo que destruye el valor de haber pagado dos estimaciones: la media entre 190 y 340 es 265, un número que nadie puede defender y que además oculta que el rango existe. Su salida es un **rango** con `driving_assumptions` y `open_questions` — y esa lista de preguntas abiertas es lo más útil que produce el sistema entero, porque es lo que hay que ir a preguntarle al cliente. Un estimador único jamás la produce: no sabe en qué se estaba jugando el número.

**Cuándo esto es un fraude.** Tres formas de tirar el dinero. **La trampa de la correlación**: mismo modelo, mismo contexto y prompts que se diferencian en un adjetivo producen salidas muy parecidas — has pagado tres llamadas por la ilusión de una segunda opinión, y lo peor es que la divergencia baja resultante es una **señal falsa de confianza**. Para que la competición valga algo hacen falta criterios sustantivos distintos (no adjetivos), **evidencia distinta** (el que más impacto tiene y menos se usa: dale al conservador los presupuestos que se pasaron de plazo y al agresivo los que salieron limpios) e idealmente **modelos distintos**. **Competir donde no hay nada que juzgar**: extraer requisitos tiene una respuesta razonablemente correcta y los agentes convergerán; si tú no sabrías defender las dos posturas, tus agentes tampoco. **Escalar a N competidores**: los retornos decaen rápido y el coste es lineal; quédate en dos salvo que puedas nombrar un tercer criterio de verdad ortogonal. Y conoce la alternativa barata: **muestrear el mismo prompt varias veces** y mirar la dispersión mide el ruido del modelo; la competición mide la **incertidumbre del dominio**, y solo la segunda es accionable con un cliente delante.

**El coste, sin adornos.** Un estimador, una llamada. Competición: dos en paralelo más una síntesis, ×3 en coste y ≈×2 en latencia. Si la salida es un presupuesto que se manda a un cliente y compromete a la empresa durante meses, triplicar el coste de una inferencia para obtener un rango defendible, supuestos explícitos y una medida real de incertidumbre es el mejor dinero del sistema. Si es una estimación orientativa para priorizar un backlog interno, no: pon un estimador y sigue.

### 6. 📄 Mínimo privilegio, validación de acciones y auditoría de agentes — 19 min

Hasta aquí los agentes **leen**, y el coste de un error es un número equivocado que caza el validador o el humano. Eso cambia por completo el día que alguien añada la tool que faltaba — `save_estimate`, `update_budget_status`, `send_estimate_email` — y tengas un componente gobernado por un modelo de lenguaje con permiso para modificar datos de la empresa o mandar correos en su nombre. El coste del error pasa a ser una fila borrada, un correo al destinatario equivocado, un estado corrupto en producción. La tesis es incómoda de entrada: **la contención no puede vivir en el prompt**.

**Por qué el prompt no es un mecanismo de seguridad.** Un system prompt es una **instrucción**, no una restricción: el modelo lo pondera junto al resto del contexto y lo respeta *la mayoría de las veces*. Compáralo con cómo proteges cualquier otra cosa: no confías en que el frontend no envíe un campo prohibido, lo rechazas en el backend. La regla de toda la vida —**no confíes en el cliente**— se aplica aquí sin una sola modificación. El modelo es el cliente: una entrada no confiable que **propone** acciones, y las entradas no confiables se validan en una capa que el cliente no controla. Todo lo demás es esa idea aplicada tres veces.

**Capa 1 — Mínimo privilegio en el reparto de tools.** Ya lo construiste sin llamarlo seguridad: si un agente no tiene una tool en la mano, no puede usarla mal por mucho que alucine, porque la capacidad no existe en su mundo. La consecuencia es que el reparto deja de ser comodidad y pasa a ser **decisión de seguridad**, lo que obliga a nombrar la naturaleza de cada tool: `PURE` (sin efectos), `READ` (lee estado), `WRITE` (muta estado), `EXTERNAL` (actúa sobre el mundo). Y sugiere una decisión que va más allá del reparto: **sacar la escritura a un `persistence_agent` propio**, de forma que la superficie peligrosa de todo el sistema quepa en un fichero que se lee entero en un minuto — la misma lógica por la que se aísla el código de pagos. Como el grant es **un dato y no una instrucción**, se puede verificar en el arranque: un agente cableado con una tool que no le corresponde **rompe el despliegue** en lugar de llegar a producción. Una política de seguridad convertida en invariante que el sistema comprueba solo.

**Capa 2 — Validar la acción, no solo tenerla permitida.** El mínimo privilegio dice si un agente puede usar una tool; no dice nada sobre **con qué argumentos**. El `persistence_agent` tiene permiso para escribir; nadie dijo que tuviera permiso para escribir *cualquier cosa*: una estimación de −400 horas, un `estimation_id` que no es el de esta ejecución, un objeto al que le faltan la mitad de los campos. Hace falta un **guardia** entre la intención del agente y la ejecución real, con tres propiedades. Es **código plano y determinista** (nada de un LLM validando a otro LLM: eso solo añade una segunda máquina falible; las reglas de negocio se escriben, se testean y las cubre un test unitario, cosa que un prompt no permite). Comprueba que la acción está **atada al `estimation_id` en curso** — la comprobación que más importa y más se olvida, porque un agente que puede escribir sobre cualquier `estimation_id` es un agente que, ante el input adecuado, modifica la estimación de otro cliente. Y las **acciones irreversibles piden más que validación**: guardar una fila se deshace, enviar un correo al cliente no, así que esa clase de acciones se enruta al **gate humano que ya construiste**. El human-in-the-loop no era solo para la baja confianza: es también el mecanismo de aprobación de lo que no admite marcha atrás. La misma pausa, disparada por otra señal.

**Capa 3 — Auditoría, porque lo que no se registra no ocurrió.** Las dos primeras previenen; la tercera hace que todo sea reconstruible después, y es la que separa un sistema que puedes operar de uno que solo puedes rezar para que funcione. La regla es tajante: **toda acción con efectos se registra, incluidas las denegadas** — que son de hecho las más valiosas, porque son el sistema diciéndote dónde un agente intentó salirse de su carril; una tasa de denegaciones que sube es una alarma temprana. El registro lleva el `estimation_id`, el mismo identificador que atraviesa las tres capas y las trazas, así que reconstruir un caso es una consulta y no arqueología. Y se **redactan los datos sensibles**: un log de auditoría que copia datos personales en texto plano es él mismo un problema de privacidad. Se audita la acción (quién, qué tool, con qué forma de argumentos, con qué resultado), no el contenido íntegro.

**Qué es y qué no es "sandboxing" aquí.** Todo lo anterior vive a **nivel de aplicación** y responde a una pregunta: qué puede hacer este agente dentro de la lógica de negocio. Es la capa correcta para el privilegio, la validación de argumentos y la auditoría, porque son decisiones de dominio que ningún contenedor puede responder. Hay una segunda frontera —aislamiento de proceso, políticas de red, límites de CPU/memoria/tiempo, gestión de secretos— que responde a otra pregunta: qué daño puede hacer el proceso si un agente se comporta de forma imprevista. Eso vive en el runtime y en el despliegue, y llega en la siguiente sesión. **No se sustituyen, se complementan, y ninguna sola es suficiente**: la validación de dominio no te protege de un agente que ejecuta código arbitrario por una tool mal diseñada, y el aislamiento de proceso no te protege de una estimación negativa guardada con argumentos perfectamente válidos para el sistema operativo.

**Cierre del módulo.** El recorrido tiene forma: empezaste con un grafo lineal que funcionaba, lo cuestionaste, y solo al aparecer límites concretos lo reorganizaste en supervisor y especialistas; elegiste cómo se comunican sabiendo que la pizarra que ya tenías era el punto de partida correcto; le diste la capacidad de pararse y pedir ayuda apoyándote en el mismo checkpointer; aprendiste a hacer que compitan cuando el desacuerdo es información; y pusiste límites, validación y registro a lo que cada agente puede tocar. Ninguna pieza era un paradigma nuevo. El sistema está **funcionalmente completo** — y corre en tu máquina: nadie lo ha desplegado, monitorizado, medido bajo carga ni le ha puesto un techo de coste mensual. Esa otra mitad de "en producción" es lo que queda por delante.

---

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Sistemas multi-agente y patrones avanzados

**🚨 Fecha límite indicada en la plataforma: domingo 13 de septiembre, 23:59 de tu hora local.** El criterio operativo del programa es, en todo caso, entregar **al menos dos días antes de la sesión en vivo**: las entregas posteriores no entran en la revisión grupal con la que arranca el directo. Tiempo estimado del enunciado: 19 min. Punto de partida: tu propio servicio IA tal como quedó tras las Sesiones 9–13. Repositorio de referencia: <https://github.com/LIDR-academy/ai-engineering>. Autor del enunciado: Antonio Pérez.

#### Objetivo

Reorganizar el proceso de estimación como un **sistema multi-agente**: un **agente supervisor** que coordina **agentes especializados**, cada uno con acceso solo a las tools que necesita, y un **punto de intervención humana** que pausa el flujo cuando la confianza de la estimación es baja y lo reanuda con la decisión de una persona.

Todo vive **dentro del servicio IA** (Python + FastAPI). El contrato hacia el backend de negocio se mantiene, salvo la superficie nueva del human-in-the-loop.

#### Contexto arquitectónico

Partes de la S13 y **no montas infraestructura nueva**:

- El **estado tipado** de la S13 es tu **pizarra compartida**: todos los agentes leen y escriben sobre él.
- El **checkpointer** (`AsyncPostgresSaver`, sobre el mismo Postgres con pgvector) es lo que hace posible **pausar y reanudar** en el Nivel 2.
- Las **tools son las de la S12** (`search_budgets`, `calculate_estimate`, `validate_estimate`). **No crees tools nuevas: las repartes.**

Idea de fondo: un sistema multi-agente aquí es tu grafo de la S13 reorganizado con un nodo que enruta y agentes que solo ven sus herramientas. Nada mágico.

#### El sistema que vas a construir

Topología supervisor/workers, con el control volviendo al centro tras cada especialista:

```text
                  ┌─────────────────────────────────────────────┐
                  │                                             ▼
START ──▶ supervisor ──▶ requirements_extractor ──▶ supervisor ──▶ budget_searcher ──▶ supervisor
                  │                                             │
                  ├──▶ estimate_generator ──▶ supervisor ───────┤
                  ├──▶ coherence_validator ──▶ supervisor ──────┘
                  │
                  └──▶ human_review_gate ──(interrupt si baja confianza)──▶ finalize ──▶ END
```

Reparto de privilegios (mínimo privilegio de tools):

| Agente | Tools que puede usar |
| --- | --- |
| `supervisor` | **ninguna**: solo enruta |
| `requirements_extractor` | ninguna tool de negocio (solo el modelo) |
| `budget_searcher` | `search_budgets` |
| `estimate_generator` | `calculate_estimate` |
| `coherence_validator` | `validate_estimate` |

#### Niveles

**Nivel 1 — Supervisor + agentes especializados (obligatorio)**

Convierte el grafo lineal de la S13 en una topología supervisor/workers.

1. **Supervisor construido a mano** con `StateGraph` + `Command`: recibe el estado, decide el siguiente agente y consolida. **Nada de `create_supervisor`** — queremos ver el enrutado en las trazas.
2. **Estado tipado extendido** desde el de la S13, con al menos un **reducer acumulador** para las contribuciones de los agentes.
3. **Cada agente es una función pura** que devuelve una actualización parcial del estado.
4. Cada agente accede **solo a sus tools**; el extractor no usa ninguna tool de negocio.
5. El endpoint mantiene el contrato: transcripción → estimación + `status`.

**Nivel 2 — Human-in-the-loop (obligatorio)**

Añade un punto de intervención humana que pausa el grafo cuando la estimación no es fiable.

1. **Señal de disparo** (calculada en el validador o en el supervisor): la pausa se activa si se cumple **alguna** de estas condiciones — confianza por debajo del umbral, estimación fuera del rango histórico, o transcripción sin precedente en presupuestos. **Umbral por defecto configurable.**
2. **Pausa con `interrupt()`** sobre el checkpointer de la S13: el estado queda persistido en el checkpoint y la ejecución se detiene esperando decisión.
3. **Superficie de contrato**: cuando el grafo se pausa, el endpoint responde con `status = "awaiting_human_review"` en lugar de la estimación final. Expón un **endpoint de reanudación** que reciba la decisión y continúe el grafo desde el checkpoint.
4. **Reanudación**: la decisión humana (**aprobar / ajustar / rechazar**) se pliega en el estado y el grafo continúa hasta el final.

**Nivel 3 — Validación de acciones y auditoría (ampliación, opcional)**

Para quien vaya sobrado; prepara el terreno de seguridad del directo.

1. **Validación antes de ejecutar**: cada agente valida la acción que va a realizar contra su **privilegio declarado**; si intenta algo fuera de su conjunto de tools, se **rechaza y se registra**.
2. **Auditoría**: registra cada acción de agente (**qué agente, qué tool, con qué input, con qué resultado**) con **`structlog`**, de forma que una ejecución completa sea reconstruible desde el log.

#### Scaffolding (si vienes flojo de la S13)

En `scaffolding/session_14/` tienes el **estado tipado base**, un **supervisor vacío** con las firmas de referencia y un **`sample_transcript_edge_case.txt`** diseñado para **disparar la baja confianza**. Rellena la lógica de enrutado y de disparo; **no toques el contrato del endpoint**.

#### Qué se difiere al directo (no entra en la entrega)

- **Patrón de competición**: agente conservador vs. agresivo + sintetizador.
- **Hardening de sandboxing**: acotar acciones potencialmente destructivas más allá del mínimo privilegio básico.
- **Testing del flujo HITL** con varias transcripciones *edge case* (fuera de rango, sin precedente).

#### Criterios de aceptación ("hecho")

- [ ] El **supervisor está construido a mano** con `StateGraph` + `Command`; **cada decisión de enrutado aparece en la traza**.
- [ ] Cada agente accede **solo a sus tools** (mínimo privilegio); el extractor no usa ninguna tool de negocio.
- [ ] El estado es **tipado**, extendido desde el de la S13, con **al menos un reducer acumulador**.
- [ ] El grafo corre de principio a fin y el endpoint devuelve la estimación con su `status`; el contrato hacia el backend de negocio es el de siempre.
- [ ] La **pausa humana se dispara** con la señal de confianza y **persiste en el checkpoint**; el endpoint devuelve `status = "awaiting_human_review"`.
- [ ] El **endpoint de reanudación** continúa el grafo desde el checkpoint con la decisión humana en el estado.
- [ ] Existe una **traza completa** de una ejecución que **pasa por la pausa y se reanuda**.

#### Entregable y cómo entregar

1. Sube la rama **`session-14/pre-work`** con el sistema multi-agente implementado.
2. Envía por correo a **george@lidr.co** el enlace a la rama (URL completa de GitHub) **y** el enlace a la **traza de una ejecución que dispare la pausa humana** sobre `sample_transcript_edge_case.txt`, **al menos dos días antes de la sesión en vivo**. Las entregas posteriores no entran en la revisión grupal del inicio del directo.

La rama debe:

- Ejecutar de principio a fin **sin errores**.
- Contener los **Niveles 1 y 2 completos**: supervisor construido a mano con enrutado visible en traza, agentes con mínimo privilegio de tools, estado tipado con reducer acumulador, pausa humana persistida en checkpoint y endpoint de reanudación funcionando.
- Ser **accesible** (repositorio público o con permisos).

#### Pitfalls comunes

- **Efectos laterales antes de `interrupt()`.** Al reanudar, LangGraph **re-ejecuta el nodo entero desde su primera línea** y `interrupt()` devuelve el valor en vez de pausar. Todo lo que hubiera antes se ejecuta dos veces (y se paga dos veces). Regla: **el nodo que interrumpe solo interrumpe**; el trabajo real va en un nodo anterior.
- **Campos de sobrescritura donde hay concurrencia.** `budget_matches`, `proposals` y `routing_trail` deben ser acumuladores (`operator.add`). Un campo de sobrescritura bajo paralelismo pierde datos **en silencio**.
- **Pasar campos acumuladores al reanudar.** El reducer **concatena** con lo persistido y duplicas datos. Pasa solo entradas nuevas (o `Command(resume=...)`).
- **Supervisor sin presupuesto de enrutado.** Sin `MAX_ROUTING_STEPS`, un supervisor confundido rebota entre agentes y agota tu cuenta. `recursion_limit` es la red de seguridad, no la estrategia.
- **Supervisor con tools de negocio.** Si enruta *y* trabaja, has reintroducido el nodo sobrecargado que querías eliminar.
- **Enrutado con texto libre.** La decisión tiene que ser un `Literal` validado; el mismo `Literal` que tipa `Command[...]`.
- **Pasar el historial completo al supervisor.** Usa un **digest** compacto: coste constante por decisión.
- **Usar `create_supervisor`.** El enunciado lo prohíbe explícitamente: se pierde la visibilidad del enrutado en las trazas.
- **Olvidar `graph=Command.PARENT`** si experimentas con handoff directo: sin eso el `goto` busca un nodo dentro del propio agente.
- **Mandar los errores al humano.** Un fallo de tool o un timeout se resuelve con reintento/fallback; la puerta humana es para juicio, no para reintentos manuales.
- **Umbral de revisión demasiado alto.** Si casi todo pasa por revisión, el revisor aprueba en bloque y se destruye la señal.
- **Reglas de negocio duras dentro del grafo.** Los flujos de aprobación por importe viven en el backend de negocio, no en el servicio IA.
- **Reanudación no idempotente.** Dos revisores aprobando el mismo caso: idempotencia en el endpoint o bloqueo en negocio.
- **Romper el contrato HTTP.** `awaiting_human_review` es un **valor nuevo de un campo que ya existía**, no un contrato nuevo.
- **Usar el checkpointer síncrono.** El stack es async (FastAPI + asyncpg): `AsyncPostgresSaver`, y `await checkpointer.setup()` una vez.
- **Estado gordo.** Todo se serializa en cada transición: IDs y datos destilados, nunca respuestas crudas del modelo.

#### Nota de coste de API

Con el supervisor enrutando por modelo, cada salto añade **una llamada que no produce trabajo útil**: una ejecución que toque los cuatro especialistas cuesta ~4 llamadas de trabajo + ~5 de enrutado. Mitigaciones recomendadas: **supervisor híbrido** (reglas para las precondiciones deterministas, modelo solo ante ambigüedad real), **digest compacto** en lugar de historial completo, **temperatura baja** en el enrutado y `MAX_ROUTING_STEPS` como techo duro. Para depurar, reutiliza el modo **`--stub` / `--memory`** de la S13 (retrieval enlatado y `MemorySaver`) y reserva las ejecuciones reales para el entregable. Instrumenta el coste por `estimation_id` desde el principio: con la traza delante, "cuánto cuesta una estimación" es una consulta, no una intuición.

---

### 🛠️ Contexto técnico para la implementación

Material de referencia consolidado de los seis artículos, del esqueleto publicado en el enunciado y de lo que ya existe en el proyecto tras la S13, con todo lo necesario para implementar el sistema multi-agente con **Claude Code CLI**. Todo el código, nombres, docstrings y logs **en inglés**.

**Punto de partida real.** El grafo secuencial de la S13 vive en `ai-service/app/domain/graph/` (`state.py`, `nodes.py`, `build.py`, `checkpointer.py`, `observability.py`), el endpoint en `app/api/routers/estimate_graph.py` y el grafo se construye en el `lifespan` de `app/main.py` y se guarda en `app.state.graph`. El kit y la solución de referencia del programa viven en `ai-service/exercises/session-13/` de la rama `main` del repositorio oficial, y el stub de retrieval offline en `ai-service/exercises/session-12/reference_retrieval.py`. El scaffolding de esta sesión está en `scaffolding/session_14/`.

#### Estructura de módulos

La capa multi-agente **extiende** la de orquestación; no la sustituye:

```text
ai-service/
├── app/
│   ├── domain/
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   ├── state.py              # EstimationState extendido + reducers acumuladores
│   │   │   ├── digest.py             # build_state_digest(): proyección compacta del estado
│   │   │   ├── supervisor.py         # supervisor a mano: decisión tipada + Command(goto=..., update=...)
│   │   │   ├── agents.py             # los 4 especialistas como funciones puras (+ logfire.span)
│   │   │   ├── hitl.py               # human_review_gate(): señal de disparo + interrupt()
│   │   │   ├── build.py              # build_graph(checkpointer): START -> supervisor y nada más
│   │   │   ├── checkpointer.py       # AsyncPostgresSaver (reutilizado de la S13)
│   │   │   └── observability.py      # configuración de Logfire (no-op sin token)
│   │   ├── security/
│   │   │   ├── grants.py             # AGENT_TOOL_GRANTS + ToolRisk + verify_tool_grants()
│   │   │   ├── guard.py              # guard_action(): validación determinista de argumentos
│   │   │   └── audit.py              # execute_guarded(): structlog + redact_sensitive()
│   │   └── schemas/
│   │       └── graph_estimation.py   # contrato HTTP (request / response / HumanDecision)
│   ├── api/
│   │   └── routers/
│   │       └── estimate_graph.py     # POST /v1/estimate/graph, POST .../{id}/resume, GET .../{id}/state
│   └── main.py                       # lifespan: checkpointer -> build_graph -> app.state.graph
├── scripts/
│   └── run_graph_s14.py              # ejecuta el sistema, imprime routing_trail y estado
└── tests/
    └── domain/graph/                 # e2e con MemorySaver + dobles del LLMWrapper y del retrieval
```

#### El estado tipado y sus reducers

```python
# app/domain/graph/state.py
import operator
from typing import Annotated, Literal, Optional, TypedDict


class EstimationState(TypedDict):
    # --- Input ---
    transcript: str
    estimation_id: str

    # --- Agent contributions ---
    requirements: list[str]
    # Accumulators: several agents (or several invocations) contribute here.
    budget_matches: Annotated[list[dict], operator.add]
    proposals: Annotated[list[dict], operator.add]   # competition pattern (live session)
    errors: Annotated[list[str], operator.add]

    # --- Outcome (overwrite semantics: last write wins) ---
    estimate: Optional[dict]
    validation: Optional[dict]
    confidence: Optional[float]

    # --- Human-in-the-loop ---
    human_decision: Optional[dict]

    # --- Routing bookkeeping ---
    routing_steps: int
    routing_trail: Annotated[list[dict], operator.add]

    # "validated" | "needs_review" | "awaiting_human_review" | "routing_budget_exhausted"
    status: str
```

Decide **campo a campo** si acumula o sobrescribe. Los campos que produce un solo agente una vez (`estimate`, `validation`, `confidence`) sobrescriben; los que reciben aportaciones de varios agentes o varias invocaciones (`budget_matches`, `proposals`, `routing_trail`, `errors`) acumulan. Mantén el estado ligero: identificadores y datos destilados, nunca respuestas crudas del modelo.

#### El digest: lo único que ve el supervisor

```python
# app/domain/graph/digest.py
from app.domain.graph.state import EstimationState


def build_state_digest(state: EstimationState) -> str:
    """Compact projection of the state. This is all the supervisor gets to see."""
    lines = [
        f"requirements_extracted: {len(state['requirements'])} items",
        f"budget_matches_found: {len(state['budget_matches'])}",
        f"estimate_produced: {state['estimate'] is not None}",
        f"validation_done: {state['validation'] is not None}",
        f"confidence: {state['confidence']}",
        f"routing_steps_so_far: {state['routing_steps']}",
    ]
    return "\n".join(lines)
```

Coste **constante** por decisión, independiente de la longitud de la transcripción y del número de iteraciones. Si el supervisor necesita más información para decidir bien, se añade al digest de forma explícita y sabes exactamente lo que estás pagando.

#### El supervisor: decisión tipada y `Command`

```python
# app/domain/graph/supervisor.py
from typing import Literal

import logfire
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.domain.graph.digest import build_state_digest
from app.domain.graph.state import EstimationState

MAX_ROUTING_STEPS = 12

AgentName = Literal[
    "requirements_extractor",
    "budget_searcher",
    "estimate_generator",
    "coherence_validator",
    "human_review_gate",
    "finalize",
]


class SupervisorDecision(BaseModel):
    next_agent: AgentName = Field(description="The specialist that must act next.")
    reason: str = Field(description="Why this specialist, in one sentence.")


SUPERVISOR_INSTRUCTIONS = """You coordinate a software estimation pipeline.
Given the current progress digest, choose the single specialist that must act next.

Rules:
- Requirements must be extracted before budgets are searched.
- Budgets must be searched before an estimate is produced.
- An estimate must exist before it can be validated.
- Route to "human_review_gate" once validation is done.
- Never choose a specialist whose work is already done.
"""


def _bump(state: EstimationState, decision: dict) -> dict:
    return {
        "routing_steps": state["routing_steps"] + 1,
        "routing_trail": [decision],
    }


async def supervisor(state: EstimationState) -> Command[AgentName]:
    with logfire.span("supervisor.route") as span:
        # Hard ceiling: a confused router must not burn the API budget.
        if state["routing_steps"] >= MAX_ROUTING_STEPS:
            span.set_attribute("routing_budget_exhausted", True)
            return Command(
                goto="finalize",
                update={"status": "routing_budget_exhausted"},
            )

        # --- Hybrid routing: deterministic preconditions need no model call. ---
        if not state["requirements"]:
            decision = {"next_agent": "requirements_extractor", "reason": "no requirements yet"}
            span.set_attribute("next_agent", decision["next_agent"])
            return Command(goto="requirements_extractor", update=_bump(state, decision))

        if not state["budget_matches"]:
            decision = {"next_agent": "budget_searcher", "reason": "no reference budgets yet"}
            span.set_attribute("next_agent", decision["next_agent"])
            return Command(goto="budget_searcher", update=_bump(state, decision))

        if state["estimate"] is None:
            decision = {"next_agent": "estimate_generator", "reason": "no estimate yet"}
            span.set_attribute("next_agent", decision["next_agent"])
            return Command(goto="estimate_generator", update=_bump(state, decision))

        if state["validation"] is None:
            decision = {"next_agent": "coherence_validator", "reason": "estimate not validated yet"}
            span.set_attribute("next_agent", decision["next_agent"])
            return Command(goto="coherence_validator", update=_bump(state, decision))

        # --- Genuine ambiguity: here the model earns its keep. ---
        response = await client.responses.parse(
            model="gpt-5",
            input=[
                {"role": "system", "content": SUPERVISOR_INSTRUCTIONS},
                {"role": "user", "content": build_state_digest(state)},
            ],
            text_format=SupervisorDecision,
        )
        parsed = response.output_parsed

        span.set_attribute("next_agent", parsed.next_agent)
        span.set_attribute("reason", parsed.reason)

        return Command(goto=parsed.next_agent, update=_bump(state, parsed.model_dump()))
```

Tres cosas que no son opcionales: `Command` **actualiza el estado y mueve el control a la vez**; el tipo de retorno `Command[AgentName]` es el **mismo `Literal`** que puede devolver el modelo (un destino nuevo sin actualizar el `Literal` no funciona en runtime); y el **span lleva la decisión** (`next_agent`, `reason`), que es justo lo que se pierde si delegas el enrutado en una abstracción.

#### Los agentes especializados

```python
# app/domain/graph/agents.py
from typing import Literal

import logfire
from langgraph.types import Command

from app.domain.graph.state import EstimationState


async def budget_searcher(state: EstimationState) -> Command[Literal["supervisor"]]:
    """Only tool: search_budgets. Returns control to the supervisor."""
    with logfire.span("agent.budget_searcher"):
        matches = await search_budgets(requirements=state["requirements"])
        # Partial update only; operator.add merges into the accumulator field.
        return Command(goto="supervisor", update={"budget_matches": matches})


async def coherence_validator(state: EstimationState) -> Command[Literal["supervisor"]]:
    """Only tool: validate_estimate. Produces the confidence signal."""
    with logfire.span("agent.coherence_validator"):
        result = await validate_estimate(
            estimate=state["estimate"],
            budget_matches=state["budget_matches"],
        )
        return Command(
            goto="supervisor",
            update={"validation": result.model_dump(), "confidence": result.confidence},
        )
```

```python
# app/domain/schemas/graph_estimation.py (validation contract)
from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    is_coherent: bool
    confidence: float = Field(ge=0.0, le=1.0)
    concerns: list[str]
    reasoning: str
```

Cada especialista: hace su trabajo, escribe su parcial y devuelve el testigo al supervisor. Funciones puras, sin mutar el estado recibido, sin decidir quién va después.

#### La puerta humana: señal de disparo e `interrupt()`

```python
# app/domain/graph/hitl.py
from typing import Literal

from langgraph.types import Command, interrupt

from app.domain.graph.state import EstimationState

CONFIDENCE_THRESHOLD = 0.7  # configurable via settings


def requires_human_review(state: EstimationState) -> bool:
    """A trigger signal is a boolean condition over the state. Nothing else."""
    validation = state["validation"] or {}

    low_confidence = (state["confidence"] or 0.0) < CONFIDENCE_THRESHOLD
    out_of_range = is_outside_historical_band(state["estimate"], state["budget_matches"])
    no_precedent = len(state["budget_matches"]) == 0

    return low_confidence or out_of_range or no_precedent


def human_review_gate(state: EstimationState) -> Command[Literal["finalize"]]:
    """This node does nothing but interrupt: no side effects before interrupt()."""
    if not requires_human_review(state):
        return Command(goto="finalize", update={"status": "validated"})

    # The payload is the reviewer's interface, not a log line.
    decision = interrupt(
        {
            "reason": build_review_reason(state),
            "estimate": state["estimate"],
            "confidence": state["confidence"],
            "historical_band": historical_band(state["budget_matches"]),
            "budget_matches": state["budget_matches"],
        }
    )

    # On resume the whole node runs again and interrupt() returns this value.
    return Command(
        goto="finalize",
        update={
            "human_decision": decision,
            "estimate": apply_human_decision(state["estimate"], decision),
            "status": "validated",
        },
    )
```

```python
# Decision contract: approve / adjust / reject
class HumanDecision(BaseModel):
    action: Literal["approve", "adjust", "reject"]
    adjusted_hours: float | None = None
    comment: str | None = None
    reviewer_id: str | None = None
```

#### Cableado y compilación del grafo

```python
# app/domain/graph/build.py
from langgraph.graph import START, StateGraph

from app.domain.graph.agents import (
    budget_searcher,
    coherence_validator,
    estimate_generator,
    requirements_extractor,
)
from app.domain.graph.hitl import human_review_gate
from app.domain.graph.state import EstimationState
from app.domain.graph.supervisor import supervisor


def build_graph(checkpointer):
    builder = StateGraph(EstimationState)

    builder.add_node("supervisor", supervisor)
    builder.add_node("requirements_extractor", requirements_extractor)
    builder.add_node("budget_searcher", budget_searcher)
    builder.add_node("estimate_generator", estimate_generator)
    builder.add_node("coherence_validator", coherence_validator)
    builder.add_node("human_review_gate", human_review_gate)
    builder.add_node("finalize", finalize)

    # The only declared edge. Every other transition lives inside a Command.
    builder.add_edge(START, "supervisor")

    return builder.compile(checkpointer=checkpointer)
```

El grafo ya no describe un flujo: describe un **conjunto de capacidades y un enrutador**. La forma del recorrido emerge en ejecución y queda registrada en `routing_trail`.

#### El contrato HTTP (frontera con el backend de negocio)

```python
# app/api/routers/estimate_graph.py
from langgraph.types import Command


@router.post("/v1/estimate/graph")
async def create_estimation(payload: EstimationRequest) -> EstimationResponse:
    config = {"configurable": {"thread_id": payload.estimation_id}, "recursion_limit": 25}
    result = await request.app.state.graph.ainvoke(
        {"transcript": payload.transcript, "estimation_id": payload.estimation_id},
        config,
    )

    if interrupts := result.get("__interrupt__"):
        return EstimationResponse(
            estimation_id=payload.estimation_id,
            status="awaiting_human_review",
            review_payload=interrupts[0].value,
            estimate=None,
        )

    return EstimationResponse(
        estimation_id=payload.estimation_id,
        status=result["status"],
        estimate=result["estimate"],
    )


@router.post("/v1/estimate/graph/{estimation_id}/resume")
async def resume_estimation(estimation_id: str, payload: HumanDecision) -> EstimationResponse:
    config = {"configurable": {"thread_id": estimation_id}}
    result = await request.app.state.graph.ainvoke(Command(resume=payload.model_dump()), config)

    return EstimationResponse(
        estimation_id=estimation_id,
        status=result["status"],
        estimate=result["estimate"],
    )


@router.get("/v1/estimate/graph/{estimation_id}/state")
async def get_estimation_state(estimation_id: str) -> dict:
    config = {"configurable": {"thread_id": estimation_id}}
    snapshot = await request.app.state.graph.aget_state(config)
    return {"values": snapshot.values, "next": snapshot.next}
```

`thread_id = estimation_id` es el identificador que atraviesa las tres capas, el checkpointer y las trazas. `status` **no es un campo nuevo**: solo gana el valor `awaiting_human_review`, así que el backend de negocio necesita una rama nueva, no una integración nueva. La autorización del revisor, la notificación y el histórico de aprobaciones viven en negocio.

#### Mínimo privilegio, validación de acciones y auditoría (Nivel 3)

```python
# app/domain/security/grants.py
from enum import Enum


class ToolRisk(str, Enum):
    PURE = "pure"          # no side effects: calculate_estimate
    READ = "read"          # reads state: search_budgets, validate_estimate
    WRITE = "write"        # mutates state: save_estimate
    EXTERNAL = "external"  # acts on the world: send_estimate_email


AGENT_TOOL_GRANTS: dict[str, set[str]] = {
    "supervisor": set(),
    "requirements_extractor": set(),
    "budget_searcher": {"search_budgets"},
    "estimate_generator": {"calculate_estimate"},
    "coherence_validator": {"validate_estimate"},
    # Write access concentrated in one small, reviewable agent.
    "persistence_agent": {"save_estimate"},
}


def verify_tool_grants(graph_agents: dict) -> None:
    """Fail at startup if an agent was wired with a tool it was not granted."""
    for name, agent in graph_agents.items():
        granted = AGENT_TOOL_GRANTS.get(name, set())
        actual = {tool.name for tool in agent.tools}
        if not actual.issubset(granted):
            raise ConfigurationError(
                f"Agent '{name}' has ungranted tools: {actual - granted}"
            )
```

```python
# app/domain/security/guard.py
from dataclasses import dataclass

from app.domain.security.grants import AGENT_TOOL_GRANTS


@dataclass(frozen=True)
class ActionRequest:
    agent: str
    tool: str
    args: dict


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str


def guard_action(request: ActionRequest) -> GuardDecision:
    # 1. Privilege: is this tool granted to this agent at all?
    if request.tool not in AGENT_TOOL_GRANTS.get(request.agent, set()):
        return GuardDecision(False, f"{request.agent} is not granted {request.tool}")

    # 2. Argument validation: plain, deterministic, unit-testable business rules.
    if request.tool == "save_estimate":
        estimate = request.args.get("estimate", {})
        if estimate.get("hours", 0) <= 0:
            return GuardDecision(False, "estimate hours must be positive")
        # The check that matters most and is forgotten most often.
        if estimate.get("estimation_id") != current_estimation_id.get():
            return GuardDecision(False, "estimation_id does not match this run")

    return GuardDecision(True, "ok")
```

```python
# app/domain/security/audit.py
async def execute_guarded(request: ActionRequest, tool) -> ToolResult:
    decision = guard_action(request)

    log = logger.bind(
        agent=request.agent,
        tool=request.tool,
        args=redact_sensitive(request.args),
        estimation_id=current_estimation_id.get(),
        allowed=decision.allowed,
    )

    # Denied actions are the most valuable log lines you have.
    if not decision.allowed:
        log.warning("action_denied", reason=decision.reason)
        raise ActionDeniedError(decision.reason)

    result = await tool(**request.args)
    log.info("action_executed", result_summary=summarize(result))
    return result
```

Regla de arquitectura: las **acciones irreversibles** (enviar un correo al cliente) no se resuelven con validación automática, se **enrutan al gate humano** que ya existe. La misma pausa, disparada por otra señal.

#### Checkpointer y observabilidad (reutilizados de la S13)

```python
# app/domain/graph/checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

pool = AsyncConnectionPool(conninfo=DATABASE_URL, max_size=10, open=False)
await pool.open()

checkpointer = AsyncPostgresSaver(pool)
await checkpointer.setup()  # run once: creates checkpoints, checkpoint_writes, checkpoint_blobs
```

```python
# app/domain/graph/observability.py
import logfire

logfire.configure()               # no-op without LOGFIRE_TOKEN
logfire.instrument_fastapi(app)   # HTTP layer
logfire.instrument_asyncpg()      # retrieval queries and the checkpointer
logfire.instrument_httpx()        # OpenAI Responses API calls
```

Con `LOGFIRE_TOKEN` en el entorno, cada ejecución exporta un span por agente y por decisión de enrutado dentro de la traza de la petición; sin token los spans se ejecutan igual pero no se exportan. Consulta de coste y latencia por ejecución:

```sql
SELECT attributes->>'thread_id' AS estimation_id,
       SUM((attributes->>'llm_cost_usd')::float) AS cost,
       MAX(duration) AS wall_time
FROM records
WHERE service_name = 'ai-service'
GROUP BY estimation_id;
```

Alternativa válida (documentándola en el README de la entrega): **LangSmith**, activada por entorno con `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` y `LANGSMITH_PROJECT`.

#### Comandos de referencia

```bash
# Dependencias (ya instaladas si vienes de la S13)
uv add langgraph langgraph-checkpoint-postgres logfire structlog

# Smoke parcialmente offline: MemorySaver + retrieval enlatado.
# Solo necesita OPENAI_API_KEY para los agentes que llaman al modelo.
uv run python scripts/run_graph_s14.py --memory --stub

# Levantar el stack e ingerir el corpus de tareas históricas
docker compose exec estimator python scripts/build_task_corpus.py --ingest

# Ejecución real que dispara la pausa humana (entregable)
docker compose exec estimator python scripts/run_graph_s14.py \
  --transcript scaffolding/session_14/sample_transcript_edge_case.txt

# Reanudar una ejecución pausada con la decisión humana
curl -X POST localhost:8000/v1/estimate/graph/{estimation_id}/resume \
  -H 'Content-Type: application/json' \
  -d '{"action": "adjust", "adjusted_hours": 180, "reviewer_id": "u-42"}'

# Ejecución real exportando la traza a Logfire
LOGFIRE_TOKEN=pylf_v1_... docker compose exec -e LOGFIRE_TOKEN estimator \
  python scripts/run_graph_s14.py

# Tests: sistema multi-agente de punta a punta, sin red y sin clave
uv run pytest tests/domain/graph -v
```

**Qué testear** (el camino es no-determinista, el resultado no): que se produjo una estimación, que ningún agente actuó sin sus precondiciones, que `routing_steps` no superó el techo, que la pausa se disparó con la transcripción *edge case* y que la reanudación dejó `human_decision` en el estado. `routing_trail` te da todo eso desde un test, sin instrumentación adicional.

#### Qué se añade en el directo (fuera del alcance de la pre-sesión)

El directo hace crecer esta topología hacia el patrón de competición y el hardening de seguridad:

```text
requirements_extractor ──┬──▶ conservative_estimator ──┐
                         └──▶ aggressive_estimator  ───┴──▶ synthesizer ──▶ human_review_gate
```

- **Competición y síntesis**: dos estimadores con criterios opuestos en paralelo (`proposals` con `operator.add` hace el fan-in), `compute_divergence()` determinista y un sintetizador instruido explícitamente para **no promediar**, que devuelve rango, `driving_assumptions` y `open_questions`.
- **Diversidad real entre competidores**: prompts con criterios sustantivos, **evidencia distinta** por agente y, si es posible, modelos distintos.
- **La divergencia alimenta la confianza**, y la confianza alimenta la puerta humana.
- **Hardening de sandboxing**: aislamiento de proceso, políticas de red, límites de CPU/memoria/tiempo y gestión de secretos — capa de runtime y despliegue, material de la sesión siguiente.
- **Testing del flujo HITL** con varias transcripciones *edge case*, políticas de reanudaciones huérfanas e idempotencia de la reanudación.

---

## Checklist antes de la siguiente sesión

- [ ] Sabes defender **por qué** un sistema multi-agente, y reconocer los cuatro síntomas del techo del grafo único: prompt sobrecargado, demasiadas tools en un espacio de decisión, orden desconocido de antemano y responsabilidades con ejes de cambio distintos.
- [ ] Entiendes que lo que separa un *workflow* de un sistema agéntico no es el número de nodos, sino **quién es dueño del control flow**.
- [ ] Distingues **cooperación** (contribuciones ortogonales, una pasada por el flujo) de **competición** (misma tarea, criterios opuestos, ×3 de coste) y sabes cuándo aplica cada una.
- [ ] Puedes enumerar las contrapartidas: impuesto de enrutado, pérdida de contexto en las transiciones, no-determinismo, superficie de fallo mayor y coste cognitivo.
- [ ] Sabes decir **cuándo NO** ir a multi-agente: flujo fijo, prompt malo o falta de observabilidad.
- [ ] Construyes un supervisor **a mano** con `StateGraph` + `Command`, sin `create_supervisor`, y explicas por qué (visibilidad del enrutado en las trazas y control del contexto de cada agente).
- [ ] Tu supervisor **no tiene tools de negocio**: solo descompone, delega y consolida.
- [ ] Le pasas un **digest** compacto del estado, no el historial de mensajes, y sabes que eso da coste constante por decisión.
- [ ] La decisión de enrutado es un **tipo cerrado** (`Literal` + modelo Pydantic con `next_agent` y `reason`), y el `Literal` coincide con `Command[AgentName]`.
- [ ] Tienes un **presupuesto de enrutado** (`MAX_ROUTING_STEPS`) y `recursion_limit` solo como red de seguridad.
- [ ] Cada decisión de enrutado deja `next_agent` y `reason` en un **span** y en `routing_trail`.
- [ ] Sabes argumentar el **supervisor híbrido**: reglas para las precondiciones deterministas, modelo solo ante ambigüedad real.
- [ ] Testeas **el resultado y las invariantes**, no el camino.
- [ ] Nombras los tres patrones de comunicación (**estado compartido / handoff / mensajes**), su orden de adopción y el criterio para subir de escalón.
- [ ] Sabes que el acoplamiento del *blackboard* es **al esquema**, no entre agentes, y que su antídoto contra el objeto Dios son las **proyecciones** por agente.
- [ ] Decides **campo a campo** si acumula o sobrescribe, y sabes que un campo de sobrescritura bajo concurrencia pierde datos en silencio.
- [ ] Si experimentas con handoff, recuerdas `graph=Command.PARENT` y que el **`task_brief`** es la decisión de diseño real.
- [ ] Sabes que la pausa humana **es persistencia**, y que el checkpointer de la S13 ya es el mecanismo completo.
- [ ] Escribes la señal de disparo como un **booleano sobre el estado**: confianza baja, fuera de rango histórico o sin precedente.
- [ ] Distingues **error** (reintento / fallback / degradación) de **revisión** (juicio humano), y defiendes **una puerta en el punto crítico**, no diez repartidas.
- [ ] El payload de `interrupt()` está diseñado como **interfaz del revisor**, no como log.
- [ ] Sabes que al reanudar el nodo **se re-ejecuta entero**, y que por eso el nodo que interrumpe no tiene efectos laterales antes de `interrupt()`.
- [ ] Reanudas con `Command(resume=...)` sobre el mismo `thread_id = estimation_id`, y no pasas campos acumuladores.
- [ ] El contrato solo gana el valor `awaiting_human_review` en `status`, más un endpoint de reanudación; la autorización y la notificación viven en el backend de negocio.
- [ ] Tienes previstas las reanudaciones **huérfanas** y la **doble reanudación** (idempotencia o bloqueo).
- [ ] Guardas la **decisión humana** como dato: es material de evaluación y de ajuste de umbrales.
- [ ] Entiendes que la **divergencia se calcula** (aritmética, cero tokens) y que el sintetizador **no promedia**: devuelve rango, supuestos determinantes y preguntas abiertas.
- [ ] Sabes detectar la **trampa de la correlación** y qué hace falta para que la competición dé señal: criterios sustantivos, evidencia distinta y, si se puede, modelos distintos.
- [ ] Defiendes que **el prompt no es un mecanismo de seguridad**: el modelo es el cliente y el cliente no se valida a sí mismo.
- [ ] Aplicas las tres capas: **mínimo privilegio** (grants como dato, verificados en arranque), **validación de argumentos** determinista (incluida la comprobación del `estimation_id` en curso) y **auditoría** de toda acción con efectos, denegadas incluidas y con datos sensibles redactados.
- [ ] Diferencias el sandboxing **de aplicación** (privilegio, argumentos, auditoría) del sandboxing **de runtime** (proceso, red, recursos, secretos) y sabes que se complementan.
- [ ] **Niveles 1 y 2 funcionando** en tu repo, con una traza completa de una ejecución que pasa por la pausa y se reanuda, sobre `sample_transcript_edge_case.txt`.
- [ ] Rama **`session-14/pre-work`** publicada y enlace enviado con **al menos dos días de antelación**.

---

## Documentación de referencia

**LangGraph: multi-agente, enrutado y estado**

- LangGraph — sistemas multi-agente (supervisor, swarm, subgrafos): <https://docs.langchain.com/oss/python/langgraph/multi-agent>
- LangGraph — Graph API: `Command`, enrutado, reducers, esquema de estado y `recursion_limit`: <https://docs.langchain.com/oss/python/langgraph/graph-api>
- LangGraph — StateGraph, nodos, aristas y estado (documentación oficial): <https://docs.langchain.com/oss/python/langgraph>

**Human-in-the-loop y persistencia**

- LangGraph — human-in-the-loop e `interrupt`: <https://docs.langchain.com/oss/python/langgraph/human-in-the-loop>
- LangGraph — interrupts e intervención humana: <https://docs.langchain.com/oss/python/langgraph/interrupts>
- LangGraph — persistencia y checkpointers (Postgres): <https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph — memoria a corto y largo plazo: <https://docs.langchain.com/oss/python/langgraph/memory>

**Observabilidad**

- Logfire — observabilidad de IA y full-stack (Pydantic): <https://pydantic.dev/docs/logfire/get-started/ai-observability/>
- Logfire — primeros pasos e instrumentación: <https://pydantic.dev/docs/logfire/get-started/>
- LangSmith — trazabilidad y evaluación de agentes: <https://docs.smith.langchain.com/>
- OpenTelemetry — convenciones semánticas para aplicaciones GenAI: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>

**Repositorios del programa**

- Repositorio oficial de soluciones: <https://github.com/LIDR-academy/ai-engineering>
- Kit y solución de referencia de la sesión anterior (base de partida): <https://github.com/LIDR-academy/ai-engineering/tree/main/ai-service/exercises/session-13>
- Rama de entrega de esta sesión: `session-14/pre-work`
