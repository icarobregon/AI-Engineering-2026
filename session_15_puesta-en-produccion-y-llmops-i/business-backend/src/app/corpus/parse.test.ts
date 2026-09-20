/**
 * Los dos parseadores de la ampliación del corpus.
 *
 * `sourcePathDe` es el que ya falló una vez: derivaba la clave del id del RUN,
 * así que el mismo presupuesto enviado dos veces entraba dos veces, y la
 * pantalla promete justo lo contrario.
 */

import { describe, expect, it } from "vitest";

import { parseDocuments, sourcePathDe } from "./parse";

describe("parseDocuments", () => {
  it("un objeto suelto se envuelve en lista", () => {
    expect(parseDocuments('{"budget_id":"A"}')).toEqual([{ budget_id: "A" }]);
  });

  it("una lista se respeta", () => {
    expect(parseDocuments('[{"a":1},{"b":2}]')).toHaveLength(2);
  });

  it("un JSON malformado explica qué pasó, no revienta en bruto", () => {
    expect(() => parseDocuments("{no es json")).toThrow(/El JSON no es válido/);
  });

  it("rechaza lo que es JSON válido pero no un documento", () => {
    // La app de referencia envuelve cualquier cosa: `null` viaja como `[null]` y
    // `123` como `[123]`, y el servicio los rechaza con un 422 sin contexto.
    expect(() => parseDocuments("null")).toThrow(/tiene que ser un objeto/);
    expect(() => parseDocuments("123")).toThrow(/tiene que ser un objeto/);
    expect(() => parseDocuments('"un string"')).toThrow(/tiene que ser un objeto/);
    expect(() => parseDocuments("[[1,2]]")).toThrow(/tiene que ser un objeto/);
  });

  it("dice cuántos de cuántos están mal", () => {
    expect(() => parseDocuments('[{"a":1}, null, 5]')).toThrow(/2 de 3/);
  });

  it("una lista vacía no es un lote válido", () => {
    expect(() => parseDocuments("[]")).toThrow(/al menos un documento/);
  });
});

describe("sourcePathDe", () => {
  it("la clave sale del documento, no del lote", () => {
    // Esto es lo que hace que reenviar el mismo presupuesto lo salte en vez de
    // duplicarlo. Con el id del run dentro, nunca coincidirían.
    expect(sourcePathDe({ budget_id: "BUD-2024-001" }, 0)).toBe("corpus-ui::BUD-2024-001");
    expect(sourcePathDe({ budget_id: "BUD-2024-001" }, 7)).toBe("corpus-ui::BUD-2024-001");
  });

  it("recorta los espacios del id", () => {
    expect(sourcePathDe({ budget_id: "  BUD-1  " }, 0)).toBe("corpus-ui::BUD-1");
  });

  it("sin id estable cae al índice, que permite duplicar pero no rechaza", () => {
    // Rechazar el documento sería peor: el servicio puede aceptarlo igual.
    expect(sourcePathDe({ sin: "id" }, 3)).toBe("corpus-ui::sin-id#3");
    expect(sourcePathDe({ budget_id: "   " }, 1)).toBe("corpus-ui::sin-id#1");
    expect(sourcePathDe({ budget_id: 42 }, 2)).toBe("corpus-ui::sin-id#2");
  });

  it("no revienta con null", () => {
    expect(sourcePathDe(null, 0)).toBe("corpus-ui::sin-id#0");
  });
});
