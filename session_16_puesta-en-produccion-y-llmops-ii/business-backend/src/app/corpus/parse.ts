/**
 * Los dos parseadores de la ampliación del corpus.
 *
 * Viven aquí y no en `actions.ts` porque un módulo `"use server"` sólo puede
 * exportar funciones async, así que desde allí no se pueden ni exportar ni, por
 * tanto, probar. Son las dos piezas con lógica real de esta pantalla.
 */

/**
 * El JSON que pega la persona: un objeto o un array de objetos.
 *
 * Se valida que cada elemento sea un OBJETO. La app de referencia envuelve en
 * array cualquier JSON válido, así que `null` viaja como `[null]` y `123` como
 * `[123]`, y el servicio IA los rechaza con un 422 que llega sin contexto.
 */
export function parseDocuments(raw: string): unknown[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(
      `El JSON no es válido: ${error instanceof Error ? error.message : "error de sintaxis"}`,
    );
  }
  const lista = Array.isArray(parsed) ? parsed : [parsed];
  if (lista.length === 0) {
    throw new Error("Pega al menos un documento (un objeto JSON o un array de objetos).");
  }
  const noSonObjetos = lista.filter((d) => d === null || typeof d !== "object" || Array.isArray(d));
  if (noSonObjetos.length > 0) {
    throw new Error(
      `Cada documento tiene que ser un objeto JSON. ${noSonObjetos.length} de ${lista.length} no lo son.`,
    );
  }
  return lista;
}

/**
 * La identidad del documento para el servicio IA.
 *
 * `source_path` es su clave de deduplicación, así que TIENE que derivarse del
 * documento y no del run: si llevara el id del run, el mismo presupuesto enviado
 * dos veces entraría dos veces, y la pantalla promete justo lo contrario. Es la
 * misma convención que usan los scripts de siembra (`data/…::<budget_id>`).
 *
 * Sin `budget_id` no hay identidad estable que usar, así que se cae al índice
 * dentro del lote: ese documento se podrá duplicar, y es mejor que rechazarlo.
 */
export function sourcePathDe(documento: unknown, indice: number): string {
  const id = (documento as { budget_id?: unknown })?.budget_id;
  return typeof id === "string" && id.trim().length > 0
    ? `corpus-ui::${id.trim()}`
    : `corpus-ui::sin-id#${indice}`;
}
