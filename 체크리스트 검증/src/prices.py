"""주가·시가총액.

- Yahoo 'close'는 분할 반영(현재 기준), 'adj_close'는 분할+배당 반영.
- 원래 주가(raw) = close × (그 날 이후 일어난 분할 비율의 곱)
- 시가총액(t) = raw(t) × 표지 주식수(기준일 ≤ t 인 최신값) × (표지 기준일~t 사이 분할 비율 곱)
"""
import numpy as np
import pandas as pd

from fundamentals import DATA

PR = DATA / "prices"


def load_companies():
    c = pd.read_csv(DATA / "sec" / "companies.csv", dtype={"cik": int})
    c["ticker"] = c["tickers"].fillna("").str.split(";").str[0].str.replace(".", "-", regex=False)
    return c


def load_splits():
    p = PR / "splits.csv"
    if not p.exists():
        return pd.DataFrame(columns=["ticker", "date", "ratio"])
    s = pd.read_csv(p, parse_dates=["date"])
    s["ratio"] = s["numerator"] / s["denominator"]
    return s[s.ratio > 0]


WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def load_price(ticker):
    if ticker.upper() in WIN_RESERVED:  # 윈도우 예약 장치명: 파일 대신 콘솔을 열어 영원히 대기함
        return None
    p = PR / f"{ticker}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["close", "adj_close"])
    return df[(df.close > 0) & (df.adj_close > 0)]


def raw_close(df, splits_tk):
    """분할 이전 실제 주가로 복원."""
    f = pd.Series(1.0, index=df.index)
    for d, r in zip(splits_tk.date, splits_tk.ratio):
        f[df.index < d] *= r
    return df["close"] * f


def cover_shares(facts):
    """표지 주식수. companyfacts(filed·accn 있음)면 같은 공시 안의 같은 기준일 값(클래스별)을 합산하고,
    여러 공시에 같은 기준일이 있으면 최초 공시 것을 쓴다."""
    cs = facts[facts.concept.eq("EntityCommonStockSharesOutstanding")].copy()
    cs["end"] = pd.to_datetime(cs["end"])
    if "filed" in cs.columns:
        cs = cs.groupby(["cik", "accn", "end"], as_index=False).agg(val=("val", "sum"), filed=("filed", "min"))
        cs = cs.sort_values("filed").drop_duplicates(["cik", "end"], keep="first")
    return cs[["cik", "end", "val"]].sort_values(["cik", "end"]).drop_duplicates(["cik", "end"], keep="last")


def mcap_series(raw, cover_cik, splits_tk):
    """일별 시가총액. 표지 주식수를 기준일 이후 분할로 보정해 이어붙임."""
    if cover_cik.empty:
        return pd.Series(np.nan, index=raw.index)
    sh = pd.Series(cover_cik.val.values, index=cover_cik.end.values).sort_index()
    sh = sh[~sh.index.duplicated(keep="last")]
    asof = sh.reindex(raw.index, method="ffill")
    base_date = pd.Series(sh.index, index=sh.index).reindex(raw.index, method="ffill")
    adj = pd.Series(1.0, index=raw.index)
    for d, r in zip(splits_tk.date, splits_tk.ratio):
        m = (base_date < d) & (raw.index >= d)
        adj[m] *= r
    # 표지 주식수가 18개월 넘게 갱신 안 되면 신뢰하지 않음
    stale = (raw.index.to_series() - base_date).dt.days > 550
    out = raw * asof * adj
    out[stale.values] = np.nan
    return out
