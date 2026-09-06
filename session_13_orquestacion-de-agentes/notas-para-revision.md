# Notas para la revisión — Sesión 13

Pre-work de la Sesión 13: el flujo de estimación **reexpresado como un grafo de LangGraph** dentro
del servicio IA, con estado tipado, persistencia en el Postgres del proyecto y un span por nodo.
Niveles 1, 2 y 3 completos.

Todo el código va en inglés (nombres, comentarios, logs, prompts); esta prosa, en español.

---

## 1. Qué se ha construido

```
app/domain/graph/
├── state.py            # EstimationState (TypedDict) + dos acumuladores
├── schemas.py          # contratos de los nodos LLM
├── nodes.py            # los cinco nodos + el terminal de revisión, con su span
├── build.py            # cableado, la arista condicional y la compilación
├── checkpointer.py     # AsyncPostgresSaver sobre el Postgres del proyecto
└── observability.py    # Logfire (no-op sin token)
app/domain/schemas/graph_estimation.py   # contrato HTTP
app/api/routers/estimate_graph.py        # POST /v1/estimate/graph
scripts/run_graph_s13.py                 # CLI: --memory / --stub / --out
tests/domain/graph/ + tests/api/test_estimate_graph_endpoint.py
```

El grafo se construye una vez en el `lifespan` con su checkpointer ya abierto y vive en
`app.state.graph`; el endpoint lo invoca con `thread_id = estimation_id`.

## 2. Decisiones de diseño

**Los nodos se construyen con una factoría.** `app/domain/` no puede importar `app.dependencies`
(ARCHITECTURE.md §3), así que el composition root construye los nodos con sus colaboradores y el
grafo los recibe cableados. Siguen siendo funciones puras del estado, que es lo que el grafo y los
tests necesitan, y el cableado se queda en el único sitio autorizado a saber de cableado.

**Un solo sitio de cableado.** `scripts/run_graph_s13.py` usa `get_graph_nodes()`, no construye los
suyos. Cuando lo hacía, un arreglo de timeout aplicado al servicio no le llegaba y la ejecución del
entregable moría con el mismo error dos veces seguidas.

**`Component` lleva un tercer campo, `search_query`, en inglés.** El esqueleto del enunciado solo
tiene `name` y `category`, pero el corpus histórico está en inglés y en la S12 medimos que la misma
consulta en español devuelve 0 resultados donde la inglesa devuelve 5. El nombre se queda en el
idioma de la reunión porque es lo que lee el humano; la query es un artefacto de máquina.

**Los joins van por un `id` que asignamos nosotros**, nunca por el nombre que escribe el modelo.
Ver §4.

**Dos acumuladores desde el principio** (`budget_matches`, `errors`) aunque el grafo va secuencial:
son lo que hará posible el fan-out del directo sin reescribir el estado. Un campo de sobrescritura
bajo fan-out se queda con una rama y tira el resto.

**El modelo caro solo donde piensa.** Extracción y clasificación van con `REFORMULATION_MODEL`; la
estimación con `GENERATION_MODEL` a `GENERATION_REASONING_EFFORT`, con `GENERATION_MAX_TOKENS` de
presupuesto y un timeout propio (`GRAPH_LLM_TIMEOUT`, 300 s frente a los 30 s del resto del
servicio).

## 3. Lo que enseñó ejecutar de verdad

El grafo compiló y corrió a la primera. Las cinco iteraciones siguientes fueron **la costura entre
lo que el modelo escribe y lo que el código espera**, y ninguna se ve sin ejecutar:

| Síntoma | Causa | Arreglo |
|---|---|---|
| Los 7 componentes marcados "claims grounding with no reference" | Unía estimación y evidencia **por el nombre**, y el modelo copió la etiqueta `Nombre (categoría)` que le mostraba el prompt | `id` asignado por nosotros; el modelo lo devuelve en `component_id` |
| Los 9 componentes marcados "no es uno de los clasificados" | El brief mostraba `[c1]` y el modelo devolvió `"[c1]"`, con corchetes | Formato inequívoco (`id: c1`) **y** normalización al unir |
| `litellm.Timeout` en `generate_estimate`, seis reintentos | Al reenviar por fin `reasoning_effort`, los tokens de razonamiento agotaban `max_tokens` (4000) y la llamada excedía los 30 s | `GENERATION_MAX_TOKENS` + `GRAPH_LLM_TIMEOUT` |
| El mismo timeout otra vez, ya arreglado | El script cableaba sus propios nodos: el arreglo no le llegaba | El script usa `get_graph_nodes()` |

## 4. Lo que encontró la revisión adversarial

Antes de dar la traza por buena se pasó el código por cinco lentes independientes (API real de
LangGraph 1.0.1 leída del venv, control de flujo y reanudación, reglas de capas, semántica de los
nodos, cumplimiento del enunciado), cada una seguida de un escéptico que intentaba refutar sus
hallazgos. Sobrevivieron cuatro de severidad alta, **los cuatro reproducidos contra el código vivo**:

1. **Un `thread_id` reutilizado heredaba el `validated` anterior.** El validador escribía `status`
   solo al pasar; como es un canal *last-write-wins* que el checkpointer restaura, un hilo que ya
   había terminado bien conservaba ese valor, la arista lo leía y una ejecución cuyas guardrails
   acababan de fallar se respondía como validada. Ahora se escribe siempre, `None` incluido: un
   campo por el que enrutan las aristas no puede ser heredable.
2. **Re-invocar un hilo terminado duplicaba la evidencia.** LangGraph abre un *superstep* nuevo
   sobre los canales persistidos y `operator.add` concatena. Variante grave: si el retrieval del
   reintento fallaba, el conjunto `backed` seguía teniendo las referencias de la primera ejecución
   y los componentes se certificaban como *grounded* sobre evidencia que esa ejecución nunca
   recuperó. Ahora un hilo terminado se **responde**, no se re-ejecuta.
3. **La ejecución producía cinco trazas sueltas**, no una con un span por nodo — que es el criterio
   de aceptación del Nivel 2. Sin span padre cada nodo abría su propia raíz. Y las tres llamadas a
   `logfire.instrument_*` **fallaban** por extras no declarados.
4. **La guardrail de grounding era unidireccional**: `grounded=false` con horas inventadas pasaba
   como validado, y una ejecución cuyas búsquedas fallaron todas también.

De regalo: los spans estampaban `llm_cost_usd=None` en todos los nodos porque `complete_structured`
no devolvía coste (lo asumí de `complete()`). Un atributo siempre nulo es peor que ausente, porque
un panel lo suma como cero.

## 5. Observabilidad

**Logfire**, configurado en el `lifespan`. Sin `LOGFIRE_TOKEN` los spans se abren y cierran igual
pero no se exportan, así que el servicio funciona idéntico sin cuenta. Con token, cada ejecución
exporta un span por nodo colgando del span de la ejecución (bajo el endpoint, del span de la
petición), con `model`, `latency_ms`, `llm_cost_usd` y `total_tokens` donde la llamada los reporta.

El coste por estimación es entonces una consulta sobre los spans, no una estimación a ojo.

## 6. Limitaciones conocidas

- **Secuencial a propósito.** `search_budgets` recorre los componentes uno tras otro; en la
  ejecución del entregable son ~2,3 s de los ~80 s totales, así que el cuello está en el LLM, no en
  el fan-out. Paralelizarlo con la Send API es trabajo del directo.
- **Sin reintentos, timeouts por nodo, fallback ni HITL**: fuera del alcance del pre-work.
- **El corpus no tiene apps móviles**, así que ese componente se apoya en análogos de otras
  categorías. El agente lo declara en `notes` en vez de ocultarlo.
- **Reanudación parcial no ejercitada**: el endpoint distingue hilo terminado (responde) de hilo a
  medias (reanuda), pero solo el primer caso tiene test contra un grafo real.

## 7. Cómo reproducir

```bash
docker compose up -d --build
docker compose exec estimator python scripts/build_task_corpus.py --ingest

cd estimator
# Smoke barato: checkpointer en memoria y retrieval enlatado
uv run python scripts/run_graph_s13.py --memory --stub

# La ejecución del entregable (host, contra el stack)
REDIS_URL=redis://localhost:6379 uv run python scripts/run_graph_s13.py \
    --out exercises/session-13/example_run_complex.txt

# Con exportación de traza
LOGFIRE_TOKEN=pylf_v1_... uv run python scripts/run_graph_s13.py

uv run python -m pytest tests/domain/graph tests/api -q
```

## 8. Criterios de aceptación

Traza en `estimator/exercises/session-13/example_run_complex.txt`:

- [x] El grafo corre de principio a fin y el endpoint devuelve la estimación con su `status`; el
      contrato hacia el backend de negocio es el de siempre.
- [x] Estado **tipado** con **dos** reducers acumuladores (`budget_matches`, `errors`).
- [x] Los **cinco nodos** son funciones puras que devuelven actualizaciones parciales; ninguno
      decide quién va después.
- [x] El **checkpointer persiste en el Postgres del proyecto** (tablas `checkpoints`,
      `checkpoint_writes`, `checkpoint_blobs`, junto a `budget_chunks` y `documents`) y cada
      ejecución lleva su `thread_id` — 7 checkpoints en la última.
- [x] **Traza completa** de una ejecución con un span por nodo, en una sola traza (test con el
      exporter de Logfire que exige un único `trace_id`).
- [x] Nivel 3: arista condicional `validated → END` / resto → `flag_for_review`.
