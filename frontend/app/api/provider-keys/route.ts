import { listProviderKeys } from "@/lib/provider-keys";

// The listing carries masked hints only, so this route is safe to expose to
// the page. There is deliberately no route that reads a credential back:
// the backend has no endpoint for it, and adding one here would be the
// disclosure this bead exists to prevent.
export async function GET() {
  const { status, keys, serverBacked } = await listProviderKeys();
  if (!serverBacked) {
    return Response.json(
      {
        error: {
          code: "provider_keys.not_in_this_profile",
          message: "This deployment keeps model credentials in your browser.",
        },
      },
      { status: 404 },
    );
  }
  return Response.json({ keys }, { status });
}
