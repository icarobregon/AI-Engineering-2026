import { prisma } from "@/lib/db";
import { getModelsConfig } from "@/lib/estimator/config";
import { EstimatorError } from "@/lib/estimator/errors";
import { ConsoleView } from "./console-view";

export const dynamic = "force-dynamic";

export const metadata = { title: "Consola de agentes" };

export default async function AgentesPage() {
  // El catálogo de modelos lo tiene el servicio IA. Que no conteste no debe
  // vaciar la consola: sólo deja el desplegable sin opciones, y se dice.
  let availableModels: string[] = [];
  let modelsError: string | null = null;
  try {
    availableModels = (await getModelsConfig()).available_models;
  } catch (error) {
    modelsError =
      error instanceof EstimatorError
        ? error.userMessage
        : "No se pudo leer el catálogo de modelos.";
  }

  const [profiles, runs] = await Promise.all([
    prisma.agentProfile.findMany({ orderBy: [{ isDefault: "desc" }, { createdAt: "asc" }] }),
    prisma.agentRun.findMany({
      orderBy: { createdAt: "desc" },
      take: 20,
      select: {
        id: true,
        status: true,
        model: true,
        reasoningEffort: true,
        estimate: true,
        createdAt: true,
        profile: { select: { name: true } },
      },
    }),
  ]);

  return (
    <ConsoleView
      availableModels={availableModels}
      modelsError={modelsError}
      profiles={profiles.map((p) => ({
        id: p.id,
        name: p.name,
        description: p.description,
        model: p.model,
        reasoningEffort: p.reasoningEffort,
        maxIterations: p.maxIterations,
        isDefault: p.isDefault,
      }))}
      runs={runs.map((r) => ({
        id: r.id,
        status: r.status,
        model: r.model,
        reasoningEffort: r.reasoningEffort,
        profileName: r.profile?.name ?? null,
        totalHours: (r.estimate as { total_hours?: number } | null)?.total_hours ?? null,
        createdAt: r.createdAt.toISOString(),
      }))}
    />
  );
}
