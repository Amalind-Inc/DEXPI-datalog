import { restoreReviewSession } from "@/lib/review-backend";

export async function GET(_request: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const review = await restoreReviewSession(sessionId);
  if (!review) return Response.json({ error: "review not found" }, { status: 404 });
  return Response.json(review);
}
