import { getTurnFromBackend } from "@/lib/review-backend";

export async function GET(
  _req: Request,
  context: { params: Promise<{ sessionId: string; turnId: string }> },
) {
  const { sessionId, turnId } = await context.params;
  const result = await getTurnFromBackend(sessionId, turnId);
  if (!result.turn) return new Response("Turn fetch failed", { status: result.status });
  return Response.json(result.turn);
}
