/**
 * Los formateadores.
 *
 * Parecen triviales y no lo son: los dos casos que hay aquí salieron de fallos
 * reales en pantalla —la misma columna mezclando «5000 €» y «35.750 €», y dos
 * cifras etiquetadas «Coste» en monedas distintas sin forma de distinguirlas—.
 */

import { describe, expect, it } from "vitest";

import { eur, hours, percent, usd, usdPerMillion } from "./format";

/**
 * `Intl` separa la cifra de su unidad con un espacio NO SEPARABLE (U+00A0), no
 * con el espacio normal que uno teclea. Sin normalizar, estas comparaciones
 * fallan enseñando dos cadenas idénticas en pantalla — que es exactamente la
 * clase de test que hace perder media hora.
 */
const normal = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

describe("eur", () => {
  it("agrupa también los millares de cuatro dígitos", () => {
    // El default de es-ES es `min2`, que sólo agrupa desde cinco cifras: una
    // tabla de fases pintaba «5000 €» junto a «35.750 €», en la misma columna.
    expect(normal(eur(5000))).toBe("5.000 €");
    expect(normal(eur(35750))).toBe("35.750 €");
  });

  it("sin decimales: un presupuesto no se estima al céntimo", () => {
    expect(normal(eur(13425.49))).toBe("13.425 €");
  });
});

describe("hours", () => {
  it("agrupa y añade la unidad", () => {
    expect(normal(hours(1240))).toBe("1.240 h");
    expect(normal(hours(195))).toBe("195 h");
  });
});

describe("percent", () => {
  it("recibe 0..1, no 0..100", () => {
    expect(normal(percent(0.52))).toBe("52 %");
    expect(normal(percent(1))).toBe("100 %");
  });

  it("null es un guion, no un 0 %", () => {
    // «No lo sé» y «es cero» son cosas distintas, y aquí se distinguen.
    expect(normal(percent(null))).toBe("—");
    expect(normal(percent(undefined))).toBe("—");
    expect(normal(percent(0))).toBe("0 %");
  });
});

describe("usd", () => {
  it("dice la divisa, porque en la misma pantalla hay euros", () => {
    // La pantalla de conversación enseña «Coste 13.000 €» y «Coste 0,0005 US$»
    // a la vez. Sin la marca, la segunda se lee como euros.
    expect(normal(usd(0.000535))).toContain("US$");
  });

  it("cuatro decimales: una llamada cuesta céntimos de céntimo", () => {
    expect(normal(usd(0.000535))).toBe("0,0005 US$");
    expect(normal(usd(0))).toBe("0,0000 US$");
  });
});

describe("usdPerMillion", () => {
  it("entrada y salida con una sola marca de divisa", () => {
    expect(normal(usdPerMillion(0.15, 0.6))).toBe("0,15 / 0,60 US$");
  });

  it("dos decimales fijos, para que la columna quede alineada", () => {
    expect(normal(usdPerMillion(150, 600))).toBe("150,00 / 600,00 US$");
    expect(normal(usdPerMillion(0.05, 0.4))).toBe("0,05 / 0,40 US$");
  });
});
