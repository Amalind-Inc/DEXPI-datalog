import { answerChatWithReviewBackend, type ChatRequest } from "@/lib/review-backend";

export async function POST(req: Request) {
  const body = (await req.json()) as ChatRequest;
  return Response.json(await answerChatWithReviewBackend(body));
}
