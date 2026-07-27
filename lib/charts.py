"""
Static SVG chart generators for the daily report. Pure markup, no JS/canvas --
this is deliberate: headless-Chrome / Playwright print-to-pdf has a known timing
bug where ECharts (canvas or svg renderer, live-JS) only partially paints before
the PDF snapshot is taken, producing charts that are cut off after ~1/5 of their
width. Hand-built static SVG sidesteps the whole JS-rendering-timing class of bug
and is what the reference report in this repo uses. Do not reintroduce a JS
charting library for the PDF path.

Usage: from charts import index_line_chart, distribution_chart, fund_flow_chart, sector_trend_chart
Each returns a raw <svg>...</svg> string ready to embed in a div.chart-box.
"""


def line_chart(width, height, series, x_labels, y_max=None, y_min=0, y_ticks=5, unit=""):
    pad_l, pad_r, pad_t, pad_b = 55, 20, 30, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    all_vals = [v for s in series for v in s["data"]]
    if y_max is None:
        y_max = max(all_vals) * 1.08
    if y_min is None:
        y_min = min(all_vals) * 0.95
    n = len(x_labels)

    def xpos(i):
        return pad_l + (plot_w * i / (n - 1) if n > 1 else 0)

    def ypos(v):
        return pad_t + plot_h - (v - y_min) / (y_max - y_min) * plot_h

    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="-apple-system,PingFang SC,Microsoft YaHei,sans-serif">']
    for t in range(y_ticks + 1):
        v = y_min + (y_max - y_min) * t / y_ticks
        y = ypos(v)
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        svg.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" font-size="11" fill="#64748b" text-anchor="end">{v:,.0f}{unit}</text>')
    for i, lbl in enumerate(x_labels):
        svg.append(f'<text x="{xpos(i):.1f}" y="{height-pad_b+18}" font-size="11" fill="#64748b" text-anchor="middle">{lbl}</text>')
    for s in series:
        pts = " ".join(f"{xpos(i):.1f},{ypos(v):.1f}" for i, v in enumerate(s["data"]))
        dash = ' stroke-dasharray="5,4"' if s.get("dashed") else ""
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{s["color"]}" stroke-width="{s.get("width",2)}"{dash}/>')
        for i, v in enumerate(s["data"]):
            svg.append(f'<circle cx="{xpos(i):.1f}" cy="{ypos(v):.1f}" r="{s.get("r",3)}" fill="{s["color"]}"/>')
    lx, ly = pad_l, 14
    for s in series:
        svg.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+16}" y2="{ly}" stroke="{s["color"]}" stroke-width="3"/>')
        svg.append(f'<text x="{lx+20}" y="{ly+4}" font-size="11" fill="#1e293b">{s["name"]}</text>')
        lx += 20 + len(s["name"]) * 12 + 18
    svg.append("</svg>")
    return "\n".join(svg)


def bar_chart_v(width, height, labels, values, colors, unit="", y_ticks=5):
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 45
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    y_max = max(values) * 1.1 if values else 1
    n = len(labels)
    gap = plot_w / n
    bw = gap * 0.55

    def ypos(v):
        return pad_t + plot_h - (v / y_max * plot_h)

    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="-apple-system,PingFang SC,Microsoft YaHei,sans-serif">']
    for t in range(y_ticks + 1):
        v = y_max * t / y_ticks
        y = ypos(v)
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        svg.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" font-size="10.5" fill="#64748b" text-anchor="end">{v:,.0f}{unit}</text>')
    for i, (lbl, v, c) in enumerate(zip(labels, values, colors)):
        cx = pad_l + gap * i + gap / 2
        y = ypos(v)
        h = pad_t + plot_h - y
        svg.append(f'<rect x="{cx-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{c}" rx="2"/>')
        svg.append(f'<text x="{cx:.1f}" y="{y-6:.1f}" font-size="10" fill="#1e293b" text-anchor="middle">{v:,.0f}</text>')
        svg.append(f'<text x="{cx:.1f}" y="{height-pad_b+16:.1f}" font-size="10.5" fill="#64748b" text-anchor="middle">{lbl}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def bar_chart_h(width, height, labels, values, color, unit="亿", x_max=None):
    pad_l, pad_r, pad_t, pad_b = 130, 40, 10, 10
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(labels)
    gap = plot_h / n
    bh = gap * 0.55
    xmax = x_max or (max(values) * 1.15 if values else 1)
    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="-apple-system,PingFang SC,Microsoft YaHei,sans-serif">']
    for i, (lbl, v) in enumerate(zip(labels, values)):
        cy = pad_t + gap * i + gap / 2
        w = v / xmax * plot_w
        svg.append(f'<text x="{pad_l-10}" y="{cy+4:.1f}" font-size="12" fill="#1e293b" text-anchor="end">{lbl}</text>')
        svg.append(f'<rect x="{pad_l}" y="{cy-bh/2:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="{color}" rx="2"/>')
        svg.append(f'<text x="{pad_l+w+8:.1f}" y="{cy+4:.1f}" font-size="11.5" fill="#1e293b">{v:,.2f}{unit}</text>')
    svg.append("</svg>")
    return "\n".join(svg)
