/** Sesión 11 — el corpus vectorial: mirarlo y ampliarlo. */
import "server-only";

import { callEstimator } from "./client";
import {
  corpusStatsSchema,
  ingestResponseSchema,
  type ChunkType,
  type CorpusStats,
  type IngestResponse,
} from "./contracts";

/** La foto del corpus: documentos y chunks por colección, y si hay índice HNSW. */
export async function getCorpusStats(): Promise<CorpusStats> {
  const payload = await callEstimator<unknown>("/embeddings/index/stats", {
    timeoutMs: 15_000,
  });
  return corpusStatsSchema.parse(payload);
}

/**
 * Indexa UN documento.
 *
 * El servicio IA no tiene ingesta por lotes: `/embeddings/ingest` acepta un
 * documento y responde cuando lo ha troceado, embebido y persistido. El lote y
 * su progreso son cosa de esta capa, que es exactamente el reparto que hace la
 * aplicación de referencia — su sondeo también va contra su propio backend, no
 * contra el servicio IA.
 *
 * `source_path` es la clave de deduplicación del servicio: un documento ya
 * ingerido responde 409, que aquí no es un error sino «saltado».
 */
export async function ingestDocument(input: {
  document: unknown;
  chunkType: ChunkType;
  sourcePath: string;
}): Promise<IngestResponse> {
  const payload = await callEstimator<unknown>("/embeddings/ingest", {
    method: "POST",
    // Trocear + embeber un presupuesto entero tarda segundos, no milisegundos.
    timeoutMs: 120_000,
    body: {
      source_path: input.sourcePath,
      document_type: "historical_budget",
      chunk_type: input.chunkType,
      content: input.document,
    },
  });
  return ingestResponseSchema.parse(payload);
}
