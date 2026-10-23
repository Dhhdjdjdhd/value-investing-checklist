"""사건연구: 패턴 발생 후 h일 보유 수익을 무조건부 기준선과 비교.

수익 정의: 신호일 t 종가 판정 -> t+1 시가 매수 -> t+h 종가 매도, 왕복 비용 차감.
기준선: 같은 종목·같은 기간(IS/OOS)의 모든 날에 같은 방식으로 진입했을 때의 평균.
t-통계: 진입월별로 초과수익을 평균낸 뒤 월 단위 t (같은 날 동시다발 신호의 상관을 완화).

실행: py src/event_study.py
"""
import sys

import numpy as np
import pandas as pd

from common import COST, IS_END, RESULTS, load_all, market_of
from patterns import FILTERS, build_features, pattern_table

HORIZONS = [1, 5, 10, 20]


def build_panel(data):
    frames = []
    for t, df in data.items():
        f = build_features(df)
        pt = pattern_table(df, f)
        flt = pd.DataFrame({k: fn(f) for k, fn in FILTERS.items()}).add_prefix("F_")
        x = pd.concat([pt, flt], axis=1)
        entry = df["open"].shift(-1)
        for h in HORIZONS:
            x[f"r{h}"] = df["close"].shift(-h) / entry - 1 - 2 * COST
        x["ticker"] = t
        x["market"] = market_of(t)
        x["period"] = np.where(x.index <= IS_END, "IS", "OOS")
        x = x.dropna(subset=[f"r{h}" for h in HORIZONS])
        # 기준선 대비 초과수익(종목·기간별 평균 차감)
        for h in HORIZONS:
            x[f"x{h}"] = x[f"r{h}"] - x.groupby("period")[f"r{h}"].transform("mean")
        frames.append(x.reset_index(names="date"))
    return pd.concat(frames, ignore_index=True)


def month_t(dates, vals):
    m = pd.Series(vals.values, index=pd.DatetimeIndex(dates.values).to_period("M")).groupby(level=0).mean()
    if len(m) < 6 or m.std(ddof=1) == 0:
        return np.nan
    return m.mean() / m.std(ddof=1) * np.sqrt(len(m))


def summarize(panel, pattern_cols):
    rows = []
    groups = {
        ("ALL", p): panel[panel.period == p] for p in ("IS", "OOS")
    }
    for mk in ("US", "KR"):
        for p in ("IS", "OOS"):
            groups[(mk, p)] = panel[(panel.market == mk) & (panel.period == p)]
    for (mk, per), g in groups.items():
        if g.empty:
            continue
        for fl in FILTERS:
            gf = g[g[f"F_{fl}"]]
            # 필터 조건부 기준선: 같은 필터 상태의 날 평균을 종목별로 차감 (필터 자체 효과 분리)
            xf = {h: gf[f"r{h}"] - gf.groupby("ticker")[f"r{h}"].transform("mean") for h in HORIZONS}
            for pat in pattern_cols:
                ev = gf[gf[pat]]
                if len(ev) < 30:
                    continue
                for h in HORIZONS:
                    r, xr = ev[f"r{h}"], ev[f"x{h}"]
                    xfr = xf[h][gf[pat]]
                    tk = ev.groupby("ticker")[f"x{h}"].agg(["mean", "size"])
                    tk = tk[tk["size"] >= 5]
                    rows.append({
                        "market": mk, "period": per, "filter": fl, "pattern": pat, "h": h,
                        "n": len(ev), "n_tickers": ev.ticker.nunique(),
                        "mean": r.mean(), "win": (r > 0).mean(),
                        "base_mean": g[f"r{h}"].mean(), "base_win": (g[f"r{h}"] > 0).mean(),
                        "excess": xr.mean(), "t": month_t(ev["date"], xr),
                        "base_f_mean": gf[f"r{h}"].mean(), "base_f_win": (gf[f"r{h}"] > 0).mean(),
                        "excess_f": xfr.mean(), "t_f": month_t(ev["date"], xfr),
                        "pct_tk_pos": (tk["mean"] > 0).mean() if len(tk) else np.nan,
                    })
    return pd.DataFrame(rows)


def main():
    data = load_all()
    print(f"loaded {len(data)} tickers")
    panel = build_panel(data)
    pattern_cols = list(pattern_table(next(iter(data.values()))).columns)
    panel.to_parquet(RESULTS / "panel.parquet")
    res = summarize(panel, pattern_cols)
    res.to_csv(RESULTS / "event_study.csv", index=False, encoding="utf-8-sig")
    print(f"rows: {len(res)} -> {RESULTS / 'event_study.csv'}")


if __name__ == "__main__":
    sys.exit(main())
