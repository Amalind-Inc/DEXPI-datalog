import { createRulePack, listAllRulePacks } from "@/lib/review-backend";

export async function GET() {
  const result = await listAllRulePacks();
  return Response.json(result.body, { status: result.status });
}

export async function POST(request: Request) {
  const body = (await request.json()) as { markdown?: unknown };
  if (typeof body.markdown !== "string" || body.markdown === "") {
    return Response.json(
      {
        error: {
          code: "request.invalid",
          message: "request body must include a non-empty markdown",
        },
      },
      { status: 400 },
    );
  }
  const result = await createRulePack(body.markdown);
  return Response.json(result.body, { status: result.status });
}
