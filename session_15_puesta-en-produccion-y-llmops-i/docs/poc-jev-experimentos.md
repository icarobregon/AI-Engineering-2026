# PoC Jev — los tres escenarios medidos

Índice de las seis ejecuciones que sostienen las conclusiones del PoC. El diseño
y las alternativas descartadas están en [`poc-jev-supervisor.md`](poc-jev-supervisor.md);
esto es sólo la evidencia.

Todas se lanzaron desde la interfaz el 2026-09-23 contra la misma versión del
servicio, cambiando entre medias un único ajuste: el modelo del supervisor, desde
la pantalla **Ajustes**. El Run A de cada escenario tuvo que terminar antes de
tocar el knob, porque el modelo se resuelve en cada decisión y cambiarlo a mitad
habría contaminado la ejecución.

## La variable que lo gobierna todo

Los tres escenarios se distinguen por una sola cosa: **cuánto del encargo puede
respaldar el corpus histórico**. Esa cobertura decide si el supervisor llega a
tener algo que preguntar.

| | CANTERA | ALTAIR | TORNAVOZ |
|---|---|---|---|
| Encargo | plataforma de formación | observatorio astronómico | restauración de un órgano de 1748 |
| Componentes respaldados | 24/24 · 16/16 | 11/13 · 10/13 | 1/12 · **0/21** |
| Confianza | 0,877 · 0,884 | 0,693 · 0,646 | 0,071 · **0,000** |
| Reservas del validador | 0 · 0 | 2 · 3 | 11 · 22 |
| Estado final | `validated` | `awaiting_human_review` | `awaiting_human_review` |
| ¿Se consultó al router? | **No** | Sí, una vez | Sí, una vez |
| Latencia del salto | 0,01 · 0,06 s | 9,12 · 1,17 s | 8,48 · 1,02 s |
| Coste del salto (US$) | 0 · 0 | 0,001396 · 0,0000265 | 0,001319 · 0,0000371 |
| Horas estimadas | 2608,9 · 1766,0 | 1066,4 · 907,0 | 82,8 · **0,0** |

En cada casilla, primero el run con `gpt-5-mini` como router y después el run con
`typesafe-ai/jev`.

## Informes

Tres páginas publicadas, enlazadas entre sí:

1. **Nadie preguntó al modelo** — CANTERA · <https://claude.ai/artifact/K9k6fothc7VRYfkhG2312N>
2. **Dos routers, una decisión** — ALTAIR · <https://claude.ai/artifact/RgcWQQjFWT6A7q56BBu9dp>
3. **Cero horas, y con razón** — TORNAVOZ · <https://claude.ai/artifact/2NmPbdw2kCnzPz8z7qzbu8>

## Trazas de Logfire

Públicas y sin caducidad. Se revocan desde el panel de Logfire, en el control de
compartición de cada traza.

| Escenario | Router | `estimation_id` | Traza |
|---|---|---|---|
| CANTERA | gpt-5-mini | `d4d715b2-2a70-469a-a54b-c6a36a81b8cc` | <https://logfire-eu.pydantic.dev/public-trace/186f1505-adf6-430b-abbd-a33709e1e5c5> |
| CANTERA | typesafe-ai/jev | `e5953913-9630-4488-9626-249ad6181491` | <https://logfire-eu.pydantic.dev/public-trace/802fa450-fe87-43e7-874e-f5b517d33416> |
| ALTAIR | gpt-5-mini | `9700da27-1153-4d61-8514-61bc4d1099fd` | <https://logfire-eu.pydantic.dev/public-trace/b648a037-1316-4108-865f-40cddcde5c12> |
| ALTAIR | typesafe-ai/jev | `78e96600-7479-4daf-8f1e-1fde7c159424` | <https://logfire-eu.pydantic.dev/public-trace/2c72b965-cc32-454a-84a6-8e4ff3a5b910> |
| TORNAVOZ | gpt-5-mini | `2f3bb32d-9a52-4710-b0f4-e5f3627b9cad` | <https://logfire-eu.pydantic.dev/public-trace/4468cd2b-8358-48db-98df-d3e6ec195432> |
| TORNAVOZ | typesafe-ai/jev | `39818b49-1795-4619-a162-ddb245d7d7f5` | <https://logfire-eu.pydantic.dev/public-trace/5988f2e5-36a1-4524-b2ce-d4defd594520> |

Dentro del servicio, el correlador es el atributo `estimation_id` del span raíz
`estimation graph run (detached)`. En el SQL Workbench de Logfire:

```sql
select start_timestamp, attributes->>'model' as router,
       attributes->>'next_agent' as decision,
       round(duration::numeric, 2) as segundos, attributes->>'reason' as motivo
from records
where span_name = 'supervisor.route' and attributes->>'model' is not null
order by start_timestamp
```

## Transcripciones y logs

| Escenario | Transcripción | Log del contenedor |
|---|---|---|
| CANTERA | [`sample_transcript_formacion.txt`](../estimator/exercises/session-15/sample_transcript_formacion.txt) | [`evidencia-poc-jev-cantera.txt`](evidencia-poc-jev-cantera.txt) |
| ALTAIR | [`sample_transcript_observatorio.txt`](../estimator/exercises/session-15/sample_transcript_observatorio.txt) | [`evidencia-poc-jev-altair.txt`](evidencia-poc-jev-altair.txt) |
| TORNAVOZ | [`sample_transcript_organo.txt`](../estimator/exercises/session-15/sample_transcript_organo.txt) | [`evidencia-poc-jev-tornavoz.txt`](evidencia-poc-jev-tornavoz.txt) |

Los logs están acotados a la ventana de cada prueba, separados por ejecución
mediante el `request_id`, y limpios de healthchecks y del sondeo de `/progress`
y `/state`. Sólo escribe `ai-service`: el backend de negocio no emitió una sola
línea en ninguna de las tres ventanas.

## Qué NO demuestran estos datos

- **Son dos ejecuciones por escenario.** Las medidas de latencia y coste del salto
  son sólidas —es el mismo nodo, cronometrado por el checkpointer, y el span HTTP
  saliente las corrobora—, pero que los dos routers coincidieran en las cuatro
  consultas es una observación, no una calibración.
- **La varianza entre ejecuciones idénticas es el hallazgo incómodo.** Medida
  siempre igual, como diferencia en horas sobre la ejecución mayor: 32 % en
  CANTERA, 15 % en ALTAIR y 100 % en TORNAVOZ. El troceado en componentes no es
  estable, y eso pesa mucho más que la elección de router.
- **CANTERA está construido para salir bien** (la transcripción se escribió leyendo
  antes el corpus) y **TORNAVOZ para salir mal** (un órgano barroco no puede tener
  precedente en un corpus de software). Miden los bordes, no el caso medio.
- **Falta el caso peligroso**: un encargo de software de un tipo que el corpus no
  tenga, pero lo bastante cercano en vocabulario como para devolver
  correspondencias *equivocadas* con distancia baja. Ahí el sistema no diría cero:
  diría un número, y estaría mal.
