import { startTurnOnBackend } from "@/lib/review-backend";

export async function POST(
  req: Request,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as {
    question?: string;
    request_id?: string;
    conversation?: unknown[];
    selected_node_id?: string;
  };
  return Response.json(
    await startTurnOnBackend(sessionId, {
      question: body.question ?? "",
      request_id: body.request_id ?? "",
      conversation: body.conversation,
      selected_node_id: body.selected_node_id,
    }),
  );
}
