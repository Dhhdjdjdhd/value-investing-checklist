"""패턴 정의. 각 패턴은 df(수정 OHLCV) -> bool Series(당일 종가 기준 신호).

신호가 True인 날 t의 종가에서 판정, 진입은 t+1 시가 (event_study 참고).
"""
import numpy as np
import pandas as pd

from indicators import atr, bollinger, ibs, macd, rsi, sma, streak


def _cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def build_features(df):
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    f = pd.DataFrame(index=df.index)
    f["ret1"] = c.pct_change()
    f["sma20"], f["sma50"], f["sma200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    f["rsi2"], f["rsi14"] = rsi(c, 2), rsi(c, 14)
    f["streak"] = streak(c)
    f["bb_lo"], _, f["bb_hi"] = bollinger(c)
    f["macd"], f["macd_sig"] = macd(c)
    f["atr14"] = atr(df)
    f["ibs"] = ibs(df)
    f["vol20"] = v.where(v > 0).rolling(20, min_periods=15).mean()  # 0거래량(휴장·결측) 행 제외
    f["hi20"] = h.rolling(20).max().shift()
    f["lo20"] = l.rolling(20).min().shift()
    f["hi55"] = h.rolling(55).max().shift()
    f["cmax252"] = c.rolling(252).max().shift()
    f["cmin252"] = c.rolling(252).min().shift()
    f["cmin10"] = c.rolling(10).min().shift()
    f["rng"] = h - l
    f["above200"] = c > f["sma200"]
    return f


def pattern_table(df, f=None):
    """모든 패턴 신호를 열로 갖는 DataFrame 반환."""
    if f is None:
        f = build_features(df)
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    pc, po, ph, pl = c.shift(), o.shift(), h.shift(), l.shift()
    body = (c - o).abs()
    hasvol = v > 0

    P = {}
    # --- 평균회귀 ---
    P["rsi2_lt10"] = f["rsi2"] < 10
    P["rsi2_lt5"] = f["rsi2"] < 5
    P["rsi2_gt90"] = f["rsi2"] > 90
    P["rsi14_lt30"] = f["rsi14"] < 30
    P["rsi14_gt70"] = f["rsi14"] > 70
    P["down3"] = f["streak"] <= -3
    P["down5"] = f["streak"] <= -5
    P["up3"] = f["streak"] >= 3
    P["up5"] = f["streak"] >= 5
    P["close_10d_low"] = c < f["cmin10"]
    P["bb_lower_break"] = c < f["bb_lo"]
    P["bb_upper_break"] = c > f["bb_hi"]
    P["ibs_lt0.2"] = f["ibs"] < 0.2
    P["ibs_gt0.8"] = f["ibs"] > 0.8
    P["drop_gt5pct"] = f["ret1"] < -0.05
    P["jump_gt5pct"] = f["ret1"] > 0.05
    P["gap_down_2pct"] = (o / pc - 1 < -0.02) & (o < pl)
    P["gap_up_2pct"] = (o / pc - 1 > 0.02) & (o > ph)
    # --- 추세/돌파 ---
    P["golden_cross"] = _cross_up(f["sma50"], f["sma200"])
    P["death_cross"] = _cross_up(f["sma200"], f["sma50"])
    P["cross_above_sma200"] = _cross_up(c, f["sma200"])
    P["cross_below_sma200"] = _cross_up(f["sma200"], c)
    P["new_52w_high"] = c > f["cmax252"]
    P["new_52w_low"] = c < f["cmin252"]
    P["donchian20_break"] = c > f["hi20"]
    P["donchian20_breakdown"] = c < f["lo20"]
    P["donchian55_break"] = c > f["hi55"]
    P["macd_cross_up"] = _cross_up(f["macd"], f["macd_sig"])
    P["macd_cross_down"] = _cross_up(f["macd_sig"], f["macd"])
    # --- 변동성 ---
    P["nr7"] = f["rng"] <= f["rng"].rolling(7).min()
    P["inside_day"] = (h < ph) & (l > pl)
    P["vol_spike_up"] = hasvol & (v > 2.5 * f["vol20"].shift()) & (c > pc)
    P["vol_spike_down"] = hasvol & (v > 2.5 * f["vol20"].shift()) & (c < pc)
    # --- 캔들 ---
    P["bull_engulf"] = (pc < po) & (c > o) & (o <= pc) & (c >= po)
    P["bear_engulf"] = (pc > po) & (c < o) & (o >= pc) & (c <= po)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    P["hammer"] = (lower_wick > 2 * body) & (upper_wick < body) & (f["streak"].shift() <= -2)
    P["shooting_star"] = (upper_wick > 2 * body) & (lower_wick < body) & (f["streak"].shift() >= 2)

    out = pd.DataFrame(P).fillna(False).astype(bool)
    # 지표가 준비되지 않은 초반 200일은 신호 없음
    out[f["sma200"].isna()] = False
    return out


FILTERS = {
    "all": lambda f: pd.Series(True, index=f.index),
    "up200": lambda f: f["above200"].fillna(False),
    "dn200": lambda f: (~f["above200"]) & f["sma200"].notna(),
}
