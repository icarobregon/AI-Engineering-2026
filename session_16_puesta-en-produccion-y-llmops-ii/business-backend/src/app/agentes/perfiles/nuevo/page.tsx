import type { ModelsConfig } from "@/lib/estimator/contracts";
import { getModelsConfig } from "@/lib/estimator/config";
import { ProfileForm } from "../profile-form";

export const dynamic = "force-dynamic";
export const metadata = { title: "Nuevo perfil de agente" };

export default async function NuevoPerfilPage() {
  let availableModels: string[] = [];
  let modelPrices: ModelsConfig["model_prices"] = {};
  try {
    const config = await getModelsConfig();
    availableModels = config.available_models;
    modelPrices = config.model_prices;
  } catch {
    // Sin catálogo, el desplegable queda vacío y no hay precios que enseñar.
  }
  return <ProfileForm availableModels={availableModels} modelPrices={modelPrices} profile={null} />;
}
