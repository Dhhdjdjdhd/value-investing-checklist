"""한국(코스피) 백테스트용 주가 수집기.

사용법 (작업 폴더 '체크리스트 검증' 기준):
    py src/kr_fetch_prices.py naver     # 현재 코스피(Y) + 상장폐지(E) 전부: 네이버 일봉(수정주가, 폐지 종목도 폐지일까지)
    py src/kr_fetch_prices.py yahoo     # 현재 코스피(Y) + 벤치마크: Yahoo 일봉(close·배당 반영 adj_close) + 분할 이력
    --refresh : 이미 받은 파일도 다시 받기

저장
- data/kr/prices/naver/{종목코드}.csv : date,open,high,low,close,volume (수정주가, 배당 미반영)
- data/kr/prices/yahoo/{종목코드}.csv : date,open,high,low,close,adj_close,volume
- data/kr/prices/yahoo/splits.csv     : code,date,numerator,denominator
- data/kr/prices/manifest.csv         : src,code,status,rows,start,end,error
"""
from __future__ import annotations

import random
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "차트 아록리즘 분석" / "src"))
sys.path.insert(0, str(ROOT / "src"))
from data_fetch import URL, http_get_json, parse_chart  # noqa: E402
from fetch_prices import parse_splits  # noqa: E402

KR = ROOT / "data" / "kr"
PRICES = KR / "prices"
MANIFEST = PRICES / "manifest.csv"
NAVER = "https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=3300&requestType=0"
# 벤치마크: KODEX 200(배당 포함 총수익 근사), 코스피200·코스피 지수
BENCH = {"069500": "069500.KS", "KS200": "^KS200", "KS11": "^KS11"}


def naver_daily(code: str) -> pd.DataFrame:
    req = urllib.request.Request(NAVER.format(code=code), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("euc-kr", errors="replace")
    rows = []
    for part in txt.split('<item data="')[1:]:
        d, o, h, l, c, v = part.split('"', 1)[0].split("|")
        rows.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "volume": int(v)})
    if not rows:
        raise ValueError("빈 응답")
    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date")


MAN_COLS = ["src", "code", "status", "rows", "start", "end", "error"]


def append_csv(path: Path, rows: list[dict]):
    if rows:  # 열 순서 고정(첫 행이 실패 기록이어도 열 개수가 같게)
        pd.DataFrame(rows).reindex(columns=MAN_COLS).to_csv(path, mode="a", header=not path.exists(), index=False,
                                                           encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    src = sys.argv[1]
    refresh = "--refresh" in sys.argv
    comp = pd.read_csv(KR / "companies.csv", dtype=str)
    if src == "naver":
        jobs = [(c, c) for c in comp[comp.corp_cls.isin(["Y", "E"])].stock_code]
    else:
        jobs = [(c, c + ".KS") for c in comp[comp.corp_cls == "Y"].stock_code] + list(BENCH.items())
    out = PRICES / src
    out.mkdir(parents=True, exist_ok=True)
    todo = [j for j in jobs if refresh or not (out / f"{j[0]}.csv").exists()]
    print(f"{src}: 대상 {len(jobs)}, 남은 {len(todo)}", flush=True)
    splits = []
    for i, (code, sym) in enumerate(todo, 1):
        rec = {"src": src, "code": code}
        try:
            if src == "naver":
                df = naver_daily(code)
            else:
                payload = http_get_json(URL.format(ticker=urllib.request.quote(sym)))
                df = parse_chart(payload)
                splits += [{"code": code, **{k: s[k] for k in ("date", "numerator", "denominator")}}
                           for s in parse_splits(payload, code)]
            df.to_csv(out / f"{code}.csv", index=False)
            rec.update(status="ok", rows=len(df), start=df.date.iloc[0], end=df.date.iloc[-1])
        except Exception as e:  # noqa: BLE001 - 실패는 기록 후 계속
            rec.update(status="fail", error=f"{type(e).__name__}: {e}"[:200])
        append_csv(MANIFEST, [rec])
        if i % 100 == 0 or rec["status"] != "ok":
            print(f"[{i}/{len(todo)}] {code}: {rec['status']} {rec.get('error', '')}", flush=True)
        time.sleep(random.uniform(0.3, 0.6) if src == "naver" else random.uniform(1.0, 1.5))
    if src == "yahoo":
        sp = out / "splits.csv"
        old = pd.read_csv(sp, dtype={"code": str}) if sp.exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(splits)]).drop_duplicates().to_csv(sp, index=False)
    m = pd.read_csv(MANIFEST, dtype={"code": str}).drop_duplicates(["src", "code"], keep="last")
    m.to_csv(MANIFEST, index=False)
    mm = m[m.src == src]
    print(f"{src}: ok {(mm.status == 'ok').sum()} / fail {(mm.status == 'fail').sum()}")


if __name__ == "__main__":
    main()
