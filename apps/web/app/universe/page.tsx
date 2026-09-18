import { api, settle } from "@/lib/api";
import { fmtAge, fmtInt, fmtPrice, fmtTime, shortAddr } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { Panel, Empty } from "@/components/Panel";
import { Unavailable } from "@/components/Unavailable";

export default async function UniversePage() {
  const [status, assets] = await Promise.all([settle(api.status()), settle(api.assets())]);
  if (!status || !assets) {
    return (
      <div className="container">
        <div className="report-head">
          <h1>Asset universe</h1>
        </div>
        <Unavailable />
      </div>
    );
  }
  const eligible = assets.filter((a) => a.eligible);
  const cells: [string, string, string?][] = [
    ["Allowlist", fmtInt(status.config.allowlist.length), "configured symbols"],
    ["Eligible", fmtInt(eligible.length), "tradable now"],
    ["Hold-only", fmtInt(assets.filter((a) => !a.eligible && a.hold_only).length), "carried, not traded"],
    ["Ineligible", fmtInt(assets.filter((a) => !a.eligible && !a.hold_only).length)],
    ["Last refresh", status.system.last_universe_refresh_at ? fmtAge(status.system.last_universe_refresh_at) : "—", "GET /rhj/assets · /rhj/prices"],
    ["History provider", status.config.history_provider, "underlying equity bars"],
  ];
  return (
    <div className="container">
      <AutoRefresh seconds={120} />
      <div className="report-head">
        <div>
          <h1>
            Asset universe <span className="sub">— Robinhood Stock Tokens on chain {status.chain.chain_id}</span>
          </h1>
          <div className="meta">
            listed · active · deployed on {status.chain.chain_id} · tradable · priced with a sane spread · not halted · reported volume. Prices are the underlying equity bid/ask from Robinhood&apos;s public API; a token&apos;s value is that price × its ERC-8056 multiplier.
          </div>
        </div>
      </div>
      <div className="stats" role="list" aria-label="Universe summary">
        {cells.map(([label, value, sub]) => (
          <div className="stat" role="listitem" key={label}>
            <div className="label">{label}</div>
            <div className="value" style={{ fontSize: 20 }}>
              {value}
            </div>
            <div className="sub">{sub ?? " "}</div>
          </div>
        ))}
      </div>
      <Panel title="Stock Tokens" meta={`${assets.length} tracked`} flush>
        {assets.length === 0 ? (
          <Empty>
            No assets yet — run <code>zl universe</code>.
          </Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Name</th>
                  <th>Contract</th>
                  <th>Status</th>
                  <th>Eligibility</th>
                  <th className="num">Bid</th>
                  <th className="num">Ask</th>
                  <th className="num">Multiplier</th>
                  <th className="num">Token value</th>
                  <th className="num">Daily vol</th>
                  <th>Priced (UTC)</th>
                  <th>Sessions</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => {
                  const mid = a.price ? Number(a.price.mid) : null;
                  const mult = Number(a.current_multiplier);
                  return (
                    <tr key={a.id}>
                      <td>
                        <span className="sym">{a.symbol}</span>
                      </td>
                      <td className="muted wrap" style={{ maxWidth: "24ch" }}>
                        {a.name}
                      </td>
                      <td>
                        {a.deployment ? (
                          a.explorer_token_url ? (
                            <a className="mono" href={a.explorer_token_url} target="_blank" rel="noopener noreferrer" title={a.deployment.contract_address}>
                              {shortAddr(a.deployment.contract_address)} ↗
                            </a>
                          ) : (
                            <code>{shortAddr(a.deployment.contract_address)}</code>
                          )
                        ) : (
                          <span className="muted">none</span>
                        )}
                        {a.deployment?.verified_onchain ? <span className="muted small"> verified</span> : null}
                      </td>
                      <td className="mono">
                        {a.status.replace("ASSET_STATUS_", "")} {a.is_halted ? <Chip tone="red">HALTED</Chip> : null}
                      </td>
                      <td>
                        {a.eligible ? <Chip tone="green">ELIGIBLE</Chip> : a.hold_only ? <Chip tone="amber">HOLD ONLY</Chip> : <Chip tone="red">INELIGIBLE</Chip>}
                        {!a.eligible ? <div className="muted small">{a.eligibility_reasons.filter((r) => r !== "hold_only").join(", ")}</div> : null}
                      </td>
                      <td className="num">{a.price ? fmtPrice(a.price.bid) : "—"}</td>
                      <td className="num">{a.price ? fmtPrice(a.price.ask) : "—"}</td>
                      <td className="num muted">{mult.toFixed(6)}</td>
                      <td className="num">{mid !== null ? fmtPrice(mid * mult) : "—"}</td>
                      <td className="num muted">{a.price?.daily_volume ? fmtInt(a.price.daily_volume) : "—"}</td>
                      <td className="mono muted">{a.price ? fmtTime(a.price.generated_at ?? a.price.fetched_at) : "—"}</td>
                      <td className="muted small">
                        {a.fractional_tradability ? "market " : ""}
                        {a.all_day_tradability ? "24h" : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
