import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { RELAY_PAUSED } from "@/lib/relay";

/**
 * Refreshes the Supabase auth session on each request so Server Components and
 * route handlers see a valid user. No-op if Supabase env vars are unset.
 */
export async function middleware(request: NextRequest) {
  if (RELAY_PAUSED) {
    // Answer the relay API at once instead of letting each handler wait on a
    // Supabase host that is gone; the units' cloud client reads any non-200
    // as "unreachable" and retries later, exactly as with no internet.
    if (request.nextUrl.pathname.startsWith("/api/")) {
      return NextResponse.json({ error: "relay_paused" }, { status: 503, headers: { "Retry-After": "3600" } });
    }
    return NextResponse.next({ request });
  }

  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) return response;

  const supabase = createServerClient(url, anon, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options?: Record<string, unknown> }[]) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options as never)
        );
      },
    },
  });

  await supabase.auth.getUser();
  return response;
}

export const config = {
  // Static assets, the service worker and the manifest never need a session.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|audio/|buku-audio/|models/|api/tts|api/describe|icons/|sw.js|manifest.webmanifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
