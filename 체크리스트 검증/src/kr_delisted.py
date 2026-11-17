"""상장폐지 종목 중 백테스트 대상 선별 -> data/kr/delisted_targets.csv

2016년 이후 거래가 있었던 상장폐지(E) 종목마다 폐지 직전 회계연도의 주식수(DART 1건)를 받아
2016년 이후 월말 종가 최고치 × 주식수 ≥ 2천억 원이면 대상에 넣는다(시총 하한 후보 3천억보다 여유).
코스피·코스닥 구분은 할 수 없어 둘 다 포함한다(보수적: 생존편향을 줄이는 쪽).
실행: py src/kr_delisted.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kr_fetch_dart as kd  # noqa: E402
from kr_fundamentals import KR, shares_from  # noqa: E402

MIN_CAP = 2e11


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    kd.KEY = kd.api_key()
    comp = pd.read_csv(KR / "companies.csv", dtype=str)
    rows = []
    try:
        for r in comp[comp.corp_cls == "E"].itertuples():
            p = KR / "prices" / "naver" / f"{r.stock_code}.csv"
            if not p.exists():
                continue
            d = pd.read_csv(p, parse_dates=["date"])
            d = d[d.date >= "2016-01-01"]
            if d.empty:
                continue
            last = d.date.iloc[-1]
            fy = last.year - 1 if last.month >= 4 else last.year - 2  # 폐지 전에 사업보고서가 나온 마지막 해
            fy = max(fy, 2016)
            sp = kd.DART / r.corp_code / f"{fy}_sh.json"
            if not sp.exists():
                kd.save(sp, kd.call("stockTotqySttus.json", corp_code=r.corp_code, bsns_year=fy, reprt_code="11011"))
            _, tot = shares_from(sp)
            hi = d.set_index("date").close.resample("ME").last().max()
            rows.append({"corp_code": r.corp_code, "stock_code": r.stock_code, "name": r.name, "last": last.date(),
                         "fy": fy, "shares": tot, "max_cap": hi * tot if tot == tot else None})
    except kd.Stop as e:
        print("중단:", e)
    x = pd.DataFrame(rows)
    x.to_csv(KR / "delisted_screen.csv", index=False, encoding="utf-8-sig")
    t = x[x.max_cap >= MIN_CAP]
    t.to_csv(KR / "delisted_targets.csv", index=False, encoding="utf-8-sig")
    print(f"후보 {len(x)} / 주식수 없음 {x.shares.isna().sum()} / 대상(최고 시총 ≥ 2천억) {len(t)}")
    print(t.sort_values("max_cap", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
