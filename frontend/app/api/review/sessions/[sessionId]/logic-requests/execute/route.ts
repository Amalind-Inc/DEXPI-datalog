import {
  BackendExecutionUnavailableError,
  executeConfirmedDatalog,
  GeneratedDatalogExecutionError,
} from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as { confirmation?: unknown };
  const confirmation =
    typeof body.confirmation === "object" && body.confirmation !== null
      ? (body.confirmation as Record<string, unknown>)
      : {};
  try {
    return Response.json(await executeConfirmedDatalog(sessionId, confirmation));
  } catch (caught) {
    if (caught instanceof BackendExecutionUnavailableError) {
      return Response.json(
        {
          error: {
            code: "review_backend.execution_unavailable",
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
            code: "generated_datalog.execution_rejected",
            message: caught.message,
          },
        },
        { status: 422 },
      );
    }
    throw caught;
  }
}
