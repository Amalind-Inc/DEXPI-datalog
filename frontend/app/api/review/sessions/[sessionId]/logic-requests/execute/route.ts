import { executeConfirmedDatalog } from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as { confirmation?: unknown };
  const confirmation =
    typeof body.confirmation === "object" && body.confirmation !== null
      ? (body.confirmation as Record<string, unknown>)
      : {};
  return Response.json(await executeConfirmedDatalog(sessionId, confirmation));
}
