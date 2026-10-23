"""IS 1위 규칙 + 대표 규칙에 대한 견고성 검증 실행.

- 무작위 진입 몬테카를로(IS/OOS 각각)
- 비용 민감도(OOS)
- 슬롯 K 민감도(OOS)
- 연도별 수익(전체 기간) vs 동일비중 B&H

실행: py src/run_robustness.py   (strategy_search.py 실행 후)
산출: results/robust_*.csv
"""
import pandas as pd

from common import IS_END, OOS_START, RESULTS, load_all, market_of
from robustness import cost_sensitivity, k_sensitivity, random_entry_mc, yearly
from strategy import portfolio, run_trades, stats
from strategy_search import make_rules

START = pd.Timestamp("1994-01-01")


def main():
    data = {t: d for t, d in load_all().items() if market_of(t) == "US"}
    grid = pd.read_csv(RESULTS / "strategy_grid.csv")
    grid = grid[~grid.rule.str.startswith("BENCH")]
    names = [grid.nlargest(1, "Sharpe").rule.iloc[0], "rsi2<10|up200|close>sma5|stop=None"]
    rules = {r.name: r for r in make_rules()}
    ew = pd.DataFrame({t: d["close"].pct_change() for t, d in data.items()}).loc[START:].mean(axis=1).fillna(0)

    mc_rows, cost_rows, k_rows, yr = [], [], [], {"EW buy&hold": yearly(ew)}
    for nm in dict.fromkeys(names):
        rule = rules[nm]
        tr = run_trades(data, rule)
        for per, s, e in (("IS", START, IS_END), ("OOS", OOS_START, None)):
            _, tk = portfolio(data, tr, K=10, start=s, end=e)
            mc_rows.append({"rule": nm, "period": per, **random_entry_mc(data, tk, s, e, n_sim=300)})
            print(mc_rows[-1], flush=True)
        c = cost_sensitivity(data, rule, OOS_START, None)
        c.insert(0, "rule", nm)
        cost_rows.append(c)
        k = k_sensitivity(data, tr, OOS_START, None)
        k.insert(0, "rule", nm)
        k_rows.append(k)
        d, _ = portfolio(data, tr, K=10, start=START)
        yr[nm] = yearly(d)
    pd.DataFrame(mc_rows).to_csv(RESULTS / "robust_mc.csv", index=False, encoding="utf-8-sig")
    pd.concat(cost_rows).to_csv(RESULTS / "robust_cost.csv", index=False, encoding="utf-8-sig")
    pd.concat(k_rows).to_csv(RESULTS / "robust_k.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(yr).to_csv(RESULTS / "robust_yearly.csv", encoding="utf-8-sig")
    print("done", flush=True)


if __name__ == "__main__":
    main()
