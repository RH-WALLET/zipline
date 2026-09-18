import Link from "next/link";
import { notFound } from "next/navigation";
import { api, settle } from "@/lib/api";
import { fmtAge, fmtInt, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, statusClass, twrToReturnPct } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { PerformanceCurve } from "@/components/Curves";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { Panel, Empty } from "@/components/Panel";
import { Money, Pct } from "@/components/Signed";
import { SignalTable } from "@/components/SignalTable";
import { RiskTable, StatsStrip } from "@/components/StatsStrip";
import { Tabs } from "@/components/Tabs";
import { Unavailable } from "@/components/Unavailable";

const MODULE: Record<string, string> = {
  TREND: "trend.TrendStrategy",
  MOMENTUM: "momentum.MomentumStrategy",
  MEANREV: "meanrev.MeanReversionStrategy",
  BREAKOUT: "breakout.BreakoutStrategy",
  LOWVOL: "lowvol.LowVolStrategy",
  REVERSAL: "reversal.ReversalStrategy",
  DUALMA: "dualma.DualMovingAverageStrategy",
  RISKON: "riskon.RiskOnStrategy",
  PAIRS: "pairs.PairsStrategy",
  ZEROIQ: "zeroiq.ZeroIQStrategy",
};

function ruleText(v: unknown): string {
  return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
}

export default async function StrategyPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const [status, detail] = await Promise.all([settle(api.status()), settle(api.strategy(code))]);
  if (detail === null) {
    if (!status) {
      return (
        <div className="container">
          <div className="report-head">
            <h1>{code.toUpperCase()}</h1>
          </div>
          <Unavailable />
        </div>
      );
    }
    notFound();
  }
  const s = detail;
  const [metrics, signals, fills, crosses, executions] = await Promise.all([
    settle(api.strategyMetrics(s.code)),
    settle(api.strategySignals(s.code, 150)),
    settle(api.strategyFills(s.code, 150)),
    settle(api.strategyCrosses(s.code, 60)),
    settle(api.strategyExecutions(s.code, 60)),
  ]);
  const st = s.state;
  const rules = s.rules ?? {};
  const ruleOrder = ["universe", "signal", "regime", "filter", "entry", "exit", "ranking", "selection", "sizing", "rebalance", "state", "purpose", "lineage"];
  const orderedRules = [...ruleOrder.filter((k) => k in rules), ...Object.keys(rules).filter((k) => !ruleOrder.includes(k) && k !== "parameters")];
  const paramValues = (rules.parameters as Record<string, unknown> | undefined) ?? s.params ?? {};

  const performance = (
    <div className="grid-2">
      <Panel title="Sleeve accounting" meta={st ? `marked ${fmtAge(st.last_rebalance_at ?? st.inception_at)} · raw Stock Token units` : undefined} flush>
        {st ? (
          <div className="body">
            <KV
              ariaLabel="Sleeve accounting"
              rows={[
                { label: "Virtual NAV", value: fmtMoney(st.current_nav), big: true },
                { label: "Weight", value: `${s.weight_pct ? `${Number(s.weight_pct).toFixed(1)}%` : "—"} of deployable · ${s.allocation_policy}` },
                { label: "Allocated capital", value: fmtMoney(st.allocated_capital) },
                { label: "Virtual cash", value: fmtMoney(st.virtual_cash) },
                { label: "Return (TWR)", value: <Pct v={twrToReturnPct(st.twr_index)} /> },
                { label: "Realized PnL", value: <Money v={st.realized_pnl} sign /> },
                { label: "Unrealized PnL", value: <Money v={st.unrealized_pnl} sign /> },
                { label: "Total PnL", value: <Money v={s.total_pnl} sign /> },
                { label: "Peak NAV", value: fmtMoney(st.peak_nav) },
                { label: "Drawdown (current / max)", value: `${fmtPct(st.current_drawdown_pct, 2, false)} / ${fmtPct(st.max_drawdown_pct, 2, false)}` },
                { label: "Cumulative turnover", value: fmtMoney(st.cumulative_turnover) },
                { label: "Signals / fills", value: `${fmtInt(st.signals_count)} / ${fmtInt(st.fills_count)}` },
                { label: "Age", value: `${s.age_days ?? 0} days · since ${fmtTime(st.inception_at).slice(0, 10)}` },
              ]}
            />
          </div>
        ) : (
          <Empty>No state yet.</Empty>
        )}
      </Panel>
      <Panel title="Risk metrics" meta="empyrical-reloaded · rolling windows over completed sessions" flush>
        <div className="body">
          <RiskTable metrics={metrics} />
        </div>
      </Panel>
    </div>
  );

  const positions = (
    <Panel title="Virtual holdings" meta="raw Stock Token units held by this sleeve" flush>
      {s.positions.length === 0 ? (
        <Empty>Sleeve is in cash.</Empty>
      ) : (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>Asset</th>
                <th className="num">Quantity</th>
                <th className="num">Avg cost</th>
                <th className="num">Last price</th>
                <th className="num">Value</th>
                <th className="num">Weight</th>
                <th className="num">Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {s.positions.map((p) => {
                const nav = Number(st?.current_nav ?? 0);
                return (
                  <tr key={p.symbol}>
                    <td>
                      <span className="sym">{p.symbol}</span>
                    </td>
                    <td className="num">{fmtQty(p.quantity)}</td>
                    <td className="num muted">{fmtPrice(Number(p.cost_basis) / Math.max(Number(p.quantity), 1e-18))}</td>
                    <td className="num">{fmtPrice(p.last_price)}</td>
                    <td className="num">{fmtMoney(p.market_value)}</td>
                    <td className="num muted">{nav > 0 ? fmtPct((Number(p.market_value) / nav) * 100, 1, false) : "—"}</td>
                    <td className="num">
                      <Money v={p.unrealized_pnl} sign />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );

  const transactions = (
    <>
      <Panel title="Virtual fills" meta="how this sleeve's book changed and by which mechanism" flush>
        {(fills ?? []).length === 0 ? (
          <Empty>No fills yet.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Time (UTC)</th>
                  <th>Cycle</th>
                  <th>Mechanism</th>
                  <th>Asset</th>
                  <th>Side</th>
                  <th className="num">Quantity</th>
                  <th className="num">Price</th>
                  <th className="num">Notional</th>
                  <th className="num">Realized</th>
                  <th>Ref</th>
                </tr>
              </thead>
              <tbody>
                {(fills ?? []).map((f) => (
                  <tr key={f.id}>
                    <td className="mono muted">{fmtTime(f.created_at)}</td>
                    <td className="mono muted">{f.cycle_id ? `#${f.cycle_id}` : "—"}</td>
                    <td>
                      <Chip tone={f.kind === "ONCHAIN_EXECUTION" ? "green" : f.kind === "INTERNAL_CROSS" ? "blue" : "amber"}>{f.kind.replace("_", " ")}</Chip>
                    </td>
                    <td>
                      <span className="sym">{f.symbol}</span>
                    </td>
                    <td className={f.side === "BUY" ? "pos" : "neg"}>{f.side}</td>
                    <td className="num">{fmtQty(f.quantity)}</td>
                    <td className="num">{fmtPrice(f.price)}</td>
                    <td className="num">{fmtMoney(f.notional)}</td>
                    <td className="num">{Number(f.realized_pnl) === 0 ? <span className="muted">—</span> : <Money v={f.realized_pnl} sign />}</td>
                    <td className="mono muted">{f.internal_cross_id ? `cross #${f.internal_cross_id}` : f.execution_order_id ? `order #${f.execution_order_id}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Panel title="Internal crosses involving this sleeve" meta="no blockchain transaction" flush>
        <CrossTable crosses={crosses ?? []} />
      </Panel>
      <Panel title="Executions attributed to this sleeve" meta="the onchain (or dry-run) orders this strategy's net demand participated in" flush>
        <ExecutionTable executions={executions ?? []} />
      </Panel>
    </>
  );

  const source = (
    <div className="grid-2">
      <Panel title="Rules" meta="rendered from describe_rules() at request time — cannot drift from the code that runs" flush>
        <div className="tablewrap">
          <table className="table">
            <tbody>
              {orderedRules.map((k) => (
                <tr key={k}>
                  <td style={{ width: "1%", fontWeight: 600 }}>{k}</td>
                  <td className="wrap">{ruleText(rules[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div>
        <Panel title="Parameters" meta={<code>{s.current_version_hash}</code>}>
          <pre className="code" style={{ margin: 0 }}>{JSON.stringify(paramValues, null, 2)}</pre>
        </Panel>
        {Object.keys(s.persisted_state).length ? (
          <Panel title="Persisted state" meta="stored after every cycle so the next decision can be reproduced exactly">
            <pre className="code" style={{ margin: 0 }}>{JSON.stringify(s.persisted_state, null, 2)}</pre>
          </Panel>
        ) : null}
        <Panel title="Provenance" flush>
          <div className="body">
            <KV
              rows={[
                { label: "Class", value: <code>zipline_engine.strategies.{MODULE[s.code] ?? s.code}</code>, left: true },
                { label: "Version hash", value: <code>{s.current_version_hash}</code> },
                { label: "Source hash", value: <code>{s.source_hash}</code> },
                { label: "Guarantees", value: s.provenance.join(" · "), left: true },
                { label: "Raw", value: <a href={`/api/engine/strategies/${s.code}`}>strategy JSON ↗</a> },
              ]}
            />
          </div>
        </Panel>
      </div>
    </div>
  );

  return (
    <div className="container">
      <AutoRefresh seconds={60} />
      <div className="crumbs">
        <Link href="/strategies">Strategies</Link> › {s.code}
      </div>
      <div className="report-head">
        <div>
          <h1>
            {s.code} <span className="sub">— {s.name}</span>
          </h1>
          <div className="meta">
            {s.description} <code>zipline_engine.strategies.{MODULE[s.code] ?? s.code}</code> · version <code>{s.current_version_hash}</code>
            {s.status_reason && s.status !== "ACTIVE" ? ` · ${s.status_reason}` : ""}
          </div>
        </div>
        <div className="actions">
          <Chip tone={statusClass(s.status)}>{s.status}</Chip>
          {s.provenance.map((p) => (
            <Chip key={p} tone="">
              {p}
            </Chip>
          ))}
        </div>
      </div>

      <StatsStrip metrics={metrics} totalReturnPct={st ? twrToReturnPct(st.twr_index) : null} />

      <Panel title="Cumulative performance" meta="sleeve time-weighted return vs SPY · capital allocated to the sleeve is a flow, not a return">
        <PerformanceCurve metrics={metrics} label={s.code} />
      </Panel>

      <Tabs
        tabs={[
          { id: "performance", label: "Performance", content: performance },
          { id: "positions", label: "Positions", count: s.positions.length, content: positions },
          { id: "signals", label: "Signals", count: signals?.length ?? 0, content: <Panel title="Signal history" meta="SIGNAL — every indicator reading and target this strategy produced" flush><SignalTable signals={signals ?? []} showStrategy={false} /></Panel> },
          { id: "transactions", label: "Transactions", count: fills?.length ?? 0, content: transactions },
          { id: "source", label: "Source", content: source },
        ]}
      />
      {s.code === "ZEROIQ" ? (
        <div className="callout">
          <strong>Control group.</strong> ZEROIQ uses no market information. It exists so the rule-based sleeves can be compared against chance under identical costs and constraints.
        </div>
      ) : null}
    </div>
  );
}
