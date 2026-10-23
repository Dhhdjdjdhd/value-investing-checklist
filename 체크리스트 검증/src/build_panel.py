"""패널 생성: 연도행(재무+판정 지표+FY말 PER) / 월말 행렬(시총, 총수익 지수, 52주 고점 대비).

시가총액(t) = Yahoo close(t, 현재 분할 기준) × 오늘 기준 주식수(avail ≤ t 인 최신 연도행의 sh_adj)
실행: py src/build_panel.py [first|last]  -> data/panel/annual_{mode}.parquet, monthly_*.parquet
"""
import sys
import time

import numpy as np
import pandas as pd

from checklist import row_features
from fundamentals import DATA, build_annual_cf, excluded_sector
from prices import load_companies, load_price, load_splits

OUT = DATA / "panel"
OUT.mkdir(parents=True, exist_ok=True)
START = pd.Timestamp("2005-01-01")


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "first"
    comp = load_companies()
    comp = comp[comp.ticker.str.len() > 0].drop_duplicates("cik")
    tick = dict(zip(comp.cik, comp.ticker))
    splits = load_splits()
    ann = build_annual_cf(mode=mode, splits=splits, tickers=tick)
    log(f"annual rows {len(ann)}")
    ann = ann.merge(load_companies()[["cik", "ticker", "sic", "sicDescription"]].drop_duplicates("cik"), on="cik", how="left")
    ann["sector_excl"] = ann.sic.map(excluded_sector)
    ann_g = dict(tuple(ann.groupby("cik")))

    m_mcap, m_tri, m_dd, fy_mcap = {}, {}, {}, {}
    for j, (cik, tk) in enumerate(tick.items()):
        if cik not in ann_g:
            continue
        df = load_price(tk)
        if df is None or len(df) < 260:
            continue
        df = df[df.index >= START - pd.Timedelta(days=400)]
        a = ann_g[cik]
        sh = pd.Series(a.sh_adj.values, index=a.avail.values).dropna().sort_index()
        sh = sh[~sh.index.duplicated(keep="last")]
        if sh.empty:
            continue
        shd = sh.reindex(df.index, method="ffill")
        mc = df.close * shd
        me = df.index.to_series().groupby(df.index.to_period("M")).max()
        me = me[me >= START]
        m_mcap[cik] = pd.Series(mc.loc[me.values].values, index=me.index)
        m_tri[cik] = pd.Series(df.adj_close.loc[me.values].values, index=me.index)
        hi = df.close.rolling(252, min_periods=200).max()
        m_dd[cik] = pd.Series((df.close / hi - 1).loc[me.values].values, index=me.index)
        # 회계연도말 시총: 기말 종가 × 그 해 주식수(오늘 기준)
        k = df.index.searchsorted(a.end.values, side="right") - 1
        for idx, kk, end, s in zip(a.index, k, a.end, a.sh_adj):
            if kk >= 0 and (end - df.index[kk]).days < 10:
                fy_mcap[idx] = df.close.iloc[kk] * s
        if j % 300 == 0:
            log(f"[{j}/{len(tick)}] {tk}")
    ann["mcap_fy"] = pd.Series(fy_mcap)
    ann["per_fy"] = (ann.mcap_fy / ann.ni).where(ann.ni > 0)
    log("features...")
    feats = [row_features(g) for _, g in ann.groupby("cik")]
    ann = ann.join(pd.concat(feats))
    ann["per_hist"] = [list(g.per_fy.values[max(0, i - 9):i + 1]) for _, g in ann.groupby("cik", sort=True) for i in range(len(g))]
    ann.to_parquet(OUT / f"annual_{mode}.parquet")
    pd.DataFrame(m_mcap).to_parquet(OUT / f"monthly_mcap_{mode}.parquet")
    pd.DataFrame(m_tri).to_parquet(OUT / f"monthly_tri_{mode}.parquet")
    pd.DataFrame(m_dd).to_parquet(OUT / f"monthly_dd_{mode}.parquet")
    log(f"done rows {len(ann)} priced {len(m_mcap)}")


if __name__ == "__main__":
    sys.exit(main())
