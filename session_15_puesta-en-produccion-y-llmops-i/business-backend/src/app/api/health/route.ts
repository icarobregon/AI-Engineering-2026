/**
 * Liveness of the public entry point.
 *
 * Cheap on purpose and it does NOT reach the AI service: an orchestrator polls
 * this constantly, and making it depend on a downstream hiccup is how a healthy
 * container gets restarted because something else sneezed.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
