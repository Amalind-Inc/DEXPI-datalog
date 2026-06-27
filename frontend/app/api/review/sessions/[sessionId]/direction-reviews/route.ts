import { submitDirectionReview } from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as {
    question?: string;
    decision?: "confirm" | "reverse" | "unknown";
    reviewKey?: string;
    conversation?: Array<{ question: string; answer_text: string; evidence_references: string[] }>;
  };
  return Response.json(
    await submitDirectionReview(sessionId, {
      question: body.question ?? "",
      decision: body.decision ?? "confirm",
      reviewKey: body.reviewKey ?? "",
      conversation: body.conversation,
    }),
  );
}
