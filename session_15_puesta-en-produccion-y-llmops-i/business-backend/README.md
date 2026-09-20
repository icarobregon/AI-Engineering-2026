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
│   │   ├── graph.ts          #   POST /v1/estimate/graph (+ resume)
│   │   └── config.ts         #   GET/PUT /api/v1/config/models
│   ├── data/                 # presupuestos de muestra que alimentan el laboratorio
│   ├── format.ts             # euros, horas, porcentajes y dólares, en un solo sitio
│   ├── db.ts                 # cliente Prisma
│   └── supervisor.ts         # mapeo respuesta → fila, compartido por start y resume
└── components/
    ├── app-shell.tsx         # navegación y modelo activo en la cabecera
    └── select-field.tsx      # el Select de AntD que sí llega al FormData
```

## Las pantallas

Cinco entradas de navegación sobre las capacidades que el servicio IA fue
acumulando de la S04 a la S14. Ninguna añade un endpoint nuevo en Python: todas
consumen contratos que ya existían.

**Panel** (`/`). Punto de partida con una tarjeta por capacidad y el enlace a su
pantalla. Existe porque el sistema hace cinco cosas distintas y la navegación sola
no dice cuál sirve para qué.

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

**Supervisor y revisión humana** (`/supervisor`, S14). Bandeja de ejecuciones,
lanzamiento de una nueva y detalle con la estimación, las señales que dispararon
la pausa y el formulario de decisión (aprobar, ajustar, rechazar). El detalle
incluye la **traza de enrutado**: la S14 quitó el control de flujo de las aristas
y lo metió en `Command`, así que el camino sólo existe a posteriori, en
`routing_trail`. La tabla lo recorre paso a paso y, sobre todo, atribuye cada
salto —regla, modelo o límite—, porque el supervisor es híbrido: cuatro
precondiciones son `if`s de Python y al modelo se le hace exactamente una
pregunta. Un run que no distingue quién decidió qué no se puede auditar.

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

## Limitaciones conocidas

- **Sin usuarios ni permisos.** Igual que la implementación de referencia. Toda la
  autorización que existe es el token entre servicios. Añadir login es alcance
  nuevo, no paridad.
- **La cabecera es `X-API-Key`, no `X-Service-Token`.** Mismo mecanismo, otro
  nombre; renombrarla obliga a tocar el servicio IA, sus tests y su documentación.
- **Sin tests.** El BFF no tiene batería propia todavía.
- **Pantallas no portadas:** asistente RAG de cinco pasos (S09–S12), diagrama del
  grafo (S13), consola de agentes (S12) y el asistente de grafo con propuesta y
  PDF (S13). El desglose pieza a pieza está en
  [`../docs/alcance-pendiente.md`](../docs/alcance-pendiente.md).
- **Una ampliación del corpus no sobrevive a un reinicio.** El lote se procesa en
  el proceso de Node; si se reinicia a mitad, la fila queda sin quien la mueva. El
  detalle lo detecta y lo dice —«sin señales»— en vez de sondear para siempre, pero
  no lo reanuda.
- **El laboratorio no guarda los runs.** El original tiene histórico justamente
  para no volver a pagar las estrategias caras.
- **Desarrollo fuera de Docker.** Con la frontera cerrada, `localhost:8000` y
  `localhost:5433` ya no existen; iterar sin contenedores exige publicarlos
  temporalmente.
