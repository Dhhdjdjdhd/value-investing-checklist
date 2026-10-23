"""선정된 규칙의 견고성 검증.

1) 무작위 진입 몬테카를로: 같은 종목·같은 보유일수로 진입일만 무작위 -> 평균수익/승률 분포 대비 p값
2) 비용 민감도: 편도 0.05% / 0.10% / 0.20%
3) 연도별 수익, 슬롯 수(K) 민감도
"""
import numpy as np
import pandas as pd

import common
import strategy
from common import OOS_START


def random_entry_mc(data, trades, start, end=None, n_sim=500, seed=0):
    """진입일을 [start, end] 구간 안에서 무작위로 바꿨을 때의 분포."""
    rng = np.random.default_rng(seed)
    real_mean, real_win = trades.ret.mean(), (trades.ret > 0).mean()
    means, wins = np.empty(n_sim), np.empty(n_sim)
    groups = []
    for t, g in trades.groupby("ticker"):
        d = data[t]
        lo = int(d.index.searchsorted(start))
        hi_i = int(d.index.searchsorted(end, side="right")) if end is not None else len(d)
        groups.append(((d["open"].values, d["close"].values), g.days.values.astype(int), lo, hi_i))
    for s in range(n_sim):
        rs = []
        for (o, c), days, lo, hi_i in groups:
            n = len(o)
            hi = np.minimum(hi_i, n - days - 2)
            ok = hi > lo + 1
            st = np.zeros(len(days), dtype=int)
            st[ok] = rng.integers(lo, hi[ok])
            e = st + 1
            x = np.minimum(e + np.maximum(days, 0), n - 1)
            # 청산은 시가 기준(전략과 동일). 진입 당일 청산(days=0, 당일 손절)은 당일 종가로 근사
            xp = np.where(days == 0, c[e], o[x])
            r = xp / o[e] * (1 - common.COST) ** 2 - 1
            rs.append(r[ok])
        r = np.concatenate(rs)
        means[s], wins[s] = r.mean(), (r > 0).mean()
    return {
        "real_mean": real_mean, "rand_mean": means.mean(), "p_mean": (means >= real_mean).mean(),
        "real_win": real_win, "rand_win": wins.mean(), "p_win": (wins >= real_win).mean(),
    }


def cost_sensitivity(data, rule, start, end, K=10):
    out = []
    base = common.COST
    try:
        for c in (0.0005, 0.001, 0.002):
            common.COST = strategy.COST = c
            tr = strategy.run_trades(data, rule)
            d, tk = strategy.portfolio(data, tr, K=K, start=start, end=end)
            out.append({"cost_oneway": c, **strategy.stats(d, tk)})
    finally:
        common.COST = strategy.COST = base
    return pd.DataFrame(out)


def yearly(daily):
    return daily.groupby(daily.index.year).apply(lambda r: (1 + r).prod() - 1)


def k_sensitivity(data, trades, start, end, ks=(5, 10, 20)):
    rows = []
    for k in ks:
        d, tk = strategy.portfolio(data, trades, K=k, start=start, end=end)
        rows.append({"K": k, **strategy.stats(d, tk)})
    return pd.DataFrame(rows)
