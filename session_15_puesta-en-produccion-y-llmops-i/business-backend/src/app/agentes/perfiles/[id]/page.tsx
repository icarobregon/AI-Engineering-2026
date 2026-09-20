import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
import type { ModelsConfig } from "@/lib/estimator/contracts";
import { getModelsConfig } from "@/lib/estimator/config";
import { ProfileForm } from "../profile-form";

export const dynamic = "force-dynamic";
export const metadata = { title: "Editar perfil de agente" };

export default async function EditarPerfilPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const profile = await prisma.agentProfile.findUnique({ where: { id } });
  if (!profile) notFound();

  let availableModels: string[] = [];
  let modelPrices: ModelsConfig["model_prices"] = {};
  try {
    const config = await getModelsConfig();
    availableModels = config.available_models;
    modelPrices = config.model_prices;
  } catch {
    // Sin catálogo, el desplegable queda vacío y no hay precios que enseñar.
  }

  return (
    <ProfileForm
      availableModels={availableModels}
      modelPrices={modelPrices}
      profile={{
        id: profile.id,
        name: profile.name,
        description: profile.description,
        model: profile.model,
        reasoningEffort: profile.reasoningEffort,
        maxIterations: profile.maxIterations,
        isDefault: profile.isDefault,
      }}
    />
  );
}
