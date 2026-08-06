import { authkitMiddleware } from "@workos-inc/authkit-nextjs";
import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";

const isLocalAuth = (process.env.LIMINA_UI_AUTH_MODE ?? "local") === "local";
const workosMiddleware = isLocalAuth
  ? null
  : authkitMiddleware({
      middlewareAuth: {
        enabled: true,
        unauthenticatedPaths: ["/callback", "/api/health"],
      },
    });

export default function middleware(request: NextRequest, event: NextFetchEvent) {
  if (isLocalAuth || workosMiddleware === null) {
    return NextResponse.next();
  }
  return workosMiddleware(request, event);
}

export const config = {
  runtime: "nodejs",
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
