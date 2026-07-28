"""
Orchestrates the parts of the daily pipeline that are pure mechanics (no
judgment calls needed): fetch data -> generate the automatic SVG charts -> (agent
writes reports/<date>/report.html in between, using REPORT_GUIDE.md) -> render
to PDF.

This script only does step 1 (fetch) and exposes chart-building as a library
call the report-writing step can import. It deliberately does NOT try to
generate the analysis prose itself -- picking which sector is "mainline" vs
"event pulse", writing the TLDR, risk calls, etc. requires reading the day's
actual numbers and reasoning about them, which is the cloud agent's job each
run (see REPORT_GUIDE.md). Trying to hardcode that into a template would
produce the same canned sentences every day regardless of what happened.

Usage:
    python3 run_daily.py fetch --date 2026-07-27
        -> writes data/summary_2026-07-27.json

    python3 run_daily.py charts --date 2026-07-27
        -> reads data/summary_2026-07-27.json, writes data/charts_2026-07-27/*.svg
           (index_line.svg, distribution.svg, fund_flow.svg, sector_trend.svg)
           NOTE: fund_flow.svg and sector_trend.svg need the agent to have first
           picked the top-10 net-inflow sectors / 4 tracked sectors respectively
           -- see REPORT_GUIDE.md. This command builds index_line.svg and
           distribution.svg fully automatically from summary.json; for the
           other two it prints the data needed and lets the report-writing step
           call lib/charts.py directly with its own selections.

    python3 run_daily.py pdf --html reports/2026-07-27/report.html --pdf reports/2026-07-27/report.pdf
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "lib"))


def cmd_fetch(args):
    subprocess.run([sys.executable, str(ROOT / "lib" / "fetch.py"),
                     "--date", args.date, "--outdir", str(ROOT / "data")], check=True)


def cmd_charts(args):
    import charts
    summary = json.loads((ROOT / "data" / f"summary_{args.date}.json").read_text())
    outdir = ROOT / "data" / f"charts_{args.date}"
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. index line chart -- fully automatic
    hist = summary["indices"]["history_10d"]
    colors = {"上证指数": "#dc2626", "创业板指": "#2563eb", "科创50": "#9333ea",
              "沪深300": "#ea580c", "中证500": "#0d9488", "中证1000": "#a16207"}
    x_labels = [row[0][5:].replace("-", "/") for row in next(iter(hist.values()))] if hist else []
    series = [{"name": name, "data": [row[1] for row in rows], "color": colors.get(name, "#334155")}
              for name, rows in hist.items() if rows]
    if series:
        all_vals = [v for s in series for v in s["data"]]
        svg = charts.line_chart(1120, 380, series, x_labels, y_min=0, y_max=max(all_vals) * 1.1, y_ticks=5)
        (outdir / "index_line.svg").write_text(svg)
        print(f"wrote {outdir / 'index_line.svg'}")

    # 2. distribution chart -- fully automatic
    buckets = summary["breadth"]["distribution_buckets"]
    labels = list(buckets.keys())
    values = list(buckets.values())
    colors2 = ["#dc2626"] * 5 + ["#9ca3af"] + ["#16a34a"] * 5
    svg2 = charts.bar_chart_v(1120, 340, labels, values, colors2[: len(labels)])
    (outdir / "distribution.svg").write_text(svg2)
    print(f"wrote {outdir / 'distribution.svg'}")

    print("\n--- Sector fund-flow / 6-day trend charts need your own sector selection ---")
    print("Zt pool industries today (name: count), for fund_flow.svg candidates:")
    from collections import Counter
    ind_count = Counter(x["industry"] for x in summary["zt_pool"])
    for name, n in ind_count.most_common(15):
        print(f"  {name}: {n}")
    print("\n6-day zt trend by industry (for sector_trend.svg), dates:", sorted(summary["zt_trend_6d"].keys()))
    print("Call charts.bar_chart_h(...) / charts.line_chart(...) directly -- see REPORT_GUIDE.md step 5.")


def cmd_pdf(args):
    subprocess.run([sys.executable, str(ROOT / "lib" / "render.py"), args.html, args.pdf], check=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--date", required=True)
    f.set_defaults(func=cmd_fetch)

    c = sub.add_parser("charts")
    c.add_argument("--date", required=True)
    c.set_defaults(func=cmd_charts)

    p = sub.add_parser("pdf")
    p.add_argument("--html", required=True)
    p.add_argument("--pdf", required=True)
    p.set_defaults(func=cmd_pdf)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
