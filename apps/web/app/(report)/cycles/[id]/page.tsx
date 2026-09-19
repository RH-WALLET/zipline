import Link from "next/link";
import { notFound } from "next/navigation";
import { ENGINE_URL, api, settle } from "@/lib/api";
import type { Cross, Cycle, Execution, Signal, SystemEvent } from "@/lib/types";
import { fmtTime, statusClass } from "@/lib/format";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { ReportTitle } from "@/components/ReportTitle";
import { Contents, Section } from "@/components/Section";
import { SignalTable } from "@/components/SignalTable";
import { Unavailable } from "@/components/Unavailable";

type CycleDetail = { cycle: Cycle; signals: Signal[]; internal_crosses: Cross[]; executions: Execution[]; events: SystemEvent[] };

export default async function CyclePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const status = await settle(api.status());
  let detail: CycleDetail | null = null;
  try {
    const r = await fetch(`${ENGINE_URL}/cycles/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (r.status === 404) notFound();
    if (r.ok) detail = (await r.json()) as CycleDetail;
  } catch {
    detail = null;
  }
  if (!detail) {
    if (!status) {
      return (
        <div className="page">
          <ReportTitle kicker="ZIPLINE · cycle" title={`Cycle ${id}`} status={status} />
          <Unavailable />
        </div>
      );
    }
    notFound();
  }
  const c = detail.cycle;
  const summary = c.summary as Record<string, string | number | string[]>;
  return (
    <div className="page">
      <ReportTitle
        kicker={`ZIPLINE · cycle audit trail · session ${c.session_date}`}
        title={`Cycle #${c.id}`}
        sub={`session ${c.session_date}`}
        lede="Everything this cycle did, in order: universe and data refresh, ten strategy runs, netting into internal crosses and net external orders, execution, marking, reconciliation."
        facts={[
          <>
            <Chip tone={statusClass(c.status)}>{c.status}</Chip> <Chip tone={c.mode === "LIVE" ? "green" : "amber"}>{c.mode.replace("_", " ")}</Chip>
          </>,
          <>
            started <b>{fmtTime(c.started_at)}</b>
          </>,
          <>
            finished <b>{fmtTime(c.finished_at)}</b>
          </>,
          <>
            NAV <b>{String(summary.nav_start ?? "—")} → {String(summary.nav_end ?? "—")}</b>
          </>,
        ]}
        status={status}
      />
      <Contents
        items={[
          ["summary", "Summary"],
          ["trail", "Event trail"],
          ["signals", "Signals"],
          ["crosses", "Internal crosses"],
          ["orders", "Net external orders"],
        ]}
      />
      {c.error ? (
        <div className="callout danger">
          <pre className="code" style={{ border: 0, padding: 0, whiteSpace: "pre-wrap" }}>{c.error}</pre>
        </div>
      ) : null}
      <Section id="summary" title="Summary" note="from the cycle record">
        <div className="cols even">
          <KV rows={Object.entries(summary).map(([k, v]) => ({ label: k, value: Array.isArray(v) ? v.join(" ") : String(v), left: Array.isArray(v) }))} />
        </div>
      </Section>
      <Section id="trail" title="Event trail" note={`${detail.events.length} events`}>
        <div className="log">
          <div className="lines" style={{ maxHeight: 520 }}>
            {detail.events.map((e) => (
              <span key={e.id} className={`ln ${e.level === "WARN" ? "warn" : e.level === "ERROR" ? "error" : ""}`}>
                <span className="ts">{fmtTime(e.created_at)}</span>
                {"  "}
                <span className={`ty ${e.level === "WARN" ? "warn" : e.level === "ERROR" ? "error" : ""}`}>{e.type.padEnd(26)}</span> <span className="msg">{e.message}</span>
                {"\n"}
              </span>
            ))}
          </div>
        </div>
      </Section>
      <Section id="signals" title="Signals" note="SIGNAL">
        <SignalTable signals={detail.signals} />
      </Section>
      <Section id="crosses" title="Internal crosses" note="INTERNAL_CROSS — no blockchain transaction">
        <CrossTable crosses={detail.internal_crosses} />
      </Section>
      <Section id="orders" title="Net external orders" note="ONCHAIN_EXECUTION / DRY RUN">
        <ExecutionTable executions={detail.executions} />
      </Section>
      <p className="footnote">
        <Link href="/events">← Log</Link>
      </p>
    </div>
  );
}
