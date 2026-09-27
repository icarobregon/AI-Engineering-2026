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

## Hallazgos de la primera ejecución (26/09/2026)

Línea base parcial, commit `7b05811`, ruta RAG, `gpt-5-mini` + `gpt-5` a esfuerzo
alto. Informe en `evals/production/reports/eval-rag-20260926T162538.json`; el de
un solo caso, lanzado antes como prueba del arnés, es
`eval-rag-20260926T161508.json`.

```
within_range_rate          0%
mean_absolute_error_hours  553,5 h
mean_latency_ms            93.360 ms      p95  190.197 ms
error_rate                 43%
hallucination_rate         0%
```

### 1. El sistema no estima: comprime

Cuatro casos llegaron a completarse antes del corte, y todos se quedan MUY
cortos. El séptimo, medido aparte minutos antes, se pasa por cuatro:

| Caso | Predicho | Esperado | Factor |
|---|---|---|---|
| 001 ecommerce | 232 h | 680 h | ×0,34 |
| 002 healthcare | 152 h | 900 h | ×0,17 |
| 003 finance | 232 h | 580 h | ×0,40 |
| 004 logistics | 80 h | 750 h | ×0,11 |
| 007 pequeño | 584 h | 140 h | ×4,17 |

Las cifras crudas son 29, 19, 29, 10 y 73 jornadas. El sistema mete proyectos de
entre 470 y 1200 horas históricas —y uno de 140— dentro de una banda de diez a
setenta jornadas: al pequeño le echa cuatro veces de más y al grande nueve veces
de menos. **La respuesta apenas depende del alcance.** Un sistema que contesta
siempre parecido no está estimando, está adivinando, y eso no se ve mirando una
ejecución: hace falta una vara, varios casos y tamaños distintos. El `case-007`
existe precisamente para cazar esto y lo cazó a la primera.

La causa candidata está a la vista en `app/generation/rag/prompt_builder.py`: el
prompt pide `engineer_days`, las fuentes dicen `Estimated hours: 120`, y una de
sus líneas llama *«its engineer-days»* a esa cifra en horas. **Nadie dice nunca
cuántas horas tiene una jornada.** Queda sin arreglar a propósito: una línea de
prompt es justo el cambio que pide un A/B contra el golden set, y el número que
decide cuál gana es `within_range_rate`.

### 2. El proveedor se quedó sin crédito a mitad de la tanda

Los tres últimos casos fallaron en catorce segundos cada uno, todos en la
reformulación:

```
litellm.RateLimitError: OpenAIException - You have no credits remaining.
```

No es un fallo del sistema, pero la forma en que se ve sí dice cosas. El panel lo
registró como lo que era —tasa de error del 43%, latencias de catorce segundos,
coste cero porque no se llegó a gastar nada— y la instrumentación contó las
llamadas fallidas (`failed_llm_calls=1`) sin inventarles un precio. Un fallo de
proveedor es indistinguible de una caída propia si sólo miras «el sistema no
responde»; con el desglose por ruta y el motivo en el log, se diagnostica en un
minuto.

### 3. El fallback existe y esta ruta no lo alcanza

`FALLBACK_MODEL=claude-haiku-4-5` está configurado, y Anthropic respondía con
normalidad mientras OpenAI rechazaba todo. Pero `complete_structured` **evita el
Router a propósito** —documentado desde la S03: su round-robin enrutaba de forma
no determinista hacia un despliegue que podía no estar— así que la ruta de
estimación llama siempre al modelo primario, sin red.

Resultado: el servicio tiene un fallback configurado que su camino más caro no
puede usar, y hoy se ha comprobado en condiciones reales. Se deja **documentado y
sin tocar**: cambiar el comportamiento del camino crítico un domingo, sin poder
medir después si degrada la calidad, es exactamente lo que esta sesión enseña a
no hacer.

### 4. Lo que sí funcionó

Cero fuentes inventadas en los cinco casos que llegaron al modelo: las once citas
resuelven contra documentos que existen y todas pertenecen al sector esperado. La
maquinaria de citas de la S11 aguanta. Y en el `case-007` se vio el otro riesgo
que el golden set documenta: citó un componente de presupuesto (escala 140 h)
junto a tres tareas (escala 12-71 h) — las dos granularidades del corpus
compitiendo en la misma ventana de recuperación, que es justo lo que el reparto
`sources.budgets` / `sources.tasks` existe para hacer visible.

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
