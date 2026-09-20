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
  agentTraceSchema,
  corpusStatsSchema,
  estimateTreeSchema,
  reformulationSchema,
  taskHoursResultSchema,
} from "./contracts";

describe("corpusStatsSchema", () => {
  it("acepta la foto del corpus tal y como la emite el servicio", () => {
    const real = {
      collections: [
        { collection: "budget", documents: 77, chunks: 1603, hnsw_indexed: false },
      ],
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
