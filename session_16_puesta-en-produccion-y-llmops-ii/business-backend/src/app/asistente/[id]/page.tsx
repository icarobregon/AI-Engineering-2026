import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import {
  estimateTreeSchema,
  reformulationSchema,
  taskHoursResultSchema,
} from "@/lib/estimator/contracts";
import { RunWizard } from "./run-wizard";

export const dynamic = "force-dynamic";

/** Lo guardado se parsea al leerlo, igual que lo que llega por HTTP. */
function parse<T>(
  schema: { safeParse: (v: unknown) => { success: boolean; data?: T } },
  value: unknown,
) {
  const r = schema.safeParse(value);
  return r.success ? (r.data as T) : null;
}

export default async function AsistenteRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.ragRun.findUnique({ where: { id } });
  if (!run) notFound();

  return (
    <RunWizard
      run={{
        id: run.id,
        transcript: run.transcript,
        currentStep: run.currentStep,
        confirmedAt: run.confirmedAt?.toISOString() ?? null,
        createdAt: run.createdAt.toISOString(),
      }}
      reformulation={parse(reformulationSchema, run.reformulation)}
      proposed={parse(
        estimateTreeSchema.shape.modules,
        run.structure
          ? (run.structure as { estimate?: { modules?: unknown } }).estimate?.modules
          : null,
      )}
      reviewed={parse(estimateTreeSchema.shape.modules, run.reviewedModules)}
      taskHours={parse(taskHoursResultSchema, run.taskHours)}
      verification={
        run.verification as {
          lines: {
            module: string;
            task: string;
            hours: number;
            rate: number;
            cost: number;
            reliability: number | null;
            hadMatch: boolean;
          }[];
          totalHours: number;
          totalCostEur: number;
        } | null
      }
    />
  );
}
