# DESIGN.md — ZIPLINE web interface

_Visual authority for `apps/web`. Third and current direction (2026-09-18): a **backtest-results console in the language of the Quantopian platform** that ran Zipline. Values were measured on the archived quantopian.com (2016) — `#C50000` red navbar, white pages on `#F4F5F6`, `#333` text in an Open-Sans-class sans, blue links, `#1E2024` dark console panels — and the page structure follows Quantopian's embedded backtest report exactly: statistics strip (Total Returns · Benchmark Returns · Alpha · Beta · Sharpe · Sortino · Information Ratio · Volatility · Max Drawdown), algorithm-vs-benchmark cumulative chart, Performance / Positions / Transactions / Logs / Source tabs, 1M/3M/6M/12M risk-metrics table. Same data as before; the earlier dark-terminal and Read-the-Docs renditions were rejected by the operator._

## World
- Every page is a **backtest report of something that is actually running**. Mode: Operate. Density is high but the report hierarchy is always the same: report head → statistics → curve → tabs.
- Light. The Quantopian platform was light with one strong brand colour.

## Colour
```
--q-red      #c50000   navbar (the brand cue)          --q-red-dark  #a30000
--q-ink      #333333   text                             --q-ink-2     #555b61  secondary
--q-muted    #8a9096   labels, meta                     --q-faint     #b8bec4  n/a values
--q-bg       #f4f5f6   app background                   --q-panel     #ffffff  panels
--q-border   #e1e4e8   panel borders                    --q-border-2  #d0d5da  tab borders
--q-blue     #2a7ab8   links, algorithm line            --q-green     #2e9e4f  positive / online
--q-amber    #c77c00   warnings, DEMO mode (bg #fff6df) --q-danger    #c8302a  negative / failed / paused
--q-console  #1e2024   log console (bar #26282d)        benchmark line #9aa0a6
```
Pills: `.pill.success / .warning / .danger / .info` — tinted backgrounds with matching borders, 11px uppercase semibold. Positive numbers green, negative red, only where the sign carries meaning (returns, PnL).

## Type
- **Open Sans** 14px / 20px body (Quantopian's fallback for FF Sero), weights 400/600/700. Report H1 24px/600; panel titles 15px/600; stat values 22px/600 tabular; labels 11px uppercase 0.06em muted.
- Monospace (Menlo/Monaco/Consolas) for ids, hashes, timestamps, signal kinds, code blocks and the log console. All numeric columns `font-variant-numeric: tabular-nums`, right-aligned.

## Layout
- `header.q-nav` 56px red bar: white logo box with a red "Z", `ZIPLINE` wordmark, section links (active = white 3px underline), right side ONLINE/PAUSED dot + CHAIN id. Collapses to a hamburger under 960px.
- `.mode-bar` directly under it, full width, always present: amber **DEMO MODE — LIVE TRADING DISABLED** with the one-line explanation and a link to the methodology; green for LIVE TRADING; red for SYSTEM PAUSED / ENGINE UNREACHABLE.
- `.container` 1320px; `.container.narrow` 880px for prose (methodology).
- `.report-head`: H1 with a muted `— subtitle`, a meta line (running since · base capital · sessions · benchmark · engine version · last cycle), and status pills on the right.
- `.stats`: white strip, cells `repeat(auto-fit, minmax(128px, 1fr))`, label / value / sub. Null statistics render `—` in `--q-faint` with "needs more history"; nothing is estimated.
- `.panel`: white, 1px border, 4px radius, titled head with a muted note, optional foot link. `.grid-2` for side-by-side panels (stacks under 960px).
- `.tabs`: Bootstrap-era tabs (white active tab joined to its pane), URL-hash state; all panes rendered so the page stays searchable.
- Tables `.table`: uppercase muted headers with a 2px bottom rule, 1px `#eef0f2` row rules, `#f9fafb` hover, symbols bold, ids in mono; wide tables scroll inside `.tablewrap`.
- `.kv`: two-column ledger (label muted left, tabular value right).
- `.console`: dark log block with a title bar (live dot, line count) and coloured levels — INFO blue, WARN amber, ERROR red — used for the event log and cycle trails.

## Charts (`PerfChart`)
- Cumulative performance in percent with the axis on the right (as Quantopian's Highstock chart), dotted horizontal grid, solid zero line, algorithm `#2a7ab8` 2px, benchmark `#9aa0a6` 1.5px, crosshair + tooltip on hover. Before the first completed session the intraday valuations are plotted and the legend says so; the benchmark appears once a daily series exists. NAV curves use the same component with dollar formatting.

## Motion
- Hover states and the chart crosshair only. No page-load animation, no boot sequence.

## Copy
- Report vocabulary: "Total returns", "Benchmark returns", "Risk metrics", "Positions", "Transactions", "Source". System nouns in `code`. SIGNAL / INTERNAL_CROSS / ONCHAIN_EXECUTION always distinguished; DRY RUN rows say "no tx (dry run)". Contributions are never called returns.
