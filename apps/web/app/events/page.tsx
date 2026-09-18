import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtTime, statusClass } from "@/lib/format";
import { Chip } from "@/components/Chip";
import { EventFeed } from "@/components/EventFeed";
import { Panel, Empty } from "@/components/Panel";
import { Unavailable } from "@/components/Unavailable";

export default async function EventsPage() {
  const [events, cycles] = await Promise.all([settle(api.events(400)), settle(api.cycles(50))]);
  if (!events) {
    return (
      <div className="container">
        <div className="report-head">
          <h1>Logs</h1>
        </div>
        <Unavailable />
      </div>
    );
  }
  return (
    <div className="container">
      <div className="report-head">
        <div>
          <h1>
            Logs <span className="sub">— the engine&apos;s own event log</span>
          </h1>
          <div className="meta">streamed live · every line is produced by real system activity: data refreshes, signals, netting, quotes, executions, reconciliation, pauses · nothing is narrated</div>
        </div>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <EventFeed initial={events} limit={400} height="72vh" />
        <Panel title="Cycles" meta="one per completed US equity session" flush>
          {!cycles || cycles.length === 0 ? (
            <Empty>No cycles yet.</Empty>
          ) : (
            <div className="tablewrap">
              <table className="table dense">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Session</th>
                    <th>Mode</th>
                    <th>Status</th>
                    <th className="num">Orders</th>
                    <th className="num">Crosses</th>
                    <th className="num">Fills</th>
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
                      <td className="num">{String(c.summary?.net_orders ?? "—")}</td>
                      <td className="num">{String(c.summary?.internal_crosses ?? "—")}</td>
                      <td className="num">{String(c.summary?.filled ?? "—")}</td>
                      <td className="mono muted">{fmtTime(c.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
