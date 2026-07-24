import { isByokProviderId } from "@/lib/byok-keys";
import { verifyByokCredential } from "@/lib/byok-verify";

// Proxies the "Test key" button. The credential is used for a single probe and
// is never written to disk or logged.
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as {
    provider?: unknown;
    credential?: unknown;
  };
  const provider = body.provider;
  if (!isByokProviderId(provider)) {
    return Response.json(
      { ok: false, provider: String(provider ?? ""), message: "Unknown provider." },
      { status: 400 },
    );
  }
  const credential = typeof body.credential === "string" ? body.credential : "";
  return Response.json(await verifyByokCredential({ provider, credential }));
}
