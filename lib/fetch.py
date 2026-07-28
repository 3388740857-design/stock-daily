"""
A-share daily data fetcher. Pulls everything needed for the daily recap report:
- 6 major index quotes + 10-day history
- full-market breadth (advance/decline, distribution buckets, zt/zb/dt exact counts)
- limit-up pool (today + prior 5 trading days, for sector persistence trend)
- THS limit-up reason tags (theme attribution)
- full-market dragon-tiger list + institutional buy/sell seat detail for top movers

All endpoints are public, zero-auth HTTP APIs (tencent/sina/eastmoney push2ex &
datacenter-web/10jqka dataapi). No API keys required. Some endpoints
(push2.eastmoney.com clist, push2his, data.10jqka.com.cn/funds/*) are known to be
unreliable or rate-limited from various networks/times of day -- this script does NOT
depend on them; it only uses the endpoints verified working in practice (see README).

Usage:
    python3 fetch.py --date 2026-07-27 --outdir ../data

Produces:
    <outdir>/summary_<date>.json   -- single consolidated JSON with everything below
"""
import argparse
import json
import time
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def get(url, **kw):
    kw.setdefault("timeout", 20)
    kw.setdefault("headers", {})
    kw["headers"].setdefault("User-Agent", UA)
    for attempt in range(4):
        try:
            r = SESSION.get(url, **kw)
            if r.status_code == 200:
                return r
            print(f"  [warn] {url} -> HTTP {r.status_code} (attempt {attempt+1})", file=sys.stderr)
        except Exception as e:
            print(f"  [warn] {url} -> {e} (attempt {attempt+1})", file=sys.stderr)
        time.sleep(2 * (attempt + 1) + random.uniform(0, 1))
    return None


# ---------------------------------------------------------------------------
# 1. Index quotes + 10-day history (tencent web.ifzq day-kline; zero auth)
# ---------------------------------------------------------------------------
INDEX_CODES = {
    "上证指数": "sh000001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证1000": "sh000852",
}


def fetch_indices():
    codes = ",".join(INDEX_CODES.values())
    r = get("https://qt.gtimg.cn/q=" + codes)
    quotes = {}
    if r is not None:
        data = r.content.decode("gbk", "ignore")
        for line in data.strip().split(";"):
            if not line.strip() or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 40:
                continue
            name = vals[1]
            quotes[name] = {
                "code": key,
                "price": float(vals[3]) if vals[3] else 0,
                "last_close": float(vals[4]) if vals[4] else 0,
                "change_amt": float(vals[31]) if vals[31] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "amount_yi": round(float(vals[37]) / 10000, 2) if vals[37] else 0,
            }
    history = {}
    for name, code in INDEX_CODES.items():
        r = get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": f"{code},day,,,12,"},
        )
        rows = []
        if r is not None:
            try:
                d = r.json()
                day_data = d.get("data", {}).get(code, {})
                k = day_data.get("day") or day_data.get("qfqday") or []
                rows = [[row[0], float(row[2])] for row in k[-10:]]  # [date, close]
            except Exception as e:
                print(f"  [warn] index history parse failed for {name}: {e}", file=sys.stderr)
        history[name] = rows
        time.sleep(0.5)
    return {"quotes": quotes, "history_10d": history}


# ---------------------------------------------------------------------------
# 2. Full-market breadth (sina paginated quote list)
# ---------------------------------------------------------------------------
def fetch_market_breadth(max_pages=70, per_page=100, return_raw=False):
    rows = []
    seen = set()
    for page in range(1, max_pages + 1):
        r = get(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
            params={"page": str(page), "num": str(per_page), "sort": "symbol", "asc": "1",
                     "node": "hs_a", "symbol": "", "_s_r_a": "init"},
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        if r is None:
            break
        try:
            data = r.json()
        except Exception:
            break
        if not data:
            break
        new = [x for x in data if x.get("code") not in seen]
        for x in new:
            seen.add(x["code"])
        rows.extend(new)
        if len(data) < per_page:
            break
        time.sleep(1.0)
    # compute breadth stats
    def pct(r):
        try:
            return float(r.get("changepercent"))
        except (TypeError, ValueError):
            return None
    vals = [(r, pct(r)) for r in rows]
    good = [(r, c) for r, c in vals if c is not None]
    up = sum(1 for _, c in good if c > 0)
    down = sum(1 for _, c in good if c < 0)
    flat = sum(1 for _, c in good if c == 0)
    total_amount = sum(float(r.get("amount") or 0) for r, _ in good)
    buckets_def = [
        ("≥9.8%", 9.8, None), ("7~9.8%", 7, 9.8), ("5~7%", 5, 7), ("2~5%", 2, 5),
        ("0~2%", 0, 2), ("平", 0, 0), ("0~-2%", -2, 0), ("-2~-5%", -5, -2),
        ("-5~-7%", -7, -5), ("-7~-9.8%", -9.8, -7), ("≤-9.8%", None, -9.8),
    ]
    buckets = {name: 0 for name, _, _ in buckets_def}
    for _, c in good:
        if c >= 9.8:
            buckets["≥9.8%"] += 1
        elif c >= 7:
            buckets["7~9.8%"] += 1
        elif c >= 5:
            buckets["5~7%"] += 1
        elif c >= 2:
            buckets["2~5%"] += 1
        elif c > 0:
            buckets["0~2%"] += 1
        elif c == 0:
            buckets["平"] += 1
        elif c > -2:
            buckets["0~-2%"] += 1
        elif c > -5:
            buckets["-2~-5%"] += 1
        elif c > -7:
            buckets["-5~-7%"] += 1
        elif c > -9.8:
            buckets["-7~-9.8%"] += 1
        else:
            buckets["≤-9.8%"] += 1
    result = {
        "total": len(good), "up": up, "down": down, "flat": flat,
        "total_amount_yi": round(total_amount / 1e8, 1),
        "distribution_buckets": buckets,
    }
    if return_raw:
        # full per-stock rows (code/name/trade/changepercent/turnoverratio/amount/...)
        # -- reused by lib/stock_pool.py so it doesn't need a second ~55-request
        # full-market pull just to get today's price/turnover per candidate.
        result["_raw_rows"] = [r for r, _ in good]
    return result


# ---------------------------------------------------------------------------
# 3. Limit-up / break / limit-down pools (push2ex, zero auth, stable)
# ---------------------------------------------------------------------------
ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _fmt_zt_time(t):
    s = str(t).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def _zt_api(endpoint, sort, date_str):
    r = get(
        f"https://push2ex.eastmoney.com/{endpoint}",
        params={"ut": ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 10000,
                "sort": sort, "date": date_str},
        headers={"Referer": "https://quote.eastmoney.com/"},
    )
    if r is None:
        return []
    try:
        return (r.json().get("data") or {}).get("pool") or []
    except Exception:
        return []


def fetch_zt_pool(date_str):
    out = []
    for p in _zt_api("getTopicZTPool", "fbt:asc", date_str):
        out.append({
            "code": p["c"], "name": p["n"], "price": p["p"] / 1000,
            "pct": round(p["zdp"], 2), "turnover": round(p.get("hs", 0), 2),
            "limit_days": p["lbc"], "seal_fund": p["fund"], "break_times": p["zbc"],
            "industry": p.get("hybk", ""), "first_seal": _fmt_zt_time(p["fbt"]),
        })
    return out


def fetch_zb_pool(date_str):
    out = []
    for p in _zt_api("getTopicZBPool", "fbt:asc", date_str):
        out.append({"code": p["c"], "name": p["n"], "industry": p.get("hybk", ""),
                     "break_times": p["zbc"], "pct": round(p["zdp"], 2)})
    return out


def fetch_dt_pool(date_str):
    out = []
    for p in _zt_api("getTopicDTPool", "fund:asc", date_str):
        out.append({"code": p["c"], "name": p["n"], "industry": p.get("hybk", ""),
                     "pct": round(p["zdp"], 2)})
    return out


def fetch_zt_trend(date_str, days_back=5):
    """zt_pool for `date_str` plus the `days_back` preceding weekdays."""
    d = datetime.strptime(date_str, "%Y%m%d")
    dates = []
    cursor = d
    while len(dates) < days_back + 1:
        if cursor.weekday() < 5:
            dates.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    dates.reverse()
    trend = {}
    for dt in dates:
        pool = fetch_zt_pool(dt)
        trend[dt] = pool
        time.sleep(1.3)
    return trend


# ---------------------------------------------------------------------------
# 4. THS limit-up reason tags (data.10jqka.com.cn/dataapi -- separate from the
#    rate-limited data.10jqka.com.cn/funds/* HTML pages, has held up reliably)
# ---------------------------------------------------------------------------
def fetch_limitup_reasons(date_str):
    r = get(
        "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool",
        # NOTE: limit=300 silently fails (status_code:-1, empty info) -- this
        # endpoint caps out somewhere between 200 and 300. 200 comfortably
        # covers even very high-limit-up-count days; don't raise this without
        # re-verifying against the live endpoint first.
        params={"page": 1, "limit": 200,
                "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
                "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0", "date": date_str},
    )
    if r is None:
        return []
    try:
        info = r.json().get("data", {}).get("info", []) or []
    except Exception:
        return []
    out = []
    for x in info:
        out.append({
            "code": x.get("code"), "name": x.get("name"), "pct": x.get("change_rate"),
            "reason": x.get("reason_type") or "", "high_days": x.get("high_days") or "",
        })
    return out


# ---------------------------------------------------------------------------
# 5. Dragon-tiger board (datacenter-web, zero auth, stable) + institution seats
# ---------------------------------------------------------------------------
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _datacenter(report_name, filter_str, page_size=200, sort_columns="", sort_types="-1"):
    r = get(DATACENTER_URL, params={
        "reportName": report_name, "columns": "ALL", "filter": filter_str,
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    })
    if r is None:
        return []
    try:
        return (r.json().get("result") or {}).get("data") or []
    except Exception:
        return []


def fetch_dragon_tiger(date_iso):
    rows = _datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        f"(TRADE_DATE>='{date_iso}')(TRADE_DATE<='{date_iso}')",
        sort_columns="BILLBOARD_NET_AMT",
    )
    out = []
    for r in rows:
        out.append({
            "code": r.get("SECURITY_CODE"), "name": r.get("SECURITY_NAME_ABBR"),
            "reason": r.get("EXPLANATION"), "pct": r.get("CHANGE_RATE"),
            "net_amt_yi": round((r.get("BILLBOARD_NET_AMT") or 0) / 1e8, 2),
        })
    return out


def fetch_seat_detail(code, date_iso):
    """Institution buy/sell net for one stock on one date (dragon-tiger seat detail)."""
    def seats(side):
        report = "RPT_BILLBOARD_DAILYDETAILSBUY" if side == "buy" else "RPT_BILLBOARD_DAILYDETAILSSELL"
        col = "BUY" if side == "buy" else "SELL"
        return _datacenter(report, f"(TRADE_DATE='{date_iso}')(SECURITY_CODE=\"{code}\")",
                            page_size=10, sort_columns=col)
    buy = seats("buy")
    time.sleep(1.3)
    sell = seats("sell")
    time.sleep(1.3)
    inst_buy = sum(r.get("BUY") or 0 for r in buy if r.get("OPERATEDEPT_NAME") == "机构专用")
    inst_sell = sum(r.get("SELL") or 0 for r in sell if r.get("OPERATEDEPT_NAME") == "机构专用")
    return {
        "code": code,
        "inst_buy_yi": round(inst_buy / 1e8, 2),
        "inst_sell_yi": round(inst_sell / 1e8, 2),
        "inst_net_yi": round((inst_buy - inst_sell) / 1e8, 2),
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="trading date, YYYY-MM-DD")
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--seat-detail-top", type=int, default=6,
                     help="fetch institutional seat detail for the top N dragon-tiger stocks by |net_amt|")
    args = ap.parse_args()

    date_iso = args.date
    date_str = date_iso.replace("-", "")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] indices...", file=sys.stderr)
    indices = fetch_indices()

    print(f"[2/5] market breadth (full A-share universe, ~55 paginated requests, ~1min)...", file=sys.stderr)
    breadth = fetch_market_breadth(return_raw=True)
    raw_rows = breadth.pop("_raw_rows", [])
    raw_path = outdir / f"market_raw_{date_iso}.json"
    raw_path.write_text(json.dumps(raw_rows, ensure_ascii=False))
    print(f"  wrote {raw_path} ({len(raw_rows)} stocks, for lib/stock_pool.py)", file=sys.stderr)

    print(f"[3/5] limit-up/break/limit-down pools + 5-day trend...", file=sys.stderr)
    zt = fetch_zt_pool(date_str)
    zb = fetch_zb_pool(date_str)
    dt = fetch_dt_pool(date_str)
    zt_trend = fetch_zt_trend(date_str, days_back=5)

    if not zt and not breadth["up"]:
        print(f"[!] No data returned for {date_iso} -- likely not a trading day. Aborting.", file=sys.stderr)
        sys.exit(2)

    print(f"[4/5] THS limit-up reason tags...", file=sys.stderr)
    reasons = fetch_limitup_reasons(date_str)

    print(f"[5/5] dragon-tiger board + institutional seat detail...", file=sys.stderr)
    dragon_tiger = fetch_dragon_tiger(date_iso)
    top_movers = sorted(dragon_tiger, key=lambda r: -abs(r["net_amt_yi"]))[: args.seat_detail_top]
    seat_details = []
    for m in top_movers:
        sd = fetch_seat_detail(m["code"], date_iso)
        sd["name"] = m["name"]
        seat_details.append(sd)

    summary = {
        "date": date_iso,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "indices": indices,
        "breadth": breadth,
        "zt_pool": zt,
        "zb_pool": zb,
        "dt_pool": dt,
        "zt_trend_6d": zt_trend,
        "limitup_reasons": reasons,
        "dragon_tiger": dragon_tiger,
        "seat_details": seat_details,
    }
    out_path = outdir / f"summary_{date_iso}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"WROTE {out_path}", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
