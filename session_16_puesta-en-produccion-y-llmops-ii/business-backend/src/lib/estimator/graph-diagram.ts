/** Sesiones 13–14 — el grafo multi-agente, dibujado desde sí mismo. */
import "server-only";

import { callEstimator } from "./client";
import { graphDiagramSchema, type GraphDiagram } from "./contracts";

/**
 * La topología real del grafo compilado.
 *
 * No es un dibujo mantenido a mano. Eso importa más de lo que parece: desde la
 * S14 las aristas no se declaran —viven dentro de cada `Command`— y LangGraph
 * las reconstruye resolviendo la anotación de cada nodo. Si esa anotación deja
 * de resolver, las aristas desaparecen de aquí, y ésa es la señal más temprana
 * de un fallo que por lo demás es mudo.
 */
export async function getGraphDiagram(): Promise<GraphDiagram> {
  const payload = await callEstimator<unknown>("/v1/estimate/graph/diagram", {
    timeoutMs: 15_000,
  });
  return graphDiagramSchema.parse(payload);
}
