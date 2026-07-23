import { getTurnTraceDetailFromBackend } from "@/lib/review-backend";

export async function GET(
  _req: Request,
  context: {
    params: Promise<{ sessionId: string; turnId: string; eventId: string }>;
  },
) {
  const { sessionId, turnId, eventId } = await context.params;
  const result = await getTurnTraceDetailFromBackend(sessionId, turnId, eventId);
  if (!result.detail) {
    return new Response("Trace detail fetch failed", { status: result.status });
  }
  return Response.json(result.detail);
}
