"""전략 파라미터 탐색: 학습구간(IS, ~2014)에서만 순위를 매기고, 상위 규칙을 OOS(2015~)에서 1회 검증.

실행: py src/strategy_search.py
산출: results/strategy_grid.csv, results/strategy_oos.csv
"""
import itertools

import numpy as np
import pandas as pd

from common import IS_END, OOS_START, RESULTS, load_all, market_of
from indicators import rsi, sma
from strategy import Rule, portfolio, run_trades, stats

K = 10


def entry_family():
    E = {}
    for th in (5, 10, 15, 25):
        E[f"rsi2<{th}"] = (lambda th: lambda df, f, pt: f["rsi2"] < th)(th)
    E["close_10d_low"] = lambda df, f, pt: pt["close_10d_low"]
    E["down3"] = lambda df, f, pt: pt["down3"]
    E["ibs<0.2&down"] = lambda df, f, pt: (f["ibs"] < 0.2) & (f["ret1"] < 0)
    E["bb_lower_break"] = lambda df, f, pt: pt["bb_lower_break"]
    E["donchian20_breakdown"] = lambda df, f, pt: pt["donchian20_breakdown"]
    return E


FILTERS = {
    "all": lambda f: pd.Series(True, index=f.index),
    "up200": lambda f: f["above200"].fillna(False),
}

EXITS = {
    "close>sma5": (lambda df, f, pt: df["close"] > sma(df["close"], 5), 10),
    "rsi2>70": (lambda df, f, pt: f["rsi2"] > 70, 10),
    "up_close": (lambda df, f, pt: df["close"] > df["close"].shift(), 10),
    "hold5": (lambda df, f, pt: pd.Series(False, index=df.index), 5),
}

STOPS = [None, 3.0]


def make_rules():
    rules = []
    for (en, ef), (fn, ff), (xn, (xf, mh)), st in itertools.product(entry_family().items(), FILTERS.items(), EXITS.items(), STOPS):
        rules.append(Rule(
            name=f"{en}|{fn}|{xn}|stop={st}",
            entry=(lambda ef, ff: lambda df, f, pt: ef(df, f, pt) & ff(f))(ef, ff),
            exit=xf, max_hold=mh, stop_atr=st,
            score=lambda df, f, pt: f["rsi2"],
        ))
    return rules


def evaluate(data, rules, start, end, cache):
    rows = []
    for r in rules:
        tr = run_trades(data, r, cache)
        d, tk = portfolio(data, tr, K=K, start=start, end=end)
        s = stats(d, tk)
        s["rule"] = r.name
        rows.append(s)
        print(f"{r.name:55s} CAGR={s.get('CAGR', np.nan):6.1%} MDD={s.get('MDD', np.nan):6.1%} Sh={s.get('Sharpe', np.nan):5.2f} win={s.get('win', np.nan):5.1%}")
    return pd.DataFrame(rows)


def benchmark(data, start, end):
    rows = []
    rets = pd.DataFrame({t: d["close"].pct_change() for t, d in data.items()})
    rets = rets.loc[start:end]
    ew = rets.mean(axis=1).fillna(0)
    rows.append({"rule": "BENCH equal-weight B&H", **stats(ew)})
    if "SPY" in rets:
        rows.append({"rule": "BENCH SPY B&H", **stats(rets["SPY"].dropna())})
    return pd.DataFrame(rows)


def main():
    all_data = load_all()
    data = {t: d for t, d in all_data.items() if market_of(t) == "US"}
    print(f"US tickers: {len(data)}")
    cache = {}
    rules = make_rules()
    grid = evaluate(data, rules, pd.Timestamp("1994-01-01"), IS_END, cache)
    grid = pd.concat([grid, benchmark(data, pd.Timestamp("1994-01-01"), IS_END)])
    grid.sort_values("Sharpe", ascending=False).to_csv(RESULTS / "strategy_grid.csv", index=False, encoding="utf-8-sig")

    top = grid[~grid.rule.str.startswith("BENCH")].nlargest(10, "Sharpe").rule.tolist()
    sel = [r for r in rules if r.name in top]
    oos = evaluate(data, sel, OOS_START, None, cache)
    oos = pd.concat([oos, benchmark(data, OOS_START, None)])
    oos = oos.merge(grid[["rule", "CAGR", "MDD", "Sharpe", "win"]].add_prefix("IS_").rename(columns={"IS_rule": "rule"}), on="rule", how="left")
    oos.to_csv(RESULTS / "strategy_oos.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
