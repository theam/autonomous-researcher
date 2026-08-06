import { randomUUID } from "node:crypto";

import { env } from "@/lib/env";
import { getLiveTicket } from "@/lib/limina/server";
import { isTrustedMutationOrigin } from "@/lib/request-origin";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = { params: Promise<{ slug: string }> };

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  if (!isTrustedMutationOrigin(request, env.LIMINA_CONSOLE_ORIGIN)) {
    return Response.json(
      { error: { code: "ORIGIN_NOT_ALLOWED", message: "The request origin is not allowed." } },
      { status: 403, headers: { "cache-control": "no-store", vary: "Origin" } },
    );
  }
  const { slug } = await context.params;
  const ticket = await getLiveTicket(slug, randomUUID());
  return Response.json(ticket, {
    headers: { "cache-control": "no-store" },
  });
}
