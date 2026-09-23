/**
 * Los espejos zod de los schemas de Pydantic.
 *
 * No prueban zod: prueban que ESTE espejo coincide con el contrato que el
 * servicio IA emite de verdad. Es la red que ya pescó un fallo real —el espejo
 * de `Assumption` estaba inventado como `{text}` cuando el contrato es
 * `{description, impact, rationale}`— y lo convirtió en un mensaje en pantalla
 * en lugar de en una página en blanco tres componentes más abajo.
 */

import { describe, expect, it } from "vitest";

import {
  agentCanRun,
  hopSource,
  agentTraceSchema,
  corpusStatsSchema,
  estimateTreeSchema,
  reformulationSchema,
  taskHoursResultSchema,
} from "./contracts";

describe("corpusStatsSchema", () => {
  it("acepta la foto del corpus tal y como la emite el servicio", () => {
    const real = {
      collections: [{ collection: "budget", documents: 77, chunks: 1603, hnsw_indexed: false }],
      total_documents: 77,
      total_chunks: 1603,
    };

    expect(corpusStatsSchema.parse(real)).toEqual(real);
  });

  it("rechaza un hnsw_indexed que no sea booleano", () => {
    // Es el dato que decide si la pantalla dice «recorrido secuencial». Un
    // string "false" sería truthy y diría lo contrario de lo que pasa.
    const roto = {
      collections: [{ collection: "budget", documents: 1, chunks: 1, hnsw_indexed: "false" }],
      total_documents: 1,
      total_chunks: 1,
    };

    expect(() => corpusStatsSchema.parse(roto)).toThrow();
  });
});

describe("estimateTreeSchema", () => {
  it("acepta el árbol con supuestos en su forma real", () => {
    // La forma que este espejo se inventó una vez. Si alguien la vuelve a
    // simplificar a `{text}`, este test cae antes de llegar a producción.
    const arbol = {
      modules: [
        {
          name: "Backend",
          description: null,
          tasks: [{ name: "API", description: "CRUD", grounded: false, engineer_days: null }],
        },
      ],
      assumptions: [
        { description: "Se asume un único idioma", impact: "medium", rationale: "No se citó" },
      ],
      confidence: "medium",
    };

    expect(estimateTreeSchema.parse(arbol).assumptions).toHaveLength(1);
  });

  it("un supuesto sin rationale es un fallo de contrato, no un campo opcional", () => {
    const roto = {
      modules: [],
      assumptions: [{ description: "x", impact: "low" }],
      confidence: "low",
    };

    expect(() => estimateTreeSchema.parse(roto)).toThrow();
  });

  it("una confianza fuera del enum se rechaza", () => {
    expect(() =>
      estimateTreeSchema.parse({ modules: [], assumptions: [], confidence: "regular" }),
    ).toThrow();
  });
});

describe("taskHoursResultSchema", () => {
  it("una tarea sin analogía llega con horas y fiabilidad nulas", () => {
    // El caso que hace útil la pantalla: decir «no sé» en vez de inventar.
    const sinAnalogia = {
      tasks: [
        {
          module: "Gestión",
          task: "Service design",
          estimated_hours: null,
          reliability: null,
          has_match: false,
          dispersion: null,
          neighbors: [],
        },
      ],
    };

    const parsed = taskHoursResultSchema.parse(sinAnalogia);
    expect(parsed.tasks[0].has_match).toBe(false);
    expect(parsed.tasks[0].estimated_hours).toBeNull();
  });

  it("la fiabilidad vive entre 0 y 1, no en porcentaje", () => {
    // La pantalla multiplica por 100 al pintarla. Un 52 aquí saldría como 5200 %.
    const base = {
      module: "m",
      task: "t",
      estimated_hours: 30,
      has_match: true,
      neighbors: [],
    };

    expect(() => taskHoursResultSchema.parse({ tasks: [{ ...base, reliability: 52 }] })).toThrow();
    expect(taskHoursResultSchema.parse({ tasks: [{ ...base, reliability: 0.52 }] })).toBeTruthy();
  });
});

describe("reformulationSchema", () => {
  it("rellena las listas ausentes en vez de dejarlas undefined", () => {
    // La vista hace `.length` sobre ellas sin comprobar.
    const minimo = { query: { function: "Portal de reservas" }, search_text: "portal reservas" };

    const parsed = reformulationSchema.parse(minimo);
    expect(parsed.query.technologies).toEqual([]);
    expect(parsed.query.regulations).toEqual([]);
    expect(parsed.query.scale).toBe("unknown");
  });
});

describe("agentTraceSchema", () => {
  it("por defecto el corte es natural", () => {
    // La pantalla avisa cuando NO lo es, así que el default no puede ser otro:
    // un aviso de más ante una traza incompleta asusta sin motivo.
    expect(agentTraceSchema.parse({}).stop_reason).toBe("natural");
  });

  it("conserva el motivo cuando el bucle se cortó", () => {
    expect(agentTraceSchema.parse({ stop_reason: "max_iterations" }).stop_reason).toBe(
      "max_iterations",
    );
  });
});

describe("agentCanRun", () => {
  // El catálogo del servicio, copiado de `/api/v1/config/models` el 2026-09-23.
  // Está entero a propósito: lo que se prueba es el reparto sobre los nombres
  // REALES, y un puñado de ejemplos elegidos a mano no habría pescado que
  // `claude-fable-5` empieza por claude pero termina en 5, ni que `gpt-4o` y
  // `gpt-4.1` son las dos formas distintas que tiene la familia GPT-4.
  const catalogo = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-5-nano",
    "gpt-5-mini",
    "gpt-5",
    "gpt-5-pro",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-6-astra",
    "o3-mini",
    "o4-mini",
    "o3",
    "o1",
    "o1-pro",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4-5-20251101",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-fable-5",
    "claude-fable-5-1",
  ];

  it("deja fuera Anthropic entero y sólo la familia GPT-4 de OpenAI", () => {
    expect(catalogo.filter((m) => !agentCanRun(m))).toEqual([
      "gpt-4o-mini",
      "gpt-4o",
      "gpt-4.1-nano",
      "gpt-4.1-mini",
      "gpt-4.1",
      "claude-haiku-4-5-20251001",
      "claude-sonnet-4-5",
      "claude-sonnet-4-6",
      "claude-sonnet-5",
      "claude-opus-4-5-20251101",
      "claude-opus-4-6",
      "claude-opus-4-7",
      "claude-opus-4-8",
      "claude-opus-5",
      "claude-fable-5",
      "claude-fable-5-1",
    ]);
  });

  it("acepta GPT-5 en adelante y la serie o", () => {
    expect(catalogo.filter(agentCanRun)).toHaveLength(22);
    for (const modelo of ["gpt-5", "gpt-5.6-sol", "gpt-6-astra", "o1", "o4-mini"]) {
      expect(agentCanRun(modelo)).toBe(true);
    }
  });

  it("decide por la forma del nombre, así que un modelo futuro no se queda fuera", () => {
    // Lo contrario de una lista escrita a mano: `gpt-7` todavía no existe y ya
    // entra. El riesgo va en la otra dirección —entraría aunque no razonara—, y
    // por eso la pantalla avisa además de filtrar.
    expect(agentCanRun("gpt-7-lo-que-sea")).toBe(true);
    expect(agentCanRun("o9-mini")).toBe(true);
    expect(agentCanRun("gemini-3-pro")).toBe(false);
  });
});

describe("hopSource", () => {
  // Sin test hasta la S15, y RULE_REASONS duplica seis literales de
  // supervisor.py sin nada que los ate. Lo que se fija aquí es el reparto, que
  // es de lo que depende la columna «Origen» de la traza de enrutado.
  it("reconoce los motivos que escribe una regla", () => {
    expect(hopSource("nothing read yet")).toBe("regla");
    expect(hopSource("validation clean")).toBe("regla");
    expect(hopSource("evidence gaps persist after re-searching")).toBe("regla");
    expect(hopSource("unknown route 'ghost_agent'")).toBe("regla");
  });

  it("reconoce el freno de emergencia", () => {
    expect(hopSource("routing budget exhausted at 8 steps")).toBe("limite");
  });

  it("trata el motivo sintetizado de un modelo de decisión como decisión de modelo", () => {
    // Jev no devuelve prosa: el motivo lo compone el servicio con los conteos
    // del estado. Empieza por un número, así que no puede colisionar con
    // ninguno de los literales de regla — que es justamente lo que se fija.
    const sintetizado =
      "3 componentes, 1 referencias, confianza 0.49, 1 avisos del validador; jev-latest enrutó a human_review_gate (p=0.85)";

    expect(hopSource(sintetizado)).toBe("modelo");
  });

  it("trata la degradación a router de texto como decisión de modelo", () => {
    // Una caída del proveedor la decide igualmente un modelo, el de texto, y
    // el motivo lo dice. Lo que NO puede es parecerse a una regla.
    expect(
      hopSource("jev-latest no respondió; decidió gpt-5-mini: los huecos parecen reales"),
    ).toBe("modelo");
  });
});
