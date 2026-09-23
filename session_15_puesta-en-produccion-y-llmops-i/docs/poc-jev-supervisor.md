# PoC — Jev (TypeSafe) como router del supervisor

**Rama:** `session_15_poc-jev-supervisor`, sacada de `session_15_…` en `dcc047a`.
**Estado:** prueba de concepto. **No se lleva a producción y no continúa en la
S16**, que arranca de la rama de sesión. Lo que sobreviva de aquí tendrá que
portarse a mano, y este documento existe para que esa decisión se tome con lo
que se aprendió y no otra vez desde cero.

## Qué es Jev, y por qué no es "un modelo más"

Jev es un modelo de **decisión**. No devuelve texto: devuelve una elección, su
distribución de probabilidad y una confianza, por un endpoint propio.

```
POST {TYPESAFE_API_BASE}/v1/systemone
{ "state": "…", "model": "jev-latest",
  "questions": { "next_agent": { "type": "choice",
                                 "instructions": "…",
                                 "criteria": { "opcion_a": "…", "opcion_b": "…" } } } }
→ { "model": "jev-1.13.0"|null,
    "answers": { "next_agent": { "type": "choice", "choice": "…",
                                 "probabilities": {…}, "confidence": 0.82 } },
    "usage": { "input_tokens": 312, "output_tokens": 48 }|null }
```

De ahí sale casi todo lo demás:

- **No pasa por `LLMWrapper`.** `complete_structured` es
  `instructor.from_litellm(litellm.completion)`, una primitiva de *chat*, y no
  hay versión de LiteLLM en la que una llamada de chat alcance este endpoint.
  Enseñarle a `_provider_from_model` a contestar `"typesafe"` sólo habría hecho
  que `jev-latest` *pareciera* despachable: el wrapper manda todo lo que no es
  Anthropic con `OPENAI_API_KEY`.
- **`model` y `usage` son opcionales** en la respuesta. Por eso el cliente
  **omite** las claves de coste cuando faltan en vez de escribir `0.0`: un coste
  que se lee como cero es peor que uno ausente, porque un panel lo suma.
- **Los ids son tres**: `jev-latest`, `jev-1.13.0`, `jev-preview`. `jev-latest`
  resuelve hoy a `jev-1.13.0`.
- **Precio**: 0,042 US$ por millón de tokens de entrada, **sin cargo de salida**.
  Ese `0.00` de la tabla de precios es el precio real, no una fila sin rellenar.

## Transporte: por qué una llamada directa y no el proxy de LiteLLM

LiteLLM soporta Jev, pero **por su proxy** (`LITELLM_PROXY_BASE_URL/typesafe`).
Se evaluaron tres vías y ganó la directa, por este motivo:

> El proxy **no borra ni una línea** de código. Un *pass-through* reenvía el
> cuerpo idéntico, y LiteLLM no expone proveedor `typesafe` en el SDK — su
> propio cliente interno es este mismo POST. El cliente de ~50 líneas se escribe
> igual con proxy y sin él, mientras el contenedor añade un segundo custodio de
> las claves del proveedor, que es justo la frase con la que abre el
> `docker-compose.yml` de esta sesión.

Dos consecuencias que van al revés de la intuición habitual sobre pasarelas, y
que conviene no volver a discutir desde cero:

- **Observabilidad.** `logfire.instrument_httpx()` ya está cableado, así que la
  llamada directa se traza gratis **nombrando a `api.typesafe.ai`**. Un salto por
  proxy se ve como un span a un host interno con el proveedor escondido detrás.
- **Acoplamiento.** El pass-through no normaliza nada: con proxy seguirías
  cargando el esquema de TypeSafe **y además** las convenciones, la master key y
  el config schema de LiteLLM como segundo proveedor en la topología.

### Alternativas descartadas

| Vía | Por qué no |
|---|---|
| Proxy de LiteLLM (`/typesafe` pass-through) | Un sexto contenedor con su config, su key store y su modo de fallo, para una llamada. No elimina código. Rompe la frontera de red que esta sesión entrega como objetivo. |
| Cliente interno del SDK (`litellm.router_strategy.complexity_router.jev_classifier`) | Existe y está tipado, pero es una **ruta de módulo interna**, en movimiento (backports abiertos, fix de precios sin mergear). Obligaría a saltar litellm 1.86.1 → ≥1.102.1 por debajo de Instructor, moviendo `openai`/`httpx`/`tokenizers` bajo **todas** las demás llamadas. Y sigue siendo un POST directo. |
| OpenRouter (`POST /api/alpha/decisions`) | Id distinto (`typesafe/jev-1.13`, sin el `.0`) y endpoint marcado **alpha**. |

### Pasarelas que SÍ sirven este mismo contrato

No son alternativas descartadas: son la misma vía directa con otra puerta, y
funcionan **sin tocar código** porque el cliente compone `f"{api_base}/v1/systemone"`.

| Puerta | `TYPESAFE_API_BASE` | Clave | Id del modelo |
|---|---|---|---|
| TypeSafe directo | `https://api.typesafe.ai` | de TypeSafe ([console.typesafe.ai/keys](https://console.typesafe.ai/keys), lista de espera) | `jev-latest` |
| AI Gateway de Vercel | `https://ai-gateway.vercel.sh/typesafe` | del Gateway (o token OIDC de Vercel) | `typesafe-ai/jev` |

**Lo único que cambia además de las dos variables es el id del modelo**, porque
el Gateway usa su convención `proveedor/modelo`. Por eso `is_decision_model`
compara sobre el nombre ya normalizado: quitado el prefijo, ambos empiezan por
`jev` y una sola regla cubre las dos puertas.

La pasarela además contabiliza la llamada, y publica **dos** importes. De los
dos se coge `marketCost`, no `cost`, y la diferencia se midió en vivo:

```
"cost":       "0"           ← lo FACTURADO: 0, porque la cuenta tiene créditos gratis
"marketCost": "0.00001302"  ← lo que VALE la llamada
```

Coger el facturado dejaría `cost_usd` en cero, que es justo el bug que este repo
tiene documentado dos veces: un cero es un número y un panel lo suma. Peor aún
para este PoC en concreto — el A/B contra `gpt-5-mini` compararía 0 contra
0,00026 y no diría nada. Manda la tarifa, y el descuento se anota aparte en
`billed_usd`, porque es un dato de la cuenta y no del modelo.

De paso: `marketCost` coincidió al céntimo con `MODEL_COSTS` (310 tokens →
0,00001302), así que la tabla curada a mano está bien.

**El salto de versión de litellm no hace falta.** El manifiesto dice `>=1.50` y
el lock fija 1.86.1, pero por la vía directa `uv.lock` no se mueve: `httpx>=0.27`
ya era dependencia de producción.

**Migrar a una pasarela cuesta dos variables de entorno.** El cliente construye
`f"{api_base}/v1/systemone"` y nunca un host escrito a mano, así que una
pasarela en la S16 es `TYPESAFE_API_BASE=http://litellm-proxy:4000/typesafe` más
cambiar el bearer. Sin tocar código. Es un requisito, no una casualidad.

## Dónde entra, y qué se cambió para que entrara

La única llamada a modelo del supervisor ya era una pregunta cerrada entre dos
destinos — exactamente la forma que Jev consume. Tres cambios:

1. **Un puerto en vez de un cliente.** `build_supervisor` recibe `ask_router`,
   un callable que devuelve `(agente, motivo, meta)`, igual que ya recibía
   `search_tool` y `validate_tool`. El grafo no aprende que existe TypeSafe.
2. **El modelo se resuelve en cada decisión.** Antes se leía al cablear, y el
   grafo se compila una vez por proceso: un override desde Ajustes se guardaba
   en Redis y no cambiaba nada, en silencio, contra el contrato de "sin
   reinicio" que anuncia el propio endpoint de configuración.
3. **La pregunta se parte** en `instructions`, `criteria` y sesgo.
   `compose_supervisor_prompt` la vuelve a juntar para la ruta de texto, así que
   no hay una paráfrasis al lado del original para desincronizarse.

Los 89 tests del grafo pasaron **sin tocar una aserción**, que es la
comprobación de que las precondiciones, el presupuesto de routing y la guarda de
`AGENT_NAMES` nunca dependieron del modelo.

## Las tres trampas que costaron el diseño

**1. Caer al `human_review_gate` NO significa que mire una persona.**
Era el fallback del primer diseño y es un error. `build_human_review_gate` es
una pausa **condicional**: si no salta ninguno de sus tres triggers devuelve
`Command(goto="finalize")`. Medido contra el código real: con 10 componentes, 9
respaldados, `is_coherent=False` y confianza **0.887** (umbral 0.7),
`requires_human_review()` devuelve `[]`. Es decir, una caída de TypeSafe habría
terminado runs en silencio, con `status="needs_review"` y un 200 —
indistinguible de una decisión legítima, y con la UI afirmando que "decidió el
modelo". El fallback correcto es la ruta `structured_call` que ya existe, y se
**nombra en el motivo** para que una caída nunca se parezca a una decisión.

**2. La ruta de LECTURA no estaba guardada.** `RuntimeModelConfig.effective()`
es `get(key) or default(key)`, sin revalidar, y el PUT sólo valida al escribir.
Un override `jev-*` puesto con la clave configurada **sobrevive a un reinicio sin
ella**. Sin la guarda, ese nombre llegaría a `litellm.completion`.

**3. El orden de despliegue falla en el sitio equivocado.** `actions.ts` manda
todos los knobs en cada guardado y el PUT valida las claves antes de escribir,
de una pieza. Si `modelKnobs` (cliente) se adelanta a `MODEL_KEYS` (servicio),
el 422 **deja la pantalla entera sin poder guardar**, también los siete knobs de
siempre. Python primero, siempre.

## El motivo, que es lo que Jev no devuelve

`reason` no lo lee ningún código Python — `finalize` sólo mira
`trail[-1]["next_agent"]`. Su único consumidor es la persona que abre la tabla
de auditoría. Un modelo de texto escribe ahí frases como:

> *"Only 3 of 13 items lack historical matches while the budget search already
> returned 36 matches overall, suggesting a retrieval/wording gap rather than
> novel work…"*

Jev no escribe nada de eso. Así que el motivo se **construye en Python** desde el
estado (`routing_facts`) y se le pega la elección y su probabilidad:

> `3 componentes, 1 referencias, confianza 0.49, 1 avisos del validador; jev-latest enrutó a human_review_gate (p=0.85)`

La mitad que importa **no puede estar mal**, porque nada la generó: un modelo
puede equivocarse contando componentes sin respaldo, `len()` no. Se pierde la
frase de inferencia; se gana un conteo que no se alucina.

## Lo que este PoC NO resuelve

- **No hay circuit breaker.** LiteLLM envuelve esta misma llamada con
  `timeout_ms=3000` y un corte de 30 s; aquí sólo hay `GRAPH_SUPERVISOR_TIMEOUT`
  (30 s, diez veces más). Una caída degrada bien, pero reintenta en cada run.
- **El coste vive sólo en las trazas.** Con el AI Gateway de Vercel delante sí
  hay libro de gasto —el suyo, en su panel de observabilidad—, pero dentro de
  este servicio sigue sin haberlo: `SupervisorRun` no tiene columna de modelo. Lo que sí
  hay ahora es **qué router decidió cada salto**, en `routing_trail`, que es el
  mínimo para poder comparar dos routers sobre runs guardados.
- ~~**No se ha llamado a la API real.**~~ **Verificado en vivo el 2026-09-23**
  contra el AI Gateway de Vercel: el parseo, el mapeo de `usage` y la
  contabilidad son correctos. Ver «Qué dijo la API real» más abajo. Contra
  `api.typesafe.ai` directo sigue sin probarse (hace falta salir de su lista de
  espera), pero el contrato es el mismo.
- **`0,00` de salida se lee como "gratis".** Es el precio correcto ("no se
  cobra"), pero en una pantalla cuyo trabajo es decir lo que cuesta un knob, esa
  distinción no se ve. La tarifa de entrada sí se arregló: se mostraba `0,04`
  porque el formateador tenía dos decimales.
- **El resto de knobs del grafo siguen congelados al arrancar**
  (`REFORMULATION_MODEL`, `GENERATION_MODEL`, `GRAPH_PROPOSAL_MODEL`…). El del
  supervisor es el primero en caliente, y `estimator/CLAUDE.md` afirma de los dos
  primeros que ya lo eran — **no lo son**. Sigue siendo falso después de este
  PoC.

## Qué dijo la API real

Dos estados reales del supervisor, contra `typesafe-ai/jev` por el AI Gateway:

| Estado | Eligió | p | Confianza | Tokens |
|---|---|---|---|---|
| 13 componentes, 3 sin respaldo, 36 referencias | `human_review_gate` | 0,73 | 0,46 | 588 |
| 12 componentes, 0 con respaldo, 0 referencias | `human_review_gate` | 0,80 | 0,60 | 593 |

Y el motivo que acaba en la tabla de auditoría:

> `12 componentes, 0 referencias, confianza 0.31, 2 avisos del validador; typesafe-ai/jev enrutó a human_review_gate (p=0.80)`

Tres observaciones de la ejecución real:

1. **Los tres ids funcionan** por la pasarela — `typesafe-ai/jev`, `jev` y
   `jev-latest` —, todos resueltos a `typesafe-ai/jev` en la metadata de routing.
2. **La entrada cuesta el doble de lo estimado.** El digest son ~300 tokens, pero
   con las instrucciones, los criterios y la guarda de inyección la petición sale
   por ~590. Sigue siendo 0,000023 US$.
3. **Las probabilidades son menos extremas de lo esperado.** 0,73 y 0,80 donde un
   caso de manual da 1,00 — el sesgo hacia el gate humano está escrito en las
   instrucciones y se nota, pero no aplasta la señal. El caso claramente peor
   (cero precedentes) sí sale más arriba, que es lo que se querría.

Lo que NO se ha podido comprobar en vivo: que elija `budget_searcher`. Ninguno de
los dos estados lo provocó, y forzarlo pedía un corpus que aquí no hay.

## Qué diría este PoC sobre llevarlo a producción

Que el ahorro no es el argumento. Sobre los runs reales guardados en el
checkpointer, la rama que llama al modelo se dispara en **3 de 6 runs**, nunca
más de una vez por run, y cuesta ~0,00026 US$ con `gpt-5-mini` frente a
~0,00003 con Jev: **unos 8.000 runs para ahorrar un dólar**, sobre un run que
paga `gpt-5` a `reasoning_effort=high`. Es ~1 % del gasto de una estimación.

Lo que sí deja, y vale por sí solo, es el **knob del supervisor en caliente**:
que el modelo del router se pudiera cambiar desde Ajustes sin reiniciar era un
defecto real, y se arregla con `gpt-5-mini` y `gpt-5` como opciones, exista Jev
o no.
