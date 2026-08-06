import { NextResponse } from "next/server";

import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${env.LIMINA_RUNTIME_URL}/readyz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2_000),
    });
    return NextResponse.json(
      { ok: response.ok, runtime: response.ok ? "ready" : "unavailable" },
      { status: response.ok ? 200 : 503 },
    );
  } catch {
    return NextResponse.json({ ok: false, runtime: "unavailable" }, { status: 503 });
  }
}
