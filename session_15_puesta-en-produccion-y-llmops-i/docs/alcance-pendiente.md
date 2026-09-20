# Alcance pendiente del backend de negocio

Qué quedó fuera al portar la aplicación de referencia, por qué, y qué costaría
cada pieza. Escrito al cierre de la Sesión 15 para afrontarlo en la **Sesión 16**.

## De dónde sale esta lista

Del `config/routes.rb` de la aplicación Rails del profesor
(`LIDR-academy/ai-engineering`, rama `session_15`), cruzado con los endpoints que
el servicio IA expone hoy. No es una lista de ideas: es la diferencia entre dos
inventarios reales.

Cuando se decidió el alcance, el criterio fue **cimientos + camino núcleo**: la
frontera pública, el cliente HTTP único, los contratos en zod, la persistencia y
las dos pantallas que el entregable de la sesión evalúa (estimación transaccional
y supervisor con revisión humana). Todo lo demás se aplazó a propósito, no por
descuido.

Después, ya con los cimientos puestos, entraron cinco piezas más porque salían
baratas —consumían contratos que ya existían—: conversación, modo
Actor-Critic-Boss, laboratorio de chunking, traza de enrutado del supervisor y
ajustes de modelo.

## El estado, de un vistazo

| Pantalla del profesor | Aquí | Endpoints del servicio IA |
|---|---|---|
| `root` — panel | ✅ portada | — |
| `estimations` | ✅ portada | ya existen |
| `chat_sessions` (+ ACB) | ✅ portada | ya existen |
| `rag/chunking_comparisons` | ⚠️ parcial — sin histórico | ya existen |
| `rag/supervisor_estimation_runs` | ✅ portada | ya existen |
| `ai_settings` | ✅ portada | ya existen |
| `rag/index_runs` | ✅ portada | hizo falta uno nuevo |
| `rag/estimation_runs` | ✅ portada | ya existían |
| `agents/graph_flow` | ✅ portada | hizo falta uno, trivial |
| `agents/profiles` | ✅ portada | hizo falta exponer el agente |
| `rag/graph_estimation_runs` | ⚠️ parcial — sin las dos puertas | hizo falta trabajo en Python |

La tabla está ordenada por coste creciente. La columna de endpoints dice lo que
cuesta de verdad cada pieza, y conviene leerla con desconfianza: la de corpus
decía «ya existen» por parecido de nombres, y al abrir el código resultó que no.
Antes de dar por bueno que algo está cubierto, hay que leer qué hace el endpoint,
no cómo se llama.

---

## 1. Histórico del laboratorio de chunking · barato

**Qué falta.** El profesor tiene tres pantallas bajo `rag/chunking_comparisons`:
`new` (formulario), `show` (un run concreto) e `index` (histórico, las últimas 20
sin paginar). Aquí sólo existe la primera: se ejecuta y se pinta, y al recargar se
pierde.

**Por qué importa más de lo que parece.** No es comodidad. Las cuatro estrategias
de pago cuestan dinero y tardan minutos; el histórico es el mecanismo que evita
volver a pagarlas. El propio texto del profesor lo dice: «cada run se guarda para
revisitarlo sin re-pagar las estrategias LLM».

**Qué haría falta.** Una tabla en el esquema `business` con la petición, el
payload íntegro y la duración, más dos rutas. Cero cambios en Python.

## 2. Corpus e índice (S11) · ✅ hecho

Portada en `/corpus`. **Y con una corrección a lo que decía antes este documento.**

Aquí se afirmaba que no necesitaba «ni una línea de Python» porque
`POST /api/v1/ingestion/runs` y `GET /api/v1/ingestion/jobs/{id}` ya existían. Era
falso, y el error fue deducirlo del parecido de los nombres sin leer qué hacen:
esas rutas son el pipeline offline de la S06 sobre fuentes CATALOGADAS en disco,
no «indexa estos documentos». La app de referencia llama a
`/embeddings/index/{stats,runs,jobs}` y de esas tres no teníamos ninguna.

De las tres sólo hizo falta **una**, `GET /embeddings/index/stats`, porque en la
app del profesor el sondeo va contra un endpoint suyo de Rails y no contra el
servicio IA: el trabajo asíncrono podía vivir en el BFF llamando a
`/embeddings/ingest` documento a documento, que es como está hecho.

Lo que se descubrió al construirlo: **no existe ningún índice HNSW ni IVFFlat en
el sistema**. Toda búsqueda vectorial es hoy un recorrido secuencial sobre 1603
chunks. Funciona a este tamaño y dejaría de funcionar sin avisar; ahora la
pantalla lo enseña. Crear el índice es trabajo aparte, y no trivial: hay que
elegir parámetros y reindexar.

## 3. Diagrama del grafo (S13) · ✅ hecho

Portado en `/grafo`, con `GET /v1/estimate/graph/diagram` nuevo en el servicio IA.

**Y no se portó lo que hace el profesor, a propósito.** Su pantalla es 100 %
estática: ocho nodos escritos a mano en una constante de Ruby que describen el
pipeline de la S13, con personajes de Matrix y cajas de CSS. Copiar esa constante
habría documentado un grafo que nosotros ya no tenemos: el nuestro evolucionó en
la S14 hacia un supervisor con siete nodos y enrutado dinámico. El dibujo se lee
del grafo compilado.

## 4. Asistente RAG de cinco pasos (S09–S12) · ✅ hecho

Portado en `/asistente`. Aquí el pronóstico sí acertó: no hizo falta ni un
endpoint nuevo. El profesor llama a `/v1/estimate/agent/{structure,hours}` y
nosotros teníamos lo mismo en `/v1/estimate/stages/structure` y
`/v1/estimate/tasks/hours`; era un cambio de ruta, no de capacidad.

Lo que sí hizo falta arreglar fue un defecto de configuración que sólo se ve
ejecutándolo: la ruta RAG corría el modelo de razonamiento con `LLM_TIMEOUT`
(120 s), cortaba cada intento antes de que terminara y fallaba a los 362 s
habiendo pagado tres generaciones. Ver `GENERATION_TIMEOUT`.

Queda abierto, y anotado en el README del frontend: el paso de estructura es una
petición de minutos sostenida por una Server Action. Es la forma que tiene la app
de referencia, pero no es la forma correcta.

## 5. Consola de agentes (S12) · ✅ hecho

Portada en `/agentes`, con `POST /v1/estimate/agent/run` nuevo en el servicio IA.

**Y se portó la pantalla que la referencia promete, no la que entrega.** El
inventario destapó que allí nadie lee `Agents::Profile` fuera de su propio CRUD:
el asistente llama al agente con `config: {}` literal, `Profile#config_payload` no
se invoca en ningún sitio de su `app/`, el botón «Probar» no pasa el id y la
casilla «por defecto» sólo pinta una etiqueta. Era un formulario decorativo porque
el agente de la S12 no tenía endpoint. Ahora lo tiene, y un perfil gobierna modelo,
esfuerzo e iteraciones de verdad.

El trabajo asíncrono reutiliza el patrón de la ampliación del corpus en vez de
inventar uno: la acción lanza en segundo plano, la pantalla sondea su propia fila,
el sondeo sólo lee y un run sin señales se declara colgado en lugar de sondearse
para siempre.

## 6. Asistente de grafo con propuesta y PDF (S13) · el más caro

**Qué falta.** `rag/graph_estimation_runs`, y es la pieza con más partes:

- **Dos puertas humanas**, no una: `resume_structure` y `resume_final`.
- **Arranque no bloqueante + feed de actividad por agente**, sondeado mientras
  corre cada tramo.
- **Generación de propuesta comercial** tras completarse.
- **Descarga de la propuesta en PDF.**

Es su pantalla más grande: 929 líneas propias, 936 de código compartido
imprescindible y 297 de tests. Alrededor del **24 % del código de su aplicación**
en una sola pantalla — y eso es sólo la mitad cliente.

### La corrección importante: ellos tienen DOS grafos, nosotros uno

Esta sección decía antes que portar la pantalla significaba *cambiar nuestro
grafo*. No es exacto, y la diferencia cambia la decisión. Su propio `CLAUDE.md`
lo dice de la S14:

> *It is a NEW graph that COEXISTS with S13 — `graph/build.py`, `graph/agents/`
> and the seven `/v1/estimate/graph` endpoints are untouched*

|  | Su S13 | Su S14 | Aquí |
|---|---|---|---|
| Endpoints | `/v1/estimate/graph` ×7 | `/v1/estimate/supervisor` ×3 | `/v1/estimate/graph` ×4 |
| Forma | 8 nodos, fan-out Send, 2 puertas | supervisor, enrutado dinámico, 1 puerta | supervisor, enrutado dinámico, 1 puerta |
| `thread_id` | `<id>` | `s14:<id>` | `<id>` |

Comparten un solo checkpointer; de ahí el prefijo. **Ellos añadieron un grafo;
nosotros sustituimos el nuestro.** Nuestro grafo vive en la URL de su S13 pero
por dentro es su S14.

Así que el port fiel no es tocar el supervisor: es **añadir un segundo grafo**,
como hicieron ellos. Eso es menos arriesgado de lo que decía esta sección —no
hay tensión con `GRAPH_MAX_ROUTING_STEPS`, no se rompe el contrato de
`HumanDecision`, no hace falta un segundo `interrupt()` en el grafo actual— y más
trabajo en absoluto: hay que construir los ocho nodos, el fan-out por tarea, el
bucle de recuperación agéntica y el informe de fiabilidad.

Nota de navegación, por si alguien sospecha que la pantalla es código muerto de
la S13: **no lo es**. Está en la barra de navegación de su aplicación
(`layouts/application.html.erb:40`, «Grafo») y la enlaza `/agents/graph_flow` con
un botón «Probar el flujo». La que no enlaza nadie es la del supervisor (S14), y
tampoco está muerta: su `routes.rb` explica que la puerta es condicional, así que
`#index` es una cola de trabajo y no un asistente. Una bandeja no va en el menú.

### La decisión tomada

**No se porta como paridad.** Su repositorio es un museo didáctico: conserva el
artefacto de cada sesión uno al lado del otro porque enseñar la S13 y la S14
exige poder abrir las dos. Aquí el grafo evoluciona, y reconstruir su S13
obligaría a arrastrar dos grafos durante el resto del máster, con dos contratos,
dos baterías de tests y un checkpointer compartido que namespacear.

Se rescatan **las dos piezas que valen por sí solas**, sin grafo nuevo:

1. **El arranque no bloqueante.** Hoy `POST /v1/estimate/graph` hace
   `await graph.ainvoke(...)` y mantiene la petición HTTP abierta los minutos que
   dure el grafo, con una Server Action esperando al otro lado. No hay ni un
   `astream` en todo `app/`. Eso es una limitación real del diseño actual, exista
   o no la pantalla, y es el requisito previo de cualquier feed: hoy no hay nada
   que sondear porque el cliente está bloqueado esperando la respuesta.
2. **La propuesta comercial y el PDF.** Capacidad nueva, con forma de endpoint
   suelto —`POST /v1/estimate/graph/{id}/proposal`, exactamente como lo
   resolvieron ellos: redacta desde la estimación validada **sin re-ejecutar el
   grafo**— y sin tocar la topología. Cuesta cero pasos de enrutado y es
   reintentable sola. El PDF sí es de esta capa.

Lo que queda explícitamente fuera, y es una decisión de producto anterior a
escribir código: **la segunda puerta humana**. Nuestros tres disparadores
(confianza, banda histórica, sin precedente) se calculan *después* de estimar;
antes no existe ninguno. Habría que inventar el criterio, y «pausar siempre»
choca con la nota de calibración de `GRAPH_CONFIDENCE_THRESHOLD` en `CLAUDE.md`:
un umbral que manda todo a revisión destruye la señal porque el revisor empieza a
aprobar en bloque.

### Techo del feed, aunque el arranque deje de bloquear

Tres límites del estado que ninguna interfaz arregla:

- **No hay ni un timestamp** en el estado. Ni en `routing_trail`, ni en el
  estimate, ni en la validación. La línea temporal real hay que sacarla del
  checkpointer (`aget_state_history()` ya persiste un snapshot con su `created_at`
  por superstep), que es justo lo que hace el endpoint de progreso.
- **La traza registra despachos, no finalizaciones.** La entrada se escribe en
  `supervisor.py::_route` *antes* de que el agente corra. Pintarla como «agente
  terminado» miente durante todo lo que el agente tarde.
- **Coste, tokens y latencia por agente viven sólo como atributos de span**
  (`llm.py::stamp_llm`) y sólo se exportan con `LOGFIRE_TOKEN`. No hay forma de
  leerlos de vuelta: no son fuente válida para una pantalla.

### Lo que NO se porta de su implementación

Errores suyos que no conviene heredar:

- `progress` es un **GET que escribe en base de datos** (`apply_run_state!`).
- El poller va a 1,5 s fijos, **sin backoff ni tope de intentos**.
- `approved` y `validated` están **hardcodeados a `true`**: no hay camino de
  rechazo en ninguna de las dos puertas.
- El markdown de la propuesta se enseña **crudo** en pantalla y se interpreta en
  el PDF con **tres regex** escritas a mano. Dos representaciones del mismo texto,
  ninguna con un parser.
- La columna `task_hours` se escribe y **no la lee ninguna vista**.
- Las horas editadas se emparejan **por índice posicional**, no por nombre.
- El aviso «quedan N tareas sin horas» **no bloquea** el botón de validar.

---

## Lo que NO es alcance pendiente

Para que no se cuele por inercia en la sesión siguiente:

- **Usuarios y permisos.** La aplicación de referencia tampoco los tiene. Toda la
  autorización que existe es el token entre servicios. Añadir login es alcance
  nuevo, no paridad. Queda dicho en el README del frontend como limitación.
- **Fidelidad visual con la app del profesor.** Su tema declara `brand`, `ink`,
  `success` y `danger`, pero **no** declara `warning`, y usa clases `text-warning`
  por toda la interfaz que en Tailwind 4 no emiten regla. Su intención es ámbar y
  así está portado aquí, pero su pantalla se ve sin color. No validar el port
  contra una captura suya.

## Deuda propia, no del port

- ~~El BFF no tiene batería de tests.~~ **Resuelto**: 70 tests con Vitest sobre la
  taxonomía de errores, el cliente HTTP, el mapeo de respuesta a fila del
  supervisor, los parseadores de formulario, los espejos zod y el formateo.
- **`ruff format` reformatearía 33 ficheros del servicio IA.** El proyecto valida
  con `ruff check`, que pasa limpio; el formateo nunca se aplicó en bloque.
  Hacerlo es un commit ruidoso que conviene aislar.
