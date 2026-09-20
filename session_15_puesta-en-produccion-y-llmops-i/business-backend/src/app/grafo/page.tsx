import { getGraphDiagram } from "@/lib/estimator/graph-diagram";
import { EstimatorError } from "@/lib/estimator/errors";
import type { GraphDiagram } from "@/lib/estimator/contracts";
import { GraphView } from "./graph-view";

export const dynamic = "force-dynamic";

export const metadata = { title: "Flujo multi-agente" };

export default async function GrafoPage() {
  let diagram: GraphDiagram | null = null;
  let error: string | null = null;
  try {
    diagram = await getGraphDiagram();
  } catch (e) {
    // El grafo se compila en el arranque del servicio IA; si su checkpointer no
    // abrió, esta pantalla no tiene nada que enseñar y lo dice.
    error =
      e instanceof EstimatorError
        ? e.userMessage
        : "No se pudo leer la topología del grafo.";
  }

  return <GraphView diagram={diagram} error={error} />;
}
