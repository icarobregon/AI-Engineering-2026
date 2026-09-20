import { prisma } from "@/lib/db";
import { getCorpusStats } from "@/lib/estimator/corpus";
import { EstimatorError } from "@/lib/estimator/errors";
import type { CorpusStats } from "@/lib/estimator/contracts";
import { CorpusView } from "./corpus-view";

export const dynamic = "force-dynamic";

export const metadata = { title: "Corpus e índice" };

export default async function CorpusPage() {
  // Dos fuentes independientes: la foto del corpus la tiene el servicio IA, y el
  // histórico de ampliaciones lo tenemos nosotros. Que una falle no debe tapar a
  // la otra, así que el error viaja hasta la vista en vez de vaciar la página.
  let stats: CorpusStats | null = null;
  let statsError: string | null = null;
  try {
    stats = await getCorpusStats();
  } catch (error) {
    statsError =
      error instanceof EstimatorError ? error.userMessage : "No se pudo leer el estado del corpus.";
  }

  const runs = await prisma.indexRun.findMany({
    orderBy: { createdAt: "desc" },
    take: 20,
    select: {
      id: true,
      chunkType: true,
      submittedCount: true,
      processedCount: true,
      chunksCreated: true,
      status: true,
      createdAt: true,
    },
  });

  return <CorpusView stats={stats} statsError={statsError} runs={runs} />;
}
