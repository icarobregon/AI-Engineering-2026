/**
 * Lo que el revisor manda, validado antes de cruzar la frontera.
 *
 * Vive fuera de `actions.ts` porque un módulo `"use server"` sólo puede exportar
 * funciones asíncronas, y esto es aritmética pura que merece tests: es el último
 * sitio donde se puede evitar que una decisión mal formada llegue al checkpoint,
 * que es inmutable.
 */
import type { EstimatedComponent } from "@/lib/estimator/contracts";

/** Las horas que llegan del formulario, por `component_id`. */
export function parseComponentHours(raw: unknown): Record<string, number> {
  if (typeof raw !== "string" || raw.trim().length === 0) {
    throw new Error("No han llegado las horas por componente.");
  }

  let crudo: unknown;
  try {
    crudo = JSON.parse(raw);
  } catch {
    throw new Error("Las horas por componente no viajaron en un formato legible.");
  }
  if (crudo === null || typeof crudo !== "object" || Array.isArray(crudo)) {
    throw new Error("Las horas por componente no viajaron en un formato legible.");
  }

  const horas: Record<string, number> = {};
  for (const [id, valor] of Object.entries(crudo as Record<string, unknown>)) {
    // `null` es un campo que el revisor vació, no un cero: se deja fuera para
    // que lo cace la comprobación de componentes sin precio, con su nombre.
    if (valor == null) continue;
    if (typeof valor !== "number" || !Number.isFinite(valor) || valor < 0) {
      throw new Error(`Las horas de un componente no son un número válido: ${String(valor)}`);
    }
    horas[id] = valor;
  }
  return horas;
}

/**
 * Los componentes que quedarían a cero, POR NOMBRE, para poder decírselo a quien
 * revisa. Se mira contra la estimación guardada y no contra lo que manda el
 * formulario: un componente que el cliente omita entero no se puede echar de
 * menos si sólo se leen las claves que llegaron.
 */
export function componentesSinPrecio(
  components: EstimatedComponent[],
  horas: Record<string, number>,
): string[] {
  return components.filter((c) => !horas[c.component_id]).map((c) => c.name);
}
