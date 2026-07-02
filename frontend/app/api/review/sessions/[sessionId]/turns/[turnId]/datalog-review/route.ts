import { resumeDatalogReviewOnBackend } from "@/lib/review-backend";

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string; turnId: string }> },
) {
  const { sessionId, turnId } = await context.params;
  const body = (await req.json()) as {
    decision?: string;
    proposal_result?: unknown;
  };
  return Response.json(
    await resumeDatalogReviewOnBackend(sessionId, turnId, {
      decision: body.decision ?? "",
      proposal_result: body.proposal_result ?? {},
    }),
  );
}
