import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtInt, fmtMoney, fmtPct, statusClass, twrToReturnPct } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { Panel } from "@/components/Panel";
import { Pct } from "@/components/Signed";
import { StrategyTable } from "@/components/StrategyTable";
import { Unavailable } from "@/components/Unavailable";

export default async function StrategiesPage() {
  const strategies = await settle(api.strategies());
  if (!strategies) {
    return (
      <div className="container">
        <div className="report-head">
          <h1>Strategies</h1>
        </div>
        <Unavailable />
      </div>
    );
  }
  const totalWeight = strategies.reduce((a, s) => a + Number(s.weight_pct ?? 0), 0);
  const totalNav = strategies.reduce((a, s) => a + Number(s.state?.current_nav ?? 0), 0);
  return (
    <div className="container">
      <AutoRefresh seconds={60} />
      <div className="report-head">
        <div>
          <h1>
            Strategies <span className="sub">— ten deterministic sleeves</span>
          </h1>
          <div className="meta">
            configured weights sum to {totalWeight.toFixed(1)}% of deployable capital · Σ sleeve NAV {fmtMoney(totalNav)} · same history + same configuration = same decision · no strategy has a wallet
          </div>
        </div>
      </div>

      <Panel title="Allocation and performance" meta="weights are shares of deployable capital (NAV minus the cash reserve); returns are time-weighted" flush>
        <StrategyTable strategies={strategies} />
      </Panel>

      <div className="grid-2">
        {strategies.map((s) => {
          const st = s.state;
          return (
            <section className="panel" key={s.code} aria-label={s.code}>
              <div className="head">
                <h2>
                  <Link href={`/strategies/${s.code}`}>{s.code}</Link> <span className="muted" style={{ fontWeight: 400 }}>— {s.name}</span>
                </h2>
                <Chip tone={statusClass(s.status)}>{s.status}</Chip>
              </div>
              <div className="body" style={{ fontSize: 13 }}>
                <p style={{ margin: "0 0 10px" }}>{s.description}</p>
                <div className="stats" style={{ marginBottom: 8 }}>
                  <div className="stat">
                    <div className="label">Return</div>
                    <div className="value" style={{ fontSize: 18, lineHeight: "24px" }}>
                      <Pct v={twrToReturnPct(st?.twr_index)} />
                    </div>
                  </div>
                  <div className="stat">
                    <div className="label">Virtual NAV</div>
                    <div className="value" style={{ fontSize: 18, lineHeight: "24px" }}>
                      {fmtMoney(st?.current_nav)}
                    </div>
                  </div>
                  <div className="stat">
                    <div className="label">Max DD</div>
                    <div className="value" style={{ fontSize: 18, lineHeight: "24px" }}>
                      {st ? fmtPct(st.max_drawdown_pct, 2, false) : "—"}
                    </div>
                  </div>
                  <div className="stat">
                    <div className="label">Signals / fills</div>
                    <div className="value" style={{ fontSize: 18, lineHeight: "24px" }}>
                      {fmtInt(st?.signals_count)} / {fmtInt(st?.fills_count)}
                    </div>
                  </div>
                </div>
                <div className="muted small">
                  positions: <span className="mono">{s.position_symbols.length ? s.position_symbols.join(" ") : "cash"}</span> · version <code>{s.current_version_hash ?? "—"}</code> · <Link href={`/strategies/${s.code}`}>report →</Link>
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
