"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Status } from "@/lib/types";

const LINKS: [string, string][] = [
  ["/", "Treasury"],
  ["/strategies", "Strategies"],
  ["/executions", "Executions"],
  ["/universe", "Universe"],
  ["/events", "Log"],
  ["/methodology", "Methodology"],
];

/** The running head of the report: wordmark, sections, engine state; the red rule below is the brand. */
export function Masthead({ status }: { status: Status | null }) {
  const path = usePathname();
  const paused = status?.mode.paused ?? false;
  return (
    <header className="masthead">
      <div className="inner">
        <Link href="/" className="brand" aria-label="ZIPLINE">
          ZIPLINE<small>live tear sheet</small>
        </Link>
        <nav aria-label="Sections">
          {LINKS.map(([href, label]) => {
            const active = href === "/" ? path === "/" || path === "/treasury" : path === href || path.startsWith(href + "/") || (href === "/events" && path.startsWith("/cycles"));
            return (
              <Link key={href} href={href} aria-current={active ? "page" : undefined}>
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="state" aria-label="Engine state">
          <span>
            <span className={`dot ${!status ? "off" : paused ? "bad" : ""}`} aria-hidden="true" />
            {!status ? "engine offline" : paused ? "paused" : "online"}
          </span>
          <span>chain {status?.chain.chain_id ?? "—"}</span>
          <span>{status ? (status.mode.live_trading ? "live trading" : "dry run") : ""}</span>
        </div>
      </div>
    </header>
  );
}
