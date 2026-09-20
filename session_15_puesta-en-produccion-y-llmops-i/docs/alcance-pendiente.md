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
| `rag/graph_estimation_runs` | ❌ pendiente | falta trabajo en Python |

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
- **Feed de actividad por agente**, sondeado mientras corre cada tramo.
- **Generación de propuesta comercial** tras completarse.
- **Descarga de la propuesta en PDF.**

**Lo que ya está.** `POST /v1/estimate/graph`, su `resume` y
`GET /v1/estimate/graph/{id}/state`.

**Lo que no, y por qué no es sólo interfaz.** Tres cosas:

1. **Nuestro grafo tiene UNA puerta humana**, no dos. Hay un único `interrupt()`,
   en `human_review_gate`. El asistente del profesor es el de la S13, con dos
   paradas; el nuestro evolucionó en la S14 hacia el supervisor con enrutado
   dinámico y una sola pausa, que es lo que la pantalla del supervisor ya explota.
   Portar las dos puertas es **cambiar el grafo**, no cambiar la interfaz. Decidir
   si lo queremos es lo primero.
2. **No hay endpoint de progreso.** `GET .../state` devuelve el checkpoint, no una
   actividad por agente. Se puede sondear y derivar el avance de `routing_trail`,
   que es exactamente lo que ya pinta la traza de enrutado, pero es una
   aproximación, no el feed del original.
3. **La propuesta comercial no existe en ninguna capa.** Es una generación nueva y
   pertenece al servicio IA, porque aquí no se estima ni se redacta: esta capa
   valida, llama, persiste y pinta. El PDF sí es de esta capa.

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

- **El BFF no tiene batería de tests.** La del servicio IA tiene 591; ésta, cero.
  Es la deuda más incómoda de la lista, porque el BFF ya tiene lógica real —la
  taxonomía de errores, el mapeo de respuesta a fila, la recuperación del 404 de
  sesión— y ninguna está cubierta.
- **`ruff format` reformatearía 33 ficheros del servicio IA.** El proyecto valida
  con `ruff check`, que pasa limpio; el formateo nunca se aplicó en bloque.
  Hacerlo es un commit ruidoso que conviene aislar.
