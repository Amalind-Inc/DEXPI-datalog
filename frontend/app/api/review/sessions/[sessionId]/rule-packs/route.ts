import { listRulePacks } from "@/lib/review-backend";

export async function GET(
  _req: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  const result = await listRulePacks(sessionId);
  return Response.json(result.body, { status: result.status });
}
