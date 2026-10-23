"""Yahoo Finance 일봉 수집기 + 데이터 품질점검.

사용법 (작업 폴더 '차트 아록리즘 분석' 기준):
    py src/data_fetch.py                  # universe.csv 생성 후 전체 수집 (이미 받은 파일은 건너뜀)
    py src/data_fetch.py AAPL MSFT        # 지정 티커만 수집
    py src/data_fetch.py --force          # 기존 파일도 다시 받기
    py src/data_fetch.py --report         # 수집 없이 01_데이터품질.md 만 다시 작성

저장 형식: data/raw/{티커}.csv  (date,open,high,low,close,adj_close,volume)
date 는 거래소 현지 날짜 (timestamp + meta.gmtoffset).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
UNIVERSE_CSV = ROOT / "data" / "universe.csv"
QUALITY_MD = ROOT / "01_데이터품질.md"
FAIL_JSON = ROOT / "data" / "fetch_failures.json"

URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
       "?period1=0&period2=9999999999&interval=1d&events=div,split")
HEADERS = {"User-Agent": "Mozilla/5.0"}
COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
MAX_RETRIES = 5
BIG_MOVE = 0.40

UNIVERSE = [
    # 지수 ETF
    ("SPY", "SPDR S&P 500 ETF", "index_etf"),
    ("QQQ", "Invesco QQQ (Nasdaq-100)", "index_etf"),
    ("DIA", "SPDR Dow Jones Industrial Average ETF", "index_etf"),
    ("IWM", "iShares Russell 2000 ETF", "index_etf"),
    ("MDY", "SPDR S&P MidCap 400 ETF", "index_etf"),
    ("EFA", "iShares MSCI EAFE ETF", "index_etf"),
    ("EEM", "iShares MSCI Emerging Markets ETF", "index_etf"),
    ("TLT", "iShares 20+ Year Treasury Bond ETF", "index_etf"),
    ("GLD", "SPDR Gold Shares", "index_etf"),
    # 섹터 ETF
    ("XLK", "Technology Select Sector SPDR", "sector_etf"),
    ("XLF", "Financial Select Sector SPDR", "sector_etf"),
    ("XLE", "Energy Select Sector SPDR", "sector_etf"),
    ("XLV", "Health Care Select Sector SPDR", "sector_etf"),
    ("XLI", "Industrial Select Sector SPDR", "sector_etf"),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "sector_etf"),
    ("XLP", "Consumer Staples Select Sector SPDR", "sector_etf"),
    ("XLU", "Utilities Select Sector SPDR", "sector_etf"),
    ("XLB", "Materials Select Sector SPDR", "sector_etf"),
    # 미국 대형주
    ("AAPL", "Apple", "us_large"),
    ("MSFT", "Microsoft", "us_large"),
    ("AMZN", "Amazon", "us_large"),
    ("GOOGL", "Alphabet A", "us_large"),
    ("META", "Meta Platforms", "us_large"),
    ("NVDA", "NVIDIA", "us_large"),
    ("TSLA", "Tesla", "us_large"),
    ("BRK-B", "Berkshire Hathaway B", "us_large"),
    ("JPM", "JPMorgan Chase", "us_large"),
    ("BAC", "Bank of America", "us_large"),
    ("C", "Citigroup", "us_large"),
    ("WFC", "Wells Fargo", "us_large"),
    ("GS", "Goldman Sachs", "us_large"),
    ("MS", "Morgan Stanley", "us_large"),
    ("AIG", "American International Group", "us_large"),
    ("XOM", "Exxon Mobil", "us_large"),
    ("CVX", "Chevron", "us_large"),
    ("COP", "ConocoPhillips", "us_large"),
    ("SLB", "Schlumberger", "us_large"),
    ("JNJ", "Johnson & Johnson", "us_large"),
    ("PFE", "Pfizer", "us_large"),
    ("MRK", "Merck", "us_large"),
    ("ABT", "Abbott Laboratories", "us_large"),
    ("UNH", "UnitedHealth Group", "us_large"),
    ("LLY", "Eli Lilly", "us_large"),
    ("BMY", "Bristol-Myers Squibb", "us_large"),
    ("PG", "Procter & Gamble", "us_large"),
    ("KO", "Coca-Cola", "us_large"),
    ("PEP", "PepsiCo", "us_large"),
    ("WMT", "Walmart", "us_large"),
    ("COST", "Costco", "us_large"),
    ("HD", "Home Depot", "us_large"),
    ("MCD", "McDonald's", "us_large"),
    ("NKE", "Nike", "us_large"),
    ("SBUX", "Starbucks", "us_large"),
    ("DIS", "Walt Disney", "us_large"),
    ("CMCSA", "Comcast", "us_large"),
    ("T", "AT&T", "us_large"),
    ("VZ", "Verizon", "us_large"),
    ("INTC", "Intel", "us_large"),
    ("CSCO", "Cisco", "us_large"),
    ("ORCL", "Oracle", "us_large"),
    ("IBM", "IBM", "us_large"),
    ("QCOM", "Qualcomm", "us_large"),
    ("TXN", "Texas Instruments", "us_large"),
    ("AMD", "Advanced Micro Devices", "us_large"),
    ("MU", "Micron Technology", "us_large"),
    ("ADBE", "Adobe", "us_large"),
    ("CRM", "Salesforce", "us_large"),
    ("NFLX", "Netflix", "us_large"),
    ("GE", "General Electric (GE Aerospace)", "us_large"),
    ("BA", "Boeing", "us_large"),
    ("CAT", "Caterpillar", "us_large"),
    ("MMM", "3M", "us_large"),
    ("HON", "Honeywell", "us_large"),
    ("UPS", "United Parcel Service", "us_large"),
    ("FDX", "FedEx", "us_large"),
    ("F", "Ford Motor", "us_large"),
    ("GM", "General Motors", "us_large"),
    ("LMT", "Lockheed Martin", "us_large"),
    ("RTX", "RTX (Raytheon)", "us_large"),
    ("DE", "Deere & Company", "us_large"),
    ("MO", "Altria", "us_large"),
    ("PM", "Philip Morris International", "us_large"),
    ("WBA", "Walgreens Boots Alliance", "us_large"),
    ("CVS", "CVS Health", "us_large"),
    ("KHC", "Kraft Heinz", "us_large"),
    ("MA", "Mastercard", "us_large"),
    ("V", "Visa", "us_large"),
    ("AXP", "American Express", "us_large"),
    ("PYPL", "PayPal", "us_large"),
    ("EBAY", "eBay", "us_large"),
    ("BKNG", "Booking Holdings", "us_large"),
    ("AMGN", "Amgen", "us_large"),
    ("GILD", "Gilead Sciences", "us_large"),
    ("NEE", "NextEra Energy", "us_large"),
    ("DUK", "Duke Energy", "us_large"),
    ("SO", "Southern Company", "us_large"),
    # 한국
    ("005930.KS", "삼성전자", "korea"),
    ("000660.KS", "SK하이닉스", "korea"),
    ("005380.KS", "현대차", "korea"),
    ("035420.KS", "NAVER", "korea"),
    ("051910.KS", "LG화학", "korea"),
    ("006400.KS", "삼성SDI", "korea"),
    ("035720.KS", "카카오", "korea"),
    ("068270.KS", "셀트리온", "korea"),
    ("105560.KS", "KB금융", "korea"),
    ("055550.KS", "신한지주", "korea"),
    ("005490.KS", "POSCO홀딩스", "korea"),
    ("012330.KS", "현대모비스", "korea"),
    ("000270.KS", "기아", "korea"),
    ("066570.KS", "LG전자", "korea"),
    ("069500.KS", "KODEX 200", "korea"),
]


def write_universe() -> pd.DataFrame:
    df = pd.DataFrame(UNIVERSE, columns=["ticker", "name", "group"])
    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(UNIVERSE_CSV, index=False, encoding="utf-8-sig")
    return df


def http_get_json(url: str) -> dict:
    """429/5xx 는 지수 백오프로 최대 MAX_RETRIES 회 재시도."""
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or 500 <= e.code < 600
            if not retryable or attempt == MAX_RETRIES:
                raise
            wait = 2 ** (attempt + 1) + random.uniform(0, 1)
            print(f"    HTTP {e.code}, {wait:.1f}초 후 재시도 ({attempt + 1}/{MAX_RETRIES})")
            time.sleep(wait)
        except urllib.error.URLError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def parse_chart(payload: dict) -> pd.DataFrame:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"Yahoo error: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result or not result.get("timestamp"):
        raise ValueError("빈 응답 (timestamp 없음)")

    offset = timedelta(seconds=result["meta"].get("gmtoffset", 0))
    dates = [(datetime.fromtimestamp(ts, tz=timezone.utc) + offset).strftime("%Y-%m-%d")
             for ts in result["timestamp"]]
    quote = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")

    df = pd.DataFrame({
        "date": dates,
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "adj_close": adj if adj is not None else quote.get("close"),
        "volume": quote.get("volume"),
    })
    # 장중 실시간 바가 마지막에 같은 날짜로 붙는 경우가 있어 날짜 중복은 마지막 값 유지
    df = df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)

    # 아직 장이 안 끝난 당일 바와, 끝부분에 종가가 비어 있는 바(Yahoo가 최근 1~2일을 늦게 채움)는 제외
    regular_end = (result["meta"].get("currentTradingPeriod") or {}).get("regular", {}).get("end")
    if len(df) and regular_end and time.time() < regular_end and df["date"].iloc[-1] == (
            datetime.fromtimestamp(regular_end, tz=timezone.utc) + offset).strftime("%Y-%m-%d"):
        df = df.iloc[:-1]
    while len(df) and pd.isna(df["close"].iloc[-1]):
        df = df.iloc[:-1]
    df["volume"] = df["volume"].astype("Int64")
    return df[COLUMNS]


def fetch_one(ticker: str) -> pd.DataFrame:
    return parse_chart(http_get_json(URL.format(ticker=ticker)))


def fetch_all(tickers: list[str], force: bool) -> dict[str, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failures: dict[str, str] = {}
    for i, t in enumerate(tickers, 1):
        out = RAW_DIR / f"{t}.csv"
        if out.exists() and not force:
            print(f"[{i}/{len(tickers)}] {t}: 이미 있음, 건너뜀")
            continue
        try:
            df = fetch_one(t)
            df.to_csv(out, index=False)
            print(f"[{i}/{len(tickers)}] {t}: {len(df)}행 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
        except Exception as e:  # noqa: BLE001 - 실패는 기록 후 계속
            failures[t] = f"{type(e).__name__}: {e}"
            print(f"[{i}/{len(tickers)}] {t}: 실패 - {failures[t]}")
        time.sleep(random.uniform(1.0, 2.0))
    return failures


def check_quality(ticker: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(RAW_DIR / f"{ticker}.csv")
    price_cols = ["open", "high", "low", "close"]
    any_na = df[price_cols + ["adj_close", "volume"]].isna().any(axis=1)
    zero_vol = df["volume"].fillna(0) == 0

    h, l, c, o = df["high"], df["low"], df["close"], df["open"]
    hl_bad = h < l
    c_out = (c > h * (1 + 1e-6)) | (c < l * (1 - 1e-6))
    o_out = (o > h * (1 + 1e-6)) | (o < l * (1 - 1e-6))
    logic = df[hl_bad | c_out | o_out].copy()
    logic["issue"] = np.select(
        [hl_bad[logic.index], c_out[logic.index]], ["high<low", "close가 범위 밖"], "open이 범위 밖")

    ret = df["close"] / df["close"].shift(1) - 1
    adj_ret = df["adj_close"] / df["adj_close"].shift(1) - 1
    big = df[ret.abs() > BIG_MOVE].copy()
    big["ret"] = ret[big.index]
    big["adj_ret"] = adj_ret[big.index]
    big["prev_close"] = df["close"].shift(1)[big.index]

    stats = {
        "ticker": ticker,
        "start": df["date"].iloc[0],
        "end": df["date"].iloc[-1],
        "rows": len(df),
        "na_days": int(any_na.sum()),
        "zero_vol_days": int(zero_vol.sum()),
        "high<low": int(hl_bad.sum()),
        "close_out": int(c_out.sum()),
        "open_out": int(o_out.sum()),
        "big_moves": len(big),
    }
    return stats, logic, big


def fmt(x: float) -> str:
    return "" if pd.isna(x) else f"{x:,.4f}"


def write_report(universe: pd.DataFrame, failures: dict[str, str]) -> dict:
    stats_rows, logic_rows, big_rows = [], [], []
    missing = []
    for t in universe["ticker"]:
        if not (RAW_DIR / f"{t}.csv").exists():
            missing.append(t)
            continue
        s, logic, big = check_quality(t)
        stats_rows.append(s)
        for _, r in logic.iterrows():
            logic_rows.append((t, r["date"], r["issue"], r["open"], r["high"], r["low"], r["close"]))
        for _, r in big.iterrows():
            big_rows.append((t, r["date"], r["prev_close"], r["close"], r["ret"], r["adj_ret"]))

    st = pd.DataFrame(stats_rows).merge(universe[["ticker", "group"]], on="ticker")
    lines = [
        "# 01. 데이터 품질점검",
        "",
        f"- 작성: {datetime.now():%Y-%m-%d %H:%M} / 작성자: value-investing-checklist-f9 (`src/data_fetch.py --report`)",
        "- 출처: Yahoo Finance chart API v8, 일봉, 상장 이후 전체. OHLC는 분할 반영·배당 미반영, adj_close는 분할+배당 반영",
        f"- 유니버스 {len(universe)}개 / 수집 성공 {len(st)}개 / 실패 {len(missing)}개",
        f"- 기준: 결측 = 가격·거래량 중 하나라도 NaN인 날, 큰 변동 = 전일 종가 대비 |종가 변동| > {BIG_MOVE:.0%}",
        "- 문제 행은 삭제하지 않고 아래 표로만 보고함",
        "",
        "## 실패 티커",
        "",
    ]
    if missing:
        lines += ["| 티커 | 사유 |", "|---|---|"]
        lines += [f"| {t} | {failures.get(t, '파일 없음 (이전 실행 실패)')} |" for t in missing]
    else:
        lines.append("없음")

    lines += ["", "## 종목별 요약", "",
              "| 티커 | 그룹 | 시작일 | 종료일 | 행수 | 결측일 | 0거래량일 | high<low | close 범위밖 | open 범위밖 | ±40% 변동 |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in st.iterrows():
        lines.append(f"| {r.ticker} | {r.group} | {r.start} | {r.end} | {r.rows:,} | {r.na_days} | "
                     f"{r.zero_vol_days} | {r['high<low']} | {r.close_out} | {r.open_out} | {r.big_moves} |")

    lines += ["", f"## 하루 ±{BIG_MOVE:.0%} 초과 변동 (분할 미반영 의심 포함)", "",
              "adj_ret 도 비슷하게 크면 실제 급변(또는 adj도 미반영), adj_ret 이 작으면 OHLC에만 분할이 빠진 것.", ""]
    if big_rows:
        lines += ["| 티커 | 날짜 | 전일 종가 | 종가 | 종가 변동 | adj_close 변동 |", "|---|---|---:|---:|---:|---:|"]
        lines += [f"| {t} | {d} | {fmt(p)} | {fmt(c)} | {r:+.1%} | {a:+.1%} |" for t, d, p, c, r, a in big_rows]
    else:
        lines.append("없음")

    lines += ["", "## OHLC 논리오류 행", ""]
    if logic_rows:
        lines.append(f"총 {len(logic_rows)}건." + (" 앞 300건만 표시." if len(logic_rows) > 300 else ""))
        lines += ["", "| 티커 | 날짜 | 문제 | open | high | low | close |", "|---|---|---|---:|---:|---:|---:|"]
        lines += [f"| {t} | {d} | {i} | {fmt(o)} | {fmt(h)} | {fmt(l)} | {fmt(c)} |"
                  for t, d, i, o, h, l, c in logic_rows[:300]]
    else:
        lines.append("없음")

    QUALITY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": len(st), "missing": missing, "logic": len(logic_rows), "big": len(big_rows),
            "na_total": int(st["na_days"].sum()), "zero_vol_total": int(st["zero_vol_days"].sum())}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", help="지정 시 해당 티커만 수집 (기본: 유니버스 전체)")
    ap.add_argument("--force", action="store_true", help="이미 받은 파일도 다시 받기")
    ap.add_argument("--report", action="store_true", help="수집 없이 품질 보고서만 작성")
    args = ap.parse_args()

    universe = write_universe()
    failures = json.loads(FAIL_JSON.read_text(encoding="utf-8")) if FAIL_JSON.exists() else {}
    if not args.report:
        tickers = args.tickers or universe["ticker"].tolist()
        new_fail = fetch_all(tickers, args.force)
        for t in tickers:
            failures.pop(t, None)
        failures.update(new_fail)
        FAIL_JSON.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = write_report(universe, failures)
    print(f"\n품질 보고서: {QUALITY_MD}")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
