import { prepareReviewSession } from "@/lib/review-backend";

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  return Response.json(await prepareReviewSession(sessionId, await req.json()));
}
