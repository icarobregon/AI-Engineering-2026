/**
 * The single door to the AI service.
 *
 * Nothing else in this app is allowed to call the estimator over HTTP. That is
 * the frontier made code: the service token lives in this module's environment
 * and `server-only` makes importing it from a Client Component a build error, so
 * the key cannot reach a browser bundle even by accident.
 */
import "server-only";

import { EstimatorError, GuardrailViolation, RateLimited } from "./errors";

/** Inside Compose this is `http://ai-service:8000`, never localhost. */
const BASE_URL = process.env.AI_SERVICE_URL ?? "http://ai-service:8000";

/**
 * The estimator authenticates with `X-API-Key`. The exercise statement calls the
 * header `X-Service-Token`; the name differs, the mechanism does not — one
 * shared secret per environment, required on the estimate routes and absent on
 * `/health`. Documented in docs/deployment-local.md.
 */
const TOKEN_HEADER = "X-API-Key";

/** An estimate takes seconds, not milliseconds: a short timeout just hides it. */
const DEFAULT_TIMEOUT_MS = 180_000;

type RequestOptions = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  /**
   * Sent as multipart instead of JSON. The conversational turn endpoint declares
   * its scalars as `Form(...)` and its files as `File(...)`, so JSON gets a 422.
   * The Content-Type header is deliberately NOT set: the runtime has to write it
   * with the boundary.
   */
  formData?: FormData;
  /** Which key the route expects: the estimate one or the retrieval one. */
  token?: "estimate" | "retrieval" | "none";
  timeoutMs?: number;
};

/**
 * Una variable de entorno VACÍA es una variable sin configurar.
 *
 * No es una sutileza: `.env.example` trae `AI_SERVICE_RETRIEVAL_TOKEN=` sin
 * valor, porque la clave de retrieval es opcional. Con `??` —que sólo atrapa
 * `null` y `undefined`— copiar el ejemplo tal cual, que es justo lo que dice el
 * README, dejaba la cadena vacía viajando como `X-API-Key` y el servicio
 * contestando 401 a todo lo de retrieval. La misma regla vale para `:-` de
 * Compose y para el servicio IA, donde una clave en blanco desactiva su ruta.
 */
function configurado(valor: string | undefined): string | null {
  return valor && valor.trim().length > 0 ? valor : null;
}

function tokenFor(kind: NonNullable<RequestOptions["token"]>): string | null {
  if (kind === "none") return null;
  const estimate = configurado(process.env.AI_SERVICE_TOKEN);
  if (kind === "estimate") return estimate;
  return configurado(process.env.AI_SERVICE_RETRIEVAL_TOKEN) ?? estimate;
}

/** The estimator answers `{"detail": ...}`; detail is a string or an object. */
function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.length > 0) return payload;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI's 422 shape: one entry per invalid field.
      const lines = detail
        .map((item) => {
          const loc = (item as { loc?: unknown[] }).loc ?? [];
          const msg = (item as { msg?: string }).msg ?? "invalid";
          return `${loc.slice(1).join(".") || "body"}: ${msg}`;
        })
        .filter(Boolean);
      if (lines.length > 0) return lines.join("; ");
    }
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: string }).message;
      if (typeof message === "string") return message;
    }
  }
  return fallback;
}

function failureFor(status: number, payload: unknown, requestId: string | null): EstimatorError {
  if (status === 400) {
    const detail = (payload as { detail?: { reason?: string; message?: string } })?.detail;
    if (detail && typeof detail === "object" && detail.reason) {
      return new GuardrailViolation(detail.reason, detail.message ?? "Request blocked.", {
        requestId,
      });
    }
  }
  const message = messageFrom(payload, `The AI service answered ${status}.`);
  if (status === 401 || status === 403) {
    return new EstimatorError("unauthorized", message, { status, requestId });
  }
  if (status === 404) return new EstimatorError("not_found", message, { status, requestId });
  if (status === 422) return new EstimatorError("invalid_request", message, { status, requestId });
  if (status === 503) return new EstimatorError("unavailable", message, { status, requestId });
  return new EstimatorError("server_error", message, { status, requestId });
}

export async function callEstimator<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = "GET",
    body,
    formData,
    token = "estimate",
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const key = tokenFor(token);
  if (key) headers[TOKEN_HEADER] = key;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch (cause) {
    // A refused connection, a DNS miss and a timeout are the same thing to the
    // caller: the service is not answering right now.
    const timedOut = cause instanceof Error && cause.name === "TimeoutError";
    throw new EstimatorError(
      "unavailable",
      timedOut ? `No answer in ${timeoutMs / 1000}s.` : "Could not reach the AI service.",
      { cause },
    );
  }

  const requestId = response.headers.get("X-Request-ID");
  const payload = await response.json().catch(() => null);

  if (response.status === 429) {
    const retryAfter = Number(response.headers.get("Retry-After"));
    throw new RateLimited(
      messageFrom(payload, "Rate limit exceeded."),
      Number.isFinite(retryAfter) ? retryAfter : null,
      requestId,
    );
  }
  if (!response.ok) throw failureFor(response.status, payload, requestId);

  return payload as T;
}

/** Liveness of the AI service, for the dashboard. Never throws. */
export async function pingEstimator(): Promise<boolean> {
  try {
    await callEstimator("/health", { token: "none", timeoutMs: 3_000 });
    return true;
  } catch {
    return false;
  }
}
