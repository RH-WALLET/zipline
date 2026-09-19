import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Chip } from "@/components/Chip";
import { TxLink } from "@/components/TxLink";
import { PerfChart } from "@/components/PerfChart";
import { ExecutionTable } from "@/components/ExecutionTable";
import type { Execution } from "@/lib/types";

const base: Execution = {
  id: 1,
  local_id: "dry-000001",
  cycle_id: 1,
  symbol: "NVDA",
  side: "BUY",
  mode: "DRY_RUN",
  adapter: "dryrun",
  status: "DRY_RUN_FILLED",
  requested_quantity: "0.5",
  requested_notional: "100",
  quoted_quantity: "0.5",
  quoted_notional: "100",
  executed_quantity: "0.5",
  executed_notional: "100",
  reference_price: "200",
  expected_price: "200.02",
  effective_price: "200.02",
  slippage_bps: "1.0",
  price_impact_bps: null,
  gas_used: null,
  gas_cost_eth: null,
  gas_cost_usd: null,
  reject_reason: null,
  contributions: [{ strategy: "TREND", quantity: "0.5" }],
  created_at: "2026-09-18T13:54:51Z",
  updated_at: "2026-09-18T13:54:51Z",
  quotes: [],
  transactions: [],
  is_real: false,
};

describe("status pills", () => {
  it("map tones to warning / success / danger pills", () => {
    render(
      <>
        <Chip tone="amber">DEMO MODE</Chip>
        <Chip tone="green">ACTIVE</Chip>
        <Chip tone="red">FAILED</Chip>
        <Chip>WATCH</Chip>
      </>,
    );
    expect(screen.getByText("DEMO MODE")).toHaveClass("tag", "warning");
    expect(screen.getByText("ACTIVE")).toHaveClass("success");
    expect(screen.getByText("FAILED")).toHaveClass("danger");
    expect(screen.getByText("WATCH")).toHaveClass("warning");
  });
});

describe("TxLink", () => {
  it("never links without a real hash", () => {
    const { container } = render(<TxLink hash={null} url={null} />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("—");
  });
  it("links real hashes to the explorer", () => {
    const hash = "0x" + "cd".repeat(32);
    render(<TxLink hash={hash} url={`https://robinhoodchain.blockscout.com/tx/${hash}`} />);
    const a = screen.getByRole("link");
    expect(a).toHaveAttribute("href", `https://robinhoodchain.blockscout.com/tx/${hash}`);
    expect(a).toHaveAttribute("target", "_blank");
  });
});

describe("ExecutionTable", () => {
  it("shows dry-run rows as DRY RUN with a local id and no transaction", () => {
    render(<ExecutionTable executions={[base]} />);
    expect(screen.getByText("dry-000001")).toBeInTheDocument();
    expect(screen.getByText("DRY RUN")).toBeInTheDocument();
    expect(screen.getByText("no tx (dry run)")).toBeInTheDocument();
    expect(screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.includes("blockscout"))).toHaveLength(0);
  });
  it("shows live rows with an explorer link", () => {
    const hash = "0x" + "ef".repeat(32);
    const live: Execution = {
      ...base,
      id: 2,
      local_id: "ord-000002",
      mode: "LIVE",
      status: "CONFIRMED",
      gas_cost_eth: "0.000012",
      transactions: [
        {
          id: 1,
          kind: "SWAP",
          chain_id: 4663,
          tx_hash: hash,
          from_address: "0x1111111111111111111111111111111111111111",
          to_address: "0x2222222222222222222222222222222222222222",
          gas_used: 120000,
          gas_cost_eth: "0.000012",
          gas_cost_usd: "0.03",
          block_number: 777,
          status: "CONFIRMED",
          error: null,
          submitted_at: "2026-09-18T13:54:51Z",
          confirmed_at: "2026-09-18T13:54:55Z",
          explorer_url: `https://robinhoodchain.blockscout.com/tx/${hash}`,
        },
      ],
    };
    render(<ExecutionTable executions={[live]} />);
    expect(screen.getByText("ONCHAIN")).toBeInTheDocument();
    const link = screen.getAllByRole("link").find((a) => a.getAttribute("href")?.includes("blockscout"));
    expect(link).toBeDefined();
    expect(screen.getByText("block 777")).toBeInTheDocument();
  });
});

describe("PerfChart", () => {
  it("renders an empty message with fewer than two points", () => {
    render(<PerfChart series={[{ name: "NAV", color: "#000", points: [{ x: 0, y: 1, label: "a" }] }]} />);
    expect(screen.getByText("Not enough valuations yet.")).toBeInTheDocument();
  });
  it("draws one path per series with a right-hand percent axis", () => {
    const { container } = render(
      <PerfChart
        series={[
          { name: "Algorithm", color: "#2a7ab8", points: [{ x: 0, y: 0, label: "2026-09-16" }, { x: 1, y: 1.5, label: "2026-09-17" }, { x: 2, y: -0.5, label: "2026-09-18" }] },
          { name: "Benchmark", color: "#9aa0a6", points: [{ x: 0, y: 0, label: "2026-09-16" }, { x: 1, y: 0.5, label: "2026-09-17" }, { x: 2, y: 0.2, label: "2026-09-18" }] },
        ]}
      />,
    );
    expect(container.querySelectorAll("path")).toHaveLength(2);
    expect(container.textContent).toMatch(/%/);
  });
});
