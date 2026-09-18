import { NextRequest } from "next/server";
import { ENGINE_URL } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Pipes the engine's server-sent events stream to the browser. */
export async function GET(req: NextRequest) {
  const after = req.nextUrl.searchParams.get("after_id");
  const url = `${ENGINE_URL}/events/stream${after ? `?after_id=${encodeURIComponent(after)}` : ""}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, { cache: "no-store", headers: { accept: "text/event-stream" }, signal: req.signal });
  } catch (e) {
    return new Response(`event: error\ndata: ${JSON.stringify({ detail: (e as Error).message })}\n\n`, { status: 502, headers: { "content-type": "text/event-stream" } });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response("", { status: upstream.status || 502 });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: { "content-type": "text/event-stream", "cache-control": "no-store, no-transform", connection: "keep-alive", "x-accel-buffering": "no" },
  });
}
