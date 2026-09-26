import { Alert } from "antd";

import { getModelsConfig } from "@/lib/estimator/config";
import { EstimatorError } from "@/lib/estimator/errors";
import { SettingsView } from "./settings-view";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const leido = await leerConfig();

  return leido.error === null ? (
    <SettingsView config={leido.config} />
  ) : (
    <Alert
      type="warning"
      showIcon
      message="Los ajustes no están disponibles"
      description={`${leido.error} Levanta el stack y recarga.`}
    />
  );
}

/**
 * La lectura, con su fallo ya traducido a texto.
 *
 * Existe para que el try/catch NO envuelva ningún JSX. Aquí no llegaba a ser un
 * fallo —construir un elemento no ejecuta el componente, así que no hay nada que
 * el catch pudiera tragarse— pero la forma invita a creer que el catch protege
 * el render de SettingsView, y no lo hace: para cuando ese componente se
 * ejecuta, esta función ya devolvió. Separar la lectura de la pintura deja las
 * dos cosas diciendo lo que de verdad hacen.
 *
 * Degradar en vez de lanzar es la misma decisión que toma la app de referencia:
 * la página se explica sola en lugar de pintar un error boundary.
 */
async function leerConfig() {
  try {
    return { config: await getModelsConfig(), error: null };
  } catch (error) {
    return {
      config: null,
      error:
        error instanceof EstimatorError ? error.userMessage : "No se pudo leer la configuración.",
    };
  }
}
