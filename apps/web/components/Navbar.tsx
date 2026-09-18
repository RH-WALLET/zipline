"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { Status } from "@/lib/types";

const LINKS: [string, string][] = [
  ["/", "Dashboard"],
  ["/strategies", "Strategies"],
  ["/executions", "Executions"],
  ["/treasury", "Treasury"],
  ["/universe", "Universe"],
  ["/events", "Logs"],
  ["/methodology", "Methodology"],
];

/** The red bar. Identity left, sections centre, system state right. */
export function Navbar({ status }: { status: Status | null }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const paused = status?.mode.paused ?? false;
  return (
    <header className="q-nav">
      <div className="inner">
        <Link href="/" className="q-logo" aria-label="ZIPLINE home">
          <span className="box" aria-hidden="true">
            Z
          </span>
          <span className="word">ZIPLINE</span>
        </Link>
        <button type="button" className="menu-btn" aria-label="Toggle navigation" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          ≡
        </button>
        <nav className={open ? "open" : ""} aria-label="Sections">
          {LINKS.map(([href, label]) => {
            const active = href === "/" ? path === "/" : path === href || path.startsWith(href + "/") || (href === "/events" && path.startsWith("/cycles"));
            return (
              <Link key={href} href={href} aria-current={active ? "page" : undefined} onClick={() => setOpen(false)}>
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="right">
          <span className="status" title={status ? `engine ${status.software.engine} · zipline-reloaded ${status.software.zipline_reloaded}` : "engine unreachable"}>
            <span className={`dot ${!status ? "off" : paused ? "bad" : ""}`} aria-hidden="true" />
            {!status ? "ENGINE OFFLINE" : paused ? "PAUSED" : "ONLINE"}
          </span>
          <span className="status" style={{ opacity: 0.85 }}>
            CHAIN {status?.chain.chain_id ?? "—"}
          </span>
        </div>
      </div>
    </header>
  );
}
