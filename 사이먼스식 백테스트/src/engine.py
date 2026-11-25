"""공통 엔진 (부록_W1 §2~§5). 모든 배열은 날짜×종목 numpy, 유니버스 밖은 NaN/0."""
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "data" / "S_panel_slim.pkl"
LEARN = ("2003-01-01", "2015-12-31")
VALID = ("2016-01-01", "2026-10-31")
SIGNALS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
SHORT_SET = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S12"]
BORROW = 0.005
SEED = 20261122


def load_panel(path=PANEL):
    with open(path, "rb") as fh:
        return pickle.load(fh)


class Ctx:
    """패널에서 자주 쓰는 배열을 꺼내 둔다."""

    def __init__(self, P):
        self.dates = P["close"].index
        self.tickers = P["close"].columns
        self.U = P["universe"].values
        sec = P["sector"].reindex(self.tickers)
        self.sec_names = sorted(sec.unique())
        self.sec_idx = [np.where(sec.values == s)[0] for s in self.sec_names]
        self.r = P["ret_cc"].values.astype(float)
        self.r0 = np.nan_to_num(self.r)
        self.roc = P["ret_oc"].values.astype(float)
        self.P = P

    def sl(self, a, b):
        return (self.dates >= a) & (self.dates <= b)


# ---------- 횡단면 도구 ----------
def sector_demean(X, ctx):
    """유니버스 안 값에서 섹터 평균을 뺀다. NaN은 유지."""
    out = np.full_like(X, np.nan, dtype=float)
    for idx in ctx.sec_idx:
        sub = X[:, idx]
        with np.errstate(invalid="ignore"):
            m = np.nanmean(sub, axis=1, keepdims=True) if sub.size else 0
        out[:, idx] = sub - m
    return out


def rank_z(X):
    """행별 순위(동순위 평균) → 평균 0, 표준편차 1. NaN은 0."""
    df = pd.DataFrame(X)
    rk = df.rank(axis=1, method="average")
    mu = rk.mean(axis=1)
    sd = rk.std(axis=1, ddof=0).replace(0, np.nan)
    z = rk.sub(mu, axis=0).div(sd, axis=0)
    return z.fillna(0.0).values


def zscore_signal(raw, ctx, sector_neutral=True):
    X = np.where(ctx.U, raw, np.nan)
    if sector_neutral:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            X = sector_demean(X, ctx)
    return rank_z(X)


# ---------- 신호 ----------
def raw_signals(P):
    close, opn, high, low = (P[k].astype(float) for k in ["close", "open", "high", "low"])
    adj, vol, r = P["adj_close"], P["volume"].astype(float), P["ret_cc"]
    U = P["universe"]
    sec = P["sector"].reindex(close.columns)
    r5 = adj / adj.shift(5) - 1
    r21 = adj / adj.shift(21) - 1
    vavg = vol.shift(1).rolling(60, min_periods=40).mean()

    def sec_mean(X):
        Xu = X.where(U)
        out = pd.DataFrame(np.nan, index=X.index, columns=X.columns)
        for s in sec.unique():
            c = sec.index[sec == s]
            out[c] = np.repeat(Xu[c].mean(axis=1).values[:, None], len(c), axis=1)
        return out

    S = {}
    S["S1"] = -r
    S["S2"] = -r5
    S["S3"] = -(close / opn - 1)
    S["S4"] = opn / close.shift(1) - 1
    S["S5"] = -(r5 - sec_mean(r5))
    with np.errstate(divide="ignore", invalid="ignore"):
        S["S6"] = np.log(vol / vavg).replace([np.inf, -np.inf], np.nan)
    S["S7"] = (-r).where(vol < vavg, 0.0).where(r.notna() & vavg.notna())
    S["S8"] = adj.shift(21) / adj.shift(252) - 1
    S["S9"] = sec_mean(r21)
    S["S10"] = -r.rolling(60, min_periods=40).std()
    S["S11"] = adj / adj.rolling(252, min_periods=200).max()
    rng = (high - low)
    S["S12"] = -((close - (high + low) / 2) / rng.where(rng > 0))
    return S


def all_z(P, ctx):
    raw = raw_signals(P)
    out = {}
    for k in SIGNALS:
        out[k] = zscore_signal(raw.pop(k).values.astype(float), ctx, sector_neutral=(k != "S9")).astype(np.float32)
    return out


# ---------- 포트폴리오 ----------
def target_weights(score, ctx, sector_neutral=True, cap=0.01):
    X = np.where(ctx.U, score, np.nan)
    rk = pd.DataFrame(X).rank(axis=1, method="average").values
    if sector_neutral:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rk = sector_demean(rk, ctx)
    rk = rk - np.nanmean(np.where(ctx.U, rk, np.nan), axis=1, keepdims=True)
    w = np.nan_to_num(rk)
    for _ in range(3):
        pos = np.clip(w, 0, None)
        neg = np.clip(w, None, 0)
        ps = pos.sum(axis=1, keepdims=True)
        ns = -neg.sum(axis=1, keepdims=True)
        w = 0.5 * pos / np.where(ps > 0, ps, 1) + 0.5 * neg / np.where(ns > 0, ns, 1)
        w = np.clip(w, -cap, cap)
    return w


def smooth(target, lam):
    if lam >= 1.0:
        return target.copy()
    w = np.zeros_like(target)
    prev = np.zeros(target.shape[1])
    for t in range(target.shape[0]):
        cur = (1 - lam) * prev + lam * target[t]
        g = np.abs(cur).sum()
        if g > 0:
            cur = cur / g
        w[t] = cur
        prev = cur
    return w


def simulate(w, ctx, fill="close"):
    """w[t]: t일 종가 신호의 비중. 돌려주는 것: 일간 비용 전 수익, 거래 금액, 롱/숏 손익, 숏 총액.
    fill: 'close'(t+1 종가, 기본) / 'open'(t+1 시가) / 'nodelay'(t 종가, 불가능한 참고)."""
    T = w.shape[0]
    r = ctx.r0
    z = np.zeros_like(w[:1])
    w1 = np.vstack([z, w[:-1]])           # w(d-1)
    w2 = np.vstack([z, z, w[:-2]])        # w(d-2)
    if fill == "close":
        held = w2
        gross = (held * r).sum(axis=1)
        trade = np.abs(w1 - w2 * (1 + r)).sum(axis=1)
        long_ = (np.clip(held, 0, None) * r).sum(axis=1)
    elif fill == "nodelay":
        held = w1
        gross = (held * r).sum(axis=1)
        w0 = w
        trade = np.abs(w0 - w1 * (1 + r)).sum(axis=1)
        long_ = (np.clip(held, 0, None) * r).sum(axis=1)
    elif fill == "open":
        roc = np.nan_to_num(ctx.roc)
        rco = (1 + r) / (1 + roc) - 1
        gross = (w2 * rco).sum(axis=1) + (w1 * roc).sum(axis=1)
        trade = np.abs(w1 - w2 * (1 + rco)).sum(axis=1)
        long_ = (np.clip(w2, 0, None) * rco).sum(axis=1) + (np.clip(w1, 0, None) * roc).sum(axis=1)
        held = w1
    else:
        raise ValueError(fill)
    short_gross = -np.clip(held, None, 0).sum(axis=1)
    return pd.DataFrame({"gross": gross, "trade": trade, "long": long_, "short": gross - long_,
                         "short_gross": short_gross}, index=ctx.dates)


def net(sim, bp):
    return sim["gross"] - sim["trade"] * bp / 1e4 - sim["short_gross"] * BORROW / 252


# ---------- 지표 ----------
def sharpe(x):
    x = np.asarray(x, float)
    s = x.std(ddof=1)
    return float(x.mean() / s * np.sqrt(252)) if s > 0 else np.nan


def stats(x):
    x = pd.Series(x).dropna()
    cum = x.cumsum()
    return {"sharpe": sharpe(x), "ann_ret": x.mean() * 252, "vol": x.std(ddof=1) * np.sqrt(252),
            "mdd": float((cum - cum.cummax()).min()), "n": len(x)}


def boot_p(x, block=20, n=2000, seed=SEED):
    """원형 블록 부트스트랩. P(Sharpe>0)와 Sharpe 5·50·95 분위."""
    x = np.asarray(pd.Series(x).dropna(), float)
    T = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    starts = rng.integers(0, T, size=(n, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % T
    xs = x[idx.reshape(n, -1)[:, :T]]
    sh = xs.mean(axis=1) / xs.std(axis=1, ddof=1) * np.sqrt(252)
    return float((sh > 0).mean()), [float(q) for q in np.percentile(sh, [5, 50, 95])]


def market_ret(ctx):
    """시장 대용: 유니버스(전일 기준) 거래대금 가중 수익."""
    adv = np.nan_to_num(ctx.P["adv60"].values.astype(float))
    wt = np.where(ctx.U, adv, 0.0)
    wt = wt / np.where(wt.sum(axis=1, keepdims=True) > 0, wt.sum(axis=1, keepdims=True), 1)
    w1 = np.vstack([np.zeros_like(wt[:1]), wt[:-1]])
    return pd.Series((w1 * ctx.r0).sum(axis=1), index=ctx.dates)


def beta(x, m):
    d = pd.concat([x, m], axis=1).dropna()
    c = np.cov(d.iloc[:, 0], d.iloc[:, 1])
    return float(c[0, 1] / c[1, 1])


def ic_series(z, ctx, lead):
    """z(t)와 섹터 중립 수익 r(t+lead)의 일별 스피어만 상관(유니버스 안)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rn = sector_demean(np.where(ctx.U, np.roll(ctx.r, -lead, axis=0), np.nan), ctx)
    rn[-lead:] = np.nan
    a = pd.DataFrame(np.where(ctx.U, z, np.nan)).rank(axis=1)
    b = pd.DataFrame(rn).rank(axis=1)
    ok = a.notna() & b.notna()
    a, b = a.where(ok), b.where(ok)
    a = a.sub(a.mean(axis=1), axis=0)
    b = b.sub(b.mean(axis=1), axis=0)
    ic = (a * b).sum(axis=1) / np.sqrt((a ** 2).sum(axis=1) * (b ** 2).sum(axis=1))
    return pd.Series(ic.values, index=ctx.dates)


def perf_row(sim, ctx, a, b, bps=(0, 10)):
    m = ctx.sl(a, b)
    out = {}
    for bp in bps:
        st = stats(net(sim, bp)[m])
        out[f"sharpe_{bp}bp"] = st["sharpe"]
        out[f"ret_{bp}bp"] = st["ann_ret"]
        if bp == bps[0]:
            out["vol"] = st["vol"]
        out[f"mdd_{bp}bp"] = st["mdd"]
    tr = sim["trade"][m].mean()
    out["turnover_yr"] = tr * 252
    out["hold_days"] = 2 / tr if tr > 0 else np.nan
    out["long_ret"] = sim["long"][m].mean() * 252
    out["short_ret"] = sim["short"][m].mean() * 252
    return out
