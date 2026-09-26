/**
 * Lo que manda el revisor, antes de cruzar la frontera.
 *
 * Es el último sitio donde se puede parar una decisión mal formada: al otro lado
 * está el checkpoint, que es inmutable. Lo de deshabilitar el botón en pantalla
 * es cortesía; esto es la regla.
 */

import { describe, expect, it } from "vitest";

import { componentesSinPrecio, parseComponentHours } from "./review";
import type { EstimatedComponent } from "@/lib/estimator/contracts";

const COMPONENTES = [
  { component_id: "c1", name: "Backend", estimated_hours: 120, grounded: true, rationale: "" },
  {
    component_id: "c2",
    name: "Visión artificial",
    estimated_hours: 0,
    grounded: false,
    rationale: "",
  },
  { component_id: "c3", name: "Avisos", estimated_hours: 80, grounded: true, rationale: "" },
] as EstimatedComponent[];

describe("parseComponentHours", () => {
  it("lee las horas por componente", () => {
    expect(parseComponentHours('{"c1":120,"c2":150.5}')).toEqual({ c1: 120, c2: 150.5 });
  });

  it("un campo vaciado no es un cero: se deja fuera", () => {
    // Así lo caza la comprobación de componentes sin precio, que sabe el NOMBRE
    // y puede decírselo a quien revisa. Un 0 silencioso sólo se vería al final.
    expect(parseComponentHours('{"c1":120,"c2":null}')).toEqual({ c1: 120 });
  });

  it("rechaza lo que no es un número", () => {
    expect(() => parseComponentHours('{"c1":"mucho"}')).toThrow(/no son un número/);
    expect(() => parseComponentHours('{"c1":-5}')).toThrow(/no son un número/);
    expect(() => parseComponentHours('{"c1":null,"c2":[]}')).toThrow(/no son un número/);
  });

  it("un cero explícito sí pasa el parser", () => {
    // Es un valor legítimo que el parser no juzga: quien decide si se puede
    // aprobar con él es `componentesSinPrecio`, que además sabe el nombre.
    expect(parseComponentHours('{"c1":0}')).toEqual({ c1: 0 });
  });

  it("rechaza lo que no es un objeto", () => {
    expect(() => parseComponentHours("[1,2]")).toThrow(/formato legible/);
    expect(() => parseComponentHours("null")).toThrow(/formato legible/);
    expect(() => parseComponentHours("{roto")).toThrow(/formato legible/);
  });

  it("rechaza que no llegue nada", () => {
    expect(() => parseComponentHours(null)).toThrow(/No han llegado/);
    expect(() => parseComponentHours("")).toThrow(/No han llegado/);
  });
});

describe("componentesSinPrecio", () => {
  it("devuelve el NOMBRE de los que quedarían a cero", () => {
    expect(componentesSinPrecio(COMPONENTES, { c1: 120, c3: 80 })).toEqual(["Visión artificial"]);
  });

  it("un cero explícito cuenta como sin precio", () => {
    expect(componentesSinPrecio(COMPONENTES, { c1: 120, c2: 0, c3: 80 })).toEqual([
      "Visión artificial",
    ]);
  });

  it("se mira contra lo GUARDADO, no contra lo que llegó", () => {
    // Un componente que el formulario omita entero no se puede echar de menos
    // leyendo sólo las claves recibidas. Aquí aparecen los dos que faltan.
    expect(componentesSinPrecio(COMPONENTES, { c1: 120 })).toEqual(["Visión artificial", "Avisos"]);
  });

  it("con todo puesto no falta nada", () => {
    expect(componentesSinPrecio(COMPONENTES, { c1: 120, c2: 150, c3: 80 })).toEqual([]);
  });

  it("sin componentes guardados no inventa ninguno", () => {
    expect(componentesSinPrecio([], { c1: 120 })).toEqual([]);
  });
});
