import { confirmPromotedRule } from "@/lib/review-backend";

export async function POST(
  request: Request,
  context: { params: Promise<{ packId: string }> },
) {
  const { packId } = await context.params;
  const body = (await request.json()) as { draft?: unknown };
  if (!body.draft || typeof body.draft !== "object" || Array.isArray(body.draft)) {
    return Response.json(
      {
        error: {
          code: "request.invalid",
          message: "request body must include a draft object",
        },
      },
      { status: 400 },
    );
  }
  const result = await confirmPromotedRule(
    packId,
    body.draft as Record<string, unknown>,
  );
  return Response.json(result.body, { status: result.status });
}
