"""완충(보유 종목은 순위 buffer×N 안이면 유지) × 점검 주기 격자, N=20 + 재작성 데이터(last) 확인.

실행: py src/buffer.py -> results/robust_buffer.csv, results/robust_lastmode.csv
"""
import pandas as pd

from optimize import RES, Runner
from robust import CAND, split_perf


def main():
    R = Runner("first")
    rows = []
    for buf in (None, 1.5, 2.0):
        for rb in (3, 6, 12):
            r, log, _ = R.run(f"buf{buf} R{rb}", S={**CAND, "rebalance": rb, "buffer": buf}, group="buffer")
            yrs = len(r) / 12
            rows.append({"buffer": buf, "rebal": rb, **split_perf(r),
                         "buys_per_yr": (log.act == "buy").sum() / yrs, "turnover_pct_yr": (log.act == "buy").sum() / yrs / 20})
    d = pd.DataFrame(rows)
    d.to_csv(RES / "robust_buffer.csv", index=False, encoding="utf-8-sig")
    print(d[["buffer", "rebal", "ALL_CAGR", "ALL_Sharpe", "ALL_MDD", "IS_Sharpe", "OOS_Sharpe", "turnover_pct_yr"]].round(3).to_string(index=False))
    best = d.sort_values("IS_Sharpe", ascending=False).iloc[0]  # 선택은 학습 구간으로만
    print("IS 기준 선택:", best.buffer, best.rebal)
    final = {**CAND, "rebalance": int(best.rebal), "buffer": None if pd.isna(best.buffer) else float(best.buffer)}
    L = Runner("last")
    out = []
    r, _, _ = L.run("final last", S=final, group="data")
    out.append({"mode": "last", "rule": "final", **split_perf(r)})
    r, _, _ = L.run("doc last", group="data")
    out.append({"mode": "last", "rule": "doc", **split_perf(r)})
    pd.DataFrame(out).to_csv(RES / "robust_lastmode.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(out)[["rule", "ALL_CAGR", "ALL_Sharpe", "IS_Sharpe", "OOS_Sharpe"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
