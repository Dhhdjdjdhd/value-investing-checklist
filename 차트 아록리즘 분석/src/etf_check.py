"""생존편향 점검: ETF(지수 추종, 종목 교체로 생존편향 없음)만으로 주요 패턴 재측정.

실행: py src/etf_check.py  (event_study.py 실행 후)
산출: results/etf_check.csv
"""
import pandas as pd

from common import RESULTS
from event_study import month_t

ETF = "SPY QQQ DIA IWM MDY EFA EEM TLT GLD XLK XLF XLE XLV XLI XLY XLP XLU XLB 069500.KS".split()
PATTERNS = ["rsi2_lt10", "rsi2_lt5", "close_10d_low", "bb_lower_break", "down3", "down5", "new_52w_low",
            "ibs_lt0.2", "donchian20_breakdown", "rsi2_gt90", "new_52w_high", "donchian55_break", "up5"]


def main():
    p = pd.read_parquet(RESULTS / "panel.parquet")
    p = p[p.ticker.isin(ETF)]
    rows = []
    for pat in PATTERNS:
        for per in ("IS", "OOS"):
            g = p[p.period == per]
            ev = g[g[pat]]
            rows.append({
                "pattern": pat, "period": per, "n": len(ev),
                "ex5": ev.x5.mean(), "t5": month_t(ev.date, ev.x5),
                "win5": (ev.r5 > 0).mean(), "base_win5": (g.r5 > 0).mean(),
                "ex20": ev.x20.mean(), "t20": month_t(ev.date, ev.x20),
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "etf_check.csv", index=False, encoding="utf-8-sig")
    print(out.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
