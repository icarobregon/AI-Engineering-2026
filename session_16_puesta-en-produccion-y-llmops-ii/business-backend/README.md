# business-backend

El punto de entrada público del sistema de estimación: interfaz y BFF en la misma
pieza. Next.js 16 (App Router) + React 19 + Ant Design 6 + Prisma sobre Postgres.

Sustituye a la aplicación Ruby on Rails de la implementación de referencia. El
reparto de responsabilidades es el mismo: **aquí no se estima nada**. Esta capa
valida entrada, llama al servicio IA, traduce sus errores a algo accionable,
persiste el histórico y pinta el resultado. La lógica de dominio vive en Python.

## Cómo se ejecuta

Con el resto del sistema, desde la raíz de la carpeta de la sesión:

```bash
docker compose up
```

Ver [`../docs/deployment-local.md`](../docs/deployment-local.md) para el arranque
completo y las cinco comprobaciones.

## Estructura

```
src/
├── app/                      # rutas (App Router)
│   ├── page.tsx              # panel
│   ├── estimations/          # S04 — estimación transaccional
│   ├── chat/                 # S05 — conversación con memoria, y modo Actor-Critic-Boss
│   ├── lab/chunking/         # S07 — comparador de estrategias de troceado
│   ├── asistente/            # S09–S12 — asistente RAG de cinco pasos
│   ├── agentes/              # S12 — consola de perfiles y ejecuciones del agente
│   ├── grafo/                # S13–S14 — el flujo multi-agente, de sólo lectura
│   ├── corpus/               # S11 — estado del corpus y ampliaciones del índice
│   ├── supervisor/           # S14 — supervisor, traza de enrutado y bandeja de revisión
│   ├── ajustes/              # modelos en caliente (PUT /api/v1/config/models)
│   └── api/health/           # liveness del propio contenedor
├── lib/
│   ├── estimator/            # FOUNDATION — lo único que habla HTTP con el servicio IA
│   │   ├── client.ts         #   fetch + timeouts + taxonomía de errores
│   │   ├── contracts.ts      #   espejo en zod de los schemas Pydantic
│   │   ├── errors.ts         #   EstimatorError y sus siete casos
│   │   ├── estimations.ts    #   POST /api/v1/estimate
│   │   ├── sessions.ts       #   POST /sessions (+ /{id}/estimate, /{id}/estimate-acb)
│   │   ├── chunking.ts       #   POST /embeddings/compare (consultas y top_k en el mismo cuerpo)
│   │   ├── corpus.ts         #   GET /embeddings/index/stats + POST /embeddings/ingest
│   │   ├── wizard.ts         #   /v1/estimate/stages/{reformulate,structure} + /tasks/hours
│   │   ├── graph-diagram.ts  #   GET /v1/estimate/graph/diagram
│   │   ├── agent.ts          #   POST /v1/estimate/agent/run
│   │   ├── graph.ts          #   el grafo entero: start (202), resume, state,
│   │   │                     #   progress, proposal y /v1/corpus/references
│   │   └── config.ts         #   GET/PUT /api/v1/config/models
│   ├── data/                 # presupuestos de muestra que alimentan el laboratorio
│   ├── format.ts             # euros, horas, porcentajes y dólares, en un solo sitio
│   ├── markdown.ts           # el markdown de la propuesta, a bloques imprimibles
│   ├── proposal-pdf.ts       # la propuesta comercial en PDF (pdfkit, WinAnsi)
│   ├── graph-nodes.ts        # los nodos del grafo, para pintarlo sin pedírselo a Python
│   ├── db.ts                 # cliente Prisma
│   └── supervisor.ts         # mapeo respuesta → fila, compartido por start y resume
└── components/
    ├── app-shell.tsx         # navegación y modelo activo en la cabecera
    ├── collapse-card.tsx     # una Card que se pliega, sin elegir entre las dos cosas
    └── select-field.tsx      # el Select de AntD que sí llega al FormData
```

## Las pantallas

Ocho entradas de navegación —más la portada y la rueda de Ajustes de la
cabecera— sobre las capacidades que el servicio IA fue acumulando de la S04 a la
S15. Casi todas consumen contratos que ya existían; la excepción es el desglose
de referencias del supervisor, que sí obligó a una ruta nueva en Python
(`POST /v1/corpus/references`).

El orden está duplicado a propósito en la portada y en el menú, y en ese orden:
primero las dos que son el producto —Estimación y Supervisor—, después las seis
piezas con las que está hecho. Son dos sitios que hay que mover a la vez, pero un
menú que contradice a la portada se nota más que la duplicación.

**Panel** (`/`). Punto de partida con una tarjeta por capacidad y el enlace a su
pantalla. Dos tarjetas grandes arriba y seis abajo, que es la misma jerarquía del
menú. Existe porque el sistema hace ocho cosas distintas y la navegación sola no
dice cuál sirve para qué.

**Estimación transaccional** (`/estimations`, S04). Un formulario, una llamada,
un resultado persistido. Listado, alta y detalle. Es el camino corto: sin memoria,
sin agentes, con las dos cachés del servicio IA por debajo.

**Conversación** (`/chat`, S05). La memoria de sesión: ventana deslizante, anclas,
resumen acumulado y la metadata que el extractor de segunda pasada va reteniendo
—proyecto, equipo, tecnologías, alcance—. La caja de texto manda sólo lo nuevo;
el histórico lo guarda el servicio IA y aquí sólo vive el identificador, en una
cookie `httpOnly`. Admite adjuntos PDF y DOCX, cuyo texto se aplana y se funde en
la transcripción antes de estimar. Cada turno se acompaña de su telemetría:
latencia, tokens de entrada y salida, coste y cuánto creció la transcripción con
los adjuntos. En el modo Actor-Critic-Boss no aparece, y es honesto que no
aparezca: esa respuesta del servicio IA no trae observación, y lo que se enseña
en su lugar es la traza.

Dentro de esa misma pantalla, el **modo Actor-Critic-Boss**, detrás de un radio
que avisa del coste: de dos a seis llamadas frente a una. La traza enseña vuelta
a vuelta qué dijo el crítico, qué decidió el jefe y cuántas incidencias quedaron
abiertas, y dice explícitamente si el bucle no convergió. Lleva una advertencia
que hace falta para no malinterpretar lo que se lee: cuando el guardarraíl de
salida reescribe el resumen anteponiendo las reservas pendientes, el texto
original del modelo puede haber desaparecido.

**Laboratorio de chunking** (`/lab/chunking`, S07). Trocea los mismos presupuestos
de muestra con varias estrategias a la vez y compara número de chunks,
percentiles de tokens, huérfanos, obesos, coste y tiempo. Con consultas, además
corre el playground de recuperación y enseña los vecinos de cada una con su
coseno. Por defecto sólo vienen marcadas las estrategias gratuitas; las tres que
llaman al modelo —semántica, proposicional y contextual— van señaladas con `$` y,
si se seleccionan, el botón cambia a
«Comparar (gasta dinero)». El aviso de coste no es adorno, y tiene una letra
pequeña que la pantalla declara: lo que se mide es la llamada extra del troceador,
no los embeddings del playground, así que infravalora el gasto real.

**Consola de agentes** (`/agentes`, S12). Perfiles con nombre para el agente
escrito a mano —modelo, esfuerzo de razonamiento y techo de iteraciones— y las
ejecuciones que han gobernado, con su estimación y su traza.

**Aquí un perfil gobierna de verdad, y en la aplicación de referencia no.** Allí
nadie lee `Agents::Profile` fuera de su propio CRUD: el asistente que supuestamente
los usa llama al agente con `config: {}` literal, `Profile#config_payload` —
documentado como «el body que se POSTea al servicio»— no se invoca en ningún sitio
de su `app/`, el botón «Probar» no pasa el id del perfil y la casilla «por defecto»
sólo pinta una etiqueta. Era un formulario decorativo, y la razón de fondo es que
el agente de la S12 no tenía endpoint HTTP. Ahora lo tiene.

Los tres ajustes son **opcionales**, y dejar uno en blanco no es lo mismo que
copiar aquí el valor por defecto del servicio: copiarlo lo congelaría, y el día que
cambie el `.env` este perfil seguiría empujando el valor viejo. Lo que queda en
blanco lo resuelve el servicio en cada ejecución.

Los ajustes se **copian** a la ejecución al lanzarla. El perfil puede cambiar
después, o borrarse, y esa ejecución sigue diciendo con qué corrió; borrar un
perfil no borra su historia.

La traza distingue si el bucle paró solo o si lo cortamos: `natural` significa que
el modelo dejó de pedir herramientas, y cualquier otra cosa lleva un aviso, porque
la estimación es entonces la que el agente pudo cerrar con lo que llevaba.

**Flujo multi-agente** (`/grafo`, S13–S14). Qué agentes hay, qué herramienta puede
tocar cada uno y cómo se pasan el control. De sólo lectura.

**La topología se lee del grafo compilado**, no de un dibujo mantenido a mano —que
es lo que hace la aplicación de referencia, y se desincroniza en cuanto alguien
toca un nodo—. Y no es sólo higiene: desde la S14 las aristas no se declaran,
viven dentro de cada `Command`, y LangGraph las reconstruye resolviendo la
anotación de cada nodo. Si esa anotación dejara de resolver, las aristas
desaparecerían de esta pantalla, que es la señal más temprana de un fallo por lo
demás mudo.

Un nodo que se añada en Python aparece aquí sin tocar la pantalla; si no tiene
glosa escrita, sale con su nombre y sin descripción. Aparecer sin glosa es mucho
mejor que no aparecer.

El diagrama se pinta con componentes, y el Mermaid se sirve copiable en vez de
renderizarlo: la librería pesa 124 MB descomprimidos, demasiado contenedor por un
diagrama de siete nodos.

**Asistente de estimación** (`/asistente`, S09–S12). Cinco pasos con una persona
revisando entre medias: la transcripción se convierte en un brief tipado, el
brief se descompone en módulos y tareas, una persona corrige ese árbol, el corpus
histórico pone horas tarea a tarea, y una persona ajusta horas y tarifas antes de
confirmar. Cada paso se puede volver a ejecutar, y hacerlo avisa de lo que se va
a perder.

**La estructura se genera SIN mirar el corpus, y es lo importante de entender.**
Hacerlo con presupuestos históricos delante empobrecía el árbol, porque el modelo
se ceñía a lo que ya existía; desde la S10 se genera libre y el corpus vuelve a
entrar por tarea en el paso de horas. La pantalla lo dice en un aviso para que
nadie lo «arregle» sin querer.

Las horas salen del consenso ponderado de las tareas históricas más parecidas, y
la pantalla distingue tres casos: analogía firme, consenso flojo —por debajo del
66 % de fiabilidad— y sin analogía, que no recibe número. Ese último caso es el
que convierte la pantalla en útil: dice qué NO sabe el corpus, en vez de inventar
una cifra. En una prueba real sobre una cadena de clínicas dentales, «Service
design & journeys» y «Operations alignment per clinic» salieron sin analogía —no
existen en un corpus de componentes de software— y las puso la persona.

El emparejamiento horas↔tarea va **por posición**, no por nombre: el contrato
devuelve las tareas en el orden en que se enviaron, y el nombre se rompe en cuanto
alguien renombra algo entre pasos.

**Corpus e índice** (`/corpus`, S11). Qué hay indexado en la base vectorial y cómo
ampliarlo. El índice enseña dos cosas independientes: la foto EN VIVO del corpus
—documentos y chunks por colección— y el histórico de ampliaciones, que es nuestro.
Pegas uno o varios presupuestos en JSON y se indexan de uno en uno, con el progreso
en vivo y las fotos del corpus antes y después. Un documento que el servicio ya
tenga se salta en vez de duplicarse.

La columna «Índice» dice si cada colección tiene índice HNSW, y es el dato que no
se adivina mirando las filas: sin él una búsqueda vectorial recorre la tabla
entera. Hoy dice «recorrido secuencial» en presupuestos, con 1603 chunks — no es
un fallo de la pantalla, es el estado real del sistema.

**El trabajo asíncrono vive aquí, no en el servicio IA.** Su ruta de ingesta es
síncrona y acepta un documento por llamada, así que el lote, su progreso y su
resultado son estado de negocio. Es el mismo reparto que hace la aplicación de
referencia, cuyo sondeo también consulta a su propio backend.

**Supervisor y revisión humana** (`/supervisor`, S14–S15). Bandeja de
ejecuciones, lanzamiento de una nueva y detalle con la estimación, las señales
que la acompañan y la decisión humana. La bandeja identifica cada ejecución por
su **título** —el nombre que el sistema le pone al proyecto— y no por un recorte
de la transcripción: esos primeros noventa caracteres eran casi siempre la misma
fórmula de acta, y con dos ejecuciones de la misma reunión salían idénticos.
Cuando todavía no hay título —en curso, o muerta antes de estimar— cae a la
primera línea de la transcripción, que es donde el acta pone el nombre del
proyecto. El detalle
incluye la **traza de enrutado**: la S14 quitó el control de flujo de las aristas
y lo metió en `Command`, así que el camino sólo existe a posteriori, en
`routing_trail`. La tabla lo recorre paso a paso y, sobre todo, atribuye cada
salto —regla, modelo o límite—, porque el supervisor es híbrido: cuatro
precondiciones son `if`s de Python y al modelo se le hace exactamente una
pregunta. Un run que no distingue quién decidió qué no se puede auditar.

Desde la S15 el arranque **no bloquea**: la acción llama a
`POST /v1/estimate/graph/start`, que contesta 202, y lleva a la pantalla de la
ejecución mientras el grafo corre por detrás. Antes la Server Action se quedaba
esperando los minutos que durase el sistema multiagente, lo que convertía el
timeout de este cliente en un techo para la estimación y no dejaba sitio para
enseñar nada mientras tanto. Ahora la pantalla **sondea** y pinta una línea
temporal por nodo, con duraciones reales: salen del *historial* del checkpointer,
que sella cada superstep, porque el estado del grafo no lleva ni una fecha. Son
**finalizaciones**, no despachos —`routing_trail` escribe su entrada antes de que
el agente corra, así que un feed montado sobre ella enseña al agente como
terminado todo el rato que está trabajando—.

**La decisión es por componente, no por total.** El revisor fija las horas de
cada línea y el total sale de la suma, que se recalcula al teclear. Un total
editable por separado es un número puesto a ojo: no cuadra con sus partes, y eso
es justo lo que nadie puede auditar después. Lo que propuso el sistema no se
pierde —se sella el valor original de las líneas que de verdad cambiaron, y el
total siempre—, y se sella igual al aprobar y al rechazar, porque un rechazo con
las horas corregidas dice por qué se rechaza mucho mejor que un rechazo a secas.
Sólo hay dos acciones, **aprobar** y **rechazar**, y las dos exigen revisor y
motivo: aprobar sin firma es exactamente el caso que deja una estimación
aprobada sin nadie detrás.

**De dónde sale cada número.** Cada componente con precedente abre un **Drawer**
con las referencias históricas que lo respaldan. Un Drawer y no una modal porque
no es una referencia, son cinco, y cada una trae su desglose. Dentro, la
jerarquía va de «cuánto» a «por qué me lo creo»: las horas y la proximidad en la
cabecera; después el contexto que decide si la referencia vale —proyecto,
sector, año, tecnología—; y debajo el desglose por tareas, cuya suma **es** el
número que el estimador comparó. Una referencia es un módulo de un presupuesto
histórico, no una tarea suelta: `TASK-2022-0032/Authentication & Access` son tres
tareas de 16, 27 y 36 h que suman las 79 h del análogo. Las referencias que el
corpus ya no tiene se enseñan, no se esconden: el corpus se reindexa, y «parte
del respaldo ha dejado de existir» es justo lo que hay que saber antes de
aprobar.

Las referencias se guardan en la fila (`budget_matches`) y no sólo en el
checkpoint. Viajaban al BFF dentro de `review_payload`, que existe únicamente si
la ejecución se paró ante una persona: tres de cada cuatro estimaciones validadas
no lo tienen, así que su trazabilidad dependía de que el servicio IA contestara.

Y cuando la estimación está cerrada, la pantalla ofrece **redactar la propuesta
comercial** (`POST /v1/estimate/graph/{id}/proposal`) y **descargarla en PDF**
(`/supervisor/<id>/proposal.pdf`). Redactar no re-ejecuta el grafo: las horas son
las que hay, así que volver a redactar cuesta una generación y no una estimación
entera.

**Ajustes** (`/ajustes`). Los siete modelos que el servicio IA deja cambiar en
caliente, cada uno con qué hace y qué se rompe si se toca, más su estado (por
defecto u override) y el valor activo. El de embeddings aparece en sólo lectura y
con el porqué: cambiarlo invalidaría todos los vectores ya almacenados. El
catálogo sólo ofrece modelos cuyo proveedor tiene clave configurada, y cada uno
lleva al lado lo que cuesta un millón de tokens, entrada / salida: el catálogo va
de 0,05 a 600 US$ por millón —`o1-pro`, 150 de entrada y 600 de salida— y varios
de estos ajustes corren en cada turno, así que un
desplegable ciego al precio invita a poner el modelo de 150 en el resumidor. La
divisa se escribe siempre, y no es un detalle: la aplicación habla de dinero en
dos monedas —los presupuestos en euros, lo que cuesta pedirlos en dólares— y en
la pantalla de conversación las dos aparecen bajo la etiqueta «Coste». Al pie, la pantalla dice cuándo se generó el catálogo y a partir de
qué proveedores, porque se cura a mano y nada lo mantiene fresco solo.

## Decisiones de diseño

**Una sola puerta al servicio IA.** Todo lo que cruza la frontera pasa por
`lib/estimator/`, y esos módulos empiezan con `import "server-only"`. Importarlos
desde un componente de cliente es un error de compilación, así que el secreto de
servicio no puede acabar en un bundle del navegador ni por descuido.

**Y el token va por defecto, no por excepción.** `callEstimator` manda la cabecera
`X-API-Key` salvo que la llamada pida `token: "none"`, y hoy la única que lo pide
es `/health`. Es al revés de como estaba: olvidarse del token ahora es imposible
por omisión, mientras que antes bastaba con no acordarse de ponerlo.

**El sondeo es una Server Action, no un GET.** Escribe en la base de datos —
consolida la fila cuando el run termina— y un GET que escribe es justo la forma
que no convenía copiar de la aplicación de referencia, donde el endpoint de
progreso persiste el estado como efecto colateral y cualquier prefetch muta una
fila. Lo demás que ese poller no hace y éste sí: **espera creciente** (2 s → 10 s,
el suyo va a 1,5 s fijos para siempre), **se rinde** tras cinco errores seguidos
en lugar de machacar un servicio que ya contestó mal cinco veces, y **detecta el
atasco** — si el checkpoint no se mueve en un cuarto de hora, el run no está
lento, está muerto de una forma que nadie registró.

**Un parser de markdown, dos pintores.** La propuesta se guarda en markdown y se
lee en dos sitios: la pantalla y el PDF. La aplicación de referencia la enseña
cruda en la web y la interpreta en el PDF con tres expresiones regulares escritas
a mano; son dos lecturas del mismo texto y divergen en cuanto el modelo escribe
algo que una no contempla. Aquí `lib/markdown.ts` produce los bloques una vez y
cada pintor los recorre.

**Contratos parseados, no casteados.** El servicio IA devuelve el estimate como
un `dict` sin tipar. Validarlo con zod al leerlo convierte un cambio silencioso
de contrato en un mensaje claro en pantalla, en vez de una página en blanco tres
componentes más abajo.

**Errores como taxonomía, no como códigos.** `EstimatorError` distingue siete
casos (guardrail, petición inválida, no autorizado, no encontrado, rate limit, no
disponible, error del servidor) porque cada uno pide una reacción distinta de la
interfaz. Un 400 de guardrail se le enseña al usuario tal cual; un 503 no.

**El 404 de sesión se recupera, no se enseña.** El servicio IA guarda las
conversaciones en memoria: un reinicio las pierde y nuestra cookie sigue apuntando
a una que ya no existe. El chat abre sesión nueva, reintenta el turno y lo dice
con un aviso, en vez de mostrar un error sobre el que nadie puede actuar.

**Un único mapeo de respuesta a fila** (`lib/supervisor.ts`), usado por el
arranque y por la reanudación, para que la forma persistida no pueda desviarse
del contrato. Los `?? current` no son ruido defensivo: las ramas idempotentes del
router de Python contestan sin `review_payload`, así que un mapeo que
sobrescribiera a ciegas borraría el informe del revisor en cuanto alguien
recargara la página.

**La decisión humana se guarda aquí.** Quién aprobó qué, cuándo y por qué es
historia de negocio. El servicio IA sabe pausar y reanudar; la autorización y el
registro son de esta capa.

**La traza del supervisor es diagnóstico, no carga.** Se lee en vivo del servicio
IA al abrir el detalle. Si no contesta, la página sigue pintando la estimación y
la decisión humana; sólo pierde el rastro.

**Esquema de Postgres aparte.** Misma base de datos que el servicio IA,
`?schema=business` en la cadena de conexión: un datastore que operar y cero
posibilidad de colisión de tablas.

## Dos peajes del stack, por si ahorran una tarde

**Los componentes de AntD no llegan al `FormData` de una Server Action.** `Select`
y `Checkbox.Group` renderizan un `div`, no un control nativo, así que un `name`
encima no se envía. El puente es un input oculto que React mantiene sincronizado
(`components/select-field.tsx`). Con `Upload` el mismo problema es una vuelta más
difícil, porque un oculto de texto no puede llevar un `File`: el oculto es un
`<input type="file">` cuyo `files` se reconstruye desde la lista con un
`DataTransfer` (`app/chat/attachments-field.tsx`) —la única forma de escribir un `FileList` a mano—, y la acción
sigue leyendo `formData.getAll("attachments")` sin enterarse de nada. Además todo
`Select` con estado del servidor necesita una `key` que incluya el valor efectivo,
o el componente se queda con el que tenía antes de guardar.

**Un Server Component no puede leer propiedades de un componente cliente.**
`Typography.Title` es `undefined` ahí: el acceso a la propiedad se resuelve sobre
una referencia de cliente, y el error que sale (`Element type is invalid… got:
undefined`) no señala el sitio. Por eso cada ruta se parte en dos: un `page.tsx`
de servidor que sólo consulta datos y un componente cliente que pinta.

**El PDF se compone en el BFF, no en el servicio IA.** Aquí no se estima ni se
redacta: se valida, se llama, se persiste y se pinta, y renderizar un documento es
pintar. El texto llega ya escrito.

## Cómo se prueba

```bash
pnpm test          # una pasada — 117 tests en 10 ficheros
pnpm test:watch    # en vigilancia
pnpm typecheck     # tsc --noEmit
pnpm lint          # ESLint 9, config plana
pnpm format:check  # Prettier, sin escribir
```

Vitest, en Node, sin navegador y sin red. Lo que se prueba es la lógica que esta
capa tiene de verdad, no que Ant Design pinte: la taxonomía de errores, el cliente
HTTP —que el token viaje por defecto y que cada código caiga en su clase—, el
mapeo de respuesta a fila del supervisor, los parseadores de formulario, los
espejos zod, el saneado y el trazado del PDF, y las precedencias con las que la
confianza y las referencias llegan a la fila.

**El linter existe desde la S15, y no existía antes.** El script `lint` era el
`next lint` que dejó `create-next-app`: Next 16 lo eliminó, y ESLint ni siquiera
estaba instalado, así que este proyecto nunca pasó un linter. Ahora hay
`eslint.config.mjs` en formato plano —`eslint-config-next` lo exporta nativo desde
la 16, sin `FlatCompat`— y ESLint fijado en la 9, que es hasta donde llegan los
peers de sus plugins.

**Prettier también se configuró aquí, y su anchura está medida, no elegida.**
Formateando los ficheros escritos a mano con cada `printWidth` y contando cuántas
líneas se moverían, el mínimo está en 100 y sube a los dos lados: 2229 líneas a
80, 1164 a 90, 575 a 100, 742 a 105. El resto se queda en los valores por defecto
de Prettier 3, también por medición.

Dos detalles del montaje que no son obvios. `server-only` lanza a propósito al
importarse fuera de un React Server Component, así que en los tests se sustituye
por un módulo vacío: la protección sigue intacta donde importa, que es el build.
Y los parseadores viven en módulos propios (`corpus/parse.ts`, `asistente/tree.ts`)
porque un módulo `"use server"` sólo puede exportar funciones async, así que desde
`actions.ts` no se pueden ni exportar ni probar.

Las devDependencies no llegan a la imagen: el runtime se construye desde la salida
`standalone` de Next.

**pdfkit y las fuentes.** Las fuentes estándar de PDF codifican en WinAnsi
(CP1252), que cubre entero el castellano y también la tipografía que escribe un
modelo: comillas curvas, raya, semirraya, puntos suspensivos, viñeta y el euro.
No hay que incrustar ninguna fuente. Lo que no cubre son flechas, símbolos
matemáticos y emoji — y ahí está la trampa: **pdfkit no lanza ninguna excepción
con ellos, escribe un glifo equivocado**, que es un fallo silencioso dentro de un
documento que se manda a un cliente. Por eso `sanearParaPdf` traduce lo traducible
y descarta el resto.

Dos cosas más sobre pdfkit y el build `standalone`. Lee sus métricas
(`js/data/*.afm`) del disco en tiempo de ejecución, así que va en
`serverExternalPackages` —empaquetarlo reescribiría esas lecturas contra rutas que
no existen— y además hay que nombrar los `.afm` en `outputFileTracingIncludes`,
porque el trazador sigue los `import`, no los `readFileSync`. Comprobado listando
el árbol de `.next/standalone` después de construir. Y `doc.text(texto, x, y)`
**deja la X del cursor donde escribió**: tras pintar una columna de cifras a la
derecha hay que devolverla al margen, o el resto del documento se dibuja en una
franja estrecha contra el borde.

## Limitaciones conocidas

- **Sin usuarios ni permisos.** Igual que la implementación de referencia. Toda la
  autorización que existe es el token entre servicios. Añadir login es alcance
  nuevo, no paridad.
- **La cabecera es `X-API-Key`, no `X-Service-Token`.** Mismo mecanismo, otro
  nombre; renombrarla obliga a tocar el servicio IA, sus tests y su documentación.
- **La segunda puerta humana no existe, y es una decisión de producto.** La
  implementación de referencia pausa dos veces —antes y después de estimar—.
  Nuestros tres disparadores (confianza, banda histórica, sin precedente) se
  calculan *después* de estimar; antes no existe ninguno, así que habría que
  inventar el criterio. Y «pausar siempre» destruye la señal: un revisor al que se
  le manda todo empieza a aprobar en bloque.
- **Una ejecución del agente no sobrevive a un reinicio.** El bucle corre en el
  proceso de Node; si se reinicia a mitad, la fila queda sin quien la mueva. El
  detalle lo detecta y lo dice, pero no lo reanuda — el bucle del agente no es
  reanudable.
- **El paso de estructura es una petición de minutos sostenida por una Server
  Action.** `gpt-5` con razonamiento alto tarda tres minutos largos; medido, 172 s
  y 0,13 $. La app de referencia tiene la misma forma —síncrona, sin sondeo— y por
  eso se portó así, pero convertirlo en trabajo en segundo plano con sondeo, como
  el del corpus, es lo que pide una pantalla que vaya a usarse de verdad.
- **Una ampliación del corpus no sobrevive a un reinicio.** El lote se procesa en
  el proceso de Node; si se reinicia a mitad, la fila queda sin quien la mueva. El
  detalle lo detecta y lo dice —«sin señales»— en vez de sondear para siempre, pero
  no lo reanuda.
- **El laboratorio no guarda los runs.** El original tiene histórico justamente
  para no volver a pagar las estrategias caras: las cuatro estrategias de pago
  cuestan dinero y tardan minutos, y aquí se ejecutan, se pintan y al recargar se
  pierden. Es lo único del port que queda sin hacer. Costaría una tabla en el
  esquema `business` con la petición, el payload íntegro y la duración, más dos
  rutas; cero cambios en Python.
- **Desarrollo fuera de Docker.** Con la frontera cerrada, `localhost:8000` y
  `localhost:5433` ya no existen; iterar sin contenedores exige publicarlos
  temporalmente.
