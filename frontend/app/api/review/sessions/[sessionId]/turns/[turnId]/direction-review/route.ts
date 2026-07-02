import { resumeDirectionReviewOnBackend } from "@/lib/review-backend";

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string; turnId: string }> },
) {
  const { sessionId, turnId } = await context.params;
  const body = (await req.json()) as { decision?: string; review_key?: string };
  return Response.json(
    await resumeDirectionReviewOnBackend(sessionId, turnId, {
      decision: body.decision ?? "",
      review_key: body.review_key ?? "",
    }),
  );
}
