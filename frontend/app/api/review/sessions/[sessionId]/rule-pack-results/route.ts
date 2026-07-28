import { runSingleRule } from "@/lib/review-backend";

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as { pack_id?: unknown; rule_id?: unknown };
  const packId = typeof body.pack_id === "string" ? body.pack_id : "demo-process-safety";
  const ruleId = typeof body.rule_id === "string" ? body.rule_id : "";
  const result = await runSingleRule(sessionId, packId, ruleId);
  return Response.json(result.body, { status: result.status });
}
