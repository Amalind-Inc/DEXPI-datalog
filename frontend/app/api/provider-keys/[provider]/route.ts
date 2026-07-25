import { deleteProviderKey, saveProviderKey } from "@/lib/provider-keys";

type Context = { params: Promise<{ provider: string }> };

export async function PUT(req: Request, context: Context) {
  const { provider } = await context.params;
  const body: unknown = await req.json();
  const { status, saved, error } = await saveProviderKey({
    provider,
    model: readString(body, "model"),
    credential: readString(body, "credential"),
  });
  if (!saved) {
    return Response.json({ error: { code: "provider_keys.rejected", message: error } }, { status });
  }
  // `saved` is the backend's masked description: provider, model, hint, time.
  // The credential the caller just sent is not echoed back.
  return Response.json(saved, { status });
}

export async function DELETE(_req: Request, context: Context) {
  const { provider } = await context.params;
  const { status, deleted } = await deleteProviderKey(provider);
  return Response.json({ provider, deleted }, { status });
}

/** One field off an unvalidated JSON body, checked rather than asserted. */
function readString(body: unknown, name: string): string {
  if (body && typeof body === "object" && name in body) {
    const value = (body as Record<string, unknown>)[name];
    if (typeof value === "string") return value;
  }
  return "";
}
