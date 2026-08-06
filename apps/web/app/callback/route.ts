import { handleAuth } from "@workos-inc/authkit-nextjs";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const GENERIC_ERROR_HTML =
  '<!doctype html><html lang="en"><meta charset="utf-8"><title>Sign-in failed</title>' +
  "<body><main><h1>Sign-in failed</h1><p>We could not complete your sign-in. Try again.</p>" +
  '<p><a href="/">Return to Limina</a></p></main></body></html>';

const handler = handleAuth({
  returnPathname: "/",
  onError: ({ error }) => {
    console.error("WorkOS callback failed", { error });
    return new NextResponse(GENERIC_ERROR_HTML, {
      status: 400,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  },
});

export function GET(request: NextRequest) {
  if ((process.env.LIMINA_UI_AUTH_MODE ?? "local") === "local") {
    return new NextResponse("Not found", { status: 404 });
  }
  return handler(request);
}
