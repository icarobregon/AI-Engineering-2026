/**
 * El PDF de la propuesta.
 *
 * El saneado es lo que de verdad hay que probar: pdfkit NO lanza con un
 * carácter que no puede pintar, escribe un glifo equivocado. Un fallo silencioso
 * en un documento que se manda a un cliente no se descubre hasta que lo lee el
 * cliente.
 */

import { inflateSync } from "node:zlib";

import { describe, expect, it } from "vitest";

import { buildProposalPdf, sanearParaPdf } from "./proposal-pdf";
import type { CommercialProposal, DraftEstimate } from "./estimator/contracts";

const PROPUESTA: CommercialProposal = {
  title: "Propuesta · Portal de reservas",
  executive_summary: "Un resumen con acentuación y eñes: diseño, integración y años.",
  scope: ["Backend de pedidos — 160 h"],
  assumptions: ["El gemelo digital no tiene precedente histórico."],
  body_markdown: "## Contexto\n\nEl cliente necesita reservas.\n\n- Uno\n- Dos",
};

const ESTIMACION: DraftEstimate = {
  project: "RUTA",
  total_hours: 160,
  notes: "",
  components: [
    {
      component_id: "c1",
      name: "Backend de pedidos",
      estimated_hours: 160,
      grounded: true,
      rationale: "Dos presupuestos comparables.",
    },
    {
      component_id: "c2",
      name: "Gemelo digital 3D",
      estimated_hours: 0,
      grounded: false,
      rationale: "Sin precedente.",
    },
  ],
};

describe("sanearParaPdf", () => {
  it("deja intacto todo el castellano", () => {
    const texto = "Señor cliente: ¿cuánto? ÁÉÍÓÚáéíóú üÜ ñÑ ç ¡Ojo!";

    expect(sanearParaPdf(texto)).toBe(texto);
  });

  it("deja intacta la tipografía que CP1252 sí tiene", () => {
    // Comillas curvas, raya, semirraya, puntos suspensivos, viñeta y euro: todo
    // esto lo escribe un modelo constantemente y todo tiene glifo.
    const texto = "«así» ‘uno’ “dos” — – … • 100 €";

    expect(sanearParaPdf(texto)).toBe(texto);
  });

  it("traduce lo que no tiene glifo en lugar de pintarlo mal", () => {
    expect(sanearParaPdf("A → B")).toBe("A -> B");
    expect(sanearParaPdf("calidad ✓")).toBe("calidad -");
    expect(sanearParaPdf("x ≥ 3")).toBe("x >= 3");
  });

  it("descarta el emoji sin dejar interrogantes por medio", () => {
    // Un «?» por carácter ensucia la frase entera; sin él sigue leyéndose.
    expect(sanearParaPdf("Lanzamiento 🚀 en junio")).toBe("Lanzamiento  en junio");
  });

  it("conserva saltos de línea y tabulaciones", () => {
    expect(sanearParaPdf("uno\ndos\tt")).toBe("uno\ndos\tt");
  });
});

describe("buildProposalPdf", () => {
  it("produce un PDF con su cabecera", async () => {
    const pdf = await buildProposalPdf({
      proposal: PROPUESTA,
      estimate: ESTIMACION,
      estimationId: "EST-42",
    });

    expect(pdf.subarray(0, 5).toString("latin1")).toBe("%PDF-");
    expect(pdf.length).toBeGreaterThan(1000);
  });

  it("no revienta sin estimación: la propuesta se puede pedir igual", async () => {
    const pdf = await buildProposalPdf({
      proposal: PROPUESTA,
      estimate: null,
      estimationId: "EST-42",
    });

    expect(pdf.subarray(0, 5).toString("latin1")).toBe("%PDF-");
  });

  it("el texto llega al documento codificado en WinAnsi", async () => {
    const pdf = await buildProposalPdf({
      proposal: PROPUESTA,
      estimate: ESTIMACION,
      estimationId: "EST-42",
    });

    // Las cadenas viajan en hexadecimal dentro de los flujos comprimidos, así
    // que se comprueba sobre el flujo descomprimido: «diseño» con la eñe en
    // 0xF1 es la prueba de que la codificación es la que se cree.
    // Un párrafo justificado reparte los espacios como kerning en lugar de
    // escribirlos, así que la comparación va sin ellos: lo que se mira es la
    // codificación de los caracteres, no el ajuste de línea.
    const texto = sinEspacios(extraerTexto(pdf));
    expect(texto).toContain("diseño");
    expect(texto).toContain("integración");
    expect(texto).toContain("años");
    expect(texto).toContain("Elclientenecesitareservas.");
  });

  it("la tabla no arrastra el cursor: lo que sigue vuelve al margen", async () => {
    // El fallo que esto fija: `doc.text(texto, x, y)` deja la X del cursor donde
    // escribió, así que tras la columna de horas TODO el resto del documento se
    // pintaba en una franja estrecha contra el borde derecho. Se comprueba sobre
    // la coordenada y no sobre el número de páginas: con poco texto el documento
    // sigue cabiendo en una página y el síntoma no se ve.
    const pdf = await buildProposalPdf({
      proposal: PROPUESTA,
      estimate: ESTIMACION,
      estimationId: "EST-42",
    });

    // «Alcance» es el primer apartado DESPUÉS del desglose.
    expect(xDelTexto(pdf, "Alcance")).toBe(48);
    // Y la columna de horas sí está a la derecha, que es lo que lo provocaba.
    expect(xDelTexto(pdf, "Horas")).toBeGreaterThan(300);
  });

  it("marca en el desglose el componente sin precedente", async () => {
    const pdf = await buildProposalPdf({
      proposal: PROPUESTA,
      estimate: ESTIMACION,
      estimationId: "EST-42",
    });

    expect(extraerTexto(pdf)).toContain("(sin precedente)");
  });
});

/**
 * Descomprime los flujos del PDF y devuelve el texto de sus operadores.
 *
 * `latin1` de punta a punta a propósito: es la única codificación de Node que
 * no toca ningún byte, y el contenido del PDF ya viene en WinAnsi, que comparte
 * los puntos de código con Latin-1 en todo lo que usamos.
 */
function extraerTexto(pdf: Buffer): string {
  const crudo = pdf.toString("latin1");
  let salida = "";
  for (const flujo of crudo.matchAll(/stream\r?\n([\s\S]*?)endstream/g)) {
    try {
      const contenido = inflateSync(Buffer.from(flujo[1], "latin1")).toString("latin1");
      // Las cadenas van como <hex> dentro de los arrays TJ.
      for (const trozo of contenido.matchAll(/<([0-9a-fA-F]+)>/g)) {
        salida += Buffer.from(trozo[1], "hex").toString("latin1");
      }
    } catch {
      // Un flujo que no es zlib (una fuente incrustada) no aporta texto.
    }
  }
  return salida;
}

/**
 * Un párrafo justificado reparte los espacios como desplazamientos de kerning
 * en lugar de escribirlos, así que desaparecen del flujo. Comparar sin ellos es
 * lo que hace que el test mire el texto y no el ajuste de línea.
 */
function sinEspacios(texto: string): string {
  return texto.replace(/[\s\u00a0]/g, "");
}

/**
 * La X a la que se dibujó un texto concreto.
 *
 * pdfkit abre cada run con `1 0 0 1 <x> <y> Tm` y escribe las cadenas en
 * hexadecimal dentro del array `TJ` que le sigue, así que basta con recorrer los
 * pares en orden y quedarse con la X del primero cuyo texto contenga la aguja.
 */
function xDelTexto(pdf: Buffer, aguja: string): number | null {
  const crudo = pdf.toString("latin1");
  for (const flujo of crudo.matchAll(/stream\r?\n([\s\S]*?)endstream/g)) {
    let contenido: string;
    try {
      contenido = inflateSync(Buffer.from(flujo[1], "latin1")).toString("latin1");
    } catch {
      continue;
    }
    for (const run of contenido.matchAll(/1 0 0 1 ([\d.]+) [\d.]+ Tm([\s\S]*?)TJ/g)) {
      let texto = "";
      for (const trozo of run[2].matchAll(/<([0-9a-fA-F]+)>/g)) {
        texto += Buffer.from(trozo[1], "hex").toString("latin1");
      }
      if (texto.includes(aguja)) return Number(run[1]);
    }
  }
  return null;
}
