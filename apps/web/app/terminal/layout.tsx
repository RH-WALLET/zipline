import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./terminal.css";

export const metadata: Metadata = {
  title: "ZIPLINE — terminal",
  description: "The engine's own screen: live event tape, Robinhood Stock Token quote board, treasury and books. Nothing narrated, nothing replayed.",
};

export const dynamic = "force-dynamic";

/** The terminal shell: a dark full-viewport screen with no report chrome. */
export default function TerminalLayout({ children }: { children: ReactNode }) {
  return <div className="term">{children}</div>;
}
