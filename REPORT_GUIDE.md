# Daily A-share Report — Build Guide

You are running unattended, once per trading day after market close. Your job:
produce `reports/<date>/report.pdf`, matching the style and depth of
`template/example_report.html` (a real, human-approved report — read it fully
before starting; it is the ground truth for tone, structure, and visual
format). Do not invent a different layout. Do not skip the four focus areas
below — they were explicitly requested by the user and must appear as their
own labeled sections every day, not folded into general commentary.

## The four required focus areas (each gets its own `<span class="focus-badge">`
section, same as the example)

1. **今日资金重点关注板块**: which sector(s) got the most capital attention
   today, who the leading stocks are, what news/event drove it, and how that
   sector's capital flow looked over the past week.
2. **近期持续流入、成长性高的板块**: sectors with sustained (not one-day-spike)
   capital interest over the trailing week — use the 6-day limit-up trend data
   to distinguish "mainline" (interest every day) from "pulse" (one big day
   then quiet).
3. **当前主线趋势判断**: an explicit P0/P1/P2/P3-style ranking of which
   direction is the real mainline vs. which is event-driven vs. which is
   speculative/avoid, with the reasoning spelled out.
4. **整体盘面分析与风险提示**: overall market read (is this a real breadth
   move or a low-conviction technical bounce? what does the limit-up/board
   structure say?) plus concrete, specific risks — not generic disclaimers.

## Steps

### 1. Determine the trading date
Today's date, unless today is a weekend (no report needed — stop) or the
fetch step below returns "not a trading day" (Chinese market holiday — stop,
no report needed that day).

### 2. Fetch data
```
python3 run_daily.py fetch --date 2026-07-27
```
Writes `data/summary_2026-07-27.json`. This one JSON file has everything:
index quotes + 10-day history, full-market breadth (advance/decline counts,
distribution buckets, exact zt/zb/dt counts), today's full limit-up pool
(with industry/连板/封板资金/换手率 per stock), the same for the prior 5
trading days (`zt_trend_6d`, keyed by YYYYMMDD), THS limit-up reason tags
(题材归因) for every limit-up stock today, the full dragon-tiger board, and
institutional buy/sell seat detail for the top ~6 movers by net amount.

This step takes a few minutes (the breadth fetch alone paginates ~55 requests
against sina to cover the full ~5500-stock universe — that's intentional, it's
the only reliable source found for true full-market breadth; eastmoney's
push2.eastmoney.com/api/qt/clist/get endpoint is NOT used here because it was
found to return 502 unreliably — do not "fix" this by switching back to it
without re-verifying it actually works first).

If any individual endpoint inside fetch.py fails after its built-in retries,
it degrades gracefully (empty list/dict) rather than crashing the whole run —
check stderr warnings and just work with whatever came back; do not block the
whole day's report on one flaky endpoint.

### 3. Read the data and form your own judgment
Open `data/summary_<date>.json`. This is the same underlying data an analyst
would look at. Compute/derive, same as the example report did:
- index % changes (recompute from quotes, don't trust any pre-labeled % blindly)
- breadth ratio, zt/zb/dt counts, break rate, first-board vs. multi-board ladder
  (group `zt_pool` by `limit_days`)
- top sectors by today's limit-up count (`Counter` over `zt_pool[*].industry`)
- persistent vs. pulse sectors: for each industry, look at its daily count
  across all 6 dates in `zt_trend_6d` — "mainline" = nonzero on ~5+ of 6 days;
  "pulse" = concentrated in 1-2 days
- theme tags: split each `limitup_reasons[*].reason` on "+" and count frequency
  across all stocks — this tells you what's actually driving the tape (IPOs,
  policy, earnings, etc.), same as the "长鑫科技IPO" narrative in the example
- dragon-tiger + seat detail: flag stocks where price is up but institutional
  net (`seat_details`) is negative — that's the "机构出货/游资接盘" risk signal
  worth calling out by name, same as 杰瑞股份/风华高科 in the example

Do not just describe numbers — draw the same kind of conclusions the example
report does (e.g. "首板占比93%、连板梯队薄弱 → 存量筹码惜售型反弹，非增量资金
入场"). That interpretive layer is the actual value of the report.

### 4. Generate the two automatic charts
```
python3 run_daily.py charts --date 2026-07-27
```
Writes `data/charts_<date>/index_line.svg` and `distribution.svg`
automatically. It also prints candidate sectors for the other two charts.

### 5. Generate the two judgment-based charts
Using `lib/charts.py` directly (import it), build:
- **fund-flow / attention chart** — `charts.bar_chart_h(1120, 360, labels, values, '#dc2626')`
  with the top ~10 sectors you identified in step 3 as today's real focus
  (by limit-up count and/or capital conviction — there is no single clean
  "net inflow ¥" field in the data since the most reliable such source
  (10jqka funds/hyzjl) is rate-limited from most networks; use limit-up count
  + seal_fund sum per industry as the capital-conviction proxy instead, same
  as the example report's fallback did)
- **sector persistence trend chart** — `charts.line_chart(1120, 340, series, dates, y_min=0, y_max=<pick>, y_ticks=4)`
  plotting the 3-4 sectors you're highlighting (mainline vs. pulse) across
  the 6 dates in `zt_trend_6d`

Save both as `data/charts_<date>/fund_flow.svg` and `sector_trend.svg`.

### 6. Write reports/<date>/report.html
Copy the `<style>` block verbatim from `template/style_block.html` (do not
modify it — it has print-specific CSS (`page-break-inside: avoid` etc.) that
took real trial-and-error to get right for headless PDF rendering). Follow
`template/example_report.html`'s section order and tone exactly, substituting
today's real numbers, tables, and the 4 SVGs (inline the SVG markup directly
inside each `div.chart-box .chart` div — do not link to external files, the
HTML must be fully self-contained for the PDF render step).

**Hard rule: no `<script>` tags, no JS-based charting library (ECharts,
Chart.js, etc.) anywhere in this file.** The whole reason this pipeline uses
hand-built static SVG is that live JS chart rendering (canvas or SVG renderer)
was found to reliably break — only partially paint — during headless
print-to-PDF, cutting charts off after ~15-20% of their width, and no amount
of `virtual-time-budget` / resize-on-timeout / `page-break-inside: avoid`
fixed it (all were tried). Static SVG sidesteps the entire bug class. If you
are tempted to "improve" the charts with an interactive library, don't — it
will look fine on screen and be silently broken in every PDF this pipeline
produces.

### 7. Render to PDF
```
python3 run_daily.py pdf --html reports/2026-07-27/report.html --pdf reports/2026-07-27/report.pdf
```
First run in a fresh environment needs `pip install -r requirements.txt &&
playwright install --with-deps chromium` once.

Open the PDF (or at minimum grep the HTML for obviously broken things) and
sanity-check: index numbers match `data/summary_<date>.json`, all 4 charts
present, no `NaN`/`undefined`/`None` leaked into the text.

### 8. Commit and push
```
git add data/summary_<date>.json data/charts_<date>/ reports/<date>/
git commit -m "Daily report <date>"
git push
```
This is the only way the user actually receives the report — the cloud
session cannot message them directly. Push every day even if a section came
out thinner than usual (partial data beats no report).

## Known fragile points (read before "fixing" anything)
- `push2.eastmoney.com/api/qt/clist/get` and `push2his.eastmoney.com/*` are
  NOT used in this pipeline — they returned 502 / connection-reset
  unreliably during development. Everything routes through push2ex
  (limit-up pools) and datacenter-web (dragon-tiger) instead, which held up.
- `data.10jqka.com.cn/funds/hyzjl` (industry fund-flow ranking, would have
  been the cleanest source for step 5's chart) rate-limits aggressively
  (~1 request before a 401 anti-bot page). `data.10jqka.com.cn/dataapi/*`
  (limit-up reasons) is a different, more reliable endpoint on the same
  domain — don't assume a 401 on one means the other is also down.
- Full-market breadth requires ~55 sequential sina requests (~1 min). Don't
  try to shortcut this with a single big-page-size request — pz/num above
  ~100 gets silently truncated or 502s.
