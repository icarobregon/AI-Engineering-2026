/**
 * Qué hace cada nodo del grafo, en prosa.
 *
 * Vive aquí y no en una pantalla porque lo leen dos: el diagrama de `/grafo` y
 * el feed de progreso de una ejecución. Copiar las etiquetas en la segunda es
 * cómo se llega a que el mismo nodo se llame de dos maneras distintas.
 *
 * Los NOMBRES salen del grafo compilado; esto es sólo la glosa. Un nodo que no
 * esté aquí se pinta igual, con su nombre y sin descripción: así, añadir un
 * agente en Python lo hace aparecer en estas pantallas sin tocarlas, que es el
 * fallo correcto — aparecer sin glosa es mucho mejor que no aparecer.
 */
export type NodeRole = { titulo: string; que: string; herramientas?: string };

export const graphNodes: Record<string, NodeRole> = {
  supervisor: {
    titulo: "Supervisor",
    que: "Decide quién actúa en cada paso. Es híbrido: cuatro precondiciones son ifs de Python y al modelo se le hace exactamente una pregunta — el validador señaló evidencia escasa, ¿se vuelve a buscar o esto lo mira una persona?",
  },
  requirements_extractor: {
    titulo: "Extractor de requisitos",
    que: "Convierte la transcripción en requisitos y componentes.",
    herramientas: "ninguna",
  },
  budget_searcher: {
    titulo: "Buscador de presupuestos",
    que: "Busca análogos históricos, componente a componente.",
    herramientas: "search_budgets",
  },
  estimate_generator: {
    titulo: "Generador de la estimación",
    que: "Pone precio a los componentes. Las horas las da la herramienta —mediana de las referencias por 1,15 de contingencia—; al modelo sólo se le piden la justificación y las notas, así que «el modelo se inventa un número» no es un modo de fallo disponible.",
    herramientas: "calculate_estimate",
  },
  coherence_validator: {
    titulo: "Validador de coherencia",
    que: "Produce la señal de confianza. No se le pregunta al modelo cuánto confía en su propia respuesta: se calcula.",
    herramientas: "validate_estimate",
  },
  human_review_gate: {
    titulo: "Puerta humana",
    que: "Pausa la ejecución y espera. Dispara con confianza baja, con la estimación fuera de la banda histórica, o cuando el buscador corrió y no encontró nada. No hace nada más que leer el estado e interrumpir: interrupt() vuelve a ejecutar el cuerpo entero al reanudar, así que lo que escribiera se perdería.",
  },
  finalize: {
    titulo: "Cierre",
    que: "El único que escribe el estado final.",
  },
};

/** El título de un nodo, o su propio nombre si no está glosado. */
export function nodeTitle(nombre: string): string {
  return graphNodes[nombre]?.titulo ?? nombre;
}
