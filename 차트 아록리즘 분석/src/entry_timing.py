"""진입 타이밍 보조 효과: '이미 사기로 정한 종목'을 바로 살 것인가, 과매도 신호를 최대 N일 기다릴 것인가.

매월 첫 거래일을 '매수 결정일'로 보고 종목마다:
  (a) 즉시: 다음날 시가 매수
  (b) 대기: N거래일 안에 신호가 나오면 그 다음날 시가, 없으면 N+1일째 시가 매수
두 진입가의 차이(b/a - 1)와, 결정일 기준 60거래일 뒤 종가까지의 수익 차이를 측정.

실행: py src/entry_timing.py
"""
import numpy as np
import pandas as pd

from common import IS_END, OOS_START, RESULTS, load_all, market_of
from indicators import rsi

SIGNALS = {
    "rsi2<10": lambda df: rsi(df["close"], 2) < 10,
    "down3": lambda df: (df["close"].diff() < 0).rolling(3).sum() == 3,
}
WAITS = (5, 10, 20)
H = 60


def run(data):
    rows = []
    for tk, df in data.items():
        o, c = df["open"].values, df["close"].values
        n = len(df)
        first = df.index.to_series().groupby(df.index.to_period("M")).min()
        dec = df.index.get_indexer(first.values)
        sigs = {k: f(df).fillna(False).values for k, f in SIGNALS.items()}
        for d in dec:
            if d < 250 or d + max(WAITS) + 2 >= n or d + H >= n:
                continue
            base_px = o[d + 1]
            row = {"ticker": tk, "date": df.index[d], "market": market_of(tk)}
            for k, s in sigs.items():
                for w in WAITS:
                    hit = np.flatnonzero(s[d + 1:d + 1 + w])
                    e = d + 1 + hit[0] + 1 if len(hit) else d + 1 + w
                    row[f"{k}|{w}"] = o[e] / base_px - 1  # 진입가 차이(음수 = 더 싸게 삼)
                    row[f"{k}|{w}|hit"] = len(hit) > 0
            row["fwd"] = c[d + H] / base_px - 1
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    data = {t: d for t, d in load_all().items()}
    r = run(data)
    r["period"] = np.where(r.date <= IS_END, "IS", "OOS")
    out = []
    for (mk, per), g in r.groupby(["market", "period"]):
        for k in SIGNALS:
            for w in WAITS:
                col = f"{k}|{w}"
                v = g[col]
                m = g.groupby(g.date.dt.to_period("M"))[col].mean()
                out.append({
                    "market": mk, "period": per, "signal": k, "wait": w, "n": len(v),
                    "hit_rate": g[f"{col}|hit"].mean(),
                    "mean_px_diff": v.mean(), "median_px_diff": v.median(),
                    "pct_cheaper": (v < 0).mean(),
                    "t_month": m.mean() / m.std(ddof=1) * np.sqrt(len(m)),
                })
    res = pd.DataFrame(out)
    res.to_csv(RESULTS / "entry_timing.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(res.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
