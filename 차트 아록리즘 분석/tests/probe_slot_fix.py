import heapq
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import common  # noqa: E402
from strategy import Rule, portfolio, run_trades, stats  # noqa: E402

data = common.load_all()
rule = Rule("rsi2", entry=lambda d, f, p: p["rsi2_lt10"], exit=lambda d, f, p: d["close"] > f["sma20"],
            max_hold=10, stop_atr=1.0, score=lambda d, f, p: f["rsi2"])
tr = run_trades(data, rule)
tr = tr[tr.entry_date >= common.OOS_START].sort_values(["entry_date", "score"])
opx = np.array([data[r.ticker]["open"].iloc[r.xi] for r in tr.itertuples()])
# 장중 손절은 그날 시가에 아직 보유 중 -> 슬롯은 다음 거래일부터 비는 것으로 처리
release_key = np.where((tr.why.values == "stop") & (tr.exit_px.values != opx), 1, 0)


def fixed_alloc(K):
    heap, keep = [], np.zeros(len(tr), bool)
    eds, xds = tr.entry_date.values, tr.exit_date.values
    for j in range(len(tr)):
        while heap and (heap[0][0] < eds[j] or (heap[0][0] == eds[j] and heap[0][1] == 0)):
            heapq.heappop(heap)
        if len(heap) < K:
            heapq.heappush(heap, (xds[j], release_key[j]))
            keep[j] = True
    return tr[keep]


for K in (1, 10):
    d0, t0 = portfolio(data, tr, K=K, start=common.OOS_START)
    d1, t1 = portfolio(data, fixed_alloc(K), K=K, start=common.OOS_START)
    s0, s1 = stats(d0, t0), stats(d1, t1)
    print(f"K={K} 현재: trades={s0['trades']} CAGR={s0['CAGR']:.2%} MDD={s0['MDD']:.2%} Sharpe={s0['Sharpe']:.2f}")
    print(f"K={K} 수정: trades={s1['trades']} CAGR={s1['CAGR']:.2%} MDD={s1['MDD']:.2%} Sharpe={s1['Sharpe']:.2f}")

