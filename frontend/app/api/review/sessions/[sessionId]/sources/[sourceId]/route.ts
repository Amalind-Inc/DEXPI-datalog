import { activateReviewSource, deleteReviewSource } from "@/lib/review-backend";

export async function PUT(_request: Request, context: { params: Promise<{ sessionId: string; sourceId: string }> }) {
  const { sessionId, sourceId } = await context.params;
  const result = await activateReviewSource(sessionId, sourceId);
  if (!result) return Response.json({ error: "source not found" }, { status: 404 });
  return Response.json({ active_source_id: result.activeSourceId });
}

export async function DELETE(_request: Request, context: { params: Promise<{ sessionId: string; sourceId: string }> }) {
  const { sessionId, sourceId } = await context.params;
  const result = await deleteReviewSource(sessionId, sourceId);
  if (!result) return Response.json({ error: "source not found" }, { status: 404 });
  return Response.json({
    deleted_source_id: result.deletedSourceId,
    active_source_id: result.activeSourceId,
  });
}
