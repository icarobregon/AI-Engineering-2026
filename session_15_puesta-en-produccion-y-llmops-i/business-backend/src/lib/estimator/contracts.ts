/**
 * The mirror of the estimator's Pydantic schemas.
 *
 * These are the only place this app knows the shape of the AI service, so when
 * the contract moves in Python it moves here and nowhere else. Parsing (rather
 * than casting) is deliberate: the estimate arrives as an untyped `dict` on the
 * Python side, and a field that silently went missing is exactly the kind of
 * break that a cast turns into a blank screen three components later.
 */
import { z } from "zod";

// Zod's messages reach the screen — both the form's validation errors and the
// notice shown when a stored payload no longer matches its contract. A global
// side effect on import is the API zod offers, and this module is the single
// place that owns schemas, so it is where it belongs.
z.config(z.locales.es());

// --- Session 4: the transactional estimate ----------------------------------

export const projectTypes = ["mobile_app", "web_saas", "internal_tool", "data_pipeline"] as const;
export const detailLevels = ["summary", "medium", "detailed"] as const;
export const outputFormats = ["phases_table", "line_items", "narrative"] as const;

export const estimationRequestSchema = z.object({
  // The bounds are the endpoint's, not ours: mirroring them means the form
  // rejects what the service would reject, with a message the user can act on.
  description: z.string().min(20).max(80_000),
  project_type: z.enum(projectTypes),
  detail_level: z.enum(detailLevels),
  output_format: z.enum(outputFormats),
});
export type EstimationRequest = z.infer<typeof estimationRequestSchema>;

export const phaseSchema = z.object({
  name: z.string(),
  duration_weeks: z.number(),
  cost_eur: z.number(),
  summary: z.string(),
});

export const estimationResultSchema = z.object({
  summary: z.string(),
  confidence_pct: z.number(),
  phases: z.array(phaseSchema),
  total_duration_weeks: z.number(),
  total_cost_eur: z.number(),
});
export type EstimationResult = z.infer<typeof estimationResultSchema>;

export const estimationResponseSchema = z.object({
  result: estimationResultSchema,
  prompt_version: z.string(),
  cached: z.boolean().default(false),
});
export type EstimationResponse = z.infer<typeof estimationResponseSchema>;

/** The service marks a refusal in prose, not in a field. */
export const OUT_OF_SCOPE_PREFIX = "Out of scope:";
export function isOutOfScope(result: EstimationResult): boolean {
  return result.summary.startsWith(OUT_OF_SCOPE_PREFIX);
}

// --- Sessions 13-14: the supervised, interruptible estimate ------------------

export const estimatedComponentSchema = z.object({
  component_id: z.string(),
  name: z.string(),
  estimated_hours: z.number(),
  grounded: z.boolean(),
  rationale: z.string(),
});

export const draftEstimateSchema = z.object({
  project: z.string(),
  components: z.array(estimatedComponentSchema).default([]),
  total_hours: z.number(),
  notes: z.string().default(""),
  /** Present only after a reviewer adjusted the total: what the system had said. */
  original_total_hours: z.number().nullish(),
});
export type DraftEstimate = z.infer<typeof draftEstimateSchema>;

export const budgetMatchSchema = z.object({
  component_id: z.string(),
  component: z.string(),
  reference_budget_id: z.string(),
  amount: z.number(),
  distance: z.number(),
});
export type BudgetMatch = z.infer<typeof budgetMatchSchema>;

/**
 * What the graph hands a reviewer when it stops. This is an interface, not a
 * log line — every field here is something the person needs on screen to decide.
 */
export const reviewPayloadSchema = z.object({
  estimation_id: z.string().nullish(),
  reason: z.string(),
  triggers: z.array(z.string()).default([]),
  estimate: draftEstimateSchema.nullish(),
  confidence: z.number().nullish(),
  concerns: z.array(z.string()).default([]),
  historical_band: z.object({ low: z.number(), high: z.number() }).nullish(),
  budget_matches: z.array(budgetMatchSchema).default([]),
});
export type ReviewPayload = z.infer<typeof reviewPayloadSchema>;

export const graphStatuses = [
  "validated",
  "needs_review",
  "awaiting_human_review",
  "routing_budget_exhausted",
] as const;
export type GraphStatus = (typeof graphStatuses)[number];

export const graphEstimateResponseSchema = z.object({
  estimate: draftEstimateSchema.nullish(),
  status: z.enum(graphStatuses),
  estimation_id: z.string(),
  errors: z.array(z.string()).default([]),
  review_payload: reviewPayloadSchema.nullish(),
});
export type GraphEstimateResponse = z.infer<typeof graphEstimateResponseSchema>;

export const humanActions = ["approve", "adjust", "reject"] as const;
export type HumanAction = (typeof humanActions)[number];

/**
 * `action` is required on the Python side and the router forwards the payload
 * without dropping nulls, so it always travels — even when the reviewer only
 * wrote a comment.
 */
export const humanDecisionSchema = z.object({
  action: z.enum(humanActions),
  adjusted_hours: z.number().min(0).nullish(),
  comment: z.string().nullish(),
  reviewer_id: z.string().nullish(),
});
export type HumanDecision = z.infer<typeof humanDecisionSchema>;

// --- Runtime model configuration --------------------------------------------

export const modelsConfigSchema = z.object({
  models: z.record(z.string(), z.object({ effective: z.string().nullish() }).loose()).default({}),
});
