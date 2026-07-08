import { listAllRulePacks } from "@/lib/review-backend";

export async function GET() {
  const result = await listAllRulePacks();
  return Response.json(result.body, { status: result.status });
}
