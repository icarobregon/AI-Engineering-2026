import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import { agentEstimateSchema, agentTraceSchema } from "@/lib/estimator/contracts";
import { AgentRunView } from "./run-view";

export const dynamic = "force-dynamic";

export default async function EjecucionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.agentRun.findUnique({
    where: { id },
    include: { profile: { select: { name: true } } },
  });
  if (!run) notFound();

  const estimate = agentEstimateSchema.safeParse(run.estimate);
  const trace = agentTraceSchema.safeParse(run.trace);

  return (
    <AgentRunView
      run={{
        id: run.id,
        status: run.status,
        errorMessage: run.errorMessage,
        model: run.model,
        reasoningEffort: run.reasoningEffort,
        maxIterations: run.maxIterations,
        profileName: run.profile?.name ?? null,
        transcript: run.transcript,
        createdAt: run.createdAt.toISOString(),
        startedAt: run.startedAt?.toISOString() ?? null,
        finishedAt: run.finishedAt?.toISOString() ?? null,
      }}
      estimate={estimate.success ? estimate.data : null}
      trace={trace.success ? trace.data : null}
    />
  );
}
