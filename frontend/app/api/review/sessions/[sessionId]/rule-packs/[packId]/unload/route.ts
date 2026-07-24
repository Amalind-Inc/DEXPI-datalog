import { unloadRulePack } from "@/lib/review-backend";

export async function POST(
  _request: Request,
  context: { params: Promise<{ sessionId: string; packId: string }> },
) {
  const { sessionId, packId } = await context.params;
  const result = await unloadRulePack(sessionId, packId);
  return Response.json(result.body, { status: result.status });
}
