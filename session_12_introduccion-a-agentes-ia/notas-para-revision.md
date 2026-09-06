# Notas para la revisión — Sesión 12

Pre-work de la Sesión 12: un **agente de estimación hecho a mano**, con bucle manual sobre la
Responses API de OpenAI, sin framework. Este documento recoge el alcance, las decisiones de diseño,
las desviaciones respecto al enunciado y lo que la ejecución real enseñó — que fue lo más
instructivo del ejercicio.

Todo el código va en inglés (nombres, comentarios, logs, prompts, descripciones de tools), como pide
el enunciado; esta prosa, en español.

---

## 1. Alcance

El enunciado marca el pre-work: dos tools obligatorias (`search_budgets`, `calculate_estimate`), la
tercera opcional (`validate_estimate`), el bucle conducido a mano y una traza que deje ver el
razonamiento paso a paso. Está implementado todo, incluida la opcional.

Fuera de alcance por ser material del directo: endpoint HTTP, UI y comparación sistemática
pipeline-vs-agente.

## 2. Qué se ha construido

```
app/generation/agentic/
├── agent_schemas.py   # args de tools, AgentStep/AgentTrace con render(), AgentEstimate
├── agent_tools.py     # 3 schemas planos strict:true + implementaciones + dispatch_tool
└── agent_loop.py      # run_estimation_agent: el bucle razona → actúa → observa
scripts/run_agent_s12.py                   # CLI (--model/--effort/--max-iterations/--stub/--out)
tests/generation/agentic/                  # 19 tests, sin red
```

Modificados: `app/config.py` (knobs `AGENT_*`), `app/dependencies.py`
(`get_async_openai_client`, `get_budget_search_backend`).

## 3. Decisiones de diseño

**El backend de retrieval se inyecta, no se importa.** `ARCHITECTURE.md` §3 prohíbe que un hermano
de `generation` importe a otro, y `search_budgets` necesita el retrieval de `generation/rag`. La
capa agéntica declara la costura (`BudgetSearchBackend`, un callable) y el composition root
(`dependencies.py`, que sí puede alcanzar todo) la rellena. De paso, esa misma costura es la que
`--stub` intercambia por el fichero enlatado del kit.

**Excepción deliberada a `LLMWrapper`.** Es el único sitio del repo que habla con la Responses API
en crudo. El objetivo del ejercicio es ver el bucle; cualquier envoltorio —incluido el nuestro— tapa
justo la parte que hay que ver. Documentado en el docstring del módulo para que nadie lo "arregle".

**Encadenado con estado** (`store=True` + `previous_response_id`, enviando solo los
`function_call_output` nuevos). El servidor conserva el orden de los items de razonamiento, que es
donde se rompe la variante manual con modelos de razonamiento. Contrapartida asumida:
`instructions` no viaja con `previous_response_id`, así que se reenvía en cada llamada.

**Mediana, no media**, en `calculate_estimate`. El corpus mezcla tamaños de proyecto y un análogo
sobredimensionado arrastra la media. Hay un test con un outlier de 2800h que lo fija.

**Los errores de tool vuelven al modelo como observación**, no se propagan. Un argumento mal formado
o un corpus vacío son recuperables por el propio agente; romper el bucle tiraría todos los pasos
anteriores.

**Traza tipada, no `print`s.** `AgentStep`/`AgentTrace` son modelos Pydantic con `render()`. Cuando
el modelo pide varias tools en una vuelta, todos esos pasos comparten el razonamiento de esa vuelta
(razonó una vez y se abrió en abanico): el dato se guarda en cada paso, pero el render lo muestra
una vez y los repetidos apuntan al primero. Repetir tres párrafos idénticos hacía la traza ilegible.

## 4. Desviación respecto al kit: la granularidad de las referencias

El README del kit dice que `search_budgets` filtre por `chunk_type='historical_task'`. **Se filtra
por ahí, pero agregando por módulo**, y esa es la decisión de fondo del ejercicio.

El corpus es una fila por **tarea** (17–47h). Lo que una reunión de descubrimiento llama
"componente" —un backend de negocio, una integración con el ERP, una app de repartidores— es un
**subsistema**, no una tarea. Como `calculate_estimate` hace la mediana de las referencias que
recibe, alimentarlo con horas de tarea tasa una integración SAP en ~30h.

El corpus ya trae la unidad correcta: cada tarea lleva su `module` (`Fleet & Routing`,
`Data & Integrations`, `Analytics & Reporting`), y **un módulo de un proyecto pasado es un
subsistema**. Así que el retrieval busca tareas y el adaptador devuelve una referencia por cada
(proyecto, módulo) al que pertenecen, valorada en la **suma de todas las tareas de ese módulo**: un
coste real y auditable, no una extrapolación.

Nota verificada: la traza de referencia del kit (`example_trace_complex.txt`) se generó con
`--stub`, no con retrieval real — sus números (940, 1150, 780, 560, 860, 720, 430) son exactamente
los del corpus enlatado. Por eso la implementación de referencia nunca se topó con este desajuste.

## 5. Lo que enseñó la ejecución real

El bucle funcionó a la primera contra la API. Lo que costó cuatro iteraciones fue la **calidad de
las instrucciones**, que es exactamente lo que el enunciado avisa en sus *pitfalls*: cuando el
agente hace algo raro, casi siempre es la descripción, no el modelo.

| Síntoma observado | Causa real | Arreglo |
|---|---|---|
| `stop=max_iterations`, 14 búsquedas para 4 componentes | El prompt invitaba a re-buscar sin regla de parada | Máximo dos búsquedas por componente, explícito |
| El modelo repetía búsquedas vacías | La pista de qué hacer iba en `observation`, que **el modelo no lee** | El `hint` va en el `output` de la tool |
| Backend sin resultados, panel con uno | El corpus está **en inglés** y el agente consultaba en español (0 resultados frente a 5 a distancia 0,519) | La descripción de la tool le pide consultar en inglés |
| Descartaba análogos válidos y declaraba "sin respaldo" | Mi prompt decía "si no encuentras nada **comparable**, acéptalo": un listón de estrictez que nunca definí | Los ítems recuperados *son* la evidencia; un análogo de otro sector cuenta y se declara el desajuste |

## 6. Un fallo encontrado por revisión adversarial

Antes de dar la traza por buena se pasó el código por una revisión con cinco lentes independientes
(corrección contra el SDK real, control de flujo, reglas de capas, semántica de las tools,
cumplimiento del enunciado), cada una seguida de un escéptico que intentaba refutar sus hallazgos.

Cuatro hallazgos sobrevivieron y están corregidos, todos con test de regresión:

1. **`max_iterations` dejaba llamadas sin contestar.** El bucle pedía una vuelta de tools que ya no
   tenía presupuesto para responder y encadenaba el cierre sobre ella; si esa respuesta traía
   `function_call` sin su `function_call_output`, la API la rechaza (*"No tool output found for
   function call"*) y se pierde la traza justo cuando la salvaguarda debía salvarla. Además
   `trace.iterations` mentía: con `max_iterations=3`, 3 iteraciones registradas y 4 llamadas reales.
   Ahora los `function_call_output` pendientes viajan con la llamada de cierre.
2. **`output_parsed` puede ser `None`.** En el SDK es `Optional`: vale `None` ante un rechazo o una
   respuesta `incomplete` — el caso real de un modelo de razonamiento que gasta su presupuesto de
   salida en tokens de razonamiento. Se devolvía como si fuera un `AgentEstimate` y habría reventado
   como `AttributeError` al renderizar, a varios frames de la causa. Ahora lanza `AgentRunError`
   **con la traza dentro**, y el CLI la imprime igual antes de salir con código de error: la parte
   cara de la ejecución no se tira por un fallo en la barata.
3. **`validate_estimate` reimplementaba la fórmula de coste.** Su comprobación estrella —"el total
   no cuadra con la suma de sus partes"— era circular: recalculaba la mediana y se comparaba consigo
   misma, así que habría aprobado una fórmula equivocada. Y el test lo tapaba, porque pasaba la misma
   lista por ambas funciones (eso pasa con *cualquier* fórmula compartida). Ahora recibe el desglose
   que produjo `calculate_estimate` y juzga esos números.
4. **Una primera vuelta sin tool no es una parada natural.** Si el modelo responde directo desde la
   transcripción, salía con `stop=natural` y cero pasos: una estimación sin una sola llamada a tool
   detrás, indistinguible de un trabajo terminado. Ahora es `no_tool_calls`.

## 6.1 Cobertura

`agent_loop.py`, `agent_schemas.py` y `agent_tools.py` al **100%** de línea; 38 tests, todos sin red.

El primer informe daba 96% y era engañoso: el adaptador que hace el trabajo real
(`get_budget_search_backend`, ~60 sentencias) vive en el composition root, no en el paquete
`agentic`, así que no entraba en el informe — y estaba al **0%**. Contándolo, la cobertura de
partida era del 75%. Los defectos 2 y 3 de arriba vivían justo en esos huecos.

```bash
uv run --with pytest-cov python -m pytest tests -q \
    --cov=app.generation.agentic --cov=app.dependencies --cov-report=term-missing
```

## 7. Limitaciones conocidas

- **El corpus no tiene apps móviles.** Sus módulos son de backend, así que la app de repartidores
  queda `NOT GROUNDED` en la traza entregada. El agente lo declara en vez de inventar un número, que
  es el comportamiento correcto, pero es una laguna del corpus, no del agente.
- **Calibración.** Los módulos del corpus sintético son pequeños (40–125h), así que el total sale
  modesto para una plataforma de este tamaño. Es coherente consigo mismo y trazable fila a fila,
  pero no es una tarifa de mercado.
- **Sin endpoint ni UI**: el agente se ejecuta por CLI. El backend de negocio no lo ve, tal como
  pide el alcance del pre-work.
- **Reranker desactivado** por defecto (`RERANKER_ENABLED=false`), así que el retrieval del agente
  va en modo vectorial. Con el cross-encoder activo mejoraría, a costa de latencia.

## 8. Cómo reproducir

```bash
# 1. Stack + corpus (una vez)
docker compose up -d --build
docker compose exec estimator python scripts/build_task_corpus.py --ingest

# 2. Depuración barata del bucle, sin base de datos
cd estimator
uv run python scripts/run_agent_s12.py \
    exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --stub

# 3. La ejecución del entregable (host, contra el stack)
REDIS_URL=redis://localhost:6379 uv run python scripts/run_agent_s12.py \
    exercises/session-12/sample_transcript_complex.txt --model gpt-5 --effort medium \
    --out exercises/session-12/trace_complex.txt

# 4. Tests (sin red) y cobertura
uv run python -m pytest tests/generation/agentic -q
uv run --with pytest-cov python -m pytest tests -q \
    --cov=app.generation.agentic --cov=app.dependencies --cov-report=term-missing
```

`REDIS_URL` se sobreescribe porque el valor del `.env` (`redis://redis:6379`) solo resuelve dentro
de la red de Docker; desde el host es `localhost`. Sin él todo funciona igual, pero la config de
runtime cae a los defaults con un warning por llamada.

## 9. Criterios de aceptación

Sobre `sample_transcript_complex.txt`, traza en `estimator/exercises/session-12/trace_complex.txt`:

- [x] Identifica más de un componente (4) y hace más de una llamada a `search_budgets` (6).
- [x] Llama a `calculate_estimate` con los componentes y sus referencias.
- [x] Termina por sí solo (`stop=natural`, 6 iteraciones; el tope de 10 no llegó a tocarse).
- [x] Produce una estimación estructurada coherente (`AgentEstimate` validado).
- [x] La traza muestra, para cada paso, razonamiento + acción + observación.
