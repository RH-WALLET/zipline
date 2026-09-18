import { NextRequest, NextResponse } from "next/server";
import { ENGINE_URL } from "@/lib/api";

/** Same-origin read-only proxy to the engine for client components. GET only; admin routes are never proxied. */
export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (joined.startsWith("admin")) {
    return NextResponse.json({ detail: "admin endpoints are not proxied" }, { status: 403 });
  }
  const url = `${ENGINE_URL}/${joined}${req.nextUrl.search}`;
  try {
    const upstream = await fetch(url, { cache: "no-store", headers: { accept: "application/json" } });
    const body = await upstream.text();
    return new NextResponse(body, { status: upstream.status, headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" } });
  } catch (e) {
    return NextResponse.json({ detail: `engine unreachable: ${(e as Error).message}` }, { status: 502 });
  }
}
