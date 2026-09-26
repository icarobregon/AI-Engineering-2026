/**
 * El markdown mínimo que redacta el servicio IA, convertido en bloques.
 *
 * Existe para que la propuesta se lea IGUAL en pantalla y en el PDF. La
 * aplicación de referencia guarda markdown, lo enseña crudo en la web y lo
 * interpreta en el PDF con tres expresiones regulares escritas a mano: dos
 * representaciones del mismo texto, ninguna con un parser, y divergen en cuanto
 * el modelo escribe algo que una de las dos no contempla.
 *
 * Aquí hay un solo parser y dos pintores. No es un renderizador de markdown
 * completo y no pretende serlo: la plantilla del prompt pide exactamente
 * títulos `##`, párrafos y listas con `-`, así que eso es lo que se soporta.
 * Cualquier otra cosa cae a párrafo, que es la degradación legible.
 */

export type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] };

/**
 * Marcas de énfasis fuera. Enseñar `**así**` literal es peor que perder la
 * negrita.
 *
 * El énfasis simple se reconoce por lo que lo separa de una multiplicación: el
 * marcador de apertura NO lleva espacio detrás y el de cierre NO lo lleva
 * delante. Sin esa condición, `2 * 3 = 6` se come el `3 = 6`.
 */
function limpiarEnfasis(texto: string): string {
  return texto
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(?<![*_])[*_](?![\s*_])([^*_\n]*?[^\s*_])[*_](?![*_])/g, "$1");
}

const ITEM = /^\s*[-*+]\s+/;

export function parseSimpleMarkdown(markdown: string): Block[] {
  const bloques: Block[] = [];

  for (const trozo of (markdown ?? "").split(/\n{2,}/)) {
    const lineas = trozo
      .split("\n")
      .map((l) => l.trimEnd())
      .filter((l) => l.trim().length > 0);
    if (lineas.length === 0) continue;

    // Una lista puede venir pegada a su párrafo introductorio, así que los items
    // se detectan línea a línea en lugar de exigir que TODO el trozo lo sea.
    let sueltas: string[] = [];
    let items: string[] = [];

    const cerrarParrafo = () => {
      if (sueltas.length === 0) return;
      const texto = limpiarEnfasis(sueltas.join(" ").trim());
      // `#`, `##`, `###`… todos al mismo nivel: el documento tiene un único
      // rango de apartados y fingir una jerarquía que el prompt no pide sólo
      // produciría tamaños de letra arbitrarios.
      const titulo = /^#{1,6}\s+(.*)$/.exec(texto);
      bloques.push(
        titulo ? { kind: "heading", text: titulo[1].trim() } : { kind: "paragraph", text: texto },
      );
      sueltas = [];
    };
    const cerrarLista = () => {
      if (items.length === 0) return;
      bloques.push({ kind: "list", items });
      items = [];
    };

    for (const linea of lineas) {
      if (ITEM.test(linea)) {
        cerrarParrafo();
        items.push(limpiarEnfasis(linea.replace(ITEM, "").trim()));
        continue;
      }
      if (/^#{1,6}\s+/.test(linea)) {
        cerrarParrafo();
        cerrarLista();
        sueltas.push(linea);
        cerrarParrafo();
        continue;
      }
      cerrarLista();
      sueltas.push(linea);
    }
    cerrarParrafo();
    cerrarLista();
  }

  return bloques;
}
