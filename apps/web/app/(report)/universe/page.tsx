import { api, settle } from "@/lib/api";
import { fmtAge, fmtInt, fmtPrice, fmtTime, shortAddr } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { ReportTitle } from "@/components/ReportTitle";
import { Empty, Section } from "@/components/Section";
import { Unavailable } from "@/components/Unavailable";

export default async function UniversePage() {
  const [status, assets] = await Promise.all([settle(api.status()), settle(api.assets())]);
  if (!status || !assets) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · asset universe" title="Universe" status={status} />
        <Unavailable />
      </div>
    );
  }
  const eligible = assets.filter((a) => a.eligible);
  return (
    <div className="page">
      <AutoRefresh seconds={120} />
      <ReportTitle
        kicker="ZIPLINE · asset universe"
        title="Universe"
        sub={`Robinhood Stock Tokens on chain ${status.chain.chain_id}`}
        lede="An asset may trade only when it is listed, active, deployed on the chain, tradable, priced with a sane spread, not halted and has reported volume. Prices are the underlying equity bid/ask from Robinhood's public API; a token's value is that price × its ERC-8056 multiplier. Historical bars for signals are underlying-equity data, never chain data."
        facts={[
          <>
            allowlist <b>{fmtInt(status.config.allowlist.length)}</b>
          </>,
          <>
            eligible <b>{fmtInt(eligible.length)}</b>
          </>,
          <>
            hold-only <b>{fmtInt(assets.filter((a) => !a.eligible && a.hold_only).length)}</b>
          </>,
          <>
            ineligible <b>{fmtInt(assets.filter((a) => !a.eligible && !a.hold_only).length)}</b>
          </>,
          <>
            refreshed <b>{status.system.last_universe_refresh_at ? fmtAge(status.system.last_universe_refresh_at) : "—"}</b>
          </>,
          <>
            history provider <b className="mono">{status.config.history_provider}</b>
          </>,
        ]}
        status={status}
      />
      <Section id="tokens" title="Stock Tokens" note={`${assets.length} tracked · GET api.robinhood.com/rhj/assets · /rhj/prices/{symbol}`}>
        {assets.length === 0 ? (
          <Empty>
            No assets yet — run <code>zl universe</code>.
          </Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Stock Token</th>
                  <th>Contract</th>
                  <th>Eligibility</th>
                  <th className="num">Bid · ask</th>
                  <th className="num">Multiplier</th>
                  <th className="num">Token value</th>
                  <th className="num">Daily vol</th>
                  <th>
                    Priced <span className="sub">UTC</span>
                  </th>
                  <th>Trading</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => {
                  const mid = a.price ? Number(a.price.mid) : null;
                  const mult = Number(a.current_multiplier);
                  const reasons = a.eligibility_reasons.filter((r) => r !== "hold_only");
                  return (
                    <tr key={a.id}>
                      <td>
                        <span className="sym">{a.symbol}</span>
                        <span className="sub" style={{ fontFamily: "var(--font-serif)", fontSize: 12.5 }} title={a.name}>
                          {a.name.replace(/\s*[·•-]\s*Robinhood Token$/i, "")}
                        </span>
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
                        <span className="sub">{a.deployment?.verified_onchain ? "verified onchain" : a.deployment ? "unverified" : "not deployed"}</span>
                      </td>
                      <td>
                        {a.eligible ? <Chip tone="green">ELIGIBLE</Chip> : a.hold_only ? <Chip tone="amber">HOLD ONLY</Chip> : <Chip tone="red">INELIGIBLE</Chip>}
                        {a.is_halted ? (
                          <>
                            {" "}
                            <Chip tone="red">HALTED</Chip>
                          </>
                        ) : null}
                        <span className="sub">
                          {a.status.replace("ASSET_STATUS_", "").toLowerCase()}
                          {reasons.length ? ` · ${reasons.join(", ")}` : ""}
                        </span>
                      </td>
                      <td className="num">
                        {a.price ? (
                          <>
                            {fmtPrice(a.price.bid)} <span className="muted">·</span> {fmtPrice(a.price.ask)}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="num muted">{mult.toFixed(6)}</td>
                      <td className="num">{mid !== null ? fmtPrice(mid * mult) : "—"}</td>
                      <td className="num muted">{a.price?.daily_volume ? fmtInt(a.price.daily_volume) : "—"}</td>
                      <td className="mono muted">
                        {a.price ? (
                          <>
                            {fmtTime(a.price.generated_at ?? a.price.fetched_at).slice(11)}
                            <span className="sub">{fmtTime(a.price.generated_at ?? a.price.fetched_at).slice(0, 10)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="mono muted">{[a.fractional_tradability ? "market" : null, a.all_day_tradability ? "24h" : null].filter(Boolean).join(" · ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
