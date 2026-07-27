# A股每日盘后复盘报告

自动生成的A股每日收盘复盘 PDF，聚焦：今日资金重点板块、持续流入的成长性板块、当前主线趋势判断、整体盘面与风险。格式参考 [`template/example_report.html`](template/example_report.html)。

- `lib/fetch.py` — 拉取当日数据（指数、全市场涨跌分布、涨停/炸板/跌停池、近6日涨停趋势、题材归因、龙虎榜+机构席位），零 key 公开接口
- `lib/charts.py` — 静态 SVG 图表生成（不用 JS 图表库，见 `REPORT_GUIDE.md` 说明原因）
- `lib/render.py` — Playwright 把最终 HTML 渲染成 PDF
- `run_daily.py` — 串起 fetch / charts / pdf 三个纯机械步骤
- `REPORT_GUIDE.md` — 云端 agent 每天写报告正文时必须遵循的完整指南
- `data/` — 每日抓取的原始 JSON + SVG
- `reports/<date>/` — 每日最终 report.html + report.pdf

首次运行环境需要：
```
pip install -r requirements.txt
playwright install --with-deps chromium
```
