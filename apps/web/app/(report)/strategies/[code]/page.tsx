import Link from "next/link";
import { notFound } from "next/navigation";
import { api, settle } from "@/lib/api";
import { fmtAge, fmtInt, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, statusClass, twrToReturnPct } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { PerfStats, RollingTable } from "@/components/PerfStats";
import { ReportTitle } from "@/components/ReportTitle";
import { Contents, Empty, Section } from "@/components/Section";
import { Money, Pct } from "@/components/Signed";
import { SignalTable } from "@/components/SignalTable";
import { CumulativeReturns, DailyReturns, MonthlyReturns, Underwater } from "@/components/TearPlots";
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
        <div className="page">
          <ReportTitle kicker="ZIPLINE · strategy tear sheet" title={code.toUpperCase()} status={status} />
          <Unavailable />
        </div>
      );
    }
    notFound();
  }
  const s = detail;
  const [metrics, signals, fills, crosses, executions] = await Promise.all([
    settle(api.strategyMetrics(s.code)),
    settle(api.strategySignals(s.code, 120)),
    settle(api.strategyFills(s.code, 120)),
    settle(api.strategyCrosses(s.code, 60)),
    settle(api.strategyExecutions(s.code, 60)),
  ]);
  const st = s.state;
  const rules = s.rules ?? {};
  const ruleOrder = ["universe", "signal", "regime", "filter", "entry", "exit", "ranking", "selection", "sizing", "rebalance", "state", "purpose", "lineage"];
  const orderedRules = [...ruleOrder.filter((k) => k in rules), ...Object.keys(rules).filter((k) => !ruleOrder.includes(k) && k !== "parameters")];
  const paramValues = (rules.parameters as Record<string, unknown> | undefined) ?? s.params ?? {};

  return (
    <div className="page">
      <AutoRefresh seconds={60} />
      <ReportTitle
        kicker={`ZIPLINE · strategy tear sheet · ${s.code}`}
        title={s.code}
        sub={s.name}
        lede={s.description}
        facts={[
          <>
            class <b className="mono">zipline_engine.strategies.{MODULE[s.code] ?? s.code}</b>
          </>,
          <>
            version <b className="mono">{s.current_version_hash}</b>
          </>,
          <>
            weight <b>{s.weight_pct ? `${Number(s.weight_pct).toFixed(1)}%` : "—"}</b> of deployable
          </>,
          <>
            status <Chip tone={statusClass(s.status)}>{s.status}</Chip>
          </>,
          ...s.provenance.map((p) => <Chip key={p}>{p}</Chip>),
        ]}
        status={status}
        extra={s.status_reason && s.status !== "ACTIVE" ? <p className="footnote">{s.status_reason}</p> : undefined}
      />
      <Contents
        items={[
          ["performance", "Performance"],
          ["book", "Book"],
          ["rules", "Rules"],
          ["signals", "Signals"],
          ["fills", "Fills"],
          ["executions", "Executions"],
        ]}
      />

      <Section id="performance" title="Performance" note="sleeve time-weighted return vs SPY · capital allocated to the sleeve is a flow, not a return">
        <div className="cols">
          <PerfStats metrics={metrics} heroLabel="Total return" heroPct={st ? twrToReturnPct(st.twr_index) : null} />
          <div>
            <CumulativeReturns metrics={metrics} label={s.code} />
            <Underwater metrics={metrics} />
            <DailyReturns metrics={metrics} />
            <MonthlyReturns metrics={metrics} />
          </div>
        </div>
        <h3>Rolling windows</h3>
        <RollingTable metrics={metrics} />
      </Section>

      <Section id="book" title="Virtual book" note={st ? `marked ${fmtAge(st.last_rebalance_at ?? st.inception_at)} · raw Stock Token units` : undefined}>
        <div className="cols even">
          <div>
            {st ? (
              <KV
                ariaLabel="Sleeve accounting"
                rows={[
                  { label: "Virtual NAV", value: fmtMoney(st.current_nav), big: true },
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
            ) : (
              <Empty>No state yet.</Empty>
            )}
          </div>
          <div>
            <h3 style={{ marginTop: 0 }}>Holdings</h3>
            {s.positions.length === 0 ? (
              <Empty>Sleeve is in cash.</Empty>
            ) : (
              <div className="tablewrap">
                <table className="data dense">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th className="num">Quantity</th>
                      <th className="num">Avg cost</th>
                      <th className="num">Last</th>
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
          </div>
        </div>
      </Section>

      <Section id="rules" title="Rules" note="rendered from describe_rules() at request time — cannot drift from the code that runs">
        <div className="cols even">
          <div className="tablewrap">
            <table className="data">
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
          <div>
            <h3 style={{ marginTop: 0 }}>Parameters</h3>
            <pre className="code">{JSON.stringify(paramValues, null, 2)}</pre>
            {Object.keys(s.persisted_state).length ? (
              <>
                <h3>Persisted state</h3>
                <p className="footnote" style={{ marginTop: 0, marginBottom: 6 }}>Stored after every cycle so the next decision can be reproduced exactly.</p>
                <pre className="code">{JSON.stringify(s.persisted_state, null, 2)}</pre>
              </>
            ) : null}
            <p className="footnote">
              source hash <code>{s.source_hash}</code> · version <code>{s.current_version_hash}</code> · <a href={`/api/engine/strategies/${s.code}`}>strategy JSON ↗</a>
            </p>
          </div>
        </div>
      </Section>

      <Section id="signals" title="Signal history" note="SIGNAL — every indicator reading and target this strategy produced">
        <SignalTable signals={signals ?? []} showStrategy={false} />
      </Section>

      <Section id="fills" title="Virtual fills" note="how this sleeve's book changed and by which mechanism">
        {(fills ?? []).length === 0 ? (
          <Empty>No fills yet.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
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
        <h3>Internal crosses involving this sleeve</h3>
        <CrossTable crosses={crosses ?? []} />
      </Section>

      <Section id="executions" title="Executions attributed to this sleeve" note="the onchain (or dry-run) orders this strategy's net demand participated in">
        <ExecutionTable executions={executions ?? []} />
      </Section>

      {s.code === "ZEROIQ" ? (
        <div className="callout" style={{ marginTop: 32 }}>
          <strong>Control group.</strong> ZEROIQ uses no market information. It exists so the rule-based sleeves can be compared against chance under identical costs and constraints.
        </div>
      ) : null}
      <p className="footnote">
        <Link href="/strategies">← All strategies</Link>
      </p>
    </div>
  );
}
