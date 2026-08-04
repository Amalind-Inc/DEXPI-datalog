import { restoreReviewSources } from "@/lib/review-backend";

export async function GET(_request: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const restored = await restoreReviewSources(sessionId);
  if (!restored) return Response.json({ error: "review sources not found" }, { status: 404 });
  return Response.json(restored);
}
