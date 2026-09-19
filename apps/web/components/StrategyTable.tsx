import Link from "next/link";
import type { Strategy } from "@/lib/types";
import { fmtInt, fmtMoney, fmtPct, statusClass, twrToReturnPct } from "@/lib/format";
import { Chip } from "./Chip";
import { Pct } from "./Signed";

export function StrategyTable({ strategies }: { strategies: Strategy[] }) {
  return (
    <div className="tablewrap">
      <table className="data">
        <thead>
          <tr>
            <th>Strategy</th>
            <th className="num">Weight</th>
            <th className="num">Virtual NAV</th>
            <th className="num">Cash</th>
            <th className="num">Return</th>
            <th className="num">Realized</th>
            <th className="num">Unrealized</th>
            <th className="num">Max DD</th>
            <th>Positions</th>
            <th className="num">Signals</th>
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
                  </Link>{" "}
                  <span className="muted">{s.name}</span>
                </td>
                <td className="num">{s.weight_pct ? `${Number(s.weight_pct).toFixed(1)}%` : "—"}</td>
                <td className="num">{fmtMoney(st?.current_nav)}</td>
                <td className="num muted">{fmtMoney(st?.virtual_cash)}</td>
                <td className="num">
                  <Pct v={twrToReturnPct(st?.twr_index)} />
                </td>
                <td className={`num ${Number(st?.realized_pnl ?? 0) === 0 ? "muted" : ""}`}>{fmtMoney(st?.realized_pnl, { sign: true })}</td>
                <td className="num">{fmtMoney(st?.unrealized_pnl, { sign: true })}</td>
                <td className="num">{st ? fmtPct(st.max_drawdown_pct, 2, false) : "—"}</td>
                <td className="mono">{s.position_symbols.length ? s.position_symbols.slice(0, 6).join(" ") + (s.position_symbols.length > 6 ? ` +${s.position_symbols.length - 6}` : "") : <span className="muted">cash</span>}</td>
                <td className="num">{fmtInt(st?.signals_count)}</td>
                <td>
                  <Chip tone={statusClass(s.status)}>{s.status}</Chip>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
