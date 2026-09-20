import { getModelsConfig } from "@/lib/estimator/config";
import { ProfileForm } from "../profile-form";

export const dynamic = "force-dynamic";
export const metadata = { title: "Nuevo perfil de agente" };

export default async function NuevoPerfilPage() {
  let availableModels: string[] = [];
  try {
    availableModels = (await getModelsConfig()).available_models;
  } catch {
    // Sin catálogo se puede escribir el nombre del modelo a mano.
  }
  return <ProfileForm availableModels={availableModels} profile={null} />;
}
