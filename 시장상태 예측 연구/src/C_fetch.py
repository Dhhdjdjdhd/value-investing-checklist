"""파트 C 참고 사례용 일봉 수집 (삼성전자, NVDA, ANT) — Yahoo chart v8.

실행: py -I src/C_fetch.py   -> data/C_px_{이름}.csv (date, close, adj_close)
요청 머리글에는 연구용 문자열만 넣는다(개인정보 없음).
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-script)"}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1=0&period2=9999999999&interval=1d&events=div,split"
JOBS = {"005930.KS": "samsung", "NVDA": "NVDA", "ANT": "ANT"}


def fetch(sym):
    req = urllib.request.Request(URL.format(t=sym), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    q = res["indicators"]["quote"][0]["close"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for ts, c, a in zip(res["timestamp"], q, adj):
        if c is None or a is None or c <= 0:
            continue
        d = (datetime.fromtimestamp(ts, tz=timezone.utc) + off).strftime("%Y-%m-%d")
        rows.append(f"{d},{c},{a}")
    meta = res["meta"]
    return rows, meta.get("longName") or meta.get("shortName"), meta.get("instrumentType")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    DATA.mkdir(exist_ok=True)
    for sym, nm in JOBS.items():
        try:
            rows, name, kind = fetch(sym)
            (DATA / f"C_px_{nm}.csv").write_text("date,close,adj_close\n" + "\n".join(rows) + "\n", encoding="utf-8")
            print(sym, "ok", len(rows), rows[0][:10], rows[-1][:10], "|", name, "|", kind)
        except Exception as e:  # noqa: BLE001
            print(sym, "실패:", repr(e))
        time.sleep(1.5)


if __name__ == "__main__":
    main()
