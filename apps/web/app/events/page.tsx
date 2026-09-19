import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtTime, statusClass } from "@/lib/format";
import { Chip } from "@/components/Chip";
import { EventFeed } from "@/components/EventFeed";
import { ReportTitle } from "@/components/ReportTitle";
import { Empty, Section } from "@/components/Section";
import { Unavailable } from "@/components/Unavailable";

export default async function EventsPage() {
  const [status, events, cycles] = await Promise.all([settle(api.status()), settle(api.events(400)), settle(api.cycles(50))]);
  if (!events) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · system log" title="Log" status={status} />
        <Unavailable />
      </div>
    );
  }
  return (
    <div className="page">
      <ReportTitle
        kicker="ZIPLINE · system log"
        title="Log"
        sub="the engine's own events"
        lede="Streamed live. Every line is produced by real system activity — data refreshes, signals, netting, quotes, executions, reconciliation, pauses. Nothing is narrated."
        status={status}
      />
      <Section id="cycles" title="Cycles" note="one per completed US equity session · each cycle page is a complete audit trail">
        {!cycles || cycles.length === 0 ? (
          <Empty>No cycles yet.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data dense">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Session</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th className="num">Signals</th>
                  <th className="num">Net orders</th>
                  <th className="num">Crosses</th>
                  <th className="num">Fills</th>
                  <th className="num">NAV start → end</th>
                  <th>Finished (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {cycles.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/cycles/${c.id}`}>#{c.id}</Link>
                    </td>
                    <td className="mono">{c.session_date}</td>
                    <td className="mono muted">{c.mode}</td>
                    <td>
                      <Chip tone={statusClass(c.status)}>{c.status}</Chip>
                    </td>
                    <td className="num">{String(c.summary?.signals ?? "—")}</td>
                    <td className="num">{String(c.summary?.net_orders ?? "—")}</td>
                    <td className="num">{String(c.summary?.internal_crosses ?? "—")}</td>
                    <td className="num">{String(c.summary?.filled ?? "—")}</td>
                    <td className="num muted">
                      {String(c.summary?.nav_start ?? "—").slice(0, 10)} → {String(c.summary?.nav_end ?? "—").slice(0, 10)}
                    </td>
                    <td className="mono muted">{fmtTime(c.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section id="log" title="Event log" note="newest first · live over server-sent events">
        <EventFeed initial={events} limit={400} height="70vh" />
      </Section>
    </div>
  );
}
