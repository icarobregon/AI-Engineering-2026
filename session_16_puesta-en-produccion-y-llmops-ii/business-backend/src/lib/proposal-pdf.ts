/**
 * La propuesta comercial, en PDF.
 *
 * Es de esta capa y no del servicio IA: aquí no se estima ni se redacta, se
 * valida, se llama, se persiste y se pinta — y renderizar un documento es
 * pintar. El texto llega ya escrito.
 *
 * **pdfkit y por qué no hace falta una fuente.** Las fuentes estándar de PDF
 * codifican en WinAnsi (CP1252), que cubre entero el castellano —acentos, eñes,
 * signos de apertura— y también la tipografía que escribe un modelo: comillas
 * curvas, raya, semirraya, puntos suspensivos, viñeta y el euro. Comprobado
 * carácter a carácter sobre el PDF generado. Lo que NO cubre son flechas,
 * símbolos matemáticos y emoji, y ahí está la trampa: pdfkit no lanza ninguna
 * excepción con ellos, escribe un glifo equivocado. Un fallo silencioso dentro
 * de un documento que se manda a un cliente es exactamente lo que `sanear` está
 * aquí para evitar.
 */
import "server-only";

import PDFDocument from "pdfkit";

import { hours } from "./format";
import { parseSimpleMarkdown } from "./markdown";
import type { CommercialProposal, DraftEstimate } from "./estimator/contracts";

/** Lo que el modelo escribe y CP1252 no tiene, con su equivalente legible. */
const EQUIVALENTES: Record<string, string> = {
  "→": "->",
  "⇒": "=>",
  "←": "<-",
  "↑": "^",
  "↓": "v",
  "≥": ">=",
  "≤": "<=",
  "≠": "!=",
  "✓": "-",
  "✔": "-",
  "✗": "x",
  "✅": "-",
  "▪": "-",
  "◦": "-",
  // U+2015, la barra horizontal. Ojo: la semirraya U+2013 y la raya U+2014 NO
  // están aquí porque CP1252 sí las tiene, y sustituirlas por un guión empobrece
  // el texto sin motivo.
  "―": "-",
};

// ASCII imprimible, el suplemento Latin-1 y los sitios que CP1252 rellena en
// 0x80-0x9F (tipografía y el euro). Todo lo demás no tiene glifo y se va.
const SOPORTADO = /[\x20-\x7E\xA0-\xFF€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ\n\t]/;

export function sanearParaPdf(texto: string): string {
  let salida = "";
  for (const caracter of texto ?? "") {
    const equivalente = EQUIVALENTES[caracter];
    if (equivalente !== undefined) {
      salida += equivalente;
      continue;
    }
    // Se descarta en silencio a propósito: un carácter sin glifo sustituido por
    // «?» ensucia una frase entera, y el texto sigue leyéndose sin él.
    if (SOPORTADO.test(caracter)) salida += caracter;
  }
  return salida;
}

const MARGEN = 48;
const TINTA = "#141414";
const APAGADO = "#6b6b6b";
const MARCA = "#1668dc";

type Entrada = {
  proposal: CommercialProposal;
  estimate: DraftEstimate | null;
  estimationId: string;
};

function apartado(doc: PDFKit.PDFDocument, titulo: string): void {
  doc.moveDown(1);
  doc.fillColor(MARCA).font("Helvetica-Bold").fontSize(12).text(sanearParaPdf(titulo));
  doc.moveDown(0.35);
  doc.fillColor(TINTA).font("Helvetica").fontSize(10);
}

function lista(doc: PDFKit.PDFDocument, items: string[]): void {
  for (const item of items) {
    doc.text(`•  ${sanearParaPdf(item)}`, { indent: 6, paragraphGap: 3 });
  }
}

function desglose(doc: PDFKit.PDFDocument, estimate: DraftEstimate): void {
  const anchoHoras = 90;
  const anchoNombre = doc.page.width - MARGEN * 2 - anchoHoras;

  const fila = (izquierda: string, derecha: string, negrita: boolean) => {
    doc.font(negrita ? "Helvetica-Bold" : "Helvetica").fontSize(10);
    const y = doc.y;
    doc.text(sanearParaPdf(izquierda), MARGEN, y, { width: anchoNombre });
    const abajo = doc.y;
    // La columna de horas se ancla a la Y de la fila, no al cursor: un nombre
    // que ocupa dos líneas dejaría el número una línea por debajo del suyo.
    doc.text(sanearParaPdf(derecha), MARGEN + anchoNombre, y, {
      width: anchoHoras,
      align: "right",
    });
    doc.y = abajo;
    // Y la X vuelve al margen. `doc.text(texto, x, y)` deja el cursor en esa X,
    // así que sin esto todo lo que se pinte después de la tabla —los apartados,
    // las listas, el cuerpo entero— se dibuja dentro del ancho de la columna de
    // horas, en una franja de 90 puntos pegada al borde derecho.
    doc.x = MARGEN;
    doc.moveDown(0.25);
  };

  fila("Componente", "Horas", true);
  for (const componente of estimate.components) {
    fila(
      componente.grounded ? componente.name : `${componente.name}  (sin precedente)`,
      hours(componente.estimated_hours),
      false,
    );
  }
  doc.moveDown(0.25);
  fila("Total", hours(estimate.total_hours), true);
}

export async function buildProposalPdf({
  proposal,
  estimate,
  estimationId,
}: Entrada): Promise<Buffer> {
  const doc = new PDFDocument({ size: "A4", margin: MARGEN, info: { Title: proposal.title } });
  const trozos: Buffer[] = [];
  doc.on("data", (trozo: Buffer) => trozos.push(trozo));
  const cerrado = new Promise<void>((resolve) => doc.on("end", () => resolve()));

  doc.fillColor(TINTA).font("Helvetica-Bold").fontSize(20).text(sanearParaPdf(proposal.title));
  doc.moveDown(0.2);
  doc
    .fillColor(APAGADO)
    .font("Helvetica")
    .fontSize(9)
    .text(sanearParaPdf(`Estimación supervisada · ${estimationId}`));

  doc.moveDown(0.6);
  doc
    .moveTo(MARGEN, doc.y)
    .lineTo(doc.page.width - MARGEN, doc.y)
    .strokeColor("#d9d9d9")
    .stroke();

  apartado(doc, "Resumen ejecutivo");
  doc.text(sanearParaPdf(proposal.executive_summary), { align: "justify" });

  if (estimate) {
    apartado(doc, "Esfuerzo");
    desglose(doc, estimate);
  }

  if (proposal.scope.length > 0) {
    apartado(doc, "Alcance");
    lista(doc, proposal.scope);
  }

  if (proposal.assumptions.length > 0) {
    apartado(doc, "Supuestos y reservas");
    lista(doc, proposal.assumptions);
  }

  // El cuerpo se pinta desde los MISMOS bloques que la pantalla, no desde una
  // segunda interpretación del markdown.
  for (const bloque of parseSimpleMarkdown(proposal.body_markdown)) {
    if (bloque.kind === "heading") {
      apartado(doc, bloque.text);
    } else if (bloque.kind === "list") {
      lista(doc, bloque.items);
    } else {
      doc.font("Helvetica").fontSize(10).fillColor(TINTA);
      doc.text(sanearParaPdf(bloque.text), { align: "justify", paragraphGap: 6 });
    }
  }

  doc.end();
  await cerrado;
  return Buffer.concat(trozos);
}
