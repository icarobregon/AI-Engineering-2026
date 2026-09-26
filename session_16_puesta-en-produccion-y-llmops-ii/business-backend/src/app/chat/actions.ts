"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

import { tiers, type AcbResponse } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { createSession, estimateInSession, estimateWithAcb } from "@/lib/estimator/sessions";
import { SESSION_COOKIE } from "./session-cookie";

export type TurnState = {
  error: string | null;
  notice: string | null;
  result: AcbResponse | null;
};

/** The AI service is the one that keeps the conversation; we only keep its id. */
async function rememberSession(sessionId: string) {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, sessionId, { httpOnly: true, sameSite: "lax", path: "/" });
}

export async function sendTurn(_previous: TurnState, formData: FormData): Promise<TurnState> {
  const transcript = String(formData.get("transcript") ?? "").trim();
  if (transcript.length < 20) {
    return { error: "El turno necesita al menos 20 caracteres.", notice: null, result: null };
  }

  const rawTier = String(formData.get("tier") ?? "");
  // "auto" is a UI label, not a value the service accepts: omitting the field is
  // what asks it to resolve the tier itself.
  const tier = (tiers as readonly string[]).includes(rawTier) ? rawTier : undefined;

  const attachments = formData
    .getAll("attachments")
    .filter((f): f is File => f instanceof File && f.size > 0);

  const acb = formData.get("mode") === "acb";
  const jar = await cookies();
  let sessionId = jar.get(SESSION_COOKIE)?.value ?? null;
  let notice: string | null = null;

  const run = async (id: string) => {
    const input = {
      sessionId: id,
      transcript,
      projectType: String(formData.get("project_type") ?? "web_saas"),
      detailLevel: String(formData.get("detail_level") ?? "medium"),
      outputFormat: String(formData.get("output_format") ?? "phases_table"),
      tier,
      attachments,
    };
    return acb ? await estimateWithAcb(input) : ((await estimateInSession(input)) as AcbResponse);
  };

  try {
    if (!sessionId) {
      sessionId = await createSession();
      await rememberSession(sessionId);
    }

    let result: AcbResponse;
    try {
      result = await run(sessionId);
    } catch (error) {
      // The AI service keeps sessions in memory: a restart loses them, and our
      // cookie still points at one that is gone. Open a new one and say so
      // rather than showing a 404 the person cannot act on.
      if (error instanceof EstimatorError && error.kind === "not_found") {
        sessionId = await createSession();
        await rememberSession(sessionId);
        notice = "La conversación anterior se perdió en el servicio IA. Se ha abierto una nueva.";
        result = await run(sessionId);
      } else {
        throw error;
      }
    }

    revalidatePath("/chat");
    return { error: null, notice, result };
  } catch (error) {
    if (error instanceof EstimatorError) {
      return { error: error.userMessage, notice: null, result: null };
    }
    throw error;
  }
}

export async function resetSession() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  revalidatePath("/chat");
}
