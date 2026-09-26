/** Sesión 12 — el agente escrito a mano, lanzado por HTTP. */
import "server-only";

import { callEstimator } from "./client";
import { agentRunResponseSchema, type AgentRunResponse } from "./contracts";

/**
 * Corre el agente sobre una transcripción.
 *
 * Es síncrono y tarda minutos: el bucle encadena varias llamadas a un modelo de
 * razonamiento, una por vuelta. Quien llame a esto tiene que estar en segundo
 * plano — la pantalla sondea una fila, no esta promesa.
 *
 * Lo que no se pasa cae al `.env` del servicio, así que un perfil que sólo
 * cambia el modelo manda sólo el modelo.
 */
export async function runAgent(input: {
  transcript: string;
  model: string | null;
  reasoningEffort: string | null;
  maxIterations: number | null;
}): Promise<AgentRunResponse> {
  const payload = await callEstimator<unknown>("/v1/estimate/agent/run", {
    method: "POST",
    timeoutMs: 1_800_000,
    body: {
      transcript: input.transcript,
      ...(input.model ? { model: input.model } : {}),
      ...(input.reasoningEffort ? { reasoning_effort: input.reasoningEffort } : {}),
      ...(input.maxIterations ? { max_iterations: input.maxIterations } : {}),
    },
  });
  return agentRunResponseSchema.parse(payload);
}
