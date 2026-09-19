/**
 * The error taxonomy of the frontier with the AI service.
 *
 * Every failure crossing the boundary arrives here as one of these, so callers
 * branch on a type instead of parsing a status code. The split mirrors what the
 * estimator actually answers: a guardrail rejection and a malformed payload are
 * both "the request was refused", but only one of them is the user's fault and
 * only one of them is worth retrying.
 */

export type EstimatorErrorKind =
  | "guardrail"
  | "invalid_request"
  | "unauthorized"
  | "not_found"
  | "rate_limited"
  | "unavailable"
  | "server_error";

export class EstimatorError extends Error {
  readonly kind: EstimatorErrorKind;
  readonly status: number | null;
  /** Correlation id echoed by the service, for chasing a failure in the logs. */
  readonly requestId: string | null;

  constructor(
    kind: EstimatorErrorKind,
    message: string,
    options: { status?: number | null; requestId?: string | null; cause?: unknown } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "EstimatorError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.requestId = options.requestId ?? null;
  }

  /** What to show a person, phrased as something they can act on. */
  get userMessage(): string {
    switch (this.kind) {
      case "guardrail":
        return this.message;
      case "invalid_request":
        return `The AI service rejected the request: ${this.message}`;
      case "unauthorized":
        return "The service token was rejected. Check AI_SERVICE_TOKEN on both sides.";
      case "not_found":
        return "That estimation no longer exists in the AI service.";
      case "rate_limited":
        return "Too many requests to the AI service. Wait a moment and try again.";
      case "unavailable":
        return "The AI service is unavailable. The estimate could not be produced.";
      case "server_error":
        return "The AI service failed while producing the estimate.";
    }
  }
}

/** A guardrail rejection carries WHICH rule fired, which the UI shows verbatim. */
export class GuardrailViolation extends EstimatorError {
  readonly reason: string;

  constructor(reason: string, message: string, options: { requestId?: string | null } = {}) {
    super("guardrail", message, { status: 400, requestId: options.requestId });
    this.name = "GuardrailViolation";
    this.reason = reason;
  }
}

/** A 429 tells us how long to wait; keeping it lets the UI say so. */
export class RateLimited extends EstimatorError {
  readonly retryAfterSeconds: number | null;

  constructor(message: string, retryAfterSeconds: number | null, requestId: string | null) {
    super("rate_limited", message, { status: 429, requestId });
    this.name = "RateLimited";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}
