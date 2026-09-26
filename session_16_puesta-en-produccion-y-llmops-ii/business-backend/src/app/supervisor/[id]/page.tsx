import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import { getSupervisedRunState } from "@/lib/estimator/graph";
import type { GraphState } from "@/lib/estimator/contracts";
import { RunView } from "./run-view";

export const dynamic = "force-dynamic";

export default async function SupervisorRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.supervisorRun.findUnique({
    where: { id },
    select: {
      id: true,
      estimationId: true,
      transcript: true,
      runState: true,
      status: true,
      estimate: true,
      reviewPayload: true,
      budgetMatches: true,
      humanDecision: true,
      errors: true,
      proposal: true,
    },
  });
  if (!run) notFound();

  // Diagnostic, not load-bearing: if the AI service cannot answer, the page
  // still renders the estimate and the decision — it just loses the trail.
  // Skipped entirely while the run is in flight: the trail would be half
  // written, and the progress panel polls for that anyway.
  let state: GraphState | null = null;
  if (run.runState !== "running") {
    try {
      state = await getSupervisedRunState(run.estimationId);
    } catch {
      state = null;
    }
  }

  return <RunView run={run} state={state} />;
}
