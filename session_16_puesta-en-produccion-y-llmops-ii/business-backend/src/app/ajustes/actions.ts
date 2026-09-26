"use server";

import { revalidatePath } from "next/cache";

import { modelKnobs } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { updateModels } from "@/lib/estimator/config";

export type FormState = { error: string | null; saved: boolean };

export async function saveModels(_previous: FormState, formData: FormData): Promise<FormState> {
  const models: Record<string, string | null> = {};
  for (const knob of modelKnobs) {
    const value = String(formData.get(knob) ?? "");
    // "" is what the "default" option submits, and it is NOT a reset for the AI
    // service: it reaches the catalogue and comes back as a 422. null is.
    models[knob] = value === "" ? null : value;
  }

  try {
    await updateModels(models);
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage, saved: false };
    throw error;
  }

  // The badge in the navbar reads this on every render, so the whole tree.
  revalidatePath("/", "layout");
  return { error: null, saved: true };
}
