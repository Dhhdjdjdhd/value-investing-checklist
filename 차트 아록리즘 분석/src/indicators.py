"""기술적 지표. 모든 함수는 해당 일 종가까지의 정보만 사용(룩어헤드 없음)."""
import numpy as np
import pandas as pd


def sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = (100 - 100 / (1 + rs)).fillna(100.0)
    out[(up == 0) & (dn == 0)] = 50.0  # 변화 없는 구간(거래정지 등)은 중립
    return out.where(up.notna())


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(close, n=20, k=2.0):
    m = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    return m - k * sd, m, m + k * sd


def macd(close, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, sig)


def streak(close):
    """연속 상승(+)/하락(-) 일수."""
    sgn = np.sign(close.diff()).fillna(0)
    grp = (sgn != sgn.shift()).cumsum()
    return sgn * sgn.groupby(grp).cumcount().add(1)


def ibs(df):
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return (df["close"] - df["low"]) / rng
