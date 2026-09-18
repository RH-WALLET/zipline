import Link from "next/link";
import { notFound } from "next/navigation";
import { ENGINE_URL, api, settle } from "@/lib/api";
import type { Cross, Cycle, Execution, Signal, SystemEvent } from "@/lib/types";
import { fmtTime, statusClass } from "@/lib/format";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { Panel } from "@/components/Panel";
import { SignalTable } from "@/components/SignalTable";
import { Tabs } from "@/components/Tabs";
import { Unavailable } from "@/components/Unavailable";

type CycleDetail = { cycle: Cycle; signals: Signal[]; internal_crosses: Cross[]; executions: Execution[]; events: SystemEvent[] };

export default async function CyclePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let detail: CycleDetail | null = null;
  try {
    const r = await fetch(`${ENGINE_URL}/cycles/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (r.status === 404) notFound();
    if (r.ok) detail = (await r.json()) as CycleDetail;
  } catch {
    detail = null;
  }
  if (!detail) {
    const status = await settle(api.status());
    if (!status) {
      return (
        <div className="container">
          <div className="report-head">
            <h1>Cycle {id}</h1>
          </div>
          <Unavailable />
        </div>
      );
    }
    notFound();
  }
  const c = detail.cycle;
  const summary = c.summary as Record<string, string | number | string[]>;
  return (
    <div className="container">
      <div className="crumbs">
        <Link href="/events">Logs</Link> › cycle #{c.id}
      </div>
      <div className="report-head">
        <div>
          <h1>
            Cycle #{c.id} <span className="sub">— session {c.session_date}</span>
          </h1>
          <div className="meta">
            started {fmtTime(c.started_at)} · finished {fmtTime(c.finished_at)} · NAV at start {String(summary.nav_start ?? "—")} · at end {String(summary.nav_end ?? "—")}
          </div>
        </div>
        <div className="actions">
          <Chip tone={statusClass(c.status)}>{c.status}</Chip>
          <Chip tone={c.mode === "LIVE" ? "green" : "amber"}>{c.mode.replace("_", " ")}</Chip>
        </div>
      </div>
      {c.error ? (
        <div className="callout danger">
          <pre className="code" style={{ margin: 0, background: "transparent", border: 0, padding: 0, whiteSpace: "pre-wrap" }}>{c.error}</pre>
        </div>
      ) : null}
      <Tabs
        tabs={[
          {
            id: "summary",
            label: "Summary",
            content: (
              <div className="grid-2">
                <Panel title="Cycle record" flush>
                  <div className="body">
                    <KV rows={Object.entries(summary).map(([k, v]) => ({ label: k, value: Array.isArray(v) ? v.join(" ") : String(v), left: Array.isArray(v) }))} />
                  </div>
                </Panel>
                <div className="console" aria-label="Cycle event trail">
                  <div className="bar">
                    <span>event trail · {detail.events.length} lines</span>
                  </div>
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
              </div>
            ),
          },
          { id: "signals", label: "Signals", count: detail.signals.length, content: <Panel title="Signals" meta="SIGNAL" flush><SignalTable signals={detail.signals} /></Panel> },
          { id: "crosses", label: "Internal crosses", count: detail.internal_crosses.length, content: <Panel title="Internal crosses" meta="INTERNAL_CROSS — no blockchain transaction" flush><CrossTable crosses={detail.internal_crosses} /></Panel> },
          { id: "orders", label: "Net external orders", count: detail.executions.length, content: <Panel title="Net external orders" meta="ONCHAIN_EXECUTION / DRY RUN" flush><ExecutionTable executions={detail.executions} /></Panel> },
        ]}
      />
    </div>
  );
}
