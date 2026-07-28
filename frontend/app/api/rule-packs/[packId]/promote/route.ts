import { promoteAdvisoryClause } from "@/lib/review-backend";

export async function POST(
  request: Request,
  context: { params: Promise<{ packId: string }> },
) {
  const { packId } = await context.params;
  const body = (await request.json()) as { advisory_title?: unknown };
  if (typeof body.advisory_title !== "string" || body.advisory_title === "") {
    return Response.json(
      {
        error: {
          code: "request.invalid",
          message: "request body must include a non-empty advisory_title",
        },
      },
      { status: 400 },
    );
  }
  const result = await promoteAdvisoryClause(packId, body.advisory_title);
  return Response.json(result.body, { status: result.status });
}
