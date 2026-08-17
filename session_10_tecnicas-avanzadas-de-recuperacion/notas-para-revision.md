# Notas para la revisión — Sesión 10

Bitácora del ejercicio: qué problemas aparecieron, qué errores de definición encontramos, qué
decidimos y por qué, y a qué conclusiones nos llevaron los números en cada etapa. Se acompaña del PR
y de la tabla comparativa A/B/C/D.

---

## 1. Problemas, errores de definición y decisiones

### 1.1 Errores en el enunciado del ejercicio

- **La rama `session_10` contiene ya la solución completa del ejercicio, no el punto de partida.**
  Diffeándola contra `session_09_live` aparecen 7 ficheros nuevos (`retrieval/fusion.py`,
  `retrieval/pipeline.py`, `alembic/versions/0003_session10_fts.py`, `evals/golden_retrieval.json`,
  `scripts/eval_retrieval_s10.py` y 2 tests) y 17 ficheros con el cableado hecho. Partir de ahí sería
  entregar código ajeno. **El punto de partida real es `session_09_live`**, verificado limpio: sin
  paquete `retrieval/`, con solo las migraciones `0001` y `0002`, y sin rama léxica en el store.
- **`session_09_live` no incluye el wrapper de cross-encoder que el enunciado da por construido.**
  Hubo que injertar desde `session_10` únicamente `retrieval/{__init__,reranker,verify_reranker}.py`,
  el setting `RERANKER_MODEL` y la dependencia `sentence-transformers`. Nada más.
- **El comando del gate de verificación usa un servicio que no existe:** dice
  `docker compose exec ai-service …` y el servicio se llama `estimator`. Curiosamente, el propio
  `verify_reranker.py` documenta el nombre correcto en su docstring.
- **El enunciado afirma que los presupuestos están en español, y están en inglés.**
  `data/budgets_sample.json` y `data/task_corpus.json` traen nombres y descripciones de componentes
  en inglés ("Faceted search", "Order lifecycle", "Product catalog model"); solo los nombres de
  cliente y las transcripciones semilla están en español. La instrucción de usar la configuración
  `'spanish'` para el `tsvector` habría degradado la rama léxica justo en la comparación a medir.
- **El enunciado recomienda `websearch_to_tsquery` sin advertir que une los términos con AND.** Es el
  hallazgo más grave del ejercicio y está detallado en el punto 1.4.
- **La tabla de parámetros del enunciado fija el conjunto amplio en top-50, pero el
  `distance_threshold=0,6` heredado de la Sesión 09 limita antes:** la rama vectorial devuelve 12–27
  candidatos, nunca los 50 configurados. El "conjunto amplio" no es tan amplio como dice la
  configuración.

### 1.2 Problemas del entorno y del código de partida

- **El comando de test documentado en `CLAUDE.md` no funcionaba, y fallaba de las dos formas más
  desorientantes posibles.** La imagen solo copia `app/`, así que (a) pytest corría sin
  configuración, `asyncio_mode` caía a `strict` y 10 tests async fallaban con _"async def functions
  are not natively supported"_ — indistinguible de código roto; y (b) `tests/test_evals_*.py` y
  `tests/test_stress_*.py` importan el paquete `evals`, que tampoco está en la imagen, y los 4
  módulos petaban **en colección**, abortando la ejecución completa. Se montan ambos.
  Antes: 4 errores de colección. Después: 309 passed con el comando documentado.
- **El `Dockerfile` hace `uv sync` sin `--frozen`,** así que resolvía dentro del contenedor y el
  `uv.lock` del repositorio quedaba desincronizado con `pyproject.toml`. Resuelto en el host.
- **El volumen de caché de HuggingFace nace propiedad de root y el contenedor corre como el usuario
  no-root `appuser`,** así que el primer rerank moría con `PermissionError` sobre el directorio de
  caché. La solución no es un chown en el entrypoint sino **crear el directorio en el Dockerfile con
  el propietario correcto**, porque Docker inicializa un volumen nuevo desde el directorio de la
  imagen, propiedad incluida.
- **Sin volumen para los pesos, cada recreación del contenedor re-descarga 450 MB.** Añadido
  `hf_cache` con `HF_HOME`.
- **`RetrievedChunk` no exponía `budget_id`,** necesario para puntuar relevancia por presupuesto
  padre. Añadido como campo opcional y aditivo.
- **`estimator-web` (el frontend Rails de referencia del profesor) queda fuera del alcance de este
  repositorio.** Eliminado junto con sus 24 referencias en `docker-compose.yml`, `CLAUDE.md`,
  `arquitectura-actual.md`, `estimator/{ARCHITECTURE,README}.md`, `estimator/docker-compose.yml`,
  `estimator/.env.example` y 3 docstrings de código.

### 1.3 Bugs propios, detectados y corregidos

- **Sombreado de nombre en el router de etapas, y los tests lo ocultaban.** El handler de la etapa 2
  en `estimate_stages.py` se llama `retrieve`, igual que la función importada del pipeline: la
  sombreaba, así que `await retrieve(...)` dentro del handler habría resuelto al **propio handler**.
  La suite estaba en verde porque todos los tests del módulo parchean `stages.retrieve` con un fake,
  es decir, reemplazaban precisamente el nombre colisionado — **el mock tapaba el bug que el mock
  causaba**. Lo detectó `ruff check` (F811), no los 342 tests. Import aliasado a `run_retrieval`, y
  añadido un test que ejerce el camino handler → pipeline → store sin parchear la costura.
- **Una métrica propia que invertía el significado que decía medir.** Habíamos añadido `precision@5`
  sobre presupuestos deduplicados, y premia la duplicación porque el denominador se encoge con ella:
  A devolvió `[005, 005, 017, 008, 017]` → distintos `[005, 017, 008]` → 0,67, y B devolvió
  `[005, 005, 017, 017, 005]` → distintos `[005, 017]` → 1,00. B puntuaba mejor **solo por traer
  menos presupuestos distintos**. Descartada y sustituida por el recuento de presupuestos distintos,
  que muestra el mismo efecto sin fingir ser una precisión.
- **Tres expectativas propias erróneas en las verificaciones ad-hoc**, corregidas en lugar de
  descartadas: la semántica AND de `websearch_to_tsquery`, el seq scan sobre una tabla de 5 filas
  (que es la decisión correcta del planificador, no un defecto), y un `top_k=2` sobre una consulta
  que solo casaba con un documento.

### 1.4 El hallazgo que habría invalidado toda la medición

- **`websearch_to_tsquery` y `plainto_tsquery` unen los términos con AND.** Con una consulta real del
  dominio, `websearch_to_tsquery('english', 'E-commerce platform with product catalog, shopping cart
checkout and an admin panel')` produce
  `'e-commerc' <-> 'e' <-> 'commerc' & 'platform' & 'product' & 'catalog' & 'shop' & 'cart' &
'checkout' & 'admin' & 'panel'` — nueve términos **obligatorios**.
- Como la entrada real del sistema son descripciones largas de proyecto y transcripciones, la rama
  léxica habría devuelto lista vacía en casi toda consulta, **la híbrida habría degradado en silencio
  a vectorial**, y la tabla A/B/C/D habría "demostrado" que la búsqueda híbrida no aporta nada —
  cuando en realidad nunca llegó a ejecutarse. Sin error, sin excepción, sin log raro.
- **Solución:** `_or_tsquery()` cambia el operador sobre el tsquery ya normalizado por
  `plainto_tsquery`, que hace el tokenizado, el stemming y el filtrado de stopwords con la misma
  configuración que la columna indexada y nunca lanza excepción con entrada malformada. Verificado
  que el cambio es seguro: ningún lexema contiene `&` (`R&D` lexa a `'r' & 'd'`). Con OR, `ts_rank`
  hace el trabajo de discriminar, que es la conducta bag-of-words que esta rama debe tener. Hay un
  test de regresión sobre el SQL compilado, porque ningún store falso puede detectarlo.

### 1.5 Decisiones de diseño

- **Configuración de text search `'english'`,** no `'spanish'`, por el idioma real del corpus, con la
  discrepancia documentada en la migración y en el README. El literal vive en `TEXT_SEARCH_CONFIG` y
  **la migración guarda su propia copia a propósito**: una migración es un registro de lo que se
  aplicó a la base de datos, y si importara la constante, editarla mañana reescribiría el pasado en
  silencio. Un test vigila que las dos copias no divergan.
- **La columna generada se declara también en el ORM.** No es decorativo: `alembic/env.py` usa
  `target_metadata = Base.metadata`, así que sin declararla el próximo `--autogenerate` habría
  propuesto **borrar la columna**. Verificado con `alembic check`.
- **`distance` pasa a ser `float | None` en lugar de usar un centinela.** Un chunk que solo encuentra
  la rama léxica nunca entró en el ranking vectorial, así que no tiene distancia coseno. Escribir el
  centinela habitual (1,0 = "máximamente disímil") habría metido un número fabricado en el prompt del
  generador, justo al lado de un documento que la rama léxica puso primero. `None` significa "no
  puntuado", no "puntuado mal"; el `context_assembler` omite el atributo cuando falta.
- **Los filtros estructurales se extraen a un helper compartido por las dos ramas.** Si aplicaran
  filtros distintos, la fusión estaría combinando dos rankings de poblaciones distintas, y el
  resultado sería incorrecto de una forma que ningún test de cada rama por separado detectaría.
- **La inferencia del cross-encoder se despacha con `asyncio.to_thread`.** La búsqueda vectorial es
  asíncrona (I/O contra la BD) y el cross-encoder no (cómputo local): unos cientos de milisegundos de
  inferencia en el event loop bloquean **todas** las demás peticiones mientras duran. Además del test
  que comprueba el hilo, hay una prueba de comportamiento: un ticker concurrente debe completar sus 20
  ticks mientras un rerank bloqueante de 200 ms está en vuelo.
- **RRF recibe una lista de rankings, no exactamente dos.** No sabe ni le importa cuántas fuentes
  fusiona, y esa generalidad la convierte en la pieza reutilizable para la expansión de consultas y el
  routing multi-índice de la sesión en vivo.
- **Un `search_mode` desconocido lanza `ValueError`.** Una errata en configuración (`"hybird"`) debe
  fallar a gritos, no caer en silencio en una de las dos ramas.
- **El arnés de medición vive en `scripts/`, no en las capas de la aplicación.** Un arnés artesanal es
  una herramienta para **una** decisión, no infraestructura: no necesita endpoint, ni abstracción para
  casos futuros, ni tests propios. Convertirlo prematuramente en un "módulo de evaluación" es el
  exceso de ingeniería clásico que después nadie mantiene.
- **La latencia mide solo la recuperación, no el embebido de la consulta.** El embedding es la misma
  llamada de red en las cuatro configuraciones, así que incluirlo sumaría la misma constante a todas
  las filas importando jitter de red a la comparación. Se reporta aparte: 159 ms de mediana.
- **Golden set:** 5 consultas siguiendo la receta del enunciado (dos frecuentes y directas, una con
  términos exactos, una difícil de dominios colindantes, una larga y desordenada tipo transcripción),
  **criterio de anotación escrito antes de anotar**, anotación **binaria**, anotación **por
  presupuesto padre** (que es la pregunta que un humano sabe responder), y cada consulta con su trampa
  y sus **casos dudosos marcados explícitamente** para que la revisión sea posible.
- **Q5 repite deliberadamente la intención de Q1 en otra forma.** El par limpia/desordenada aísla el
  efecto de la formulación, que es el eje donde estas técnicas deben brillar y donde un golden set de
  solo consultas limpias daría un veredicto injustamente tibio.
- **Las consultas del golden set están en inglés,** porque es lo que llega al retriever: el pipeline
  embebe `compose_search_text()`, que emite inglés canónico, no la transcripción en español. Medir con
  consultas en español mediría un sistema que no existe.
- **La decisión final está aplicada en el código, no solo escrita:** `RETRIEVAL_SEARCH_MODE=hybrid` y
  `RERANKER_ENABLED=false` por defecto en `config.py` y `.env.example`. El README afirmaba una
  decisión que el código no implementaba; ahora coinciden.
- **Los avisos de lint preexistentes no se han tocado** (`RUF100` por un `noqa: BLE001`, `I001` en
  `dependencies.py`, `EXE001` y `noqa: E402` en `scripts/`): son patrones que el código de partida ya
  tenía, y "arreglarlos" ensuciaría el diff con cambios que no trazan a este ejercicio.

---

## 2. Conclusiones a partir de los números, por etapa

### Paso 1 — Columna `tsvector` e índice GIN

- **El analizador conserva los identificadores exactos, que es su razón de existir.**
  `'Stripe payment gateway integration with subscriptions and billing webhooks'` produce
  `'bill':8 'gateway':3 'integr':4 'payment':2 'stripe':1 'subscript':6 'webhook':9`: stemming
  aplicado, stopwords (`with`, `and`) fuera, y **`stripe` intacto**. Son justo los términos con menos
  masa semántica general y más valor discriminante — los que peor sobreviven a la compresión del
  embedding.
- **El punto ciego complementario también se mide:** `websearch_to_tsquery('english', 'recurring
charges')` no recupera el presupuesto de Stripe, y viceversa. Cada rama falla donde la otra acierta,
  que es el argumento entero de la búsqueda híbrida.
- **El índice GIN es usable, y el seq scan no es un defecto.** Con 60 filas el `EXPLAIN` normal da
  `Seq Scan`, que es la decisión **correcta** del planificador; forzando `enable_seqscan = off`
  aparece `Bitmap Index Scan on ix_chunks_content_tsv`. Conclusión operativa: en este corpus el índice
  no se va a usar, y eso está bien.
- **La columna generada se comporta como se prometió:** se recalcula en `UPDATE` sin trigger, y
  escribirla se rechaza con `cannot insert a non-DEFAULT value into a generated column`. No puede
  desincronizarse del texto que indexa.

### Paso 2 — Rama léxica y fusión RRF

- **La semántica AND daba cero resultados en la consulta realista; con OR pasa a resultados
  ordenados.** Ese cambio de 0 a N es la diferencia entre medir la búsqueda híbrida y creer haberla
  medido.
- **La rama léxica aporta volumen, pero buena parte es ruido** — corregido tras la revisión. Los
  recuentos reales son 17–36 hits sobre 60 chunks y un pool fusionado de 21–44 (las cifras 33–41 y
  44–48 que aparecían aquí se tomaron con otro estado de la base de datos). Y ese volumen **no es
  señal**: `client`, `main`, `sector` y `project` están en 60 de 60 chunks porque los inyecta la
  plantilla `[Project: …] [Client sector: …]`, así que una consulta con cualquiera de esas palabras
  recupera el corpus entero. En Q4 y Q5 el pool iguala a la rama léxica, o sea que la vectorial es un
  subconjunto estricto de ella. Lo que salva a la híbrida es que **RRF fusiona por posición**: los
  aciertos de plantilla quedan abajo y la fusión extrae la parte útil.
- **RRF premia el consenso con las cifras del paper:** un presupuesto 2.º en semántica y 5.º en léxica
  suma `1/61 + 1/64 ≈ 0,0320`, y uno 1.º en semántica pero ausente en léxica `1/60 ≈ 0,0167`. El
  consenso gana por un factor de casi 2, que es el rescate exacto que necesita el caso de la
  coincidencia literal.
- **La constante `k` hace lo que se dice que hace,** comprobado en test: con `k=1` domina el primer
  puesto único, con `k=60` la curva se aplana y el documento de consenso adelanta.

### Paso 3 — Integración del reranker

- **El gate del cross-encoder separa con holgura:** documento relevante 2,9526 frente a irrelevante
  −9,0109. Doce puntos de separación en un par de sanidad, así que el modelo multilingüe funciona
  sobre este corpus.
- **La carga del modelo cuesta 20,6 s y la inferencia 204 ms para 2 pares.** De ahí dos consecuencias
  arquitectónicas: singleton por worker (hacerlo por consulta sería un desastre) y **la primera
  petición de un proceso nuevo paga la carga**, que es exactamente por qué la latencia hay que medirla
  en caliente descartando la pasada en frío.
- **Primera medición end-to-end de las cuatro configuraciones:** A 66,5 / B 17,1 / C 816,7 /
  D 2.845,7 ms. Los órdenes de resultados difieren entre configuraciones, así que cada técnica actúa
  de verdad y no es un adorno.
- **La híbrida no solo paga su propia latencia: encarece la etapa siguiente.** D rerankea 48 pares
  donde C rerankea 27, porque la fusión ensancha el pool. El coste de una técnica incluye lo que le
  hace pagar a las que vienen detrás.
- **La rama léxica sale más rápida que la vectorial en este corpus** (B 17 ms frente a A 66 ms),
  porque la léxica va por índice GIN mientras la vectorial paga scan secuencial sobre los 60 chunks.
  Es un artefacto del tamaño del corpus y de que no hay índice HNSW, no una propiedad general.

### Pasos 4 y 5 — Medición y decisión

- **`recall@5` sale 1,00 en las cuatro configuraciones.** Es el número más importante de todo el
  ejercicio: todos los presupuestos relevantes ya entran en el top-5 sin hacer nada. La señal del
  artículo para saber que el reranking es la herramienta correcta es _"los relevantes están entre los
  candidatos, pero no arriba"_, y aquí ya están arriba. **El cuello de botella no está donde estas
  técnicas ayudan.**
- **`precision@5`: A 0,88 · B 0,92 · C 0,96 · D 0,92.** Partimos de 0,88, no del 0,48 del escenario
  que motiva la sesión, así que apenas hay margen que ganar.
- **Latencias limpias: A 2 · B 2 · C 327 · D 2.383 ms.** El reranking es prácticamente el 100 % de la
  latencia del pipeline en este corpus, porque la búsqueda cuesta 2 ms.
- **B es gratis: +0,04 de precisión y +0 ms medibles.** Las dos ramas corren concurrentemente y la
  léxica se sirve por índice GIN sobre el mismo PostgreSQL — ni un almacén nuevo, ni sincronización
  entre almacenes, ni un modelo más que operar. **No hay tabla de decisión que justifique rechazar una
  mejora de coste cero.**
- **El +0,08 de C son dos chunks en dos consultas, y una de las dos es la trampa que construimos a
  propósito.** Es el retrato exacto de la _zona traicionera_ del cuadrante: ganancia pequeña con coste
  pequeño, donde el coste real nunca es solo la latencia — es el modelo extra que operar, los 450 MB
  de pesos, los ~6 GB de imagen (la imagen pasó de 1,4 a 6,6 GB al añadir `sentence-transformers`), la
  dependencia que actualizar y el modo de fallo nuevo que diagnosticar a las tres de la mañana.
- **Y conviene decir qué NO es el argumento contra el reranking: la latencia.** En este producto la
  generación posterior tarda varios segundos, así que los 325 ms de C serían menos del 5 % del total
  percibido. Serían asumibles de sobra. Lo que falla es que no hay problema que resolver.
- **D se descarta con datos, no con opinión:** cuesta 7 veces lo que C, puntúa **peor** que C, y su
  única regresión es diagnosticable — puso `BUD-2024-016` (descomposición de un core bancario
  monolítico) en **primera** posición para la transcripción desordenada de e-commerce, porque la
  fusión metió candidatos que el umbral vectorial había descartado y el cross-encoder se equivocó
  puntuando uno de ellos contra una consulta verbosa y multitema. **Más candidatos no es mejor si el
  reranker tiene que ordenar más ruido.**
- **Las medias esconden dónde se mueve la aguja, y el detalle por consulta sí lo muestra:**
  - **Q4, la trampa de dominios colindantes, la desactiva el reranker.** Con A el quinto puesto lo
    ocupaba `BUD-2024-014` — almacén con AGV: sector industrial, 620 h, vocabulario de operaciones
    compartido, y logística en vez de telemetría. C y D lo sustituyen por un chunk relevante. Es
    exactamente el fallo que da nombre a la sesión, atribuido a una técnica concreta.
  - **Q1 la arregla la híbrida**, sacando `BUD-2024-008` (devoluciones de moda) del top-5.
  - **Q3 se queda en 0,80 en las cuatro porque es el techo**, no un fallo: un único presupuesto
    relevante con 4 componentes. Estaba anticipado al construir el golden set.
- **La recuperación es determinista:** tres ejecuciones independientes dieron exactamente la misma
  precisión. Las diferencias entre configuraciones son reales, no ruido de muestreo — lo que no las
  hace estadísticamente significativas con 5 consultas.
- **El contexto lleva menos referencias independientes de las que parece:** 2,0–2,4 presupuestos
  distintos por top-5, porque el chunker emite un chunk por componente y un presupuesto puede ocupar
  varias plazas legítimamente.
- **El `distance_threshold=0,6` limita el recall antes que `recall_k`:** 12–27 candidatos reales en
  lugar de 50. Eso abarata artificialmente a C, y en un corpus mayor habría que decidir cuál de los
  dos parámetros manda.
- **Y la conclusión incómoda, que preferimos decir nosotros:** este golden set **no puede decidir
  sobre el reranking**. 17 presupuestos en 4 sectores muy separados (finanzas, e-commerce, sanidad,
  industrial) dejan el techo demasiado cerca del suelo, y con 5 consultas un `+0,04` es un chunk en
  una consulta. La medición vale lo que valga su parecido con el tráfico real. La conclusión de este
  informe es sobre **este corpus**, no sobre las técnicas.

---

## 3. Decisión

**Se queda B (híbrida sin reranking).** El código de las tres técnicas permanece en el repositorio,
apagado por configuración, porque el trabajo caro ya está hecho y encenderlo cuando aparezca la
evidencia es cambiar un booleano. La evidencia que lo justificaría es observable y concreta:
`recall@k` alto con `precision@k` bajo de forma recurrente, es decir, los relevantes entrando en el
conjunto amplio pero no en el top-5.

---

## 4. Revisión posterior al cierre: qué encontró y qué se corrigió

Con el ejercicio ya entregado se pasó una revisión adversarial sobre la implementación completa
(seis revisores independientes por dimensión, cada hallazgo sometido después a un verificador cuyo
trabajo era refutarlo, verificando contra el stack en marcha). De 50 hallazgos candidatos, 36
sobrevivieron a la refutación y 14 se descartaron. Lo que cambió:

### 4.1 Un fallo real, y era del default que yo mismo recomendé

- **La rama léxica no tenía piso de relevancia, y eso desactivaba la salvaguarda de contexto
  insuficiente.** `low_confidence` se derivaba de que la lista estuviese vacía, y en modo híbrido esa
  lista casi nunca lo está — `client`/`main`/`sector`/`project` están en 60 de 60 chunks por la
  plantilla del chunk, y las stopwords españolas (`de`, `y`, `para`) sobreviven al analizador inglés.
  Resultado: una transcripción sin proyecto comparable pasaba de *"contexto insuficiente"* (config A)
  a una estimación confiada fundamentada en ruido (config B, el default). **Corregido**:
  `low_confidence` significa ahora "nada cruzó el piso semántico". Detalle completo en
  `arquitectura-actual.md` §3.5.
- **Ni un test lo detectaba.** Cambiar el comportamiento dejó los 343 tests en verde. Añadidos tres
  tests que lo fijan, y comprobado por mutación que fallan si se revierte el arreglo.

### 4.2 Tres mutaciones que se entregaban en verde, ahora cazadas

Verificado reintroduciendo cada defecto y ejecutando la suite:

| Mutación | Antes | Ahora |
|---|---|---|
| Revertir `low_confidence` a `not chunks` | 343 passed | 2 tests fallan |
| Limitar la llamada híbrida a `top_k` (hunde 5× el techo de recall de la config D) | 343 passed | 1 test falla |
| Quitar `budget_id` en la ruta solo-léxica (sesga las filas híbridas de la tabla) | 343 passed | 1 test falla |
| Quitar los filtros estructurales de `search_lexical` | 343 passed | 4 tests fallan |

Añadidos además: aserción de que el orquestador reenvía `search_text` (sin ella, un refactor mataba
la rama léxica en el endpoint principal **en silencio**, porque `plainto_tsquery('english', NULL)` casa
0 filas), un test de la rama `distance=None` del ensamblador de contexto, y 13 tests de las funciones
de métrica del arnés. Cobertura de `repository.py`: 34% → 66%. Suite: 343 → 370 tests.

### 4.3 Dos defectos aritméticos en el propio arnés de medición

- **`precision_at_k` dividía por lo devuelto, no por `k`** — premiaba devolver menos: 2 relevantes de
  2 devueltos puntuaba 1,00 frente a 4 de 5 puntuando 0,80. Es **la misma clase de defecto por la que
  yo había rechazado otra métrica** en este mismo fichero. Corregido a dividir por `k`. Latente hoy
  (las cuatro configuraciones devuelven 5), y activo en cuanto se aprieta el umbral o se añade un
  filtro. **La tabla del entregable no cambia**: re-ejecutado tras el arreglo, precisión y recall son
  idénticos.
- **`recall_at_k` devolvía 0,0 sin verdad de referencia**, confundiendo "no había nada que encontrar"
  con "no encontró nada". Ahora lanza excepción: un caso negativo fuera de dominio necesita una
  comprobación de soft-fail, no recall.

### 4.4 Afirmaciones mías que no se sostenían, corregidas

- *"La léxica se sirve por índice GIN"* — con 60 chunks el planificador elige `Seq Scan` (0,24 ms), que
  es la decisión correcta a esta escala. Lo que abarata la híbrida es la concurrencia, no el índice.
- *"`ts_rank` puntúa más alto los términos más raros"* — **no hay IDF**: un término presente en 19 de 60
  chunks puntúa exactamente igual que uno presente en 0.
- *"El parser nunca produce un lexema que contenga `&`"* — los tokens `url` y `url_path` sí lo conservan.
  Consecuencia acotada (perturba el rango, no pierde el resultado) y 0 de 60 chunks contienen URLs.
- *"Un servicio con el reranking apagado no paga nada"* — `import app.main` ya arrastra `torch`
  transitivamente. Lo que no paga es la carga del modelo ni la inferencia.
- *"El código de las tres técnicas queda apagado por configuración (`RETRIEVAL_SEARCH_MODE=hybrid`…)"* —
  ese setting es justo el que **enciende** la rama léxica y la fusión.
- *"Los cinco fallos de la Sesión 09 están cerrados"* — cuatro; el rollup del presupuesto padre sigue
  parcial, como la propia tabla de debajo indicaba.
- **Recuentos de candidatos**: los reales son 9–22 (vectorial), 17–36 (léxica) y 21–44 (pool); las
  cifras publicadas se tomaron con otro estado de la base de datos.
- **Coste del cross-encoder**: no escala con el número de pares sino con los tokens del lote (una
  consulta de 15 pares costó 1.138 ms y otra de 22 pares, 319 ms). Y la carga son ~5 s en caliente,
  no 20,6 s — esa cifra incluía la descarga de 450 MB.

### 4.5 Lo que la revisión decidió NO tocar

- **`top_k` es inerte con el reranking activo.** Es deliberado y está documentado; añadir un validador
  cruzado rompería el propósito del endpoint (que las cuatro configuraciones sean alcanzables por
  petición). Se documenta, no se "arregla".
- **La híbrida abre dos conexiones del pool por petición.** 50 peticiones concurrentes produjeron 0
  excepciones, y el embebido de 150–600 ms hace la diferencia invisible en el endpoint. Se anota que
  el "+0 ms" se midió a concurrencia 1, que es el único nivel donde se sostiene.
- **La expresión tsquery se reevalúa por fila bajo el plan genérico.** A escala ×100 la rama vectorial
  sin índice HNSW cuesta 2,2× más que el peor caso léxico, y corren en paralelo: reestructurar no
  ahorra nada en el endpoint.

### 4.6 Lo que quedó pendiente, y por qué es una decisión y no un olvido

- **`ts_rank` sin normalización por longitud.** El corpus tiene un chunk atípico de 7.700 caracteres
  (`BUD-2024-016`, frente a una media de 483) que entra en el top-5 léxico de las cinco consultas y no
  es relevante en ninguna — es el mecanismo detrás de la única regresión de la config D. Añadir el flag
  de normalización subiría `precision@5` de B de 0,92 a 0,96, empatando con C, lo que **cambia el
  argumento del entregable aunque no la decisión de quedarse con B**. Se deja como decisión explícita
  del autor, no como cambio silencioso.
- **Un caso negativo fuera de dominio en el golden set** (`relevant_budget_ids: []`), que convertiría
  el arreglo de §4.1 en algo medido y no argumentado. Requiere una métrica nueva (acierto del
  soft-fail) y tocar un golden set ya validado.
