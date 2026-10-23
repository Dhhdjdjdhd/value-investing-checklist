"""companies.csv 의 미국 상장 티커 -> Yahoo 일봉 + 분할 이벤트 (작업지시 W1, 작성: value-investing-checklist-f9).

사용법 (작업 폴더 '체크리스트 검증' 기준):
    py src/fetch_prices.py            # 이어받기 (manifest 에 있는 티커는 건너뜀)
    py src/fetch_prices.py --retry    # 실패한 티커만 다시
    py src/fetch_prices.py --max-minutes 9   # 9분 뒤 티커 사이에서 종료(종료코드 3, 다시 실행하면 이어서)
    py src/fetch_prices.py --refresh 2026-12-28   # 마지막 일봉이 이 날짜보다 오래된 티커를 다시 받기

저장
- data/prices/{티커}.csv  : date,open,high,low,close,adj_close,volume (차트 아록리즘 분석 data_fetch 와 같은 형식)
- data/prices/splits.csv  : ticker,date,numerator,denominator
- data/prices/manifest.csv: cik,ticker,yahoo,status,rows,start,end,error  (티커별 결과, 이어받기 기준)
"""
from __future__ import annotations

import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "차트 아록리즘 분석" / "src"))
sys.path.insert(0, str(ROOT / "src"))
from data_fetch import URL, http_get_json, parse_chart  # noqa: E402
from fetch_sec import COMPANIES, US_EXCHANGES, LowMemory, check_memory, log, set_deadline, time_up  # noqa: E402

PRICES = ROOT / "data" / "prices"
SPLITS = PRICES / "splits.csv"
MANIFEST = PRICES / "manifest.csv"


def yahoo_symbol(t: str) -> str:
    return t.strip().upper().replace(".", "-")


def pick_tickers(comp: pd.DataFrame) -> pd.DataFrame:
    """회사마다 미국 거래소에 상장된 첫 티커."""
    rows = []
    for r in comp.itertuples():
        if not isinstance(r.tickers, str) or not r.tickers:
            continue
        tks = r.tickers.split(";")
        exs = (r.exchanges if isinstance(r.exchanges, str) else "").split(";")
        exs += [""] * (len(tks) - len(exs))
        for t, ex in zip(tks, exs):
            if ex in US_EXCHANGES:
                rows.append({"cik": r.cik, "ticker": t, "yahoo": yahoo_symbol(t), "exchange": ex})
                break
    return pd.DataFrame(rows).drop_duplicates("yahoo")


def parse_splits(payload: dict, ticker: str) -> list[dict]:
    res = payload["chart"]["result"][0]
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    out = []
    for s in ((res.get("events") or {}).get("splits") or {}).values():
        d = (datetime.fromtimestamp(s["date"], tz=timezone.utc) + off).strftime("%Y-%m-%d")
        out.append({"ticker": ticker, "date": d, "numerator": s.get("numerator"), "denominator": s.get("denominator")})
    return out


def append_csv(path: Path, rows: list[dict]):
    if rows:
        pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False, encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    retry = "--retry" in sys.argv
    set_deadline(sys.argv)
    finished = True
    PRICES.mkdir(parents=True, exist_ok=True)
    jobs = pick_tickers(pd.read_csv(COMPANIES))
    man = pd.read_csv(MANIFEST) if MANIFEST.exists() else pd.DataFrame(columns=["yahoo", "status"])
    if "--refresh" in sys.argv:
        # 분기 재점검: 마지막 일봉이 기준일보다 오래된 티커만 다시 받는다 (이어받기 겸용)
        cutoff = sys.argv[sys.argv.index("--refresh") + 1]
        done = set(man[(man.status == "ok") & (man.end.astype(str) >= cutoff)].yahoo)
    elif retry:
        done = set(man[man.status == "ok"].yahoo)
    else:
        done = set(man.yahoo)
    todo = jobs[~jobs.yahoo.isin(done)]
    log(f"prices: 대상 {len(jobs):,}개, 남은 {len(todo):,}개")
    t0 = time.time()
    try:
        for i, r in enumerate(todo.itertuples(), 1):
            check_memory()
            if time_up():
                log(f"TIME: --max-minutes 도달, {i - 1}/{len(todo)}에서 종료 (다시 실행하면 이어서)")
                finished = False
                break
            rec = {"cik": r.cik, "ticker": r.ticker, "yahoo": r.yahoo}
            try:
                payload = http_get_json(URL.format(ticker=r.yahoo))
                df = parse_chart(payload)
                append_csv(SPLITS, parse_splits(payload, r.yahoo))  # 가격 파일보다 먼저: 중단돼도 분할이 빠지지 않게
                df.to_csv(PRICES / f"{r.yahoo}.csv", index=False)
                rec.update(status="ok", rows=len(df), start=df.date.iloc[0], end=df.date.iloc[-1])
            except Exception as e:  # noqa: BLE001 - 실패는 기록 후 계속
                rec.update(status="fail", error=f"{type(e).__name__}: {e}"[:200])
            append_csv(MANIFEST, [rec])
            if i % 25 == 0 or rec["status"] != "ok":
                log(f"[{i}/{len(todo)}] {r.yahoo}: {rec['status']} {rec.get('error', '')}  ({time.time() - t0:.0f}s)")
            time.sleep(random.uniform(1.0, 1.5))
    except LowMemory as e:
        log(f"STOP: {e}. 다시 실행하면 이어서 진행")
        return 2
    finally:
        # 재시도로 생긴 중복 정리: 티커별 마지막 기록만 남김
        if MANIFEST.exists():
            pd.read_csv(MANIFEST).drop_duplicates("yahoo", keep="last").to_csv(MANIFEST, index=False)
        if SPLITS.exists():
            pd.read_csv(SPLITS).drop_duplicates().to_csv(SPLITS, index=False)
    m = pd.read_csv(MANIFEST)
    log(f"prices: ok {(m.status == 'ok').sum():,} / fail {(m.status == 'fail').sum():,}")
    return 0 if finished else 3


if __name__ == "__main__":
    sys.exit(main())
