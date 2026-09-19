# DESIGN.md — ZIPLINE web interface

_Visual authority for `apps/web`. Fourth and current direction (2026-09-19): a **live tear sheet**. The iconic artifact of the Zipline/Quantopian ecosystem was never a dashboard — it was the pyfolio tear sheet: a typeset performance report with a statistics table and restrained matplotlib plots. Every page here is that report, set live from the running engine. Earlier renditions (dark terminal, Read-the-Docs clone, Quantopian red-navbar console) were rejected by the operator and are anti-references: no chrome, no panels, no tabs, no boxes._

## World
- **Paper, not screen.** Warm paper background, ink text, hairline rules. The page reads top-to-bottom like a printed report; the only "UI" is the running head and a contents line. Mode: Operate for the ledgers, Read for methodology — both inside the same report grammar.
- **One brand cue.** The Quantopian red (`#c50000`) appears exactly twice: the 4px rule under the masthead and the rotated document stamp that names the mode. Nothing else is red except negative numbers and errors (a different, deeper red).
- **The story:** a reader opens what looks like a printed quant report and finds it is alive — the log streams, valuations tick, the stamp says DEMO MODE.

## Colour
```
--paper   #faf9f6  page            --paper-2  #f3f1ec  hover rows, code tint
--ink     #16181d  text            --ink-2    #3d4149  secondary text, labels
--muted   #6b6f76  notes, axes     --faint    #a9adb4  "—" not-enough-history values
--rule    #dcd8cf  hairlines       --rule-2   #c9c4b9  heavier rules (section heads)
--brand   #c50000  masthead rule + stamp (Quantopian red)
--navy    #1f4e79  algorithm line, links, INFO events    --bench  #9a9a9a  benchmark line
--pos     #1d7a46  gains, ONCHAIN, ELIGIBLE               --neg    #b42318  losses, drawdown fill, errors
--warn    #9a6700  DRY RUN, HOLD ONLY, WARN events
```
Sign colours only where the sign carries meaning (returns, PnL, drawdown). Tags (`.tag`) are outlined, never filled: `success / warning / danger / info`.

## Type
- **Source Serif 4** for words and headline figures: body 15px/1.5, report H1 40px/1.05 (600) with the subtitle in muted 400, section H2 22px, hero statistic 24px, KV big value 22px, lede 16.5px. H1 uses `text-wrap: balance`.
- **Red Hat Mono** for data: table cells, kickers, section notes, facts, tags, axes, log — 11–13px with `tabular-nums`; uppercase + tracking (0.08–0.12em) only for kickers, column headers and tags.
- Paired facts stack inside one cell: the primary value on the first line, the secondary in `.sub` (11.5px muted mono) — executed over requested, effective over reference price, time over date. Column headers stack the same way.

## Layout
- `.masthead`: wordmark `ZIPLINE` + small "live tear sheet", section links (active = 2px navy underline), engine state at right (online/paused/offline dot · chain · dry run/live trading); 4px red rule beneath. Wraps to three lines under 760px.
- `.page` 1180px (32px gutters; 20px on phones); `.page.narrow` 820px for methodology.
- `.report-title`: kicker (mono uppercase) → H1 with `— subtitle` → lede (max 68ch) → `.facts` (mono key/value pairs) → hairline. The `.stamp` sits top-right (rotated −2°, red outline, "DEMO MODE / live trading disabled · dry run"; green for LIVE TRADING; deeper red −4° for SYSTEM PAUSED / ENGINE UNREACHABLE). On phones the stamp drops under the facts, left-aligned.
- `.contents`: one mono line of anchor links to the sections. Sections have `scroll-margin-top`.
- `.section`: serif H2 on a heavy hairline with a mono `.note` at the right; `.cols` = 5/7 grid (statistics table beside plots), `.cols.even` = 1/1; both stack under 900px.
- `table.stats`: pyfolio `perf_stats` — hero row (serif 24px), then groups Returns / Risk-adjusted / Distribution / Versus benchmark; label serif left, value mono right; `td.na` renders `—` in faint. The footnote states how many completed sessions exist and that nothing is estimated.
- `table.data`: mono uppercase headers on a heavy hairline, hairline rows, paper-2 hover, symbols bold, `.num` right-aligned, `.wrap` for prose-like cells, `.dense` variant. Tables are designed to fit 1116px without a scrollbar (stacked cells, merged columns); on phones they scroll inside `.tablewrap`.
- `.kv`: two-column ledger (serif label, mono value; `.big` serif 22px).
- `.log`: the system log as a printed appendix — a mono grid per line (`20ch` time · `26ch` type · message, wrapping), live dot + line count in a thin bar, INFO navy / WARN amber / ERROR red.
- `.colophon`: three mono columns (project, engine versions, chain links) on a hairline.

## Plots (`PerfChart`, `TearPlots`)
- No frame; faint horizontal grid, solid grey zero line, right-hand axis, mono 11px ticks that never scale (the viewBox tracks the rendered width via ResizeObserver). Algorithm navy 1.6px, benchmark grey 1.2px, drawdown red 1.2px with a 14% fill (underwater plot), NAV navy with dollar axis. Crosshair + paper tooltip on hover.
- Figures carry a mono legend line above and a mono caption below saying exactly what is plotted; before the first completed session the intraday valuations are plotted and the caption says so. Daily and monthly plots are replaced by one italic footnote until a session exists.

## Motion
- Hover states and the chart crosshair only. No page-load animation.

## Copy
- Report vocabulary from pyfolio/Quantopian: "Cumulative returns", "Underwater plot", "Annual volatility", "Rolling windows". System nouns in `code`. SIGNAL / INTERNAL_CROSS / ONCHAIN_EXECUTION always distinguished; DRY RUN rows say "no tx (dry run)" and carry `dry-000042` ids. Contributions and withdrawals are flows, never returns. Nothing is narrated; the log is the engine's own events.
- Print stylesheet: masthead links, contents, log bar and tooltips hidden; the page prints as the report it resembles.

## The terminal (`/terminal`)
The one page that is not paper: the machine's own screen, for watching. A full-viewport dark console (`app/terminal/terminal.css`, `components/terminal/*`), all Red Hat Mono at 12px, one accent.
- **Palette:** `--tb #0a0c10` screen, `--tp #0e1116` bars, `--tr/--tr2` rules, `--tf #e6e8ec` text, `--td` dim, `--tf2` faint; **amber `#f0b429`** for pane titles, the active filter, and everything DRY RUN; **green `#45d18f`** only for what really happened onchain, reconciles, or gained; **red `#ff5f5f`** for errors and losses; `--brand #ff3b3b` for the mode stamp. Blue = signals, violet = internal crosses, orange = risk limits/rejections.
- **Status bar:** `ZIPLINE terminal▮` (blinking block cursor — the one ornament), the two-line mode stamp (DEMO MODE / live trading disabled · dry run; green LIVE TRADING; filled red SYSTEM PAUSED), engine dot + chain, UTC and ET clocks ticking each second, NYSE session state from the XNYS calendar (`status.system.market`), countdown to the next cycle, `← report`.
- **Tape (left, 1.3fr):** the system event log over SSE, oldest at top, newest appended at the bottom with a 1.6 s amber fade; follows like `tail -f` until the reader scrolls up (then a `↓ follow` button). Filters ALL / TRADES / SIGNALS / SYSTEM. Grid `9ch time · 24ch type · message`.
- **Right column (1fr):** TREASURY (NAV 34px, TWR %, intraday sparkline, cash/tokens/reserve/gas/unrealized/valued), QUOTE BOARD (`GET /quotes`, polled every 20 s = the engine's cache TTL; rows flash green/red when a mid moves and show Δ bps since the previous observation; cached rows dimmed and tagged), BOOKS (Σ positions, then the ten sleeves).
- **Foot:** last cycle summary · reconciliation state · "dry-run fills carry local ids (dry-000042); no chain transactions · nothing narrated, nothing replayed".
- Polling pauses while the tab is hidden. Under 1100px the panes stack (tape 58dvh); under 640px the tape drops to two lines per event and the board hides spread/token-value columns. `prefers-reduced-motion` disables the cursor and flashes.
- Never add: replayed or simulated activity, sound, scanlines/glow, anything that moves without a real event behind it.
