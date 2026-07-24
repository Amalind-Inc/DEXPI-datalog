import { providerIndex, providerModels } from "@/lib/byok-catalog";

// Provider index for the API-keys picker, or one provider's models when
// ?provider= is supplied. The full catalogue is ~500 KiB, so models are
// fetched a provider at a time rather than shipped up front.
export async function GET(req: Request) {
  const provider = new URL(req.url).searchParams.get("provider");
  if (provider) {
    return Response.json({ provider, models: providerModels(provider) });
  }
  return Response.json({ providers: providerIndex() });
}
