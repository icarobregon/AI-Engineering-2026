/**
 * La única puerta HTTP al servicio IA.
 *
 * Lo que se prueba aquí es lo que no se ve al mirar una pantalla: que el token
 * viaje POR DEFECTO —olvidarlo tiene que ser imposible por omisión, y explícito
 * cuando se quiere—, que cada código de estado caiga en su clase de error, y que
 * un servicio que no contesta no se confunda con uno que contesta mal.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callEstimator } from "./client";
import { EstimatorError } from "./errors";

const respuestaOk = (cuerpo: unknown = { ok: true }) =>
  new Response(JSON.stringify(cuerpo), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

function respuestaCon(status: number, cuerpo: unknown = {}, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** Lo que el cliente acabó mandando: url y opciones del último fetch. */
function ultimaLlamada() {
  const espia = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  const [url, init] = espia.mock.calls.at(-1) as [string, RequestInit];
  return { url, init, headers: init.headers as Record<string, string> };
}

beforeEach(() => {
  process.env.AI_SERVICE_URL = "http://ai-service:8000";
  process.env.AI_SERVICE_TOKEN = "token-de-estimacion";
  process.env.AI_SERVICE_RETRIEVAL_TOKEN = "token-de-retrieval";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuestaOk()));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("el token", () => {
  it("viaja por defecto, sin tener que pedirlo", () => {
    // Ésta es la propiedad que importa: una llamada nueva escrita sin pensar en
    // el token sale autenticada. La excepción hay que escribirla.
    return callEstimator("/cualquier/ruta").then(() => {
      expect(ultimaLlamada().headers["X-API-Key"]).toBe("token-de-estimacion");
    });
  });

  it("token: 'retrieval' usa la clave de retrieval", async () => {
    await callEstimator("/search", { token: "retrieval" });
    expect(ultimaLlamada().headers["X-API-Key"]).toBe("token-de-retrieval");
  });

  it("sin clave de retrieval configurada, cae a la de estimación", async () => {
    // Es el mismo apaño que hace docker-compose, y evita que una instalación con
    // una sola clave deje de funcionar sin decir por qué.
    delete process.env.AI_SERVICE_RETRIEVAL_TOKEN;
    await callEstimator("/search", { token: "retrieval" });
    expect(ultimaLlamada().headers["X-API-Key"]).toBe("token-de-estimacion");
  });

  it("token: 'none' no manda cabecera: /health no la quiere", async () => {
    await callEstimator("/health", { token: "none" });
    expect(ultimaLlamada().headers["X-API-Key"]).toBeUndefined();
  });
});

describe("el cuerpo", () => {
  it("un GET no lleva Content-Type ni cuerpo", async () => {
    await callEstimator("/algo");
    const { init, headers } = ultimaLlamada();
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("un POST con body lo serializa a JSON", async () => {
    await callEstimator("/algo", { method: "POST", body: { a: 1 } });
    const { init, headers } = ultimaLlamada();
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });

  it("un FormData viaja tal cual, sin Content-Type", async () => {
    // Ponerlo a mano rompería el boundary que el navegador genera.
    const fd = new FormData();
    fd.append("transcript", "hola");
    await callEstimator("/algo", { method: "POST", formData: fd });
    const { init, headers } = ultimaLlamada();
    expect(init.body).toBe(fd);
    expect(headers["Content-Type"]).toBeUndefined();
  });
});

describe("los códigos de estado", () => {
  const casos: [number, string][] = [
    [401, "unauthorized"],
    [403, "unauthorized"],
    [404, "not_found"],
    [422, "invalid_request"],
    [503, "unavailable"],
    [500, "server_error"],
    [409, "server_error"],
  ];

  for (const [status, kind] of casos) {
    it(`${status} → ${kind}`, async () => {
      (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValue(
        respuestaCon(status, { detail: "lo que diga el servicio" }),
      );

      await expect(callEstimator("/algo")).rejects.toMatchObject({ kind, status });
    });
  }

  it("un 400 con motivo es un guardrail, con su razón", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValue(
      respuestaCon(400, { detail: { reason: "pii_detected", message: "Hay un DNI." } }),
    );

    await expect(callEstimator("/algo")).rejects.toMatchObject({
      kind: "guardrail",
      reason: "pii_detected",
    });
  });

  it("un 429 conserva los segundos de espera de la cabecera", async () => {
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockResolvedValue(
      respuestaCon(429, { detail: "Demasiadas." }, { "Retry-After": "42" }),
    );

    await expect(callEstimator("/algo")).rejects.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 42,
    });
  });
});

describe("cuando no hay respuesta", () => {
  it("una conexión rechazada es «no disponible», no un error del servidor", async () => {
    // Un servicio caído y un servicio que contesta 500 piden reacciones
    // distintas, y para quien llama sólo se distinguen por esta clase.
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockRejectedValue(
      new TypeError("fetch failed"),
    );

    await expect(callEstimator("/algo")).rejects.toMatchObject({ kind: "unavailable" });
  });

  it("un timeout dice cuántos segundos se esperaron", async () => {
    const timeout = new Error("timed out");
    timeout.name = "TimeoutError";
    (globalThis.fetch as never as ReturnType<typeof vi.fn>).mockRejectedValue(timeout);

    const error: unknown = await callEstimator("/algo", { timeoutMs: 5_000 }).catch((e) => e);
    expect(error).toBeInstanceOf(EstimatorError);
    expect((error as EstimatorError).message).toContain("5");
  });
});
