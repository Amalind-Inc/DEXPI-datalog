import { prepareReviewSession } from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const result = await prepareReviewSession(sessionId, await req.json());

  // A failed preparation must not arrive as 200. The browser checks
  // `response.ok` and throws, which is what surfaces the problem to the person
  // who uploaded the file instead of rendering an empty plant as though the
  // review had run. 502 rather than 500: this process is fine, the review
  // backend behind it is not.
  const status = result.status === "failed" ? 502 : 200;
  return Response.json(result, { status });
}
