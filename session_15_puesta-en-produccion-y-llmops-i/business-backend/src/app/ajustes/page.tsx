import { Alert } from "antd";

import { getModelsConfig } from "@/lib/estimator/config";
import { EstimatorError } from "@/lib/estimator/errors";
import { SettingsView } from "./settings-view";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  try {
    const config = await getModelsConfig();
    return <SettingsView config={config} />;
  } catch (error) {
    // Degrading here rather than throwing is the same choice the reference app
    // makes: the page explains itself instead of rendering an error boundary.
    const message =
      error instanceof EstimatorError ? error.userMessage : "No se pudo leer la configuración.";
    return (
      <Alert
        type="warning"
        showIcon
        message="Los ajustes no están disponibles"
        description={`${message} Levanta el stack y recarga.`}
      />
    );
  }
}
