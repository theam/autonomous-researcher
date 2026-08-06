import { getConsoleSession } from "@/lib/auth/server";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  const { accessToken } = await getConsoleSession();
  const lastEventId = request.headers.get("last-event-id");
  const response = await fetch(`${env.LIMINA_RUNTIME_URL}/v2/stream`, {
    cache: "no-store",
    headers: {
      accept: "text/event-stream",
      authorization: `Bearer ${accessToken}`,
      ...(lastEventId ? { "last-event-id": lastEventId } : {}),
    },
    signal: request.signal,
  });

  if (!response.ok || !response.body) {
    return Response.json(
      { error: { code: "STREAM_UNAVAILABLE", message: "Live updates are temporarily unavailable." } },
      { status: response.status || 503 },
    );
  }

  return new Response(response.body, {
    status: 200,
    headers: {
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "content-type": "text/event-stream; charset=utf-8",
      "x-accel-buffering": "no",
    },
  });
}
