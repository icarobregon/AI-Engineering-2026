# Notas para la revisión — Sesión 14

Pre-work de la Sesión 14: el flujo de estimación **reorganizado como un sistema multi-agente** dentro
del servicio IA. Un supervisor construido a mano enruta, cuatro especialistas con una tool cada uno
trabajan, y una **puerta humana** para la ejecución cuando la estimación no es fiable y la reanuda con
la decisión de una persona. Niveles 1, 2 y 3 completos.

Todo el código va en inglés (nombres, comentarios, logs, prompts); esta prosa, en español.

---

## 1. Qué se ha construido

```
app/domain/graph/
├── state.py        # EstimationState (total=False) + cuatro acumuladores
├── digest.py       # build_state_digest(): lo único que ve el supervisor
├── supervisor.py   # el router a mano: decisión tipada + Command(goto=, update=)
├── agents.py       # los cuatro especialistas + finalize, como funciones puras
├── hitl.py         # human_review_gate(): señal de disparo + interrupt()
├── band.py         # la banda histórica: referencia del revisor y disparador
├── schemas.py      # contratos de los agentes LLM
├── llm.py          # structured_call / stamp_llm, compartidos
├── build.py        # START → supervisor, y nada más
├── checkpointer.py # AsyncPostgresSaver (sin cambios desde la S13)
└── observability.py

app/domain/security/           # Nivel 3
├── grants.py      # AGENT_TOOL_GRANTS + ToolRisk + @grants + verify_tool_grants
├── guard.py       # guard_action(): privilegio + reglas de argumentos
└── audit.py       # execute_guarded(): structlog + redact_sensitive

app/domain/schemas/graph_estimation.py   # contrato HTTP (+ HumanDecision)
app/api/routers/estimate_graph.py        # POST /graph, POST .../resume, GET .../state
scripts/run_graph_s14.py                 # CLI: --memory / --stub / --decision / --out
exercises/session-14/                    # transcripción edge case + traza de la ejecución
tests/domain/graph/ + tests/domain/security/ + tests/api/test_estimate_graph_endpoint.py
```

Se han borrado `app/domain/graph/nodes.py` y `scripts/run_graph_s13.py`: el grafo lineal ya no existe,
y un script que dice ejecutar la S13 pero ejecuta otra cosa es peor que no tenerlo. La entrega de la
S13 vive en su rama.

**La topología ya no está en el código.** Solo hay una arista declarada, `START → supervisor`; todo lo
demás viaja dentro de un `Command`, que mueve el control y escribe el estado en el mismo valor de
retorno. La forma de una ejecución concreta solo existe después, en `routing_trail`.

## 2. Decisiones de diseño

**El supervisor es híbrido, y la parte de modelo es una sola pregunta real.** Cuatro de las cinco
transiciones son precondiciones, no juicios: no puedes buscar presupuestos de componentes que todavía
no conoces. Pagar un modelo para redescubrir eso en cada ejecución no compra nada y añade un modo de
fallo. La única decisión que este dominio tiene de verdad es la que se hace al final: *el validador
dice que la evidencia es pobre — ¿volvemos a buscar con otras consultas, o se lo damos a un humano?*
Esa sí depende del caso, y es la que hace que `routing_trail` no sea una línea recta.

**Las precondiciones leen QUIÉN HA ACTUADO, no qué campo está vacío.** Es la corrección más importante
respecto al esqueleto del enunciado. «El buscador no ha corrido» y «el buscador no encontró nada» son
hechos distintos, y un supervisor que mira `budget_matches` no los distingue: una transcripción sin
precedente en el corpus rebota supervisor → buscador → supervisor hasta agotar el presupuesto de
enrutado, **sin llegar nunca a la puerta humana** — que es justo donde ese caso pertenece, y es el
entregable que pide el enunciado. La señal sale de `routing_trail`, que ya existe por otro motivo.

**Las horas son de la tool; la prosa, del modelo.** `estimate_generator` le pide a `calculate_estimate`
los números (mediana de las referencias × 1.15 de contingencia, en Python) y al modelo solo el
`rationale` de cada línea y las `notes`. Es la única forma de que la tabla de privilegios signifique
algo: un permiso para llamar a una función que nadie llama es decoración. Y elimina de raíz el modo de
fallo que justifica todo este pipeline — que el modelo se invente una cifra.

**El join va por un `id` nuestro, nunca por el nombre que escribe el modelo.** Lección heredada de la
S13 y respetada aquí a dos niveles: a `calculate_estimate` se le pasa `name = component.id`, porque su
`name` es la clave con la que devuelve el desglose, y `BudgetMatch` lleva `component_id` además de
`component`. El segundo lo puso la revisión adversarial (§7); el primero venía de la S13.

**`confidence` se calcula, no se pregunta.** `0.5·grounded_ratio + 0.3·evidence_density +
0.2·proximity − 0.2·issues_aritméticos`, acotado a [0,1], con cada término nombrado y con test. Un
modelo al que le pides que puntúe su propia salida puntúa alto lo que acaba de decir — y el entregable
depende de que la pausa sea reproducible, no de que el modelo tenga un buen día.

**Dos techos, y solo uno es la estrategia.** `GRAPH_MAX_ROUTING_STEPS` (8) vive en el estado y por
tanto en el checkpoint; `GRAPH_RECURSION_LIMIT` (subido de 25 a 40) es la red. No son intercambiables:
LangGraph cuenta su presupuesto **por invocación**, así que una ejecución que se pausa y se reanuda
recibe uno nuevo cada vez. Con el 25 de la S13 medimos que el `GraphRecursionError` saltaba *antes* que
el presupuesto de enrutado y convertía un `routing_budget_exhausted` controlado en un 502.

**`finalize` es el único que escribe `status`,** y lo escribe en todas las ramas. Un campo del que se
lee el contrato no puede ser heredable: en la S13 un hilo reutilizado se quedaba con el `validated` de
la ejecución anterior.

## 3. Tres trampas de LangGraph 1.0.1, medidas

**`interrupt()` re-ejecuta el nodo entero al reanudar y tira lo que escribió la pasada interrumpida.**
Por eso `human_review_gate` no hace nada más que leer el estado e interrumpir: todo lo que hubiera
encima se pagaría dos veces y se perdería. La confianza, la banda y el motivo los calcula el validador,
que corre antes. Hay un test que reanuda y comprueba que el contador de llamadas al modelo no crece.

**Un `logfire.span` abierto cuando salta `interrupt()` se exporta con `status=ERROR`.** `interrupt()`
funciona lanzando una excepción, y el context manager la ve pasar. Una pausa normal apareciendo en el
dashboard como un fallo destruye la señal del propio dashboard, así que el span del gate se abre
**después** del interrupt. Verificado con `logfire.testing.TestExporter`.

**Un `goto` a un nodo inexistente NO levanta excepción.** LangGraph escribe `wrote to unknown channel`
en un log y la ejecución termina con un estado que parece completo. Por eso hay tres defensas: el
`Literal` cerrado en `SupervisorDecision` (lo rechaza Pydantic), la validación contra `AGENT_NAMES`
dentro del supervisor, y el `Command[Literal[...]]` como anotación de retorno. Esa tercera **solo
funciona si `Command` y `Literal` se importan a nivel de módulo**: LangGraph resuelve la anotación
contra los `__globals__` de la función, y con `from __future__ import annotations` un import bajo
`TYPE_CHECKING` la pierde en silencio — llevándose el diagrama y la comprobación en tiempo de
compilación. Por lo mismo, `@grants(...)` devuelve **la misma función**, no un wrapper.

## 4. El contrato HTTP: un valor nuevo, no un contrato nuevo

`status` gana `awaiting_human_review` (y `routing_budget_exhausted`), más un `review_payload`
opcional. El backend de negocio necesita una rama nueva, no una integración nueva. La autorización del
revisor, la notificación y el histórico de aprobaciones siguen viviendo en negocio.

El verbo de arranque tiene **tres** ramas, y la del medio es un bug corregido de la S13: un hilo
interrumpido tiene `values` *y* `next` no vacío, así que la versión de dos ramas lo mandaba a
re-invocar y **reejecutaba el sistema entero mientras el revisor tenía la primera ejecución en
pantalla**, duplicando todos los acumuladores. Reproducido: `matches` pasaba de `['m1','m2']` a
`['m1','m2','m1','m2']` y seguía pausado.

La reanudación es idempotente leyendo `aget_state` primero: un segundo revisor aprobando el mismo caso
recibe el resultado ya decidido en vez de arrancar una segunda ejecución. Arbitrar entre revisores es
trabajo del backend de negocio, no de este servicio.

## 5. Nivel 3 — privilegio, validación y auditoría

Tres capas, en el orden en que una acción las atraviesa:

1. **Mínimo privilegio.** `AGENT_TOOL_GRANTS` es dato; `@grants(...)` declara las tools en el propio
   nodo; `verify_tool_grants` corre en el `lifespan` **antes** del checkpointer y **levanta**. Un
   agente mal cableado rompe el arranque, no degrada a 503 — que es la señal que ya significa «Postgres
   no está».
2. **Validación de argumentos.** Reglas deterministas sobre las tres tools reales: consulta no vacía y
   no fusionada, referencias positivas y dentro de banda, nombres únicos, total finito. El prompt no es
   un mecanismo de seguridad: el modelo es el cliente, y el cliente no se valida a sí mismo.
3. **Auditoría.** `execute_guarded` es el único paso por el que van todas las llamadas a tools, con
   `structlog`: qué agente, qué tool, con qué argumentos (redactados a su forma), sobre qué
   `estimation_id` y con qué resultado. Las denegadas se registran a WARNING — son las líneas más
   valiosas del log, porque son el sistema diciéndote que un agente intentó algo que no podía.

`ToolRisk` clasifica las tres tools existentes (`READ`, `PURE`, `PURE`) y deja escrito el criterio para
las que vendrán: una acción **irreversible** no se resuelve con validación automática, se enruta a la
puerta humana que ya existe, disparada por otra señal.

## 6. Lo que enseñó ejecutar de verdad

**La fórmula de confianza contaba dos veces lo mismo.** La primera ejecución real dio `0.362` con un
81% de la estimación respaldada, que no cuadraba. La tool de validación emite **una incidencia por
componente sin referencia** — exactamente los componentes que `grounded_ratio` ya mide — así que restar
la lista entera penalizaba cada hueco dos veces. Restando solo las incidencias que la tool conoce y
nosotros no (horas fuera de banda, total que no suma), la misma transcripción da `0.636`. Hay un test
que lo fija.

**La banda histórica hay que escalarla por cobertura o no dispara nunca.** `calculate_estimate` valora
cada componente a partir de sus propias referencias, así que cualquier banda construida con esas mismas
referencias contiene el resultado por construcción — un control que se da la razón a sí mismo. La banda
se calcula sobre los componentes que *sí* tienen precedente y se escala por la fracción del proyecto
que representan. Con todo cubierto la escala es 1.0 y el disparador se calla solo.

**La tolerancia de banda por defecto bajó de 0.5 a 0.25.** A 0.5 el disparador solo saltaba con menos
del 43% del proyecto valorado, que es tardísimo. A 0.25 salta alrededor del 65% y sigue sin poder
dispararse en falso sobre una estimación completamente cubierta.

**La `distance` que devuelve el retrieval real se agolpa contra el umbral** (`proximity` ≈ 6% en la
ejecución del entregable), porque `AGENT_SEARCH_DISTANCE_THRESHOLD` es 0.6 y todo lo que vuelve está
cerca de ahí. Es un desempate, no una señal fuerte, y por eso pesa 0.2. Con el stub, cuyas distancias
van de 0.05 a 0.5, sí discrimina.

## 7. Lo que encontró la revisión adversarial

Cuatro defectos reales, todos reproducidos ejecutando el grafo, todos con test de regresión.

**El `>=` de `finalize` estaba desplazado en uno, y se comía la decisión del humano.** El supervisor
comprueba su techo **antes** de incrementar, así que una ejecución que se rinde llega a `finalize` con
`max+1`; pero el camino legítimo más largo —el que usa la segunda búsqueda— llega con exactamente
`max` (8 con el default). El mismo `>=` leía las dos como agotadas, y como esa rama se evalúa primero,
**una estimación aprobada por un revisor volvía al backend de negocio con
`status = "routing_budget_exhausted"`**. La corrección no es cambiar el operador: `finalize` ya no
deriva el hecho de un contador, lo lee de lo que el supervisor decidió (`routing_trail[-1]` apuntando a
`finalize` es la única ruta a ese nodo que no viene de la puerta humana). Derivar dos veces el mismo
hecho en dos módulos es lo que creó el bug.

**Una denegación del guard dentro de `estimate_generator` mataba la ejecución para siempre.** El
buscador y el validador capturan `ActionDeniedError` y degradan; el generador no lo hacía. Una
transcripción sin nada concreto hace que el clasificador devuelva cero componentes, el guard rechaza
—con razón— una llamada vacía a `calculate_estimate`, la excepción sube, el superstep aborta, no se
escribe `status` y **el checkpoint deja el hilo aparcado en ese nodo**: cada reintento del mismo
`estimation_id` falla igual y la puerta humana, que existe justo para ese caso, no se alcanza nunca.
Ahora degrada a una estimación sin valorar y el validador la manda al humano.

**La segunda búsqueda duplicaba la evidencia e inflaba la confianza que ella misma se comprobaba.**
`budget_matches` es un acumulador `operator.add` y la segunda pasada reemitía las consultas idénticas,
así que un análogo real contaba dos veces: `evidence_density` lo leía como cobertura completa y **una
ejecución que debía haberse parado para un humano pasaba la puerta con evidencia que ya tenía**.
Medido: 0.637 → 0.750 sin recuperar ni una fila nueva. Ahora el buscador salta los componentes ya
cubiertos, descarta filas repetidas y, en el reintento, **describe el componente de otra forma** (su
nombre y su tipo de trabajo en vez de la query en inglés) — porque repetir la consulta idéntica no es
una segunda opinión, que era justo lo que el prompt del supervisor prometía y el código no hacía.

**Dos componentes con el mismo nombre fusionaban sus referencias.** El agrupamiento iba por
`match["component"]`, el nombre. Un clasificador que llama «Integraciones» a un ERP y a un CRM hacía
que los dos recibieran la unión de ambas evidencias y se valoraran a la mediana del conjunto mezclado:
dos líneas mal, y un total que sigue cuadrando. Es la lección del `id` de la S13, un nivel más abajo de
donde se había aplicado: `BudgetMatch` ahora lleva `component_id` para los joins y `component` para lo
que lee el revisor.

Otros seis hallazgos no sobrevivieron a la verificación: el arranque del servicio con Postgres caído,
la regla de nombres duplicados del guard (vacua para este llamante pero no para el bucle de la S12),
el tope de cinco referencias de la tool, y la línea de auditoría de una tool que lanza.

## 8. Observabilidad

Un span por agente (`agent.<nombre>`) y uno por decisión de enrutado (`supervisor.route`), este último
con `next_agent` y `reason` como atributos — que es exactamente lo que se pierde si delegas el enrutado
en una abstracción. Los spans del modelo llevan `model`, `latency_ms`, `llm_cost_usd` y `total_tokens`
cuando el proveedor los reporta, así que «cuánto cuesta una estimación» es una consulta.

La ejecución del entregable costó **~0.069 USD**: 0.0064 (requisitos) + 0.0062 (componentes) + 0.0554
(la prosa, `gpt-5`) + 0.0014 (la única decisión de enrutado del modelo). El impuesto de enrutado es el
2% de la factura porque cuatro de los cinco saltos son reglas.

`scripts/run_graph_s14.py` conduce **las dos patas** —arranque y reanudación— dentro de un solo span
padre. Por HTTP son dos peticiones, y OpenTelemetry no puede unir dos trazas *a posteriori*: la
reanudación llega como un span raíz nuevo. Ambas patas llevan `estimation_id` como atributo, que es lo
que permite reconstruir la ejecución completa aunque se hayan lanzado por separado.

## 9. Limitaciones conocidas

- **El disparador de banda no puede saltar mientras las horas las ponga la tool y todos los componentes
  tengan precedente.** Es una propiedad, no un descuido (§6), pero significa que en la práctica la
  pausa la disparan la confianza y la falta de precedente. La banda sí hace su otro trabajo: es el marco
  de referencia del revisor dentro del payload.
- **La reanudación huérfana no tiene política.** Un hilo que se pausa y nadie decide se queda pausado
  para siempre. Caducidad y reasignación son de negocio, y el enunciado las difiere al directo.
- **El `interrupt()` es de uno en uno.** Si el directo abre un fan-out con varias puertas, el endpoint
  de reanudación tendrá que aceptar `{id: respuesta}` en vez de una decisión suelta.
- **`proximity` mide una distancia que no es comparable entre backends** (§6). Normalizarla contra la
  distribución observada sería más honesto que un umbral fijo.
- **El supervisor no reintenta una llamada de enrutado fallida.** Si el modelo no responde, la
  excepción sube y el endpoint devuelve 502. Correcto para el alcance de esta sesión, pero una
  degradación a «ir a la puerta humana» sería más amable.

## 10. Cómo reproducir

```bash
docker compose up -d --build
docker compose exec estimator python scripts/build_task_corpus.py --ingest

cd estimator
# Smoke barato: checkpointer en memoria y retrieval enlatado
uv run python scripts/run_graph_s14.py --memory --stub

# La ejecución del entregable (host, contra el stack; exercises/ no está en la imagen)
REDIS_URL=redis://localhost:6379 uv run python scripts/run_graph_s14.py \
    exercises/session-14/sample_transcript_edge_case.txt \
    --decision adjust --adjusted-hours 2400 \
    --out exercises/session-14/example_run_edge_case.txt

# El mismo recorrido por HTTP (pausa + reanudación)
curl -X POST localhost:8000/v1/estimate/graph -H "X-API-Key: $ESTIMATE_API_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"transcript": "...", "estimation_id": "EST-1"}'
curl -X POST localhost:8000/v1/estimate/graph/EST-1/resume -H "X-API-Key: $ESTIMATE_API_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"action": "adjust", "adjusted_hours": 1800, "reviewer_id": "u-42"}'

uv run pytest -q          # 547 tests, sin red y sin clave
uv run ruff check .
```

## 11. Criterios de aceptación

Traza en `estimator/exercises/session-14/example_run_edge_case.txt`:

- [x] **Supervisor a mano** con `StateGraph` + `Command`, sin `create_supervisor`; una sola arista
      declarada (`START → supervisor`) y **cada decisión de enrutado en la traza** (span
      `supervisor.route` con `next_agent` y `reason`) y en `routing_trail`.
- [x] **Mínimo privilegio**: una tool por especialista, ninguna para el supervisor ni para el extractor,
      declarado como dato, verificado en el arranque y comprobado en cada llamada.
- [x] **Estado tipado extendido** desde el de la S13, con cuatro acumuladores (`budget_matches`,
      `errors`, `proposals`, `routing_trail`).
- [x] El sistema corre de punta a punta y el endpoint devuelve la estimación con su `status`; el
      contrato hacia negocio es el de siempre.
- [x] **La pausa se dispara** con la señal de confianza (`0.636` frente al umbral `0.7`) y **persiste en el checkpoint** (`next = ['human_review_gate']` leído desde
      `GET .../state`); el endpoint devuelve `status = "awaiting_human_review"`.
- [x] **El endpoint de reanudación** continúa desde el checkpoint con la decisión humana: `adjust` a
      2400 h dejando en `original_total_hours` lo que dijo el sistema.
- [x] **Traza completa** de una ejecución que pasa por la pausa y se reanuda, en un único span padre.
