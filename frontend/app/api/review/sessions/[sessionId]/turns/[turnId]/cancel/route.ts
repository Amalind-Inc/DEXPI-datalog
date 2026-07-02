import { cancelTurnOnBackend } from "@/lib/review-backend";

export async function POST(
  _req: Request,
  context: { params: Promise<{ sessionId: string; turnId: string }> },
) {
  const { sessionId, turnId } = await context.params;
  return Response.json(await cancelTurnOnBackend(sessionId, turnId));
}
