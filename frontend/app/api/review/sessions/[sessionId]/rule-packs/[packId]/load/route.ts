import { loadRulePack } from "@/lib/review-backend";

export async function POST(
  _req: Request,
  context: { params: Promise<{ sessionId: string; packId: string }> },
) {
  const { sessionId, packId } = await context.params;
  const result = await loadRulePack(sessionId, packId);
  return Response.json(result.body, { status: result.status });
}
