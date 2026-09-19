import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import { RunView } from "./run-view";

export const dynamic = "force-dynamic";

export default async function SupervisorRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.supervisorRun.findUnique({
    where: { id },
    select: {
      id: true,
      estimationId: true,
      runState: true,
      status: true,
      estimate: true,
      reviewPayload: true,
      humanDecision: true,
      errors: true,
    },
  });
  if (!run) notFound();

  return <RunView run={run} />;
}
