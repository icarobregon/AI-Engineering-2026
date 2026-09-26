/**
 * El parser compartido por la pantalla y el PDF.
 *
 * Lo que se prueba aquí no es markdown: es que las dos representaciones de la
 * propuesta salgan del MISMO árbol, que es lo que impide que diverjan.
 */

import { describe, expect, it } from "vitest";

import { parseSimpleMarkdown } from "./markdown";

describe("parseSimpleMarkdown", () => {
  it("separa títulos, párrafos y listas", () => {
    const bloques = parseSimpleMarkdown(
      "## Contexto\n\nUn párrafo.\n\n- Uno\n- Dos\n\n## Alcance\n\nOtro.",
    );

    expect(bloques).toEqual([
      { kind: "heading", text: "Contexto" },
      { kind: "paragraph", text: "Un párrafo." },
      { kind: "list", items: ["Uno", "Dos"] },
      { kind: "heading", text: "Alcance" },
      { kind: "paragraph", text: "Otro." },
    ]);
  });

  it("une las líneas sueltas de un párrafo", () => {
    // El modelo corta a 80 columnas; un salto simple no es un párrafo nuevo.
    expect(parseSimpleMarkdown("Primera línea\ny su continuación.")).toEqual([
      { kind: "paragraph", text: "Primera línea y su continuación." },
    ]);
  });

  it("reconoce una lista pegada a su párrafo introductorio", () => {
    const bloques = parseSimpleMarkdown("Incluye lo siguiente:\n- Backend\n- Portal");

    expect(bloques).toEqual([
      { kind: "paragraph", text: "Incluye lo siguiente:" },
      { kind: "list", items: ["Backend", "Portal"] },
    ]);
  });

  it("acepta los tres marcadores de lista", () => {
    expect(parseSimpleMarkdown("- a\n* b\n+ c")).toEqual([
      { kind: "list", items: ["a", "b", "c"] },
    ]);
  });

  it("todos los niveles de título van al mismo rango", () => {
    // El prompt pide un solo nivel. Inventar jerarquía sería elegir tamaños de
    // letra al azar en el PDF.
    expect(parseSimpleMarkdown("# Uno\n\n### Tres")).toEqual([
      { kind: "heading", text: "Uno" },
      { kind: "heading", text: "Tres" },
    ]);
  });

  it("quita las marcas de énfasis en vez de enseñarlas", () => {
    expect(parseSimpleMarkdown("Esto es **importante** y esto *también*.")).toEqual([
      { kind: "paragraph", text: "Esto es importante y esto también." },
    ]);
  });

  it("un asterisco suelto no se confunde con énfasis", () => {
    expect(parseSimpleMarkdown("2 * 3 = 6")).toEqual([{ kind: "paragraph", text: "2 * 3 = 6" }]);
  });

  it("un texto vacío no produce bloques", () => {
    expect(parseSimpleMarkdown("")).toEqual([]);
    expect(parseSimpleMarkdown("\n\n   \n\n")).toEqual([]);
  });

  it("un título seguido de su párrafo en el mismo trozo no se fusiona", () => {
    expect(parseSimpleMarkdown("## Contexto\nEl cliente necesita reservas.")).toEqual([
      { kind: "heading", text: "Contexto" },
      { kind: "paragraph", text: "El cliente necesita reservas." },
    ]);
  });
});
