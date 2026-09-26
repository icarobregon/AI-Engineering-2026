/**
 * La taxonomía de errores.
 *
 * Existe porque cada clase pide una reacción distinta de la interfaz: un 400 de
 * guardrail se le enseña a la persona tal cual, y un 503 no. Si dos clases
 * colapsan en el mismo mensaje, la pantalla deja de poder distinguirlas y el
 * usuario recibe «algo falló» para todo.
 */

import { describe, expect, it } from "vitest";

import { EstimatorError, GuardrailViolation, RateLimited } from "./errors";

describe("EstimatorError", () => {
  it("cada clase tiene su propio mensaje de usuario", () => {
    const kinds = [
      "guardrail",
      "invalid_request",
      "unauthorized",
      "not_found",
      "rate_limited",
      "unavailable",
      "server_error",
    ] as const;

    const mensajes = kinds.map((k) => new EstimatorError(k, "crudo").userMessage);

    // Siete clases, siete mensajes distintos. Que se repita uno significa que
    // dos situaciones que piden reacciones distintas se ven igual en pantalla.
    expect(new Set(mensajes).size).toBe(kinds.length);
  });

  it("los mensajes de usuario están en castellano y no filtran jerga HTTP", () => {
    for (const k of ["unavailable", "server_error", "not_found"] as const) {
      const mensaje = new EstimatorError(k, "Internal Server Error at /v1/foo").userMessage;
      expect(mensaje).not.toContain("/v1/");
      expect(mensaje.length).toBeGreaterThan(10);
    }
  });

  it("conserva el status y el request id para poder rastrear la llamada", () => {
    const error = new EstimatorError("server_error", "crudo", {
      status: 502,
      requestId: "abc-123",
    });

    expect(error.status).toBe(502);
    expect(error.requestId).toBe("abc-123");
  });

  it("es un Error de verdad, así que `instanceof` funciona tras compilar", () => {
    // Extender Error en TS compilado a ES5 rompe instanceof. Aquí se comprueba
    // que no pasa, porque TODAS las acciones ramifican con instanceof.
    const error = new EstimatorError("not_found", "crudo");
    expect(error).toBeInstanceOf(EstimatorError);
    expect(error).toBeInstanceOf(Error);
  });
});

describe("GuardrailViolation", () => {
  it("es un 400 y enseña el motivo del servicio, que sí es accionable", () => {
    const error = new GuardrailViolation("prompt_injection", "Se detectó una inyección.");

    expect(error).toBeInstanceOf(EstimatorError);
    expect(error.kind).toBe("guardrail");
    expect(error.status).toBe(400);
    expect(error.userMessage).toContain("Se detectó una inyección.");
  });
});

describe("RateLimited", () => {
  it("es un 429 y se queda con los segundos de espera", () => {
    const error = new RateLimited("Demasiadas peticiones.", 30, "req-1");

    expect(error.kind).toBe("rate_limited");
    expect(error.status).toBe(429);
    expect(error.retryAfterSeconds).toBe(30);
    expect(error.requestId).toBe("req-1");
  });

  it("sin cabecera Retry-After, null en vez de un número inventado", () => {
    // El cliente sólo pasa el número si `Number.isFinite`; si la cabecera no
    // viene o no es un número, aquí llega null y la interfaz no puede prometer
    // una espera que no conoce.
    expect(new RateLimited("Demasiadas.", null, null).retryAfterSeconds).toBeNull();
  });
});
