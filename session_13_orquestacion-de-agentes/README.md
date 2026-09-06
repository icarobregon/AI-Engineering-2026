# Sesión 13 — Orquestación de agentes

## Objetivo de la sesión

Al cierre de la **Sesión 12** el servicio IA ya tiene capacidad de decisión: un bucle agéntico escrito a mano sobre la Responses API que, a partir de una transcripción, elige qué operación ejecutar (`search_budgets`, `calculate_estimate`, `validate_estimate`), itera hasta converger y publica su traza de razonamiento. Son unas decenas de líneas y funcionan bien mientras el flujo se mantiene corto.

La **Sesión 13** ataca el punto donde ese bucle deja de rendir. Cuando el flujo suma pasos con dependencias entre ellos, decisiones que dependen del resultado anterior, trabajo que podría ocurrir a la vez y situaciones en las que hay que retroceder, el `while` imperativo se llena de `if` anidados, banderas de estado y comentarios que justifican por qué el orden es ese. El código sigue siendo correcto; lo que se pierde es la capacidad de razonar sobre él cuando algo se rompe en producción.

El eje de la sesión es **reexpresar el flujo de estimación como un grafo explícito de LangGraph** —estado compartido y tipado, nodos con una responsabilidad cada uno, aristas que deciden el control, persistencia tras cada paso y un span por nodo— y hacerlo **con criterio, no por moda**: midiendo la línea base del bucle actual y comprobando que el grafo aporta algo medible en claridad, recuperación y observabilidad. Si no aporta nada, el bucle ya era la respuesta correcta.

Un detalle de arquitectura que atraviesa los seis artículos: **el grafo vive dentro del servicio IA**, exactamente donde vivía el bucle que sustituye. El backend de negocio sigue enviando una transcripción y recibiendo una estimación estructurada con su campo `status` por el mismo contrato de siempre. La orquestación es un detalle de implementación del servicio IA, no un cambio de arquitectura del producto — y esa frontera es lo que permite introducir el grafo sin tocar la capa de negocio, y retirarlo mañana si no compensa.

---

## Qué vas a aprender

### 1. 📄 Del bucle manual al grafo: cuando necesitamos un framework — 16 min

Arranca con la pregunta incómoda que casi nadie hace antes de adoptar una librería: **¿cuándo se gana un framework de orquestación su sitio, y cuándo el bucle a mano ya era la respuesta?**

**El panorama de 2026.** El ecosistema se ha consolidado en tres modelos. La **orquestación basada en grafos** modela el sistema como un grafo dirigido —nodos que trabajan, aristas que transitan— y su exponente es **LangGraph**, que alcanzó la 1.0 estable en octubre de 2025 junto con LangChain 1.0; el flujo está definido de antemano, lo que da control determinista y depuración sencilla a cambio de más diseño previo. La **orquestación basada en roles** define agentes como miembros de un equipo, cada uno con su rol y sus herramientas, con **CrewAI** como referencia: modelo mental intuitivo y prototipado rápido, menos control fino en ramificaciones complejas. La **orquestación conversacional** coordina por turnos de mensajes; es el linaje de **AutoGen**, que Microsoft fusionó con Semantic Kernel en el **Microsoft Agent Framework** (1.0 en abril de 2026, quedando los dos proyectos originales en mantenimiento) y es la opción natural en ecosistemas Azure/.NET. Fuera de esos tres, un equipo Python debería tener en el radar **Google ADK** —code-first, model-agnostic, con agentes secuenciales, paralelos y de bucle— y **Pydantic AI** —nativo de Python, tipado, con inyección de dependencias al estilo FastAPI, muy cómodo sobre este stack—, además de los SDK de agente de OpenAI y Anthropic para el caso de agente único.

La conclusión de fondo no es la lista: **todos resuelven variaciones del mismo problema** (coordinar pasos, mantener estado, recuperarse de errores) con abstracciones distintas. Ninguno hace magia; es ingeniería de sistemas aplicada a un tipo de servicio nuevo.

**Comprar o construir.** El consejo del equipo de LinkedIn tras llevar agentes a producción es intentar comprar antes que construir, y construir solo lo que no existe, porque el espacio se mueve muy rápido. El patrón dominante en la práctica es **híbrido**: framework para el 80% estándar del flujo, código propio para el porcentaje que es tu diferencial de dominio. Y el consejo operativo más repetido es igual de sobrio: empezar simple, instrumentar mucho y añadir complejidad solo donde los datos la exijan — la mayoría de equipos se pasa un escalón de sofisticación y monta un sistema multi-agente donde bastaba un agente bien instrumentado.

**El dato que ordena prioridades.** Según el informe de ingeniería de agentes de LangChain de 2026, **más del 60% de los incidentes de agentes en producción se originan en la gestión de estado**: agentes que pierden el hilo, repiten trabajo o se caen a medias porque el estado no se persistió bien. No en el modelo, no en el prompt: en el estado. Eso define qué tiene que resolver bien un framework para merecer la pena.

**Dónde encaja LangGraph.** Su modelo es deliberadamente pequeño — cuatro ideas: un **estado** compartido y tipado, **nodos** que son funciones que devuelven una actualización parcial, **aristas** (fijas o condicionales) que deciden la transición y un **checkpointer** que persiste el estado tras cada paso. Todo lo demás —paralelismo, subgrafos, ciclos, intervención humana— se construye encima. Conviene además separar dos niveles dentro de LangChain que se confunden: el atajo de alto nivel `create_agent` (que reemplaza al antiguo `create_react_agent`) monta en pocas líneas un agente ReAct de bucle único, terreno donde un bucle a mano rinde igual; la API de bajo nivel **`StateGraph`** es la que expresa topologías que el bucle ReAct no expresa bien — varios pasos con dependencias, enrutado condicional, paralelismo y ciclos acotados. Ahí es donde el grafo se gana su sitio.

**El impuesto de complejidad.** LangChain 1.0 es estable pero pesado: arrastra superficie de dependencias e indirección que un bucle propio no tiene. La regla práctica es directa. Una sola llamada al modelo con un formato de salida: no hay nada que orquestar, no pagues el impuesto. Un agente único que razona y llama herramientas: un bucle instrumentado ya es una respuesta profesional. El framework empieza a rentar cuando el flujo tiene **forma de grafo de verdad** — dependencias, ramas, paralelismo, persistencia y reanudación, puntos de aprobación humana — porque entonces lo que te ahorra (checkpointer, enrutado, pausa/reanudación, instrumentación por nodo) es justo el trabajo que reimplementarías peor. Y hay una prueba que no se salta: **mide la línea base antes de decidir**.

### 2. 📄 LangGraph desde cero: StateGraph, nodos, aristas y estado — 13 min

El flujo de estimación es fácil de enunciar como lista de pasos: de la transcripción salen requisitos, los requisitos se agrupan en componentes, para cada componente se buscan presupuestos de referencia, con ellos se genera una estimación y por último se valida y consolida. Cinco pasos, cada uno con su responsabilidad. Lo difícil es expresarlo en código que siga siendo legible cuando aparezcan ramas y paralelismo. **LangGraph separa tres cosas que el bucle mezclaba: el trabajo vive en los nodos, el control vive en las aristas y el dato vive en el estado compartido.**

**El estado es la decisión de más peso.** Todo lo demás se lee y se escribe contra ese objeto, así que un esquema mal pensado se paga en cada nodo. Se declara como `TypedDict` (también admite Pydantic o dataclasses: elige uno y sé consistente). La clave está en los campos anotados: por defecto una actualización **sobrescribe** —lo correcto para `status` o `estimate`, donde manda el último valor—, mientras que `Annotated[list[BudgetMatch], operator.add]` instala un **reducer acumulador** que concatena en lugar de reemplazar. Ese reducer es lo que después hace posible que varias ramas escriban a la vez sin pisarse. Disciplina asociada: **mantén el estado ligero**, porque todo lo que hay dentro se serializa en cada transición; guarda identificadores y datos ya destilados, y deja lo transitorio en el ámbito de la función.

**Los nodos son funciones puras.** Reciben el estado y devuelven un diccionario **solo con los campos que cambian**, nunca el estado entero, y no mutan lo que reciben. Así son triviales de testear y el enrutado se mantiene predecible. Cada nodo envuelve la lógica de dominio que ya existe en el servicio (la recuperación sobre la base vectorial, el cálculo de la estimación) sin orquestar nada: quién va después lo deciden las aristas.

**Las aristas son el control.** Las directas fijan el orden cuando el orden es fijo; las **condicionales** ejecutan una función de enrutado que inspecciona el estado y devuelve el nombre del siguiente nodo. `START` y `END` son los centinelas de entrada y salida. Ese mismo mecanismo —mirar el estado y elegir— es el que más adelante soporta reintentos, ciclos y bifurcaciones ricas. `compile()` cierra el diseño y produce un grafo ejecutable, invocable de forma síncrona o asíncrona, con streaming y persistencia, y con el estado tipado como contrato de toda la ejecución.

**El trade-off honesto.** Un bucle se escribe de un tirón; un grafo te obliga a decidir de antemano el esquema, qué es un nodo y dónde va una condicional. Ese diseño previo es trabajo real y para un flujo trivial no rinde. Tres reglas lo mantienen sano: **reducers solo donde de verdad acumulas**, **aristas condicionales solo en puntos de decisión reales** y **estado mínimo, tipado y validado**. Un grafo que las respeta se lee de un vistazo y se depura por nodo.

### 3. 📄 Estado y persistencia: reducers, checkpointers y memoria — 13 min

Un grafo cuyo estado vive solo en memoria tiene un punto ciego: basta un despliegue, un fallo o un timeout a mitad de estimación para perder todo el trabajo hecho. En un flujo que recupera presupuestos de varios componentes y consolida una estimación, empezar de cero cada vez no es aceptable. **Persistir el estado es lo que convierte el grafo en algo que aguanta producción.**

**Reducers, en detalle.** El reducer del campo gobierna cómo se integra cada actualización parcial: sobrescritura por defecto, acumulación con `operator.add`. Y hay un detalle que muerde en producción: **al reanudar desde un checkpoint, el reducer no reemplaza, combina**. Si le pasas un estado inicial que incluye campos acumuladores, `operator.add` concatena lo que envías con lo que ya estaba guardado y **duplicas los datos** sin darte cuenta. Regla: al reanudar, pasa solo las entradas nuevas, jamás los campos acumulados.

**Checkpointers.** Persisten el estado tras la ejecución de cada nodo, lo que habilita pausar, reanudar, inspeccionar paso a paso y —más adelante— parar para que un humano apruebe, todo sin escribir una capa de persistencia propia. Hay varios backends: `InMemorySaver` para desarrollo y tests, `SqliteSaver` para un único servidor y `PostgresSaver` con su variante asíncrona `AsyncPostgresSaver` para producción con varias instancias. Como el servicio IA es asíncrono (FastAPI sobre asyncpg), **la variante que casa es la asíncrona**. Lo importante para el proyecto: el checkpointer se apoya en **el mismo PostgreSQL que ya usa el sistema**, el que tiene pgvector con los embeddings; crea sus propias tablas y convive sin roces. **No hay infraestructura nueva que levantar.**

**`thread_id` ata cada ejecución a su historia.** Se pasa en la configuración de la invocación y es la clave bajo la que se guardan los checkpoints: mismo `thread_id`, la ejecución se reanuda desde el último checkpoint; `thread_id` distinto, ejecución nueva y limpia. Usa el identificador de la estimación y cada estimación tendrá su rastro persistente y reanudable.

**Memoria corta y memoria larga no son lo mismo**, y confundirlas lleva a malas decisiones de arquitectura. La **corta** es el estado de una ejecución, atado a su `thread_id`, viviendo en el checkpointer; su propósito es operativo (reanudar, inspeccionar, permitir una aprobación) y es efímera. La **larga** es el historial de estimaciones que sirve de contexto a futuras estimaciones: eso es **dato de negocio durable** y vive donde vive el dato de negocio y el corpus que alimenta la recuperación. De ahí la posición de arquitectura: **el checkpointer no es tu base de datos de producto**. Resuelve "reanuda esta ejecución donde se quedó", no "qué sabemos de estimaciones anteriores".

**El coste de un estado gordo.** Todo lo que metes en el estado se serializa en cada transición, así que **el tamaño del estado es una decisión de rendimiento**. Un estado ligero —IDs, hallazgos destilados, banderas de enrutado— se serializa en milisegundos. Un estado que arrastra respuestas crudas del modelo con sus metadatos puede llegar a cientos de kilobytes o megabytes, y entonces la escritura del checkpoint pasa de unos pocos milisegundos a varios cientos y se convierte en el cuello de botella real: el agente no va lento por el modelo, va lento porque serializa un objeto enorme en cada paso.

### 4. 📄 Ejecución paralela y enrutado condicional — 12 min

De los cinco pasos del flujo hay uno que arrastra al resto: **la búsqueda de presupuestos**. Recorre los componentes uno a uno y hace una recuperación por cada uno; con ocho componentes son ocho recuperaciones en fila. El resto de nodos son rápidos, así que este marca el tiempo total. Y ese trabajo **no tiene por qué ser secuencial**: buscar el presupuesto del componente A no depende del de B.

**Fan-out con la Send API.** El patrón consiste en partir `search_budgets` en dos piezas: una **función de despacho** que emite un `Send` por cada componente hacia un nodo trabajador, y un **nodo trabajador** que procesa un solo componente. LangGraph ejecuta todos los `Send` en paralelo. El despacho se conecta como arista condicional saliendo del nodo de clasificación, y el trabajador enlaza con el de estimación.

**El reducer deja de ser un detalle y pasa a ser el habilitador.** Cada rama devuelve `{"budget_matches": [match]}`. Si el campo fuera de sobrescritura, las ramas se pisarían y solo sobreviviría la última; como está anotado con `operator.add`, LangGraph concatena las salidas de todas las ramas en una sola lista. Ese es el **fan-in**: las ramas convergen, el reducer las funde y el nodo de estimación se ejecuta **una sola vez**, cuando todas han terminado. El impacto es directo: el tiempo del paso pasa de ser **la suma** de las recuperaciones a ser, aproximadamente, **la más lenta** de ellas.

**Aristas condicionales.** Resuelven el "qué va después". La función de enrutado no llama al modelo ni hace trabajo: lee el estado y decide. Mantener el trabajo en los nodos y la decisión en las aristas es lo que conserva la legibilidad — si cada transición se vuelve una función de enrutado, el grafo pierde la ventaja por la que se adoptó.

**Ciclos, pero acotados.** Las condicionales permiten volver atrás, y los ciclos son normales en sistemas agénticos. El peligro es evidente: en un flujo que llama a un modelo, un bucle infinito es una factura infinita. LangGraph trae un **`recursion_limit`** global como red de seguridad, pero **esa no es la estrategia**: la estrategia es un contador de intentos en el estado y una función de enrutado que, superado el tope, deja de reintentar y desvía a revisión. Así la salida está garantizada por diseño y no solo por el freno del framework.

**El coste del paralelismo está en el merge del estado.** Dos disciplinas: los campos que reciben escrituras concurrentes **tienen que ser acumuladores** (un campo de sobrescritura bajo paralelismo es un bug esperando a ocurrir, porque el resultado depende de qué rama acabó última), y cada rama debe consumir una entrada compatible y devolver **la misma forma** que el agregador espera. La regla que resume ambas: **mantén la salida del trabajador mínima y confinada al campo acumulador**. Un trabajador que solo devuelve `budget_matches` es trivial de combinar; uno que además toca `status` o `estimate` mete condiciones de carrera donde no las había.

### 5. 📄 Manejo de errores y recuperación en flujos complejos — 12 min

El flujo ya es rápido y flexible, pero eso describe **el camino feliz**, que en producción es solo uno de los que ocurren. Una rama paralela puede fallar, una recuperación puede agotar su tiempo, un nodo puede lanzar una excepción porque el modelo devolvió algo inesperado. "Manejar errores" no es una sola cosa: **son varias estrategias, y aplicar la equivocada al fallo equivocado es su propia fuente de problemas**.

**La taxonomía que ordena todo.** Un **fallo transitorio** (pico de latencia, corte momentáneo de red) se arregla reintentando: respuesta, **reintento con backoff**. Una **dependencia caída de forma persistente** no se arregla reintentando —solo alarga la agonía y multiplica el coste—: respuesta, **camino de fallback** y, si conviene, **circuit breaker** para dejar de golpear a la dependencia rota. Una **excepción** detiene la ejecución, pero como el estado está persistido hasta el último nodo que terminó, no se pierde trabajo: **reanudar desde el checkpoint**. Y un caso que no es fallo técnico pero sí parada: **baja confianza o ambigüedad**, donde lo correcto no es que el sistema decida solo sino que **pare y pregunte a un humano**.

**Reintentos, timeouts y degradación.** LangGraph permite adjuntar una **política de reintento** a un nodo (`RetryPolicy(max_attempts=3, backoff_factor=2.0)`) y reejecuta con backoff exponencial sin que escribas el bucle. Los **timeouts** son responsabilidad del nodo, porque el nodo conoce la operación que puede colgarse, y la clave es **degradar con gracia**: una búsqueda que expira **registra el hueco en el acumulador de errores** en lugar de propagar una excepción que tumbe la estimación entera. La rama que falló aporta su hueco, las demás aportan sus presupuestos y el nodo de estimación recibe el conjunto sabiendo qué falta.

**La puerta humana: `interrupt`.** Cuando la estimación sale con baja confianza —presupuestos escasos, componentes que no casan con el histórico—, la respuesta correcta es parar. `interrupt` pausa el grafo en mitad de un nodo, persiste el estado y expone un valor a quien invocó; la ejecución espera indefinidamente hasta que alguien la reanuda con una decisión vía `Command(resume=...)`. **Necesita checkpointer**, porque sin persistencia no hay dónde guardar el punto de pausa. Detalle que evita sorpresas: **al reanudar, el nodo se re-ejecuta desde el principio** y `interrupt` devuelve entonces el valor de reanudación en lugar de volver a pausar — el trabajo previo a la pausa se repite, así que mantenlo **barato e idempotente** y deja lo caro después.

**Automatizar todo o poner una puerta.** El trade-off es de criterio, no técnico, y las dos respuestas extremas fallan. Automatizarlo todo falla donde el sistema no tiene información para decidir bien: una estimación floja enviada a un cliente como si fuera sólida es un problema de negocio. Una puerta en cada paso falla por el lado opuesto: convierte un flujo rápido en una cola de aprobaciones y quema a quien aprueba. La regla que funciona es **proporcional al coste del error**: lo transitorio y las degradaciones se resuelven solas; la puerta humana se reserva para el punto de **alto coste y baja certeza**. **Una puerta, en el sitio crítico, no diez repartidas.**

### 6. 📄 Observabilidad: LangSmith y Logfire para el servicio IA — 10 min

Todo lo anterior repite la misma exigencia: **mide antes de decidir**. ¿El framework se gana su sitio? Línea base. ¿Merece la pena paralelizar? Antes y después. ¿Qué hacer robusto? Mira dónde falla de verdad. Todas esas preguntas asumen que **puedes ver la ejecución por dentro**. La observabilidad no es un extra final: es la instrumentación que convierte un grafo que funciona en un grafo del que sabes cosas.

**La unidad es el span**: un tramo con nombre, inicio, fin y atributos. Los spans se organizan en un árbol —la **traza**— que refleja las relaciones padre/hijo: la petición contiene la ejecución del grafo, que contiene cada nodo, que contiene la llamada al modelo o la consulta a la base. Sobre esa estructura se leen las métricas que importan aquí: **latencia por nodo, tasa de éxito por nodo y coste por estimación**. Un grafo se presta especialmente bien porque **los nodos ya son las unidades naturales de medida**.

**LangSmith** (LangChain) es una plataforma de trazabilidad, evaluación y depuración pensada para agentes: traza la ejecución del grafo de forma nativa como árbol navegable y trae la evaluación como ciudadano de primera clase. Es agnóstica del framework, pero su encaje natural es dentro del ecosistema LangChain, y se activa prácticamente con variables de entorno (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`).

**Logfire** (Pydantic) está construida sobre **OpenTelemetry** y su rasgo distintivo es que **no observa solo la capa del modelo, observa toda la aplicación**. Instrumenta con una línea cada pieza del stack —FastAPI, asyncpg, el cliente HTTP por el que salen las llamadas a la API de OpenAI— y para la latencia por nodo basta envolver el cuerpo de cada nodo en un span. Además **expone los spans por SQL**, así que el coste por estimación es una consulta y no un cuadro de mando cerrado.

**Solo-LLM frente a full-stack es el criterio de elección.** Las herramientas centradas en LLM (LangSmith, Langfuse, Arize) ven muy bien prompt, llamada, herramienta y resultado; pero cuando un nodo consulta la base vectorial, **lo que pasa en medio es una caja negra**. Y en un servicio sobre FastAPI, asyncpg y Postgres buena parte de los problemas vive justo en esas costuras: una recuperación lenta por una consulta que tarda de más, un timeout que en realidad es un problema de conexión, una estimación cara no por el modelo sino por trabajo repetido. Por eso **para este stack la elección de referencia es Logfire**; LangSmith es la natural si el proyecto se apoya fuerte en LangChain y quieres su evaluación y depuración como piezas centrales. No es que una sea mejor: **ven cosas distintas**.

---

## Ejercicios prácticos

### ✍️ Ejercicio pre-sesión — Orquestación de agentes

**Fecha límite indicada en la plataforma:** martes 14 de julio, 23:59 de tu hora local. El criterio operativo del programa es, en todo caso, **entregar al menos dos días antes de la sesión en vivo**: las entregas posteriores no entran en la revisión grupal con la que arranca el directo.
**Repositorio de referencia:** https://github.com/LIDR-academy/ai-engineering
**Punto de partida:** tu propio servicio IA tal como quedó tras las **Sesiones 9–12**.
**Autor del enunciado:** Antonio Pérez.

#### Objetivo

**Reexpresar el flujo de estimación del proyecto como un grafo de LangGraph dentro del servicio IA**, con estado compartido tipado, persistencia y observabilidad. Debes llegar al directo con **el grafo corriendo de principio a fin en secuencial** y con **una traza completa de una ejecución**.

El directo parte de ahí: lo haremos paralelo, robusto y con intervención humana. Por eso en la pre-sesión **no** tienes que resolver ni el paralelismo ni el manejo de errores avanzado.

#### Contexto

En la Sesión 12 construiste a mano un bucle agéntico sobre el pipeline RAG: decidía entre `search_budgets`, `calculate_estimate` y `validate_estimate` y exponía su traza de razonamiento. Funciona, pero se vuelve incómodo en cuanto el flujo tiene varios pasos, ramas condicionales o necesita volver atrás.

En esta sesión ese bucle pasa a ser un **grafo explícito**. **Nada cambia de puertas afuera**: el servicio IA sigue recibiendo una transcripción y devolviendo una estimación estructurada con su campo `status`. El backend de negocio ni se entera de qué hay debajo. El grafo vive dentro del servicio IA.

#### Antes de empezar

Construyes sobre **tu propio servicio IA (S9–S12)**. Si tu agente de la S12 quedó flojo, usa las funciones de referencia del **pack de scaffolding** del repositorio oficial: basta con envolverlas como nodos.

Dependencias nuevas (gestor **uv**):

```bash
uv add langgraph langgraph-checkpoint-postgres logfire
```

**Reutiliza el mismo PostgreSQL del proyecto** (el que ya tiene `pgvector`). El checkpointer crea sus propias tablas y convive sin problema con las de embeddings. **No levantes infraestructura nueva.**

#### El grafo que vas a construir

Cinco nodos, de momento **en secuencial**:

```
START → extract_requirements → classify_components → search_budgets
      → generate_estimate → validate_and_consolidate → END
```

| Nodo | Responsabilidad |
|---|---|
| `extract_requirements` | De la transcripción a una lista de requisitos (LLM estructurado vía tu `LLMWrapper`). |
| `classify_components` | Agrupa los requisitos en componentes con su categoría (LLM estructurado). |
| `search_budgets` | Para cada componente, recupera presupuestos de referencia — **por ahora, uno tras otro**. Reutiliza el `retrieve()` real de S9/S10 sobre `chunk_type='historical_task'`. |
| `generate_estimate` | Consolida los presupuestos en una estimación (LLM estructurado, anclado en las horas históricas recuperadas). |
| `validate_and_consolidate` | Guardrails deterministas + fija el `status` de salida. |

#### Niveles

**Nivel 1 — El grafo, cableado y secuencial (obligatorio)**

- Define un **estado tipado** (`TypedDict`) con **al menos un reducer acumulador** (`Annotated[..., operator.add]`) para un campo que crezca a lo largo del flujo (por ejemplo los presupuestos encontrados o los errores).
- Implementa los cinco nodos como **funciones puras**: reciben el estado y devuelven una **actualización parcial**. Reutiliza tu lógica de S9–S12 (o el scaffolding) dentro de cada nodo.
- Cablea el grafo con **aristas directas** y compílalo.
- El endpoint del servicio IA sigue devolviendo la estimación estructurada con su `status`: **el contrato hacia el backend de negocio no cambia**.

**Nivel 2 — Persistencia y observabilidad (obligatorio)**

- Añade un **checkpointer** sobre el Postgres del proyecto y pasa un **`thread_id` por ejecución** (usa el identificador de la estimación).
- Instrumenta con **Logfire** y consigue una **traza completa** de una ejecución sobre `sample_transcript_complex.txt`, **con un span por nodo**. (Si prefieres **LangSmith** porque vas a apoyarte mucho en LangChain, es válido; **documenta cuál usaste**.)

**Nivel 3 — Primera arista condicional (opcional)**

- Sustituye la arista fija `validate_and_consolidate → END` por una **arista condicional**: si la validación falla, enruta a un final con `status = "needs_review"`; si pasa, a `END` con `status = "validated"`. **Nada más**: el reintento serio, el fallback y la intervención humana se montan en el directo.

#### Lo que NO toca todavía

Para no sobre-construir, queda **fuera** de la pre-sesión:

- **Ejecución paralela** de `search_budgets` por componente (Send API). En la pre-sesión va secuencial: **medir el coste de lo secuencial y paralelizarlo es el caso estrella del directo**.
- **Manejo de errores avanzado**: reintentos con backoff, nodo de fallback, timeouts, circuit breakers.
- **Intervención humana (HITL)** con `interrupt()` en la validación.
- **Optimización a partir de la traza**: la lectura fina de las trazas para decidir qué tocar se hace en directo.

#### Criterios de aceptación ("hecho")

- [ ] El grafo corre de principio a fin y el endpoint devuelve la estimación con su `status`; el contrato hacia el backend de negocio es el de siempre.
- [ ] El estado es **tipado** y tiene **al menos un reducer acumulador**.
- [ ] Los **cinco nodos** son funciones puras que devuelven **actualizaciones parciales**.
- [ ] El **checkpointer persiste en el Postgres del proyecto** y cada ejecución lleva su **`thread_id`**.
- [ ] Existe una **traza completa** de una ejecución, **con un span por nodo**.

#### Entregable y cómo entregar

- Sube la rama **`session-13/pre-work`** con el grafo implementado.
- Envía por correo a **george@lidr.co** el enlace a la rama (URL completa de GitHub) **al menos dos días antes** de la sesión en vivo.
- Adjunta también el **enlace a la traza** de una ejecución completa sobre `sample_transcript_complex.txt`.
- La rama debe: **ejecutar de principio a fin sin errores**, contener los **Niveles 1 y 2 completos** (grafo cableado, persistencia en Postgres y traza con un span por nodo) y ser **accesible** (repositorio público o con permisos).
- No hay entrega formal más allá de eso. **La solución de referencia se abre en la rama `session_13` al cierre del directo.**

#### Pitfalls comunes

- **Duplicar datos al reanudar.** Si pasas campos acumuladores en el estado inicial de una reanudación, `operator.add` los concatena con lo persistido. Pasa **solo entradas nuevas**.
- **Olvidar `await checkpointer.setup()`.** Hay que ejecutarlo una vez para que se creen las tablas de checkpoints; sin eso, el primer arranque falla.
- **Mezclar checkpointer y almacén de negocio.** El checkpointer guarda estado de ejecución (memoria corta). El historial de estimaciones va donde va el dato de negocio.
- **Estado gordo.** Meter respuestas crudas del modelo en el estado convierte la escritura del checkpoint en el cuello de botella. Guarda IDs y datos destilados.
- **Campos de sobrescritura donde habrá concurrencia.** Aunque en la pre-sesión el grafo va secuencial, diseña ya `budget_matches` y `errors` como acumuladores: es lo que hará posible el fan-out del directo sin reescribir el estado.
- **Nodos que orquestan.** Si un nodo decide quién va después, has movido el control fuera de las aristas y pierdes la ventaja del grafo.
- **Aristas condicionales de más.** Solo en puntos de decisión reales (en la pre-sesión, como mucho una: la validación).
- **Romper el contrato HTTP.** El backend de negocio no debe notar el cambio: misma request, misma response con `status`.
- **Usar el checkpointer síncrono.** El stack es async (FastAPI + asyncpg): la variante que casa es `AsyncPostgresSaver`.

#### Nota de coste de API

El grafo hace **tres llamadas al LLM por ejecución** en la versión secuencial (`extract_requirements`, `classify_components`, `generate_estimate`); `search_budgets` y `validate_and_consolidate` no llaman al modelo (recuperación y guardrails deterministas). Depura con el modo `--stub` / `--memory` —retrieval enlatado y checkpointer en memoria— y reserva las ejecuciones reales para el entregable. Instrumenta el coste desde el principio: con la traza delante, "cuánto cuesta una estimación" es una consulta, no una estimación a ojo.

---

### 🛠️ Contexto técnico para la implementación

Material de referencia consolidado de los seis artículos, del esqueleto publicado en el enunciado y del kit oficial del programa, con todo lo necesario para implementar el grafo con **Claude Code CLI**. Todo el código, nombres, docstrings y logs **en inglés**.

> **Verificación contra el repositorio oficial.** El enunciado remite a la rama `session_13` para la solución de referencia ("se abre al cierre del directo"). Comprobado en https://github.com/LIDR-academy/ai-engineering: el **kit y la solución de referencia viven en `ai-service/exercises/session-13/` de la rama `main`**, con su propio `README.md` y los ficheros `sample_transcript_complex.txt`, `example_run_complex.txt`, `demo_ciclo_completo.txt` y `demo_ciclo_completo_run.txt`. El **stub de retrieval offline** que se reutiliza para depurar sin base de datos está en `ai-service/exercises/session-12/reference_retrieval.py`. La rama del directo es **`session_13_live`**.

#### Estructura de módulos

La capa de orquestación vive en el servicio IA y **reutiliza** la de recuperación y generación de S9–S12:

```
ai-service/
├── app/
│   ├── domain/
│   │   └── graph/
│   │       ├── __init__.py
│   │       ├── state.py            # EstimationState (TypedDict) + reducers acumuladores
│   │       ├── nodes.py            # los cinco nodos como funciones puras (+ logfire.span)
│   │       ├── build.py            # build_graph(checkpointer): cablea y compila
│   │       ├── checkpointer.py     # AsyncPostgresSaver sobre el Postgres del proyecto
│   │       └── observability.py    # configuración de Logfire (no-op sin token)
│   ├── domain/
│   │   └── schemas/
│   │       └── graph_estimation.py # contrato HTTP (request / response)
│   ├── api/
│   │   └── routers/
│   │       └── estimate_graph.py   # POST /v1/estimate/graph
│   └── main.py                     # lifespan: construye el grafo y lo guarda en app.state.graph
├── scripts/
│   └── run_graph_s13.py            # ejecuta el grafo e imprime traza/estado
└── tests/
    └── domain/graph/               # e2e con MemorySaver y dobles del LLMWrapper + retrieval
```

El grafo se construye **en el `lifespan` de `app/main.py`** (con el checkpointer ya inicializado) y se guarda en `app.state.graph`; el endpoint lo invoca con `thread_id = estimation_id`.

#### El estado tipado y sus reducers

```python
# app/domain/graph/state.py
from typing import Annotated, Optional, TypedDict
import operator


class Component(TypedDict):
    name: str
    category: str


class BudgetMatch(TypedDict):
    component: str
    reference_budget_id: str
    amount: float


class EstimationState(TypedDict):
    transcript: str
    requirements: list[str]
    components: list[Component]
    # Accumulator field: grows as each component is searched.
    budget_matches: Annotated[list[BudgetMatch], operator.add]
    estimate: Optional[dict]
    status: Optional[str]          # "validated" | "needs_review"
    errors: Annotated[list[str], operator.add]
```

Dos campos acumuladores (`budget_matches` y `errors`) y el resto por sobrescritura. Mantén el estado **ligero**: identificadores y datos ya destilados, nunca respuestas crudas del modelo.

#### Los nodos como funciones puras

Cada nodo recibe el estado, hace su trabajo y devuelve **solo los campos que cambia**, envuelto en un span:

```python
# app/domain/graph/nodes.py (one node shown; the rest follow the same shape)
import logfire


def search_budgets(state: EstimationState) -> dict:
    matches: list[BudgetMatch] = []
    with logfire.span("node: search_budgets"):
        for component in state["components"]:
            # Reuse the S9-S10 retrieval (or the offline scaffolding stub).
            matches.append(retrieve_budget_for(component))
    # Partial state update; the reducer merges into the accumulator field.
    return {"budget_matches": matches}


def classify_components(state: EstimationState) -> dict:
    with logfire.span("node: classify_components"):
        components = group_requirements_into_components(state["requirements"])
    return {"components": components}
```

#### Cableado y compilación del grafo

```python
# app/domain/graph/build.py
from langgraph.graph import StateGraph, START, END

from app.domain.graph.state import EstimationState
from app.domain.graph.nodes import (
    extract_requirements,
    classify_components,
    search_budgets,
    generate_estimate,
    validate_and_consolidate,
    flag_for_review,
)


def route_after_validation(state: EstimationState) -> str:
    # Level 3: a routing function inspects the state and returns the next node.
    return END if state["status"] == "validated" else "flag_for_review"


def build_graph(checkpointer):
    builder = StateGraph(EstimationState)
    builder.add_node("extract_requirements", extract_requirements)
    builder.add_node("classify_components", classify_components)
    builder.add_node("search_budgets", search_budgets)   # sequential for now
    builder.add_node("generate_estimate", generate_estimate)
    builder.add_node("validate_and_consolidate", validate_and_consolidate)
    builder.add_node("flag_for_review", flag_for_review)

    builder.add_edge(START, "extract_requirements")
    builder.add_edge("extract_requirements", "classify_components")
    builder.add_edge("classify_components", "search_budgets")
    builder.add_edge("search_budgets", "generate_estimate")
    builder.add_edge("generate_estimate", "validate_and_consolidate")

    # Level 1 wiring is a plain edge to END; Level 3 replaces it with this:
    builder.add_conditional_edges("validate_and_consolidate", route_after_validation)
    builder.add_edge("flag_for_review", END)

    return builder.compile(checkpointer=checkpointer)
```

#### Checkpointer sobre el Postgres del proyecto

```python
# app/domain/graph/checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

# At service startup: one pool over the project's Postgres (the pgvector one).
pool = AsyncConnectionPool(conninfo=DATABASE_URL, max_size=10, open=False)
await pool.open()

checkpointer = AsyncPostgresSaver(pool)
await checkpointer.setup()   # run once: creates checkpoints, checkpoint_writes, checkpoint_blobs
```

El checkpointer crea sus tablas (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) en el Postgres del proyecto en el primer arranque, conviviendo con las de embeddings. Para tests y depuración offline se sustituye por un `MemorySaver`.

#### Observabilidad con Logfire

```python
# app/domain/graph/observability.py  (+ app startup)
import logfire

logfire.configure()               # no-op without LOGFIRE_TOKEN
logfire.instrument_fastapi(app)   # the HTTP layer
logfire.instrument_asyncpg()      # DB queries: retrieval and the checkpointer
logfire.instrument_httpx()        # the OpenAI Responses API calls (the SDK uses httpx)
```

Con `LOGFIRE_TOKEN` en el entorno (token de escritura de https://logfire.pydantic.dev) cada ejecución exporta **un span por nodo** dentro de la traza de la petición. Sin token los spans se ejecutan igual pero no se exportan, así que el servicio funciona en cualquier caso. El coste por estimación se consulta por SQL sobre los spans:

```sql
SELECT attributes->>'thread_id' AS estimation_id,
       SUM((attributes->>'llm_cost_usd')::float) AS cost,
       MAX(duration) AS wall_time
FROM records
WHERE service_name = 'ai-service'
GROUP BY estimation_id;
```

Alternativa válida (documentándolo en el README de la entrega): **LangSmith**, activada por entorno con `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` y `LANGSMITH_PROJECT=estimation-service`.

#### El grafo detrás del endpoint (frontera con el backend de negocio)

```python
# app/api/routers/estimate_graph.py
config = {"configurable": {"thread_id": estimation_id}, "recursion_limit": 25}
result = await graph.ainvoke({"transcript": transcript}, config)

# Keep the existing contract: return the structured estimate and its status.
return {"estimate": result["estimate"], "status": result["status"]}
```

```python
# Resuming / inspecting an execution: same thread_id continues from the last checkpoint.
snapshot = await graph.aget_state(config)
```

**Regla de reanudación:** al reanudar pasa **solo entradas nuevas**, nunca campos acumuladores, o el reducer los duplicará.

#### Comandos de referencia

```bash
# Dependencias
uv add langgraph langgraph-checkpoint-postgres logfire

# Smoke parcialmente offline: sin Postgres (MemorySaver) y con retrieval enlatado.
# Solo necesita OPENAI_API_KEY para los nodos LLM (extract / classify / generate).
uv run python scripts/run_graph_s13.py --memory --stub

# Levantar el stack e ingerir el corpus de tareas históricas
docker compose exec estimator python scripts/build_task_corpus.py --ingest

# Ejecución real (entregable) sobre la transcripción compleja
docker compose exec estimator python scripts/run_graph_s13.py --out exercises/session-13/example_run_complex.txt

# Ejecución real exportando la traza a Logfire
LOGFIRE_TOKEN=pylf_v1_... docker compose exec -e LOGFIRE_TOKEN estimator python scripts/run_graph_s13.py

# Tests: el grafo de punta a punta sin red y sin clave
uv run pytest tests/domain/graph -v
```

`--memory` usa un `MemorySaver` en memoria en vez del checkpointer de Postgres. `--stub` cambia el retrieval real por el stub offline de `exercises/session-12/reference_retrieval.py`.

#### Qué se añade en el directo (fuera del alcance de la pre-sesión)

El directo hace crecer este grafo secuencial de cinco nodos hasta un **pipeline multi-agente con dos handovers explícitos y dos puertas humanas**, con los nodos convertidos en agentes especializados:

```
classifier_agent ─Command(goto)─▶ structure_agent ─▶ 🧑 puerta 1 (interrupt)
  ─Send fan-out por tarea─▶ estimate_task_hours xN ─join─▶ recover_and_handover
  ─Command(goto)─▶ analysis_agent ─▶ 🧑 puerta 2 (interrupt) ─cond─▶ proposal_agent | END
```

- **Handovers** con `Command(goto=..., update=...)`: pasan control y estado entre agentes.
- **Puertas humanas** con `interrupt()`, reanudadas por el backend de negocio con `Command(resume=...)`; el estado sobrevive a la pausa gracias al checkpointer.
- **Fan-out por tarea** con la **Send API** más un **reducer keyed** idempotente ante reanudación (evita el doble-append).
- **Recuperación agéntica** de las tareas dudosas en el join.
- **Endpoints** `POST /v1/estimate/graph` (arranque), `POST .../{id}/resume` y `GET .../{id}/state`, más un wizard en el backend de negocio que arranca y reanuda las dos puertas.
- **Reintentos y degradación**: `RetryPolicy(max_attempts=3, backoff_factor=2.0)` por nodo, timeouts con `asyncio.wait_for` que escriben el hueco en `errors` en vez de tumbar la ejecución, y circuit breaker sobre la dependencia de recuperación.

---

## Checklist antes de la siguiente sesión

- [ ] Sabes distinguir los **tres modelos de orquestación** de 2026 (grafos, roles, conversacional) y nombrar su exponente.
- [ ] Puedes defender que la pregunta correcta no es "framework sí o no" sino **qué forma tiene el flujo**, y citar el patrón híbrido 80/20.
- [ ] Recuerdas el dato que ordena prioridades: **más del 60% de los incidentes de agentes en producción vienen de la gestión de estado**.
- [ ] Enumeras las **cuatro primitivas** de LangGraph: estado tipado, nodos-función, aristas (condicionales) y checkpointer.
- [ ] Distingues `create_agent` (agente ReAct de bucle único) de **`StateGraph`** (topologías con dependencias, ramas y paralelismo).
- [ ] Sabes explicar el **impuesto de complejidad** de un framework y por qué hay que **medir la línea base antes de decidir**.
- [ ] Diseñas un `TypedDict` de estado y decides, campo a campo, **sobrescritura o reducer acumulador**.
- [ ] Escribes nodos como **funciones puras** que devuelven actualizaciones parciales y no mutan el estado recibido.
- [ ] Sabes que **`operator.add` es lo que hace posible el fan-in** y que un campo de sobrescritura bajo paralelismo es un bug esperando a ocurrir.
- [ ] Configuras un **`AsyncPostgresSaver`** sobre el Postgres del proyecto, ejecutas `setup()` una vez y pasas **`thread_id`** por ejecución.
- [ ] Tienes claro el **pitfall de la reanudación**: no pasar campos acumuladores en el estado inicial.
- [ ] Separas **memoria corta** (estado de ejecución, en el checkpointer, efímera) de **memoria larga** (historial de estimaciones, dato de negocio) — el checkpointer **no** es tu base de datos de producto.
- [ ] Entiendes que **el tamaño del estado es rendimiento**, porque todo se serializa en cada transición.
- [ ] Sabes que el paso lento del flujo es `search_budgets` y **por qué es paralelizable** (trabajo independiente por componente).
- [ ] Sabes acotar un ciclo con un **contador en el estado**, dejando `recursion_limit` como red de seguridad y no como estrategia.
- [ ] Asocias **cada tipo de fallo a su respuesta**: transitorio → reintento con backoff; dependencia caída → fallback y circuit breaker; excepción → reanudar desde checkpoint; baja confianza → puerta humana.
- [ ] Sabes que `interrupt()` **requiere checkpointer** y que **el nodo se re-ejecuta al reanudar**, así que el trabajo previo a la pausa debe ser barato e idempotente.
- [ ] Defiendes el criterio de **una puerta humana en el punto crítico**, no diez repartidas por el flujo.
- [ ] Distingues **span** de **traza** y sabes qué métricas se leen encima: latencia por nodo, tasa de éxito y coste por estimación.
- [ ] Explicas la diferencia entre observabilidad **solo-LLM** y **full-stack**, y por qué para este stack la referencia es **Logfire**.
- [ ] **Niveles 1 y 2 funcionando** en tu repo, con una traza completa (un span por nodo) sobre `sample_transcript_complex.txt`.
- [ ] Rama **`session-13/pre-work`** publicada y enlace enviado con al menos dos días de antelación.

---

## Documentación de referencia

**LangGraph: grafo, estado y persistencia**

- LangGraph — StateGraph, nodos, aristas y estado (documentación oficial): https://docs.langchain.com/oss/python/langgraph
- LangGraph — Graph API: reducers, esquema de estado, Send API, aristas condicionales y `recursion_limit`: https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph — persistencia y checkpointers (Postgres): https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph — memoria a corto y largo plazo: https://docs.langchain.com/oss/python/langgraph/memory
- LangGraph — interrupts e intervención humana (human-in-the-loop): https://docs.langchain.com/oss/python/langgraph/interrupts

**Panorama de frameworks**

- LangChain — anuncio de LangChain 1.0 y LangGraph 1.0: https://www.langchain.com/blog/langchain-langgraph-1dot0
- LangChain — comparativa de frameworks de agentes: https://www.langchain.com/resources/ai-agent-frameworks
- Microsoft Agent Framework (overview y sucesión de AutoGen y Semantic Kernel): https://learn.microsoft.com/en-us/agent-framework/overview/
- Google — Agent Development Kit (overview): https://docs.cloud.google.com/agent-builder/agent-development-kit/overview
- Patrones de orquestación de agentes en producción: https://arahi.ai/blog/ai-agent-orchestration

**Observabilidad**

- Logfire — observabilidad de IA y full-stack (Pydantic): https://pydantic.dev/docs/logfire/get-started/ai-observability/
- Logfire — primeros pasos e instrumentación: https://pydantic.dev/docs/logfire/get-started/
- LangSmith — trazabilidad y evaluación de agentes: https://docs.smith.langchain.com/
- OpenTelemetry — convenciones semánticas para aplicaciones GenAI: https://opentelemetry.io/docs/specs/semconv/gen-ai/

**Buenas prácticas**

- Buenas prácticas de diseño de estado, aristas, fan-out y ciclos acotados en LangGraph: https://www.swarnendu.de/blog/langgraph-best-practices/
- Diseño de esquema de estado y checkpointers en producción: https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/

**Repositorios del programa**

- Repositorio oficial de soluciones: https://github.com/LIDR-academy/ai-engineering
- Kit y solución de referencia de la sesión: https://github.com/LIDR-academy/ai-engineering/tree/main/ai-service/exercises/session-13
- Rama del directo: `session_13_live`
