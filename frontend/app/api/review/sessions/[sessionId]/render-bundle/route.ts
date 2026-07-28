import { fetchRenderBundle } from "@/lib/review-backend";

export async function GET(request: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const bundle = await fetchRenderBundle(sessionId, request.headers.get("if-none-match") ?? undefined);
  const headers = new Headers({ "Cache-Control": "private, max-age=0, must-revalidate" });
  if (bundle.etag) headers.set("ETag", bundle.etag);
  if (bundle.status === 304) return new Response(null, { status: 304, headers });
  return Response.json(bundle.body, { status: bundle.status, headers });
}
