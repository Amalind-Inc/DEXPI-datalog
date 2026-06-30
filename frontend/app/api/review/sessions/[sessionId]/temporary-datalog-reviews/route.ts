import {
  BackendExecutionUnavailableError,
  GeneratedDatalogExecutionError,
  submitTemporaryDatalogReview,
} from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as {
    question?: unknown;
    decision?: unknown;
    proposalResult?: unknown;
    proposal_result?: unknown;
  };
  const proposalResult = body.proposalResult ?? body.proposal_result;
  try {
    return Response.json(
      await submitTemporaryDatalogReview(sessionId, {
        question: typeof body.question === "string" ? body.question : "",
        decision: body.decision === "cancel" ? "cancel" : "confirm",
        proposalResult:
          typeof proposalResult === "object" && proposalResult !== null
            ? (proposalResult as Record<string, unknown>)
            : {},
      }),
    );
  } catch (caught) {
    if (caught instanceof BackendExecutionUnavailableError) {
      return Response.json(
        {
          error: {
            code: "review_backend.temporary_datalog_unavailable",
            message: caught.message,
          },
        },
        { status: 503 },
      );
    }
    if (caught instanceof GeneratedDatalogExecutionError) {
      return Response.json(
        {
          error: {
            code: "temporary_datalog.execution_rejected",
            message: caught.message,
          },
        },
        { status: 422 },
      );
    }
    throw caught;
  }
}
