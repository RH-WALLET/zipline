import { describe, expect, it } from "vitest";
import { explorerTx, fmtAge, fmtBps, fmtMoney, fmtPct, fmtQty, fmtUntil, isLocalId, shortHash, signClass, statusClass, twrToReturnPct } from "@/lib/format";

describe("formatters", () => {
  it("formats money from decimal strings without rounding surprises", () => {
    expect(fmtMoney("4999.72674447")).toBe("$4,999.73");
    expect(fmtMoney("-0.27325552", { sign: true })).toBe("−$0.27");
    expect(fmtMoney("12.5", { sign: true })).toBe("+$12.50");
    expect(fmtMoney(null)).toBe("—");
    expect(fmtMoney("5000")).toBe("$5,000.00");
  });
  it("formats percentages with explicit sign", () => {
    expect(fmtPct("4.18")).toBe("+4.18%");
    expect(fmtPct("-3.2")).toBe("−3.20%");
    expect(fmtPct("0")).toBe("0.00%");
    expect(fmtPct(null)).toBe("—");
  });
  it("converts a time-weighted index into a return", () => {
    expect(twrToReturnPct("1.0418")).toBeCloseTo(4.18, 8);
    expect(twrToReturnPct("1")).toBe(0);
    expect(twrToReturnPct(null)).toBeNull();
  });
  it("formats quantities, bps and hashes", () => {
    expect(fmtQty("0.795072032238902371")).toBe("0.795072");
    expect(fmtBps("2.44")).toBe("2.4 bps");
    expect(shortHash("0x" + "ab".repeat(32))).toBe("0xabababab…ababab");
    expect(shortHash(null)).toBe("—");
  });
  it("builds explorer links only from a base and a hash", () => {
    expect(explorerTx("https://robinhoodchain.blockscout.com/", "0xdead")).toBe("https://robinhoodchain.blockscout.com/tx/0xdead");
  });
  it("recognises local dry-run identifiers", () => {
    expect(isLocalId("dry-000042")).toBe(true);
    expect(isLocalId("ord-000042")).toBe(false);
    expect(isLocalId("0x" + "ab".repeat(32))).toBe(false);
  });
  it("maps statuses to restrained state colours", () => {
    expect(statusClass("ACTIVE")).toBe("green");
    expect(statusClass("WATCH")).toBe("amber");
    expect(statusClass("DISABLED")).toBe("red");
    expect(statusClass("RECONCILIATION_FAILED")).toBe("red");
    expect(statusClass("DRY_RUN_FILLED")).toBe("amber");
    expect(statusClass("CONFIRMED")).toBe("green");
    expect(signClass("-1")).toBe("neg");
    expect(signClass("0")).toBe("");
  });
  it("relative times", () => {
    const now = Date.parse("2026-09-18T12:00:00Z");
    expect(fmtAge("2026-09-18T11:59:30Z", now)).toBe("30s ago");
    expect(fmtAge("2026-09-18T10:30:00Z", now)).toBe("1h 30m ago");
    expect(fmtUntil("2026-09-18T14:20:00Z", now)).toBe("in 2h 20m");
    expect(fmtUntil("2026-09-18T11:00:00Z", now)).toBe("due");
  });
});
