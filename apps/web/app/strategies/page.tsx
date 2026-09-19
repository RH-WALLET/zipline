import Link from "next/link";
import { api, settle } from "@/lib/api";
import { fmtInt, fmtMoney, fmtPct, statusClass, twrToReturnPct } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { ReportTitle } from "@/components/ReportTitle";
import { Section } from "@/components/Section";
import { Pct } from "@/components/Signed";
import { StrategyTable } from "@/components/StrategyTable";
import { Unavailable } from "@/components/Unavailable";

export default async function StrategiesPage() {
  const [status, strategies] = await Promise.all([settle(api.status()), settle(api.strategies())]);
  if (!strategies) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · strategies" title="Strategies" status={status} />
        <Unavailable />
      </div>
    );
  }
  const totalWeight = strategies.reduce((a, s) => a + Number(s.weight_pct ?? 0), 0);
  const totalNav = strategies.reduce((a, s) => a + Number(s.state?.current_nav ?? 0), 0);
  return (
    <div className="page">
      <AutoRefresh seconds={60} />
      <ReportTitle
        kicker="ZIPLINE · strategies"
        title="Strategies"
        sub="ten deterministic sleeves"
        lede="Every strategy is a rule set and a virtual book inside the one treasury. Same history and same configuration always produce the same decision; the rules are printed on each strategy's tear sheet exactly as the code states them."
        facts={[
          <>
            configured weights <b>{totalWeight.toFixed(1)}%</b> of deployable capital
          </>,
          <>
            Σ sleeve NAV <b>{fmtMoney(totalNav)}</b>
          </>,
          <>
            active <b>{strategies.filter((s) => s.status !== "DISABLED").length}</b> / {strategies.length}
          </>,
        ]}
        status={status}
      />

      <Section id="table" title="Allocation and performance" note="weights are shares of deployable capital · returns are time-weighted">
        <StrategyTable strategies={strategies} />
      </Section>

      <Section id="index" title="Index" note="one tear sheet per strategy">
        <div className="tablewrap">
          <table className="data">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Rule</th>
                <th className="num">Return</th>
                <th className="num">Virtual NAV</th>
                <th className="num">Max DD</th>
                <th className="num">Signals / fills</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => {
                const st = s.state;
                return (
                  <tr key={s.code}>
                    <td>
                      <Link href={`/strategies/${s.code}`}>
                        <span className="sym">{s.code}</span>
                      </Link>
                      <div className="muted small">{s.name}</div>
                    </td>
                    <td className="wrap" style={{ maxWidth: "52ch" }}>
                      {s.description}
                    </td>
                    <td className="num">
                      <Pct v={twrToReturnPct(st?.twr_index)} />
                    </td>
                    <td className="num">{fmtMoney(st?.current_nav)}</td>
                    <td className="num">{st ? fmtPct(st.max_drawdown_pct, 2, false) : "—"}</td>
                    <td className="num">
                      {fmtInt(st?.signals_count)} / {fmtInt(st?.fills_count)}
                    </td>
                    <td>
                      <Chip tone={statusClass(s.status)}>{s.status}</Chip>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
