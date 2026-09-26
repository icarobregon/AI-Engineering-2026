import { prisma } from "@/lib/db";
import { AssistantIndex } from "./assistant-index";

export const dynamic = "force-dynamic";

export const metadata = { title: "Asistente de estimación" };

export default async function AsistentePage() {
  const runs = await prisma.ragRun.findMany({
    orderBy: { createdAt: "desc" },
    take: 20,
    select: {
      id: true,
      transcript: true,
      currentStep: true,
      confirmedAt: true,
      verification: true,
      createdAt: true,
    },
  });

  return (
    <AssistantIndex
      runs={runs.map((r) => ({
        id: r.id,
        // Sólo el arranque: la transcripción entera no cabe en una celda y el
        // detalle la enseña completa.
        preview: r.transcript.slice(0, 90),
        currentStep: r.currentStep,
        confirmedAt: r.confirmedAt?.toISOString() ?? null,
        totalHours: (r.verification as { totalHours?: number } | null)?.totalHours ?? null,
        totalCostEur: (r.verification as { totalCostEur?: number } | null)?.totalCostEur ?? null,
        createdAt: r.createdAt.toISOString(),
      }))}
    />
  );
}
