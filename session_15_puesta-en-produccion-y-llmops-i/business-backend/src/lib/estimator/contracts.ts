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
  /**
   * Lo que dijo el sistema, presente SÓLO en las líneas que el revisor cambió.
   * Que falte no significa «no revisado»: significa «revisado y confirmado», o
   * no tocado. La distinción la hace el servicio para que la pantalla no tenga
   * que comparar números y acabe tachando cifras idénticas.
   */
  original_estimated_hours: z.number().nullish(),
});

export type EstimatedComponent = z.infer<typeof estimatedComponentSchema>;

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
 * Una referencia abierta por dentro: el módulo histórico con sus tareas.
 *
 * `total_hours` es la suma de `tasks` y coincide con el `amount` del match que
 * la citó — el mismo número visto por dentro. Eso es lo que convierte la
 * pantalla en algo auditable: no enseña un dato parecido, enseña la
 * descomposición de lo que se usó.
 */
export const referenceTaskSchema = z.object({
  component_id: z.string(),
  name: z.string(),
  description: z.string(),
  tech_stack: z.string(),
  complexity: z.string(),
  estimated_hours: z.number(),
});
export type ReferenceTask = z.infer<typeof referenceTaskSchema>;

export const referenceSchema = z.object({
  reference_budget_id: z.string(),
  budget_id: z.string(),
  module: z.string(),
  project: z.string(),
  client_sector: z.string(),
  year: z.number().nullish(),
  main_technology: z.string(),
  total_hours: z.number(),
  tasks: z.array(referenceTaskSchema),
});
export type Reference = z.infer<typeof referenceSchema>;

export const referencesResponseSchema = z.object({
  references: z.array(referenceSchema),
  /** Lo que el grafo citó y el corpus ya no tiene: se enseña, no se esconde. */
  missing: z.array(z.string()).default([]),
});
export type ReferencesResponse = z.infer<typeof referencesResponseSchema>;

/**
 * La banda histórica: lo que han costado los proyectos de esta forma.
 *
 * NO es un campo del estado — se deriva de los componentes y sus análogos, y el
 * servicio la calcula con la misma función para el payload del revisor y para
 * `GET /state`. Los tres contadores no son adorno: la banda está ESCALADA por
 * cobertura, así que «5 de 8 componentes» es lo que dice cuánto del proyecto
 * respalda de verdad. El espejo anterior se quedaba con `low` y `high` y zod
 * descartaba el resto en silencio.
 */
export const historicalBandSchema = z.object({
  low: z.number(),
  high: z.number(),
  covered_components: z.number().int(),
  total_components: z.number().int(),
  references: z.number().int(),
});
export type HistoricalBand = z.infer<typeof historicalBandSchema>;

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
  historical_band: historicalBandSchema.nullish(),
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
  /**
   * Qué modelo decidió este salto, cuando lo decidió un modelo. Ausente en los
   * saltos de regla, que son cuatro de cada cinco. Es lo único que permite
   * preguntarle a los runs guardados si un router enruta mejor que otro.
   */
  router: z.string().nullish(),
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
      components: z
        .array(z.object({ id: z.string(), name: z.string(), category: z.string() }).loose())
        .nullish(),
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
      /**
       * Los dos que consolidan la fila cuando un run arrancado en segundo plano
       * termina. No estaban declarados porque hasta la S15 el resultado llegaba
       * en la respuesta del arranque; con el arranque no bloqueante ya no hay
       * tal respuesta y este verbo es el que lo trae.
       */
      estimate: draftEstimateSchema.nullish(),
      status: z.enum(graphStatuses).nullish(),
    })
    .loose(),
  /**
   * Derivada, no almacenada: por eso viaja fuera de `values`. Es la que permite
   * enseñar el mismo marco de referencia en una ejecución terminada que el que
   * ve un revisor cuando el sistema se para.
   */
  historical_band: historicalBandSchema.nullish(),
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

/**
 * Las que un revisor puede ELEGIR hoy. «adjust» ya no está: desde la S15 se
 * ajusta componente a componente y el total se deriva de la suma, así que
 * aprobar con cambios ES aprobar.
 */
export const humanActions = ["approve", "reject"] as const;
export type HumanAction = (typeof humanActions)[number];

/**
 * Las que se pueden LEER, que es un superconjunto y por un motivo concreto: en
 * `supervisor_runs.human_decision` hay decisiones guardadas como «adjust» de
 * antes de la S15, y este esquema las relee para pintar la tarjeta de quién
 * decidió qué. Narrow aquí y esa fila deja de parsear y su tarjeta desaparece.
 *
 * Ojo, el caso del servicio IA es el CONTRARIO y por eso allí sí se quitó: su
 * `HumanDecision` valida peticiones entrantes y nunca relee un checkpoint, así
 * que conservar el valor sólo dejaba aceptando una acción que nadie puede ya
 * enviar. Un enum de lectura y otro de entrada no es incoherencia: son dos
 * preguntas distintas.
 */
export const humanActionsHistoricas = ["approve", "adjust", "reject"] as const;

export const humanDecisionSchema = z.object({
  action: z.enum(humanActionsHistoricas),
  /** El total suelto de las S13-S14. Sólo aparece en decisiones de entonces. */
  adjusted_hours: z.number().min(0).nullish(),
  /** Las horas que decidió el revisor, por `component_id`. */
  component_hours: z.record(z.string(), z.number().min(0)).nullish(),
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
 * Los ocho knobs que expone el servicio IA, en el orden en que los declara su
 * propia tupla. Fija a propósito: el endpoint rechaza con un 422 cualquier
 * clave fuera de este conjunto, así que una errata aquí es un error en
 * ejecución y no un no-op silencioso.
 *
 * El orden de despliegue importa y falla en el sitio equivocado. `actions.ts`
 * manda TODOS los knobs en cada guardado y el PUT valida las claves antes de
 * escribir nada, de una pieza: si esta lista se adelanta a `MODEL_KEYS` en el
 * servicio, el 422 no afecta sólo a la fila nueva — deja la pantalla entera sin
 * poder guardar, también los siete de siempre. Al revés sólo falta una fila.
 */
export const modelKnobs = [
  "PRIMARY_MODEL",
  "FALLBACK_MODEL",
  "CRITIC_MODEL",
  "METADATA_EXTRACTOR_MODEL",
  "COMPRESSION_MODEL",
  "PROPOSITIONAL_CHUNKER_MODEL",
  "CONTEXTUAL_CHUNKER_MODEL",
  "GRAPH_SUPERVISOR_MODEL",
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
  /** El catálogo se cura a mano: viaja con su fecha y sus fuentes. */
  catalog_generated_at: z.string(),
  catalog_sources: z.array(z.string()),
  /** USD por millón de tokens, por modelo del catálogo. */
  model_prices: z.record(z.string(), z.object({ input: z.number(), output: z.number() })),
  /**
   * La excepción del catálogo, servida como dato (S15 PoC).
   *
   * `available_models` es una lista plana porque casi todo sirve para casi
   * todo. Los modelos de DECISIÓN no: devuelven una elección, no texto, así que
   * sólo valen donde se decide algo. La regla viene del servidor —que es quien
   * la aplica con un 422— en lugar de reimplementarse aquí, que es como una
   * pantalla y su endpoint acaban opinando distinto.
   */
  decision_only_knobs: z.array(z.string()).default([]),
  decision_models: z.array(z.string()).default([]),
});
export type ModelsConfig = z.infer<typeof modelsConfigSchema>;

// ---------------------------------------------------------------------------
// Corpus e índice (S11) — GET /embeddings/index/stats
// ---------------------------------------------------------------------------

export const collectionStatSchema = z.object({
  collection: z.string(),
  documents: z.number().int().nonnegative(),
  chunks: z.number().int().nonnegative(),
  /**
   * Sin índice HNSW la búsqueda vectorial es un sequential scan: funciona con
   * mil chunks y deja de funcionar con cien mil, sin avisar y sin error.
   */
  hnsw_indexed: z.boolean(),
});
export type CollectionStat = z.infer<typeof collectionStatSchema>;

export const corpusStatsSchema = z.object({
  collections: z.array(collectionStatSchema),
  total_documents: z.number().int().nonnegative(),
  total_chunks: z.number().int().nonnegative(),
});
export type CorpusStats = z.infer<typeof corpusStatsSchema>;

/** Lo que `POST /embeddings/ingest` responde por documento aceptado. */
export const ingestResponseSchema = z.object({
  document_id: z.number().int(),
  chunks_created: z.number().int().nonnegative(),
  embedding_dimension: z.number().int(),
  ingestion_time_ms: z.number().int().nonnegative(),
});
export type IngestResponse = z.infer<typeof ingestResponseSchema>;

/** Los dos tipos de chunk que el corpus acepta hoy. */
export const chunkTypes = ["budget_component", "historical_task"] as const;
export type ChunkType = (typeof chunkTypes)[number];

/** Estados de una ampliación. `failed` existe para que un fallo no se pinte en verde. */
export const indexRunStatuses = ["pending", "running", "completed", "failed"] as const;
export type IndexRunStatus = (typeof indexRunStatuses)[number];

// ---------------------------------------------------------------------------
// Asistente RAG de cinco pasos (S09–S12)
// ---------------------------------------------------------------------------

export const scales = ["small", "medium", "large", "unknown"] as const;
export const confidences = ["high", "medium", "low", "insufficient"] as const;

/** Lo que la reformulación saca de una transcripción llena de ruido. */
export const estimationQuerySchema = z.object({
  function: z.string(),
  technologies: z.array(z.string()).default([]),
  sector: z.string().nullable().default(null),
  scale: z.enum(scales).default("unknown"),
  country: z.string().nullable().default(null),
  regulations: z.array(z.string()).default([]),
  constraints: z.array(z.string()).default([]),
});
export type EstimationQuery = z.infer<typeof estimationQuerySchema>;

export const reformulationSchema = z.object({
  query: estimationQuerySchema,
  search_text: z.string(),
});
export type Reformulation = z.infer<typeof reformulationSchema>;

/**
 * El árbol que devuelve la estructura.
 *
 * `grounded`, `sources` y `engineer_days` llegan vacíos o nulos en este flujo:
 * desde la S10 la estructura se genera LIBRE, sin presupuestos delante, y el
 * retrieval vuelve a entrar por tarea en el paso de horas. Se mantienen en el
 * espejo porque el contrato los trae, no porque la pantalla los pinte.
 */
export const taskItemSchema = z.object({
  name: z.string(),
  description: z.string().nullable().default(null),
  grounded: z.boolean().default(false),
  engineer_days: z.number().int().nullable().default(null),
});
export type TaskItem = z.infer<typeof taskItemSchema>;

export const workModuleSchema = z.object({
  name: z.string(),
  description: z.string().nullable().default(null),
  tasks: z.array(taskItemSchema).default([]),
});
export type WorkModule = z.infer<typeof workModuleSchema>;

export const estimateTreeSchema = z.object({
  modules: z.array(workModuleSchema).default([]),
  /** Un supuesto del modelo: qué asume, cuánto pesa y por qué. */
  assumptions: z
    .array(
      z.object({
        description: z.string(),
        impact: z.string(),
        rationale: z.string(),
      }),
    )
    .default([]),
  confidence: z.enum(confidences),
});
export type EstimateTree = z.infer<typeof estimateTreeSchema>;

export const structureResultSchema = z.object({ estimate: estimateTreeSchema }).loose();
export type StructureResult = z.infer<typeof structureResultSchema>;

/** Una tarea histórica de la que salieron las horas. */
export const taskNeighborSchema = z.object({
  source_id: z.number().int(),
  budget_id: z.string().nullable().default(null),
  estimated_hours: z.number().int().nonnegative(),
  distance: z.number(),
});

export const taskHoursEstimateSchema = z.object({
  module: z.string(),
  task: z.string(),
  estimated_hours: z.number().int().nonnegative().nullable().default(null),
  reliability: z.number().min(0).max(1).nullable().default(null),
  has_match: z.boolean(),
  dispersion: z.number().nonnegative().nullable().default(null),
  neighbors: z.array(taskNeighborSchema).default([]),
});
export type TaskHoursEstimate = z.infer<typeof taskHoursEstimateSchema>;

export const taskHoursResultSchema = z.object({
  tasks: z.array(taskHoursEstimateSchema).default([]),
});
export type TaskHoursResult = z.infer<typeof taskHoursResultSchema>;

/** Los cinco pasos, en orden. El `current_step` de la fila es uno de éstos. */
export const wizardSteps = [
  "reformulation",
  "structure",
  "review",
  "hours",
  "verification",
] as const;
export type WizardStep = (typeof wizardSteps)[number];

/** Por debajo de esto, las horas se enseñan en ámbar: el consenso fue flojo. */
export const RELIABILITY_OK = 0.66;

/** Tarifa por defecto de una fila nueva. Sin ella el coste sale 0 sin avisar. */
export const DEFAULT_RATE_EUR = 75;

// ---------------------------------------------------------------------------
// Diagrama del grafo multi-agente (S13–S14)
// ---------------------------------------------------------------------------

export const graphDiagramSchema = z.object({
  /** Sintaxis Mermaid, derivada del grafo COMPILADO. */
  mermaid: z.string(),
  nodes: z.array(z.string()),
  entry_point: z.string(),
});
export type GraphDiagram = z.infer<typeof graphDiagramSchema>;

// ---------------------------------------------------------------------------
// Consola de agentes (S12) — POST /v1/estimate/agent/run
// ---------------------------------------------------------------------------

export const reasoningEfforts = ["minimal", "low", "medium", "high"] as const;
export type ReasoningEffort = (typeof reasoningEfforts)[number];

/**
 * Si el agente puede ejecutar ese modelo, que son MENOS que los del catálogo.
 *
 * `available_models` sirve a toda la aplicación, pero el bucle del agente llama
 * a la Responses API de OpenAI y le manda `reasoning` en todas las vueltas. Eso
 * deja fuera dos grupos: los modelos de Anthropic —el cliente es `AsyncOpenAI`,
 * y esa ruta no tiene proveedor de reserva— y los de OpenAI que no razonan, o
 * sea las familias GPT-4o y GPT-4.1, que rechazan el parámetro.
 *
 * Se decide por la FORMA del nombre y no con una lista escrita a mano, igual
 * que `_provider_from_model` en el servicio y por el mismo motivo: una lista
 * enumerada se queda atrás en cuanto sale un modelo nuevo, y lo hace callando.
 * La forma se equivoca en el otro sentido —un futuro GPT-7 que no razonara
 * entraría sin merecerlo—, y de ahí que la pantalla avise ADEMÁS de filtrar:
 * el filtro quita lo que hoy se sabe roto, el aviso cubre lo que no se sabe.
 */
export function agentCanRun(model: string): boolean {
  if (/^o\d/.test(model)) return true;
  const generacion = /^gpt-(\d+)/.exec(model);
  return generacion !== null && Number(generacion[1]) >= 5;
}

export const agentComponentSchema = z
  .object({
    name: z.string(),
    estimated_hours: z.number(),
  })
  .loose();

export const agentEstimateSchema = z.object({
  project: z.string(),
  components: z.array(agentComponentSchema).default([]),
  total_hours: z.number(),
  notes: z.string(),
});
export type AgentEstimate = z.infer<typeof agentEstimateSchema>;

/** Un paso del bucle: qué herramienta pidió el modelo y qué le contestó. */
export const agentStepSchema = z
  .object({
    tool: z.string().nullable().default(null),
  })
  .loose();

export const agentTraceSchema = z.object({
  steps: z.array(agentStepSchema).default([]),
  iterations: z.number().int().default(0),
  /** `natural` = el modelo dejó de pedir herramientas. Cualquier otro = se cortó. */
  stop_reason: z.string().default("natural"),
  model: z.string().default(""),
  reasoning_effort: z.string().default(""),
});
export type AgentTrace = z.infer<typeof agentTraceSchema>;

export const agentRunResponseSchema = z.object({
  estimate: agentEstimateSchema,
  trace: agentTraceSchema,
});
export type AgentRunResponse = z.infer<typeof agentRunResponseSchema>;

// --- Sesión 15: arranque no bloqueante, progreso y propuesta -------------------

/**
 * `POST /v1/estimate/graph/start` (202). No trae la estimación a propósito: su
 * respuesta llega antes de que exista.
 *
 * `status` repite los cuatro de `graphStatuses` y añade `running`, así que el
 * enum se construye desde aquellos en vez de reescribirlos: una lista copiada a
 * mano es una lista que se queda atrás.
 */
export const graphStartResponseSchema = z.object({
  estimation_id: z.string(),
  status: z.enum([...graphStatuses, "running"]),
  /** Falso cuando el hilo ya estaba terminado o pausado y no se relanzó nada. */
  started: z.boolean(),
});
export type GraphStartResponse = z.infer<typeof graphStartResponseSchema>;

/** Un superstep del checkpointer: qué nodo corrió y cuánto tardó. */
export const runStepSchema = z.object({
  node: z.string(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
  /** Nulo, nunca cero: un cero se lee como un nodo instantáneo. */
  seconds: z.number().nullable(),
});
export type RunStep = z.infer<typeof runStepSchema>;

export const runProgressSchema = z.object({
  estimation_id: z.string(),
  status: z.enum(["running", "awaiting_human_review", "failed", "finished"]),
  /** El nodo en vuelo. Sólo lo hay mientras `status` es `running`. */
  current: z.string().nullable(),
  /** El motivo de un run muerto. `null` en todos los demás casos. */
  failure: z.string().nullable(),
  steps: z.array(runStepSchema).default([]),
  counts: z.object({
    requirements: z.number().int(),
    components: z.number().int(),
    budget_matches: z.number().int(),
    routing_steps: z.number().int(),
    has_estimate: z.boolean(),
    confidence: z.number().nullable(),
  }),
  errors: z.array(z.string()).default([]),
  routing_trail: z.array(routingHopSchema).default([]),
  last_activity_at: z.string().nullable(),
  review_payload: reviewPayloadSchema.nullish(),
});
export type RunProgress = z.infer<typeof runProgressSchema>;

/**
 * `POST /v1/estimate/graph/{id}/proposal`.
 *
 * Sin total propio, y es deliberado en las dos capas: las horas son de
 * `calculate_estimate` y viajan en la estimación. Una segunda copia aquí es un
 * número que puede acabar contradiciendo al que describe.
 */
export const commercialProposalSchema = z.object({
  title: z.string(),
  executive_summary: z.string(),
  scope: z.array(z.string()).default([]),
  assumptions: z.array(z.string()).default([]),
  body_markdown: z.string(),
});
export type CommercialProposal = z.infer<typeof commercialProposalSchema>;
