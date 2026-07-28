"""
20-stock main-board recommendation pool.

Combines three signals, all main-board only (沪市 60xxxx / 深市 000xxx,001xxx,002xxx --
explicitly excludes 创业板 300/301, 科创板 688, 北交所 8/4/92xxx per user requirement):

1. Theme/sector momentum -- THS "热点" endpoint (zx.10jqka.com.cn), which returns
   today's strong stocks *with* a human-curated reason/theme tag baked in. This is
   used instead of a separate industry-classification lookup because the obvious
   candidates for that (eastmoney push2/slist) are on the push2.eastmoney.com host,
   which this pipeline's network policy does NOT allow (see REPORT_GUIDE.md --
   push2.eastmoney.com was found unreliable/blocked and deliberately excluded).
   zx.10jqka.com.cn is a different host from the rate-limited data.10jqka.com.cn/funds/*
   pages and has held up in testing.

2. Today's price/volume -- cross-referenced from the full-market breadth data
   already fetched in fetch.py (data/market_raw_<date>.json), which has
   change%/turnover%/amount/price per stock. Avoids a second full-market pull.

3. K-line technical trend -- tencent daily K-line (web.ifzq.gtimg.cn), fetched
   only for the shortlist that survives steps 1-2 (~30 stocks). MA5/10/20 are
   computed locally from the raw closes (this endpoint doesn't bake them in
   the way baidu's does, but baidu's finance.pae.baidu.com was found to
   rate-limit hard -- works once, then 403s even with multi-second delays
   between calls -- so it's not usable for a ~30-stock loop). Tencent's
   web.ifzq.gtimg.cn is already used elsewhere in this pipeline (index 10-day
   history) and held up under repeated calls all session; reusing it here
   also avoids needing a second new domain on the network allowlist.

Usage:
    python3 lib/stock_pool.py --date 2026-07-28 --raw-market data/market_raw_2026-07-28.json --outdir data

Produces data/stock_pool_<date>.json: a ranked shortlist (default top 30, pick 20)
with all the raw numbers needed to write the final table -- this script does NOT
write the one-line rationale per stock or make the final 20-of-30 cut; that's the
daily agent's job (same hybrid split as the rest of the pipeline -- see
REPORT_GUIDE.md's stock-pool section), because "which 20" and "why" is a judgment
call that should reflect that day's actual narrative (e.g. prefer stocks in a
sector already flagged as P0 mainline elsewhere in the report), not a fixed formula.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch import get  # noqa: E402


MAINBOARD_PREFIXES = ("60", "000", "001", "002")


def is_mainboard(code: str) -> bool:
    return code.startswith(MAINBOARD_PREFIXES)


def fetch_hot_reason(date_iso: str) -> list[dict]:
    """THS 热点: today's strong stocks with theme/reason tags baked in."""
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_iso}/orderby/date/orderway/desc/charset/GBK/"
    r = get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
    })
    if r is None:
        return []
    try:
        d = r.json()
    except Exception:
        return []
    if d.get("errocode", 0) != 0:
        return []
    return d.get("data") or []


def tencent_daily_kline(code: str, n: int = 30) -> list[dict]:
    """Daily K-line (open/close/high/low/volume), unadjusted. Same endpoint
    used for index 10-day history in fetch.py -- proven reliable this session."""
    prefix = "sh" if code.startswith(("6", "9")) else ("bj" if code.startswith("8") else "sz")
    r = get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{prefix}{code},day,,,{n},"},
    )
    if r is None:
        return []
    try:
        d = r.json()
        day_data = d.get("data", {}).get(f"{prefix}{code}", {})
        rows = day_data.get("day") or day_data.get("qfqday") or []
    except Exception:
        return []
    out = []
    for row in rows:
        # tencent format: [date, open, close, high, low, volume, ...]
        if len(row) < 6:
            continue
        out.append({"date": row[0], "open": row[1], "close": row[2],
                     "high": row[3], "low": row[4], "volume": row[5]})
    return out


def technical_signal(bars: list[dict]) -> dict:
    """Bullish MA alignment + volume ratio + candle strength from recent bars."""
    if len(bars) < 21:
        return {}

    def f(rec, key):
        try:
            return float(rec.get(key))
        except (TypeError, ValueError):
            return None

    closes = [f(b, "close") for b in bars]
    if any(c is None for c in closes[-20:]):
        return {}

    today = bars[-1]
    close = closes[-1]
    high = f(today, "high")
    low = f(today, "low")
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20

    vol_today = f(today, "volume")
    prior_vols = [f(b, "volume") for b in bars[-6:-1]]
    prior_vols = [v for v in prior_vols if v]
    vol_ratio = (vol_today / (sum(prior_vols) / len(prior_vols))) if (vol_today and prior_vols) else None

    ma_stack = close > ma5 > ma10 > ma20  # textbook bullish alignment
    above_all = close > ma5 and close > ma10 and close > ma20

    candle_strength = None
    if close and high and low and high != low:
        candle_strength = round((close - low) / (high - low), 2)  # 1.0 = closed at high

    return {
        "close": round(close, 2), "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2),
        "ma_bullish_stack": ma_stack,
        "above_all_ma": above_all,
        "volume_ratio_vs_5d": round(vol_ratio, 2) if vol_ratio else None,
        "candle_strength": candle_strength,
    }


def build_pool(date_iso: str, raw_market_path: Path, top_n: int = 30) -> list[dict]:
    hot = fetch_hot_reason(date_iso)
    market = {r["code"]: r for r in json.loads(raw_market_path.read_text())}

    candidates = []
    for h in hot:
        code = h.get("code", "")
        if not is_mainboard(code):
            continue
        m = market.get(code)
        if not m:
            continue
        name = m.get("name", "")
        if "ST" in name or "退" in name:
            continue
        try:
            pct = float(m.get("changepercent"))
            turnover = float(m.get("turnoverratio"))
            amount = float(m.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if pct <= 0:
            continue
        if not (2.0 <= turnover <= 25.0):  # avoid illiquid tails and manipulation-prone extremes
            continue
        if amount < 1e8:  # floor: at least 1亿元 today's turnover, basic liquidity
            continue
        candidates.append({
            "code": code, "name": name, "reason": h.get("reason", ""),
            "pct": pct, "turnover_pct": turnover, "amount_yi": round(amount / 1e8, 2),
            "price": m.get("trade"),
        })

    # cheap pre-rank before spending K-line calls: blend momentum + liquidity
    candidates.sort(key=lambda c: -(c["pct"] * 0.6 + min(c["turnover_pct"], 15) * 0.4))
    shortlist = candidates[:top_n]

    for c in shortlist:
        bars = tencent_daily_kline(c["code"])
        c["technical"] = technical_signal(bars)
        time.sleep(0.6)

    return shortlist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--raw-market", required=True, help="path to data/market_raw_<date>.json")
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--top-n", type=int, default=30)
    args = ap.parse_args()

    pool = build_pool(args.date, Path(args.raw_market), args.top_n)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"stock_pool_{args.date}.json"
    out_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2))
    print(f"WROTE {out_path} ({len(pool)} candidates)", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
