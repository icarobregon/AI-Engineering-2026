/**
 * Los cinco pasos, con nombre humano.
 *
 * Fichero aparte y sin `"use server"`: lo comparten el índice, el detalle y la
 * barra de progreso, y un módulo de acciones sólo puede exportar funciones async.
 */
export const stepLabels: Record<string, string> = {
  reformulation: "Reformulación",
  structure: "Estructura",
  review: "Revisión",
  hours: "Horas",
  verification: "Verificación",
};

export const stepOrder = ["reformulation", "structure", "review", "hours", "verification"] as const;
