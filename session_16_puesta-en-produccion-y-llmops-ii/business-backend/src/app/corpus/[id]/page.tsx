import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import { corpusStatsSchema, type CorpusStats } from "@/lib/estimator/contracts";
import { RunView } from "./run-view";

export const dynamic = "force-dynamic";

/** Las fotos se guardaron como JSON: se parsean al leerlas, como todo contrato. */
function parseStats(value: unknown): CorpusStats | null {
  const resultado = corpusStatsSchema.safeParse(value);
  return resultado.success ? resultado.data : null;
}

export default async function AmpliacionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.indexRun.findUnique({ where: { id } });
  if (!run) notFound();

  return (
    <RunView
      run={{
        id: run.id,
        chunkType: run.chunkType,
        submittedCount: run.submittedCount,
        processedCount: run.processedCount,
        skippedCount: run.skippedCount,
        chunksCreated: run.chunksCreated,
        status: run.status,
        errorMessage: run.errorMessage,
        createdAt: run.createdAt.toISOString(),
      }}
      before={parseStats(run.beforeStats)}
      after={parseStats(run.afterStats)}
    />
  );
}
