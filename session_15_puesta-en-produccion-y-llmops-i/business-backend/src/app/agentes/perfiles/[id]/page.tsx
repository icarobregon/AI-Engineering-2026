import { notFound } from "next/navigation";

import { prisma } from "@/lib/db";
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
  try {
    availableModels = (await getModelsConfig()).available_models;
  } catch {
    // Sin catálogo se puede escribir el nombre del modelo a mano.
  }

  return (
    <ProfileForm
      availableModels={availableModels}
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
