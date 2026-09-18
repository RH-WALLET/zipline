import type { Cross } from "@/lib/types";
import { fmtMoney, fmtPrice, fmtQty, fmtTime } from "@/lib/format";

/** Internal crosses: one sleeve sold to another inside the treasury. No blockchain transaction exists for these. */
export function CrossTable({ crosses }: { crosses: Cross[] }) {
  if (crosses.length === 0) return <p className="help" style={{ padding: 16 }}>No internal crosses yet — sleeves have not yet wanted opposite sides of the same asset.</p>;
  return (
    <div className="tablewrap">
      <table className="table">
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Cycle</th>
            <th>Asset</th>
            <th>Seller</th>
            <th>Buyer</th>
            <th className="num">Quantity</th>
            <th className="num">Price</th>
            <th className="num">Notional</th>
            <th>Onchain</th>
          </tr>
        </thead>
        <tbody>
          {crosses.map((c) => (
            <tr key={c.id}>
              <td className="mono muted">{fmtTime(c.created_at)}</td>
              <td className="mono muted">#{c.cycle_id}</td>
              <td>
                <span className="sym">{c.symbol}</span>
              </td>
              <td className="neg">{c.seller}</td>
              <td className="pos">{c.buyer}</td>
              <td className="num">{fmtQty(c.quantity)}</td>
              <td className="num">{fmtPrice(c.price)}</td>
              <td className="num">{fmtMoney(c.notional)}</td>
              <td className="muted">none — INTERNAL_CROSS</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
