"""2단계: 후보 규칙(품질 관문 + qv 순위 상위 N, k개월 재구성)의 견고성 점검.

- 이웃 파라미터: N ∈ {10,15,20,25,30}, 재구성 ∈ {1,2,3,6,12}개월
- 비용: 편도 0.1% / 0.3%
- 연도별 수익 vs SPY·EW, 블록 부트스트랩으로 SPY 대비 초과 Sharpe의 신뢰구간
- 데이터 버전: first(시점 정확) vs last(재작성 반영)
실행: py src/robust.py  -> results/robust_*.csv
"""
import numpy as np
import pandas as pd

from backtest import perf
from optimize import IS, OOS, RES, Runner, ew_universe, spy_monthly

CAND = {"use_price": None, "rank": "qv", "slots": 20, "rebalance": 3, "swap_gap": None}
DOC = {}


def split_perf(r):
    out = {}
    for tag, (a, b) in (("IS", IS), ("OOS", OOS), ("ALL", (IS[0], None))):
        rr = r[(r.index >= pd.Period(a, "M")) & ((r.index <= pd.Period(b, "M")) if b else True)]
        out.update({f"{tag}_{k}": v for k, v in perf(rr).items()})
    return out


def boot_sharpe_diff(a, b, n=2000, block=6, seed=0):
    """월 수익 a, b의 Sharpe 차이에 대한 블록 부트스트랩 90% 구간."""
    rng = np.random.default_rng(seed)
    x = pd.concat([a, b], axis=1).dropna().values
    T = len(x)
    diffs = []
    for _ in range(n):
        idx = np.concatenate([np.arange(s, s + block) % T for s in rng.integers(0, T, T // block + 1)])[:T]
        y = x[idx]
        sa = y[:, 0].mean() / y[:, 0].std() * np.sqrt(12)
        sb = y[:, 1].mean() / y[:, 1].std() * np.sqrt(12)
        diffs.append(sa - sb)
    return np.percentile(diffs, [5, 50, 95]), (np.array(diffs) > 0).mean()


def main():
    R = Runner("first")
    spy = spy_monthly()
    ew = ew_universe(R.mc, R.tri)
    rows = []
    series = {}
    # 이웃 파라미터 격자
    for n in (10, 15, 20, 25, 30):
        for rb in (1, 2, 3, 6, 12):
            r, _, _ = R.run(f"qv N{n} R{rb}", S={**CAND, "slots": n, "rebalance": rb}, group="grid")
            rows.append({"N": n, "rebal": rb, **split_perf(r)})
            series[(n, rb)] = r
    pd.DataFrame(rows).to_csv(RES / "robust_grid.csv", index=False, encoding="utf-8-sig")
    # 비용
    crow = []
    for c in (0.001, 0.003):
        r, log, _ = R.run(f"qv N20 R3 cost{c}", S={**CAND, "cost": c}, group="cost")
        crow.append({"cost": c, **split_perf(r), "trades_per_yr": (log.act == "buy").sum() / (len(r) / 12)})
        r2, _, _ = R.run(f"doc cost{c}", S={"cost": c}, group="cost")
        crow.append({"cost": c, "rule": "doc", **split_perf(r2)})
    pd.DataFrame(crow).to_csv(RES / "robust_cost.csv", index=False, encoding="utf-8-sig")
    # 연도별 + 부트스트랩
    cand = series[(20, 3)]
    doc, _, _ = R.run("문서 규칙", S=DOC, group="year")
    qual, _, _ = R.run("품질만 전부", S={"use_price": None, "slots": 1000, "swap_gap": None}, group="year")
    yr = pd.DataFrame({"후보(qv N20 R3)": cand, "문서 규칙": doc, "품질만 전부": qual, "SPY": spy, "EW 대형주": ew})
    yr = yr[yr.index >= pd.Period(IS[0], "M")].dropna(how="all")
    annual = yr.groupby(yr.index.year).apply(lambda d: (1 + d).prod() - 1)
    annual.to_csv(RES / "robust_yearly.csv", encoding="utf-8-sig")
    yr.to_csv(RES / "robust_monthly.csv", encoding="utf-8-sig")
    brow = []
    for nm in ("후보(qv N20 R3)", "문서 규칙", "품질만 전부"):
        for bn in ("SPY", "EW 대형주"):
            for tag, (a, b) in (("IS", IS), ("OOS", OOS), ("ALL", (IS[0], None))):
                sub = yr[(yr.index >= pd.Period(a, "M")) & ((yr.index <= pd.Period(b, "M")) if b else True)]
                ci, p = boot_sharpe_diff(sub[nm], sub[bn])
                ex = (sub[nm] - sub[bn]).dropna()
                brow.append({"전략": nm, "비교": bn, "구간": tag, "Sharpe차 5%": ci[0], "중앙": ci[1], "95%": ci[2],
                             "P(차>0)": p, "월초과 평균": ex.mean(), "월초과 t": ex.mean() / ex.std() * np.sqrt(len(ex)),
                             "이긴 해 비율": (annual[nm] > annual[bn]).mean() if tag == "ALL" else np.nan})
    pd.DataFrame(brow).to_csv(RES / "robust_boot.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(brow).round(3).to_string(index=False))
    # 재작성 데이터(last)로 같은 규칙
    print(annual.round(3).to_string())


if __name__ == "__main__":
    main()
