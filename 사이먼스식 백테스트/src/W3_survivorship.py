# -*- coding: utf-8 -*-
"""W3-A: 생존편향 주입 시뮬레이션 (부록_W3.md A-2의 1, 3번)
생존 종목 가격으로 대리 전략을 돌리고, 가상의 실패 종목을 주입해 Sharpe 변화를 잰다.
실행: py -I W3_survivorship.py
"""
import os, sys, glob, pickle
import numpy as np, pandas as pd

BASE = r"E:/value-investing-checklist/사이먼스식 백테스트"
PRICES = r"E:/value-investing-checklist/체크리스트 검증/data/prices"
CACHE = os.path.join(BASE, "data", "W3_surv_panel.pkl")
OUT = os.path.join(BASE, "results", "W3_survivorship_sim.csv")
TRAIN = ("2003-01-01", "2015-12-31"); TEST = ("2016-01-01", "2026-10-31")
EXCL = {"BXSL", "MSDL"}

def load_panel():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    cl, ac, vo = {}, {}, {}
    for f in glob.glob(os.path.join(PRICES, "*.csv")):
        t = os.path.basename(f)[:-4]
        if t in EXCL: continue
        try:
            d = pd.read_csv(f, usecols=["date", "close", "adj_close", "volume"], index_col=0, parse_dates=True)
        except ValueError:
            print("skip(형식 다름)", t); continue
        d = d[d.index >= "1998-06-01"]
        if len(d) < 300: continue
        d = d[~d.index.duplicated()]
        cl[t], ac[t], vo[t] = d["close"], d["adj_close"], d["volume"]
    close = pd.DataFrame(cl).sort_index().astype("float32")
    adj = pd.DataFrame(ac).sort_index().astype("float32")
    vol = pd.DataFrame(vo).sort_index().astype("float32")
    p = dict(close=close, adj=adj, vol=vol)
    pickle.dump(p, open(CACHE, "wb"))
    return p

def universe(close, vol, n=500):
    adv = (close * vol).rolling(60, min_periods=40).median()
    hist = close.notna().cumsum() >= 252
    ok = hist & (close.shift(1) >= 5) & adv.notna()
    rk = adv.where(ok).rank(axis=1, ascending=False)
    return (rk <= n).values

def raw_signals(adj):
    """원시 신호(부호 반영) 배열 dict와 일간 수익. adj: DataFrame(날짜x종목)"""
    r = adj.pct_change(fill_method=None)
    raw = {
        "S1": -r,
        "S2": -(adj / adj.shift(5) - 1),
        "S8": adj.shift(21) / adj.shift(252) - 1,
        "S10": -r.rolling(60, min_periods=40).std(),
        "S11": adj / adj.rolling(252, min_periods=200).max(),
    }
    return {k: v.values.astype("float32") for k, v in raw.items()}, r.values.astype("float32")

def zr(x):
    """1차원 순위 z (NaN은 0)"""
    out = np.zeros(len(x), dtype="float64"); m = ~np.isnan(x); n = m.sum()
    if n > 1:
        rk = np.empty(n); rk[np.argsort(x[m], kind="stable")] = np.arange(1, n + 1)
        out[m] = (rk - (n + 1) / 2) / n * np.sqrt(12)
    return out

def backtest(raw, r, uni, fraw=None, fr=None, funi=None, cap=0.01):
    """t 신호 -> t+1 종가 체결 -> t+2 수익. 전략별 일간 손익 배열 반환. f*: 주입 종목"""
    T = r.shape[0]; out = {k: np.zeros(T) for k in STRATS}
    rr = np.nan_to_num(r, nan=0.0); frr = None if fr is None else np.nan_to_num(fr, nan=0.0)
    for t in range(252, T - 2):
        ix = np.flatnonzero(uni[t])
        if len(ix) < 50: continue
        fx = np.flatnonzero(funi[t]) if funi is not None else np.empty(0, dtype=int)
        z = {}
        for k in raw:
            x = raw[k][t, ix]
            if len(fx): x = np.concatenate([x, fraw[k][t, fx]])
            z[k] = zr(x)
        nxt = rr[t + 2, ix]
        if len(fx): nxt = np.concatenate([nxt, frr[t + 2, fx]])
        for name, ks in STRATS.items():
            sc = sum(z[k] for k in ks)
            n = len(sc); rk = np.empty(n); rk[np.argsort(sc, kind="stable")] = np.arange(1, n + 1)
            w = rk - (n + 1) / 2; w = np.clip(w / np.abs(w).sum(), -cap, cap)
            out[name][t + 2] = (w * nxt).sum()
    return out

def sharpe(x, a, b):
    x = x[a:b]
    return x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan

def make_fail_path(rng, kind):
    if kind == "grad":
        T = int(rng.integers(120, 251)); tot = np.log(0.15)
        e = rng.normal(0, 0.05, T); lr = e - e.mean() + tot / T
        ret = np.exp(lr) - 1
    else:
        T = 60; tot = np.log(0.5)
        e = rng.normal(0, 0.04, T); lr = e - e.mean() + tot / T
        ret = np.concatenate([np.exp(lr) - 1, [-0.60, -1.0]])
    return ret

def inject(p, rates, seed):
    """rates: {(start,end): 연간 개수}. 주입 종목 열을 추가한 (close, adj, vol, forced) 반환"""
    rng = np.random.default_rng(seed)
    idx = p["close"].index
    cols_c, cols_v = {}, {}
    k = 0
    for (a, b), rate in rates.items():
        days = idx[(idx >= a) & (idx <= b)]
        yrs = len(days) / 252
        n = rng.poisson(rate * yrs)
        for _ in range(n):
            kind = "grad" if rng.random() < 0.7 else "sudden"
            ret = make_fail_path(rng, kind)
            end_i = int(rng.integers(0, len(days)))            # 실패 종료일
            end_pos = idx.get_loc(days[end_i])
            st = end_pos - len(ret)
            pre = 300                                          # 주입 전 평탄한 이력(유니버스 자격용)
            if st - pre < 1: continue
            px = np.full(len(idx), np.nan, dtype="float32")
            pre_r = rng.normal(0.0003, 0.02, pre)
            path = 40 * np.exp(np.cumsum(np.log1p(pre_r)) - np.sum(np.log1p(pre_r)))
            px[st - pre:st] = path
            px[st:end_pos] = 40 * np.cumprod(1 + ret)
            name = f"_FAIL{k}"; k += 1
            cols_c[name] = px
            cols_v[name] = np.where(np.isnan(px), np.nan, 1e12)   # 항상 거래대금 상위
    if not cols_c:
        return None
    return pd.DataFrame(cols_c, index=idx)

STRATS = {"a_S1": ["S1"], "b_S1+S2": ["S1", "S2"], "c_S1+S2+S8+S10+S11": ["S1", "S2", "S8", "S10", "S11"]}

def stats(o, idx):
    res = {}
    for k, x in o.items():
        x = pd.Series(x, index=idx)
        res[k] = (sharpe(x, *TRAIN), sharpe(x, *TEST), x[TRAIN[0]:TRAIN[1]].mean() * 252, x[TEST[0]:TEST[1]].mean() * 252,
                  x[TRAIN[0]:TRAIN[1]].std() * 252 ** .5, x[TEST[0]:TEST[1]].std() * 252 ** .5)
    return res

if __name__ == "__main__":
    nseed = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    p = load_panel(); idx = p["close"].index
    print("panel", p["close"].shape, idx[0].date(), idx[-1].date(), flush=True)
    uni = universe(p["close"], p["vol"])
    hist = ((p["close"].notna().cumsum() >= 252) & (p["close"].shift(1) >= 5)).values
    for y in [2003, 2006, 2010, 2016, 2020, 2026]:
        d = int(np.searchsorted(idx.values, np.datetime64(f"{y}-01-02")))
        print(f"자격 종목 수 {y}: {int(hist[d].sum())} (유니버스 {int(uni[d].sum())})", flush=True)
    raw, r = raw_signals(p["adj"]); del p["vol"], hist
    base = stats(backtest(raw, r, uni), idx)
    rows = []
    for k, v in base.items():
        rows.append(dict(scen="base", strat=k, tr=v[0], te=v[1], tr_ret=v[2], te_ret=v[3], tr_vol=v[4], te_vol=v[5]))
        print(rows[-1], flush=True)
    SCEN = {"low": (1, 0.3), "mid": (2.5, 1), "high": (5, 2.5)}
    for sn, (rt, re_) in SCEN.items():
        acc = {k: [] for k in STRATS}
        for seed in range(nseed):
            f = inject(p, {TRAIN: rt, TEST: re_}, seed)
            if f is None:
                for k in STRATS: acc[k].append(base[k][:4]); continue
            fraw, fr = raw_signals(f)
            fc = f.values
            funi = (np.roll(fc, 1, axis=0) >= 5) & ~np.isnan(fc); funi[0] = False
            st = stats(backtest(raw, r, uni, fraw, fr, funi), idx)
            for k in STRATS: acc[k].append(st[k][:4])
        for k in STRATS:
            m = np.array(acc[k]); mu = m.mean(0); sd = m.std(0); b = base[k]
            rows.append(dict(scen=sn, strat=k, tr=mu[0], te=mu[1], tr_ret=mu[2], te_ret=mu[3],
                             bias_tr=b[0] - mu[0], bias_te=b[1] - mu[1], bias_tr_sd=sd[0], bias_te_sd=sd[1],
                             bias_tr_ret=b[2] - mu[2], bias_te_ret=b[3] - mu[3], nseed=nseed))
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8-sig")
    print("saved", OUT)
