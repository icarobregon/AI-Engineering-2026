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

/**
 * `GET /v1/estimate/graph/{id}/state` declares no response_model, so what comes
 * back is the LangGraph checkpoint serialised as-is. Everything is optional:
 * outside the four accumulators, a key does not exist in the state until some
 * node writes it.
 */
export const routingHopSchema = z.object({
  next_agent: z.string(),
  reason: z.string(),
});
export type RoutingHop = z.infer<typeof routingHopSchema>;

export const graphStateSchema = z.object({
  estimation_id: z.string(),
  next: z.array(z.string()).default([]),
  values: z
    .object({
      routing_trail: z.array(routingHopSchema).default([]),
      routing_steps: z.number().nullish(),
      requirements: z.array(z.string()).nullish(),
      components: z.array(z.object({ id: z.string(), name: z.string(), category: z.string() }).loose()).nullish(),
      budget_matches: z.array(budgetMatchSchema).nullish(),
      validation: z
        .object({
          is_coherent: z.boolean(),
          confidence: z.number(),
          concerns: z.array(z.string()).default([]),
          reasoning: z.string(),
        })
        .nullish(),
      confidence: z.number().nullish(),
      errors: z.array(z.string()).default([]),
    })
    .loose(),
});
export type GraphState = z.infer<typeof graphStateSchema>;

/**
 * Who decided a hop. The AI service does not label them, but the reasons the
 * rules write are literal constants in `supervisor.py`, so the three cases are
 * told apart reliably instead of guessed:
 *
 *   regla   — a precondition. You cannot search budgets before knowing the
 *             components; paying a model to rediscover that buys nothing.
 *   modelo  — the one question this domain genuinely has an opinion about.
 *   limite  — the routing budget ran out. The emergency brake, not a decision.
 *
 * It is the hybrid supervisor of Session 14, made visible.
 */
const RULE_REASONS = new Set([
  "nothing read yet",
  "no references gathered yet",
  "no estimate yet",
  "estimate not validated yet",
  "validation clean",
  "evidence gaps persist after re-searching",
]);

export type HopSource = "regla" | "modelo" | "limite";

export function hopSource(reason: string): HopSource {
  if (reason.startsWith("routing budget exhausted at")) return "limite";
  if (RULE_REASONS.has(reason) || reason.startsWith("unknown route ")) return "regla";
  return "modelo";
}

/** A denial the guard recorded. The only audit residue that travels over HTTP. */
export function deniedActions(errors: string[]): string[] {
  return errors.filter((e) => e.includes("denied —"));
}

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

// --- Session 5: conversational sessions --------------------------------------

export const tiers = ["executive", "pm", "developer", "default"] as const;
export type Tier = (typeof tiers)[number];

export const projectMetadataSchema = z.object({
  project_name: z.string().nullish(),
  assumed_team_size: z.number().nullish(),
  /** Never null: accumulated case-insensitively across turns. */
  mentioned_technologies: z.array(z.string()).default([]),
  agreed_scope: z.string().nullish(),
});

export const sessionInfoSchema = z.object({
  session_id: z.string(),
  /**
   * Messages in the sliding window, not turns. Compression trims it to
   * max_turns*2, so from turn seven on it sits at 12 forever — dividing by two
   * does NOT give you a turn count.
   */
  message_count: z.number(),
  max_turns: z.number(),
  metadata: projectMetadataSchema,
  /** Commitments promoted out of the window: NDA, frozen scope, compliance. */
  anchors_count: z.number().default(0),
  summary_chars: z.number().default(0),
  last_resolved_tier: z.string().nullish(),
  last_tier_rule: z.string().nullish(),
});
export type SessionInfo = z.infer<typeof sessionInfoSchema>;

export const turnObservationSchema = z
  .object({
    enriched_transcript_chars: z.number(),
    attachments_total_chars: z.number(),
    messages_in_window: z.number(),
    anchors_count: z.number(),
    summary_chars: z.number(),
    tokens_in: z.number(),
    tokens_out: z.number(),
    cost_usd: z.number(),
    latency_ms: z.number(),
    last_resolved_tier: z.string().nullish(),
  })
  .loose();

export const sessionEstimationSchema = estimationResponseSchema.extend({
  /** Populated by the conversational route; always null on the ACB one. */
  observation: turnObservationSchema.nullish(),
});

// --- Session 5: the Actor-Critic-Boss trace ----------------------------------

export const acbIterationSchema = z.object({
  /** Zero-indexed, as the service emits it. */
  iteration: z.number(),
  decision_after: z.string(),
  /** Typed as a plain string on the server, so no strict enum here. */
  critic_verdict: z.string(),
  /** The critic's confidence IN ITS OWN REVIEW, 0..100. */
  critic_confidence: z.number(),
  /** Pre-rendered "[severity] category @ field_path", capped at five. */
  issue_summary: z.array(z.string()).default([]),
});

export const bossTraceSchema = z
  .object({
    iterations: z.array(acbIterationSchema).default([]),
    /** In practice only "accept" or "synthesize": the budget branch is dead code. */
    final_decision: z.string(),
    iterations_run: z.number(),
  })
  .loose();
export type BossTrace = z.infer<typeof bossTraceSchema>;

export const acbResponseSchema = sessionEstimationSchema.extend({ acb: bossTraceSchema });
export type AcbResponse = z.infer<typeof acbResponseSchema>;

/**
 * The server rewrites the summary when it synthesises, prefixing the open
 * caveats and truncating to 1200 chars — so the model's own text can be gone
 * entirely. This prefix is the reliable way to tell that apart.
 */
export const SYNTHESIS_PREFIX = "⚠ Open caveats from independent review";

// --- Session 7: chunking strategy comparison ---------------------------------

/**
 * The eight strategies, in the order the AI service declares them. Three of them
 * call an external API per component, so they cost real money and take minutes;
 * the request must ALWAYS carry an explicit list, because an empty one means
 * "all eight" on the server side and that default spends money.
 */
export const chunkingStrategies = [
  { name: "structural", label: "Estructural", paid: false, provider: null },
  { name: "fixed_size", label: "Tamaño fijo", paid: false, provider: null },
  { name: "recursive", label: "Recursiva", paid: false, provider: null },
  { name: "sentence_window", label: "Ventana de frases", paid: false, provider: null },
  { name: "hierarchical", label: "Jerárquica", paid: false, provider: null },
  { name: "semantic", label: "Semántica", paid: true, provider: "OpenAI" },
  { name: "propositional", label: "Proposicional", paid: true, provider: "OpenAI" },
  { name: "contextual_retrieval", label: "Contextual", paid: true, provider: "Anthropic" },
] as const;

export type StrategyName = (typeof chunkingStrategies)[number]["name"];

/** What the reference app premarks: the cheap ones that run in seconds. */
export const defaultStrategies: StrategyName[] = ["structural", "fixed_size", "recursive"];

export const tokenDistributionSchema = z.object({
  // min/max are integers and p50/p95 interpolated floats. Not the same type.
  min: z.number(),
  p50: z.number(),
  p95: z.number(),
  max: z.number(),
});

export const chunkingStatsSchema = z.object({
  strategy: z.string(),
  n_chunks: z.number(),
  token_distribution: tokenDistributionSchema,
  /** Fewer than 20 tokens: too small to carry meaning on its own. */
  n_orphan_chunks: z.number(),
  /** More than 800 tokens: too big to retrieve precisely. */
  n_obese_chunks: z.number(),
  ingestion_cost_usd: z.number(),
  ingestion_seconds: z.number(),
});
export type ChunkingStats = z.infer<typeof chunkingStatsSchema>;

export const topChunkSchema = z.object({
  chunk_id: z.string(),
  /** Cosine similarity: it can be negative, so do not clamp it at zero. */
  cosine: z.number(),
  text_preview: z.string(),
});

export const queryResultSchema = z.object({
  strategy: z.string(),
  query: z.string(),
  top_k: z.array(topChunkSchema).default([]),
});
export type QueryResult = z.infer<typeof queryResultSchema>;

export const compareResponseSchema = z.object({
  // Dynamic keys: the strategy name. A z.object() would break the moment
  // somebody ticks a different box.
  stats_per_strategy: z.record(z.string(), chunkingStatsSchema),
  /** Arrives as {} — not as empty arrays per strategy — when no queries are sent. */
  queries_per_strategy: z.record(z.string(), z.array(queryResultSchema)).default({}),
});
export type CompareResponse = z.infer<typeof compareResponseSchema>;

// --- Runtime model configuration --------------------------------------------

/**
 * The seven knobs the AI service exposes, in the order its own tuple declares
 * them. Fixed on purpose: the endpoint rejects any key outside this set with a
 * 422, so a typo here becomes a runtime error rather than a silent no-op.
 */
export const modelKnobs = [
  "PRIMARY_MODEL",
  "FALLBACK_MODEL",
  "CRITIC_MODEL",
  "METADATA_EXTRACTOR_MODEL",
  "COMPRESSION_MODEL",
  "PROPOSITIONAL_CHUNKER_MODEL",
  "CONTEXTUAL_CHUNKER_MODEL",
] as const;
export type ModelKnob = (typeof modelKnobs)[number];

export const knobStateSchema = z.object({
  /** What the next LLM call will use: the override if there is one, else the default. */
  effective: z.string(),
  /** What `.env` says. Restoring a knob means going back to this. */
  default: z.string(),
  overridden: z.boolean(),
});
export type KnobState = z.infer<typeof knobStateSchema>;

export const modelsConfigSchema = z.object({
  models: z.record(z.string(), knobStateSchema),
  available_models: z.array(z.string()),
  /** Outside the knobs on purpose: changing it would invalidate every stored vector. */
  embedding_model: z.string(),
  embedding_model_note: z.string(),
});
export type ModelsConfig = z.infer<typeof modelsConfigSchema>;
