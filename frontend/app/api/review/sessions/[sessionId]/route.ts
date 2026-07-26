import { restoreReviewSession } from "@/lib/review-backend";

export async function GET(_req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const result = await restoreReviewSession(sessionId);

  // 404 rather than an empty review, for the same reason prepare returns 502:
  // a session that cannot be read is not a session with nothing in it. The
  // browser can then leave the previous view alone and say so, instead of
  // redrawing the reviewer's plant as blank and looking like it finished.
  if (!result) return Response.json({ error: "session not found" }, { status: 404 });
  return Response.json(result);
}
