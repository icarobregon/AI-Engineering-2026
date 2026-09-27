# Evaluación y observabilidad

Cómo se mide si el sistema estima **bien**, y cómo se ve lo que hace en producción.

Son dos cosas distintas y las dos hacen falta. La **evaluación** es la prueba de
laboratorio: nosotros elegimos las entradas y la vara, y la lanzamos cuando
queremos; responde *¿es bueno en mis casos?*. La **observabilidad** es el monitor
de constantes vitales: las entradas las manda el mundo, no hay vara y está
siempre puesta; responde *¿qué hace el sistema ahora mismo con el tráfico real?*.
La primera caza lo que rompen nuestros cambios; la segunda, lo que no supimos
imaginar.

---

## Por qué esto no está en CI

En CI el modelo se dobla, porque CI prueba **nuestro código**: tiene que ser
determinista, gratis y correr en cada commit. El arnés es lo contrario —llama al
**modelo real**, porque lo que evalúa es al modelo— así que no es determinista,
cuesta dinero y tarda minutos. Se lanza a propósito, contra el sistema
desplegado, y deja un informe.

Testear y evaluar son las dos caras de la misma moneda. Meter el arnés en CI
convierte cada push en una factura y cada fallo del proveedor en un build rojo.

## Dónde vive cada cosa

```
estimator/evals/production/
├── golden_set.json        # la vara: 7 casos con su banda, en horas
├── run_eval.py            # el arnés: --target rag|graph
├── compare_reports.py     # la regresión: esta ejecución contra la línea base
└── reports/               # un informe por ejecución, con su procedencia
```

Va en `evals/production/` y no en un `eval/` nuevo junto al `evals/` que ya
existía: dos carpetas casi homónimas es un pie de banco. Los `evals` hermanos
miden otras cosas —la ruta conversacional de la S05 en euros y semanas, la
recuperación de la S10-S11 con conjuntos de relevancia— y se quedan donde están.

La instrumentación y el panel viven en el servicio y en el backend de negocio:

```
estimator/app/foundation/observability/metrics.py   # el acumulador por petición
estimator/app/foundation/persistence/repositories/metrics.py
estimator/app/api/routers/metrics.py                # GET /v1/metrics/summary
business-backend/src/app/observabilidad/            # la pantalla
```

---

## El golden set

Siete transcripciones de reunión, en castellano y con marcas de tiempo, como las
que el producto recibe de verdad. Cada una lleva su banda aceptable y un `notes`
que dice de qué proyectos históricos sale.

| Caso | Dificultad | Sector | Esperado | Banda | Qué mide |
|---|---|---|---|---|---|
| `case-001` | fácil | ecommerce | 680 h | 450–950 | El precedente más denso. Si falla, no funciona nada. |
| `case-002` | medio-alto | healthcare | 900 h | 550–1250 | Grande y regulado, con precedente para cada bloque. |
| `case-003` | medio | finance | 580 h | 380–880 | Reunión corta y sin cerrar. El único sector donde compiten las dos granularidades del corpus. |
| `case-004` | medio | logistics | 750 h | 450–1150 | El precedente más fino: sólo cuatro proyectos. |
| `case-005` | borde | education + media | 1100 h | 750–1450 | Cruza dos sectores: hay que componer, no anclarse en uno. |
| `case-006` | **abstención** | — | — | — | El suelo de seguridad. |
| `case-007` | pequeño | ecommerce | 140 h | 60–260 | El control contra el sesgo a la mediana. |

**La unidad está escrita en el fichero.** Las expectativas van en **horas** —la
unidad en la que habla el corpus— más `hours_per_day: 8`. La ruta RAG multiplica
sus `engineer_days`; el grafo compara sus `total_hours` directamente. Eso es lo
que hace comparables las dos rutas entre sí y lo que convierte un error de
unidad en un factor legible en vez de en un «sale muy alto».

**Las bandas no son a ojo.** Salen del corpus de tareas (60 proyectos, 1543
componentes), que es el 96% de lo que la recuperación devuelve: ecommerce son 7
proyectos de 508 a 804 h, healthcare 9 de 537 a 1182, logistics sólo 4 de 469 a
1135. Cada `notes` cita los identificadores y las horas.

**El caso de abstención se eligió midiendo.** Simulación numérica científica
(CFD) tiene cero apariciones de sus términos en los 1603 chunks y una similitud
léxica máxima de 0,081 frente al 0,528 de un caso en dominio. Se descartaron dos
candidatos que parecían mejores: *blockchain* engancha con chunks de finance
**que llevan horas** (ledger, KYC, liquidación, rotación de claves) y el modelo
podría citarlos literalmente pasando la verificación de citas de la S11; y
*aviónica DO-178C* enlaza «trazabilidad de requisitos» con «Discovery &
requirements». Queda un riesgo asumido y escrito en el propio caso: 335 de los
1603 chunks son andamiaje agnóstico de sector (gestión, infraestructura, QA) y
son citables para cualquier proyecto. Si el sistema construye un número encima
de ellos, no es que el caso falle: es el fallo que el caso existe para cazar.

## El arnés

Corre **dentro de la red privada**, porque desde la S15 el servicio IA no
publica puerto y esa frontera no se relaja para poder medir. No se mete en la
imagen de producción —en la S15 se sacó Streamlit de ahí por pesar 190 MB de
herramienta de desarrollo, y esto es otra—, así que va en un contenedor de usar
y tirar con `evals/` montado:

```bash
cd session_16_puesta-en-produccion-y-llmops-ii

docker compose run --rm --no-deps \
  -v "$(pwd)/estimator/evals:/app/evals" \
  -e AI_SERVICE_URL=http://ai-service:8000 \
  -e GIT_SHA="$(git rev-parse --short HEAD)" \
  ai-service python -m evals.production.run_eval --target rag

# la otra ruta, la del supervisor multi-agente
… --target graph

# un solo caso, para probar el arnés sin pagar siete
… --target rag --case case-007-ecommerce-small
```

`GIT_SHA` se pasa desde fuera porque el contenedor no tiene git. La clave llega
por el entorno del servicio (`ESTIMATE_API_KEY`), nunca escrita en el fichero.

**No se manda `idempotency_key`.** Con ella, la segunda ejecución devolvería la
estimación guardada: la petición parecería rápida y gratis y la evaluación no
mediría nada. Ojo, que la caché guarda también las abstenciones, 24 horas.

### Las métricas

| Métrica | Qué fallo caza |
|---|---|
| `within_range_rate` | Cifras flojas. La tasa de acierto. |
| `mean_absolute_error_hours` | *Cuánto* falla, no sólo *si* falla. |
| `abstention_correct` | Responder donde debía abstenerse. Seguridad, no calidad. |
| `mean_latency_ms` / `p95_latency_ms` | Lentitud, y la minoría que la sufre. |
| `error_rate` | Caídas, timeouts, bloqueos. |
| `hallucination_rate` | Fuentes citadas que no existen en el corpus. |
| `sources.budgets` / `sources.tasks` | Sobre qué granularidad razonó, que es invisible desde la petición. |

Cada informe guarda además **contra qué se midió**: commit, modelos, jornada y la
configuración de recuperación leída **en vivo** del servicio, no del `.env`,
porque el modo de búsqueda y el reranker se resuelven primero contra Redis y la
pantalla de Ajustes puede cambiarlos sin que se mueva una línea del repositorio.
Sin eso, una caída de cinco puntos entre dos informes no significa nada.

### Cómo se lee una regresión

```bash
python -m evals.production.compare_reports \
  estimator/evals/production/reports/<linea-base>.json \
  estimator/evals/production/reports/<ultima>.json
```

Falla —código de salida 1— si algún caso que pasaba ahora falla, si la tasa de
acierto cae más del umbral, o si se pierde la abstención, que nunca es un
redondeo. Imprime primero **qué cambió** entre las dos ejecuciones: una caída con
un prompt distinto y una caída con otro modelo debajo no son la misma noticia.

---

## El panel

`http://localhost:3000/observabilidad`. Tres señales sobre la ventana elegida
(1 h, 24 h, 7 días):

- **Latencia media y p95.** La media esconde a la minoría que sufre; el p95 dice
  si hay usuarios esperando una eternidad.
- **Coste por petición**, derivado de los tokens y la tabla de precios, con el
  total de la ventana.
- **Tasa de error**: todo lo que no acabó en 2xx ni en `completed`.

Debajo, el desglose por ruta y las últimas peticiones.

### Qué NO enseña, a propósito

- **El `/health`.** Compose lo llama cada quince segundos: contarlo haría que «la
  latencia p95 del servicio» fuese en realidad la de un latido y que la mediana
  del coste por petición fuese cero.
- **Sus propias lecturas.** Una pantalla abierta con refresco acabaría siendo la
  ruta más transitada del sistema. Observar no puede cambiar lo observado.

### Qué sí enseña, y no lo hacía

Tres puntos ciegos se taparon en esta sesión. El **agente de la S12** conduce la
Responses API a mano y descartaba el `usage` de sus tres llamadas; con
`store=True` el proveedor re-factura la conversación entera en cada vuelta, así
que es la ruta más cara del servicio y aparecía a 0,00 $. El **embebedor** tiraba
el `usage` que la respuesta ya traía, de modo que el coste de recuperar no
existía. Y las **ejecuciones del grafo** lanzadas por `/graph/start` corren en
una tarea de fondo, es decir después de que el middleware haya cerrado: casi todo
el gasto del sistema caía fuera del registro.

### El cero que se cree un panel

`estimated_cost` se redondea a ocho decimales y no a seis. Una recuperación
embebe ocho tokens, o sea 0,00000016 $, que a seis decimales se escribe `0.0`.
Un cero es peor que un hueco, porque es un número y alguien se lo cree. Lo mismo
con las llamadas cuyo proveedor no informa de tokens: se cuentan aparte, en
`calls_without_usage`, en vez de sumar cero.

### Lo que el panel no es

No es el health check. `/health` sigue siendo barato y tonto: dice «estoy vivo»,
sin autenticación y sin tocar el modelo. Comprobar que el modelo responde con
calidad es trabajo del golden set, y vigilar lo que cuesta es trabajo de esta
pantalla.

Tampoco sustituye a las trazas. El panel dice **que** la latencia se disparó; el
trace por tramos —embedding → recuperación → generación, ya instrumentado con
Logfire desde la S13— dice **dónde**.

---

## Hallazgos (26-27/09/2026)

Tres ejecuciones completas, siete casos cada una. Los informes están en
`evals/production/reports/`; la captura del panel, en
[`evidencia-panel-observabilidad.png`](evidencia-panel-observabilidad.png).

| | RAG · línea base | Grafo · línea base | RAG · tras el arreglo |
|---|---|---|---|
| commit | `44caecf` | `44caecf` | `e2de5f0` |
| `within_range_rate` | **0 %** | **33 %** | **17 %** |
| `mean_absolute_error_hours` | 553 h | 514 h | 583 h |
| `abstention_correct` | sí | sí | sí |
| latencia media / p95 | 123 s / 163 s | 92 s / 132 s | 94 s / 132 s |
| `error_rate` | 0 % | 0 % | 0 % |
| `hallucination_rate` | 0 % | 0 % | 0 % |

### 1. El suelo de seguridad aguanta

El caso de abstención **pasa en las dos arquitecturas**. En la ruta RAG por el
camino más limpio posible: catorce segundos, cero citas y
`confidence="insufficient"`. Eso significa que se abstuvo por **distancia
coseno** —ningún chunk cruzó el umbral de 0,6, así que el corto-circuito de
recuperación respondió sin llegar a llamar al generador— y conviene decirlo con
precisión: **el caso valida el umbral de recuperación, no el criterio del
modelo**. Una prueba más dura del juicio del modelo necesitaría un caso que SÍ
recupere algo y aun así deba abstenerse. En el grafo la respuesta correcta tomó
la otra forma legítima: escaló a una persona.

### 2. La arquitectura que no deja elegir el número mide mejor

| Caso | RAG | Grafo | Esperado |
|---|---|---|---|
| 001 ecommerce | 232 h ×0,34 | 1495 h ×2,2 | 680 h |
| 002 healthcare | 120 h ×0,13 | **dentro** ×1,35 | 900 h |
| 003 finance | 168 h ×0,29 | 909 h ×1,57 | 580 h |
| 004 logistics | 192 h ×0,26 | **dentro** ×1,38 | 750 h |
| 005 borde | 600 h ×0,55 | 2024 h ×1,84 | 1100 h |
| 007 pequeño | 760 h ×5,43 | 552 h ×3,94 | 140 h |

El RAG se queda corto entre dos y ocho veces; el grafo se pasa, pero entre 1,35
y 2,2 — fallos de cerca en vez de fallos de orden de magnitud. Y encima es más
rápido (92 s contra 123 s de media).

La diferencia es de diseño, no de suerte: en el grafo **el número lo calcula una
función de Python** (mediana de las referencias × 1,15 de contingencia) y al
modelo sólo se le pide la prosa, mientras que en el RAG la cifra la elige el
modelo. Esa decisión se tomó en la Sesión 13 por argumentos; ésta es la primera
vez que hay un número detrás.

### 3. El sistema comprime: la respuesta apenas depende del alcance

En la línea base del RAG las cifras crudas son 29, 15, 21, 24, 75 y 95
jornadas. El sistema mete proyectos cuyos análogos históricos van de 470 a 1200
horas —y uno de 140— dentro de una banda estrecha: al pequeño le echa cinco
veces de más y al grande ocho veces de menos. Un sistema que contesta siempre
parecido no está estimando.

Esto **no se ve en una ejecución suelta**: hace falta una vara, varios casos y
tamaños distintos. El `case-007` existe para cazar exactamente el sesgo a la
mediana y lo cazó en las tres tandas.

### 4. El A/B: una métrica sube y otra baja

El cambio juzgado fue una declaración de unidades en el prompt (`e2de5f0`): las
fuentes hablan en horas, la respuesta va en jornadas, 120 horas son 15 jornadas,
y un proyecto entero del histórico son 60-150 jornadas. El veredicto del
comparador:

```
within_range_rate          0% → 17%
mean_absolute_error_hours  553.0 h → 582.8 h
mean_latency_ms            123 s → 94 s
arreglados: case-001-ecommerce-checkout
regresiones: ninguna
sin regresión
```

**El acierto sube y el error medio empeora.** No hay ninguna regresión en el
sentido estricto —ningún caso que pasara ha dejado de pasar— pero declarar el
cambio «una mejora» sería quedarse con la mitad de los números. Es literalmente
el aviso de la sesión: los KPIs se mueven unos contra otros, y el equilibrio se
decide a sabiendas, con las cifras delante.

Lo más revelador está en un caso concreto. El `case-007` pasó de contestar 760 h
—cinco veces de más— a **no contestar**: `confidence="insufficient"`, sin cifra,
en un caso donde sí debía haberla. El sistema se volvió más prudente y se pasó
de frenada. Reducir el exceso puede convertirse en abstenerse donde no toca, y
esa es una forma de degradación que la tasa de acierto sola no ve.

### 5. La misma entrada, tres respuestas distintas

El `case-007`, sin cambiar una coma de la transcripción:

- 584 h en la prueba de humo,
- 760 h en la línea base, con el mismo código y el mismo prompt,
- sin cifra tras el cambio de prompt.

Un 30% de diferencia entre dos tiradas idénticas. Juzgar este sistema por una
ejecución es juzgar un dado por un lanzamiento, y ésa es la razón por la que el
arnés guarda un informe por tanda en vez de imprimir un número y olvidarlo.

### 6. Lo que enseñó quedarse sin crédito

La primera tentativa de la línea base murió a mitad: la cuenta de OpenAI se
quedó sin saldo y los tres últimos casos fallaron en la reformulación, catorce
segundos cada uno. El informe parcial se conserva
(`eval-rag-20260926T162538.json`) porque el que recoge una caída de proveedor
vale tanto como el que sale limpio.

Dos cosas se aprendieron ahí. Primera: el panel lo contó como lo que era —tasa
de error del 43%, latencias de catorce segundos y coste cero, porque no se llegó
a gastar nada— y la instrumentación contó las llamadas fallidas sin inventarles
precio. Segunda, y más seria: **`FALLBACK_MODEL` está configurado y Anthropic
respondía con normalidad**, pero `complete_structured` evita el Router a
propósito desde la S03 (su round-robin enrutaba de forma no determinista), así
que la ruta de estimación llama siempre al primario y se cayó con él. El
servicio tiene una red que su camino más caro no puede usar. Queda documentado y
sin parchear: tocar el camino crítico sin poder medir después si degrada es lo
que esta sesión enseña a no hacer.

### 7. Lo que funcionó sin ruido

**Cero fuentes inventadas en las tres tandas.** Todas las citas resuelven contra
documentos que existen en el corpus. La maquinaria de citas por línea de la S11
aguanta bajo medición.

Y el reparto por granularidad enseñó lo suyo: el `case-003` (finance) citó seis
documentos de los que **sólo uno era de su sector** (`sector_match_rate` 0,17),
y el `case-007` construyó 95 jornadas sobre dos tareas de unas 15 horas cada
una. Las citas son reales, la verificación las da por buenas, y aun así el
número no se sostiene. Es el recordatorio de que una cita válida no es una
justificación: sólo dice que el documento existe.

---

## Cuánto cuesta

Una ejecución completa de siete casos con `gpt-5` a esfuerzo alto: entre uno y
tres dólares y entre quince y cuarenta minutos, con hasta tres generaciones por
caso (los reintentos de citas y de coherencia son caminos reales). La ruta del
grafo es algo más cara. Por eso se lanza a propósito y no en cada push.

Para probar el arnés sin pagar la tanda entera, `--case`.

---

## Correr los tests

El scoring del arnés y el acumulador de coste se prueban **sin red y sin gastar
un token**, que es lo que les permite vivir en CI:

```bash
cd estimator
uv run pytest tests/test_evals_production.py tests/test_request_metrics.py -v
```

La imagen de producción no lleva pytest (se construye con `--no-dev`), así que
los tests corren en el host con uv, como dice `CLAUDE.md`.
