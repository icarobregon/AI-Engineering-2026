/** Session 5 — the conversational flow and its Actor-Critic-Boss variant. */
import "server-only";

import { callEstimator } from "./client";
import {
  acbResponseSchema,
  sessionEstimationSchema,
  sessionInfoSchema,
  type AcbResponse,
  type SessionInfo,
} from "./contracts";
import { z } from "zod";

const createdSchema = z.object({ session_id: z.string() }).loose();

/** Las cuatro exigen el token de servicio: `callEstimator` lo manda por defecto. */
export async function createSession(): Promise<string> {
  const payload = await callEstimator<unknown>("/sessions", {
    method: "POST",
    body: {},
    timeoutMs: 10_000,
  });
  return createdSchema.parse(payload).session_id;
}

export async function getSession(sessionId: string): Promise<SessionInfo> {
  const payload = await callEstimator<unknown>(`/sessions/${encodeURIComponent(sessionId)}`, {
    timeoutMs: 10_000,
  });
  return sessionInfoSchema.parse(payload);
}

type TurnInput = {
  sessionId: string;
  transcript: string;
  projectType: string;
  detailLevel: string;
  outputFormat: string;
  /** Omitted entirely for automatic resolution: "auto" and "" are both a 422. */
  tier?: string;
  attachments: File[];
};

function turnForm(input: TurnInput): FormData {
  const form = new FormData();
  form.set("transcript", input.transcript);
  form.set("project_type", input.projectType);
  form.set("detail_level", input.detailLevel);
  form.set("output_format", input.outputFormat);
  if (input.tier) form.set("tier", input.tier);
  // Every file goes under the same literal field name.
  for (const file of input.attachments) form.append("attachments", file);
  return form;
}

export async function estimateInSession(input: TurnInput) {
  const payload = await callEstimator<unknown>(
    `/sessions/${encodeURIComponent(input.sessionId)}/estimate`,
    { method: "POST", formData: turnForm(input) },
  );
  return sessionEstimationSchema.parse(payload);
}

/**
 * Actor drafts, critic reviews, boss decides — up to three rounds, two LLM calls
 * each. The trace only exists in this response: the session keeps a single
 * assistant message, so it cannot be rebuilt from `GET /sessions/{id}` later.
 */
export async function estimateWithAcb(input: TurnInput): Promise<AcbResponse> {
  const payload = await callEstimator<unknown>(
    `/sessions/${encodeURIComponent(input.sessionId)}/estimate-acb`,
    { method: "POST", formData: turnForm(input) },
  );
  return acbResponseSchema.parse(payload);
}
