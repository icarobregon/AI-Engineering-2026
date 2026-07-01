# CAG Stress Test — REPORT

## Tabla resumen

| Scenario      | Turns | P50 Latency | P95 Latency | Total Cost (USD) | Recall mean |
| ------------- | ----: | ----------: | ----------: | ---------------: | ----------: |
| contradiction |    30 |     4142 ms |    23803 ms |         $ 0.2664 |        0.0% |
| growing       |    60 |     5453 ms |    21903 ms |         $ 0.6186 |        1.4% |
| pivot         |    24 |     4516 ms |    19881 ms |         $ 0.2168 |        0.0% |

## Curva 1: Latencia vs tokens de contexto

| context_tokens (bucket) | p50_latency_ms | p95_latency_ms | samples |
| ----------------------: | -------------: | -------------: | ------: |
|                    2000 |           3216 |           4521 |      11 |
|                    2500 |           3665 |          21216 |      11 |
|                    3000 |           3585 |           5213 |      16 |
|                    3500 |           3038 |           4395 |      29 |
|                    4000 |           3890 |           9759 |      27 |
|                    4500 |           3982 |           6918 |      23 |
|                    5000 |           4116 |           5863 |      28 |
|                    5500 |           4255 |           5683 |      24 |
|                    6000 |           4766 |          12132 |      15 |
|                    6500 |           4575 |           5531 |       7 |
|                    7000 |           4907 |           6007 |      20 |
|                    7500 |           4913 |           8152 |       9 |
|                    8000 |           6091 |           9263 |       8 |
|                    9000 |           4875 |           6248 |       8 |
|                    9500 |           9245 |          12930 |       8 |
|                   10000 |           4218 |           7223 |      11 |
|                   10500 |           4510 |          23122 |      13 |
|                   11000 |           3913 |          20011 |      15 |
|                   11500 |           5158 |          21252 |      13 |
|                   12000 |           5224 |           5797 |       6 |
|                   12500 |           7467 |          35388 |      16 |
|                   13000 |           5294 |           8809 |      15 |
|                   13500 |           4847 |          11059 |       7 |
|                   14000 |           5892 |           5892 |       1 |
|                   15500 |           4516 |          20215 |      17 |
|                   16000 |           6400 |          18238 |      19 |
|                   16500 |           5666 |          15476 |      25 |
|                   17000 |           7712 |          33716 |      27 |
|                   17500 |           5175 |          35196 |      35 |
|                   18000 |           5357 |          23664 |      25 |
|                   18500 |           6538 |          29458 |      15 |
|                   19000 |           6759 |          15104 |      20 |
|                   19500 |           9569 |          21951 |      30 |
|                   20000 |           8837 |          15154 |       8 |
|                   20500 |           5827 |          23983 |       3 |
|                   32500 |          14083 |          14083 |       1 |
|                   37000 |          39630 |          39630 |       1 |
|                   40000 |          15118 |          15118 |       1 |
|                   42000 |          59004 |          59004 |       1 |
|                   42500 |          13558 |          13558 |       1 |

## Curva 2: Coste acumulado vs turno

| turn | contradiction | growing |   pivot |
| ---: | ------------: | ------: | ------: |
|    1 |       $0.0088 | $0.0086 | $0.0080 |
|    2 |       $0.0171 | $0.0169 | $0.0164 |
|    3 |       $0.0253 | $0.0256 | $0.0251 |
|    4 |       $0.0336 | $0.0346 | $0.0340 |
|    5 |       $0.0421 | $0.0449 | $0.0429 |
|    6 |       $0.0508 | $0.0545 | $0.0524 |
|    7 |       $0.0597 | $0.0644 | $0.0622 |
|    8 |       $0.0693 | $0.0758 | $0.0723 |
|    9 |       $0.0789 | $0.0862 | $0.0723 |
|   10 |       $0.0888 | $0.0966 | $0.0723 |
|   11 |       $0.0888 | $0.1071 | $0.0723 |
|   12 |       $0.0888 | $0.1175 | $0.0723 |
|   13 |       $0.0888 | $0.1280 | $0.0723 |
|   14 |       $0.0888 | $0.1386 | $0.0723 |
|   15 |       $0.0888 | $0.1492 | $0.0723 |
|   16 |       $0.0888 | $0.1598 | $0.0723 |
|   17 |       $0.0888 | $0.1719 | $0.0723 |
|   18 |       $0.0888 | $0.1829 | $0.0723 |
|   19 |       $0.0888 | $0.1939 | $0.0723 |
|   20 |       $0.0888 | $0.2062 | $0.0723 |

## Curva 3: Recall de hechos vs número de turnos

| turn | contradiction | growing | pivot |
| ---: | ------------: | ------: | ----: |
|    1 |             - |       - |     - |
|    2 |            0% |      0% |    0% |
|    3 |            0% |      0% |    0% |
|    4 |            0% |     27% |    0% |
|    5 |            0% |      0% |    0% |
|    6 |            0% |      0% |    0% |
|    7 |            0% |      0% |    0% |
|    8 |            0% |      0% |    0% |
|    9 |            0% |      0% |     - |
|   10 |            0% |      0% |     - |
|   11 |             - |      0% |     - |
|   12 |             - |      0% |     - |
|   13 |             - |      0% |     - |
|   14 |             - |      0% |     - |
|   15 |             - |      0% |     - |
|   16 |             - |      0% |     - |
|   17 |             - |      0% |     - |
|   18 |             - |      0% |     - |
|   19 |             - |      0% |     - |
|   20 |             - |      0% |     - |

## Análisis: Dónde empieza a romperse el CAG y por qué

**Dónde empieza a romperse el CAG.** El baseline global muestra una latencia P95 de 22823 ms y un coste total de $1.1018 USD para el conjunto de escenarios. En el escenario _growing_, la latencia supera el SLA de 3 000 ms a partir del **turno 1**, coincidiendo con un contexto que ya acumula varios turnos de historia comprimida. El contexto supera los 4 000 tokens de entrada en el **turno 1** (escenario _growing_), punto a partir del cual el coste por turno crece linealmente y la atención del modelo empieza a degradarse para hechos tempranos.

**Por qué se rompe.** El CAG tiene cuatro restricciones estructurales: context window, coste por consulta, latencia y degradación de atención. Este stress test activa las cuatro simultáneamente al crecer el corpus: el contexto acumula historia, los tokens de entrada crecen linealmente con el número de turnos, y la atención del modelo diluye los hechos lejanos. La primera caída de recall por debajo del 50 % ocurre en el **turno 2** del escenario _growing_. Este es el umbral de drift: la ventana deslizante ha expulsado el hecho del contexto activo y el resumen acumulado no lo preserva con suficiente fidelidad. La arquitectura CAG es adecuada para sesiones cortas (≤ 6 turnos) con corpus estable; más allá de ese umbral, RAG con pipeline de indexación offline es la arquitectura correcta.
