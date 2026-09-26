"use server";

import { redirect } from "next/navigation";

import { prisma } from "@/lib/db";
import { EstimatorError } from "@/lib/estimator/errors";
import { requestEstimation } from "@/lib/estimator/estimations";
import { estimationRequestSchema } from "@/lib/estimator/contracts";

export type FormState = { error: string | null; reason?: string | null };

/** The field names are the AI service's; what the form shows is the label. */
const fieldLabels: Record<string, string> = {
  description: "Descripción",
  project_type: "Tipo de proyecto",
  detail_level: "Nivel de detalle",
  output_format: "Formato",
};

/**
 * Transport, nothing else: validate, call, persist, redirect. The estimation
 * itself is the AI service's job — if any sizing logic appeared in this file,
 * there would be two systems deciding what a project costs.
 */
export async function createEstimation(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = estimationRequestSchema.safeParse({
    description: formData.get("description"),
    project_type: formData.get("project_type"),
    detail_level: formData.get("detail_level"),
    output_format: formData.get("output_format"),
  });

  if (!parsed.success) {
    const first = parsed.error.issues[0];
    const field = String(first.path[0] ?? "");
    return { error: `${fieldLabels[field] ?? "Formulario"}: ${first.message}` };
  }

  let id: string;
  try {
    const response = await requestEstimation(parsed.data);
    const row = await prisma.estimation.create({
      data: {
        description: parsed.data.description,
        projectType: parsed.data.project_type,
        detailLevel: parsed.data.detail_level,
        outputFormat: parsed.data.output_format,
        responsePayload: response,
        promptVersion: response.prompt_version,
        cached: response.cached,
      },
    });
    id = row.id;
  } catch (error) {
    if (error instanceof EstimatorError) {
      return {
        error: error.userMessage,
        reason: "reason" in error ? (error as { reason: string }).reason : null,
      };
    }
    throw error;
  }

  // Outside the try: redirect() signals by throwing, and catching it here would
  // turn a successful estimate into an error message.
  redirect(`/estimations/${id}`);
}
