import { validateProviderSettings } from "@/lib/byok-catalog";
import { startTurnOnBackend } from "@/lib/review-backend";

export async function POST(req: Request, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  const body = (await req.json()) as {
    question?: string;
    request_id?: string;
    conversation?: unknown[];
    selected_node_id?: string;
    provider_settings?: unknown;
  };
  // BYOK keys live in the browser, so the client sends its active provider
  // with the turn. When it sends nothing usable, startTurnOnBackend falls
  // back to the server's own env/.env configuration.
  const providerSettings = validateProviderSettings(body.provider_settings);
  return Response.json(
    await startTurnOnBackend(
      sessionId,
      {
        question: body.question ?? "",
        request_id: body.request_id ?? "",
        conversation: body.conversation,
        selected_node_id: body.selected_node_id,
      },
      providerSettings ? { providerSettings } : {},
    ),
  );
}
