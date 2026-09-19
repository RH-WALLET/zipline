import type { ReactNode } from "react";
import type { Status } from "@/lib/types";
import { Stamp } from "./Stamp";

/** The title block of a report page: kicker, serif title, lede, facts, and the mode stamp. */
export function ReportTitle({ kicker, title, sub, lede, facts, status, extra }: { kicker: string; title: string; sub?: string; lede?: ReactNode; facts?: ReactNode[]; status: Status | null; extra?: ReactNode }) {
  return (
    <div className="report-title">
      <div>
        <div className="kicker">{kicker}</div>
        <h1>
          {title}
          {sub ? <span className="sub"> — {sub}</span> : null}
        </h1>
        {lede ? <p className="lede">{lede}</p> : null}
        {facts?.length ? (
          <div className="facts">
            {facts.map((f, i) => (
              <span key={i}>{f}</span>
            ))}
          </div>
        ) : null}
        {extra}
      </div>
      <Stamp status={status} />
    </div>
  );
}
