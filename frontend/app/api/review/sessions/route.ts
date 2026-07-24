import { listReviewSessions } from "@/lib/review-backend";

export async function GET() {
  const result = await listReviewSessions();
  return Response.json({ sessions: result.sessions }, { status: result.status });
}
