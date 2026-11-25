# -*- coding: utf-8 -*-
"""W3-B: ETF 30개 독립 시험 (부록_W3.md B절). 실행: py -I W3_etf.py
자료: Yahoo 일봉 -> data/W3_etf_<티커>.csv (있으면 다시 받지 않음)
"""
import os, json, time, urllib.request
import numpy as np, pandas as pd

BASE = r"E:/value-investing-checklist/사이먼스식 백테스트"
DATA = os.path.join(BASE, "data"); RES = os.path.join(BASE, "results")
UA = "Mozilla/5.0 (compatible; research-script)"
SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
CTRY = ["EWJ", "EWG", "EWU", "EWZ", "EWY", "EWC", "EWA", "EWH", "EWT", "EWW", "EWS", "FXI"]
OTHR = ["TLT", "IEF", "LQD", "GLD", "VNQ"]
BRD = ["EFA", "EEM", "IWM", "QQQ"]
TICKERS = SECT + CTRY + OTHR + BRD
TRAIN = ("2003-01-01", "2015-12-31"); TEST = ("2016-01-01", "2026-10-31")
SIGS = ["S1", "S2", "S3", "S4", "S6", "S7", "S8", "S10", "S11", "S12"]
COMBOS = {"C1": SIGS, "C3형": ["S1", "S2", "S3", "S4", "S6", "S7", "S12"]}
LAMS = [1.0, 0.5, 0.2]; COSTS = [0, 5, 10, 20]; BORROW = 0.005; CAP = 0.10

def fetch(t):
    f = os.path.join(DATA, f"W3_etf_{t}.csv")
    if os.path.exists(f):
        return pd.read_csv(f, index_col=0, parse_dates=True)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?period1=0&period2=9999999999&interval=1d"
    for k in range(4):
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40))
            break
        except Exception as e:
            print("재시도", t, e); time.sleep(3 + 3 * k)
    else:
        raise RuntimeError("받기 실패 " + t)
    r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    d = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                      "adj_close": r["indicators"]["adjclose"][0]["adjclose"], "volume": q["volume"]},
                     index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    d.index.name = "date"; d = d.dropna(subset=["close"]); d = d[~d.index.duplicated()]
    d.to_csv(f); time.sleep(1.0)
    return d

def panel(end=None):
    P = {t: fetch(t) for t in TICKERS + ["SPY"]}
    idx = P["SPY"].index
    idx = idx[(idx >= "1998-12-22") & (idx <= "2026-10-31")]
    if end: idx = idx[idx <= end]
    g = lambda c: pd.DataFrame({t: P[t][c] for t in TICKERS}).reindex(idx)
    return dict(o=g("open"), h=g("high"), l=g("low"), c=g("close"), a=g("adj_close"), v=g("volume"),
                spy=P["SPY"]["adj_close"].reindex(idx).pct_change())

def raw_signals(p):
    a, c, o, h, l, v = p["a"], p["c"], p["o"], p["h"], p["l"], p["v"]
    r = a.pct_change(fill_method=None)
    v60 = v.rolling(60, min_periods=40).mean()
    rng = (h - l).where((h - l) > 0)
    s = {
        "S1": -r,
        "S2": -(a / a.shift(5) - 1),
        "S3": -(c / o - 1),
        "S4": o / c.shift(1) - 1,
        "S6": np.log(v.where(v > 0) / v60),
        "S7": -r * (v < v60).astype(float),
        "S8": a.shift(21) / a.shift(252) - 1,
        "S10": -r.rolling(60, min_periods=40).std(),
        "S11": a / a.rolling(252, min_periods=200).max(),
        "S12": -(c - (h + l) / 2) / rng,
    }
    uni = (c.notna().cumsum() >= 252) & c.notna()
    return s, r, uni

def zrank(x, uni):
    x = x.where(uni); n = x.notna().sum(axis=1)
    z = x.rank(axis=1).sub((n + 1) / 2, axis=0).div(n.where(n > 1), axis=0) * np.sqrt(12)
    return z.where(uni).fillna(0.0).where(uni)

def target(score, uni):
    sc = score.where(uni); n = sc.notna().sum(axis=1)
    w = sc.rank(axis=1, method="first").sub((n + 1) / 2, axis=0)
    w = w.div(w.abs().sum(axis=1).where(n >= 6), axis=0).clip(-CAP, CAP)
    return w.fillna(0.0)

def smooth(tg, lam):
    if lam == 1.0: return tg
    w = np.zeros_like(tg.values); x = tg.values
    for i in range(1, len(x)):
        w[i] = (1 - lam) * w[i - 1] + lam * x[i]
    return pd.DataFrame(w, index=tg.index, columns=tg.columns)

def run(w, r):
    """w(t): t 종가 신호의 목표 비중. t+1 종가 체결, t+2 수익부터."""
    rr = r.fillna(0.0)
    held = w.shift(2).fillna(0.0)                       # d일 동안 들고 있는 비중 = w(d-2)
    gross = (held * rr).sum(axis=1)
    lng = (held.clip(lower=0) * rr).sum(axis=1); sht = (held.clip(upper=0) * rr).sum(axis=1)
    new = w.shift(1).fillna(0.0)                        # d일 종가에 맞추는 비중 = w(d-1)
    drift = held * (1 + rr)                             # d일 종가 직전의 흘러간 비중
    to = (new - drift).abs().sum(axis=1)                # d일 종가 거래 금액(편도 합계)
    borrow = held.clip(upper=0).abs().sum(axis=1) * BORROW / 252
    return dict(gross=gross, to=to, borrow=borrow, long=lng, short=sht)

def net(o, bp): return o["gross"] - o["to"] * bp / 1e4 - o["borrow"]

def sharpe(x): return x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan

def metrics(x, o=None, spy=None):
    eq = (1 + x).cumprod(); m = dict(sharpe=sharpe(x), ret=x.mean() * 252, vol=x.std() * np.sqrt(252),
                                     mdd=(eq / eq.cummax() - 1).min())
    if o is not None:
        to = o["to"].reindex(x.index)
        m.update(turnover_yr=to.mean() * 252, hold_days=2 / to.mean() if to.mean() > 0 else np.nan,
                 long_ret=o["long"].reindex(x.index).mean() * 252, short_ret=o["short"].reindex(x.index).mean() * 252)
    if spy is not None:
        s = spy.reindex(x.index); ok = s.notna()
        m["beta"] = np.cov(x[ok], s[ok])[0, 1] / s[ok].var()
    return m

def boot_p(x, B=2000, blk=20, seed=0):
    rng = np.random.default_rng(seed); v = x.values; n = len(v); k = int(np.ceil(n / blk)); cnt = 0
    for _ in range(B):
        st = rng.integers(0, n - blk + 1, k)
        s = np.concatenate([v[i:i + blk] for i in st])[:n]
        cnt += s.mean() > 0
    return cnt / B

def sl(x, per): return x[per[0]:per[1]]

def build(p):
    s, r, uni = raw_signals(p)
    z = {k: zrank(s[k], uni) for k in SIGS}
    return s, z, r, uni

if __name__ == "__main__":
    os.makedirs(RES, exist_ok=True)
    p = panel(); s, z, r, uni = build(p)
    L = []
    def P(*a):
        t = " ".join(str(x) for x in a); L.append(t); print(t, flush=True)
    P("W3-B. ETF 30개 독립 시험 (작업자 W3, 2026-11-22). 설계는 부록_W3.md B절(결과 전 작성).")
    P("=" * 60)
    P("자료:", p["c"].index[0].date(), "~", p["c"].index[-1].date(), "/ ETF", len(TICKERS), "개 / 유니버스 크기:",
      {y: int(uni.loc[str(y)].sum(axis=1).iloc[0]) for y in [2003, 2006, 2010, 2016, 2026]})
    P("첫 거래일:", {t: str(p["c"][t].first_valid_index().date()) for t in TICKERS})

    # --- 신호별 IC와 단독 성과
    P("\n■ 신호별 IC(순위 상관, 일별 평균)와 단독 성과(λ=1, 비용 0 / 10bp Sharpe)")
    P("신호   IC(t+1)학습 t값   IC(t+1)검증 t값   IC(t+2)검증   Sharpe0 학습/검증   Sharpe10 학습/검증")
    rows = []
    rk_r1 = r.shift(-1).where(uni).rank(axis=1); rk_r2 = r.shift(-2).where(uni).rank(axis=1)
    for k in SIGS:
        zk = z[k].rank(axis=1)
        ic1 = zk.corrwith(rk_r1, axis=1); ic2 = zk.corrwith(rk_r2, axis=1)
        o = run(target(z[k], uni), r)
        f = lambda x: (x.mean(), x.mean() / x.std() * np.sqrt(x.notna().sum()))
        a1, t1 = f(sl(ic1, TRAIN)); a2, t2 = f(sl(ic1, TEST)); b2, _ = f(sl(ic2, TEST))
        P(f"{k:5s} {a1:+.4f} {t1:+6.1f}   {a2:+.4f} {t2:+6.1f}   {b2:+.4f}   "
          f"{sharpe(sl(o['gross'], TRAIN)):+.2f}/{sharpe(sl(o['gross'], TEST)):+.2f}   "
          f"{sharpe(sl(net(o, 10), TRAIN)):+.2f}/{sharpe(sl(net(o, 10), TEST)):+.2f}")

    # --- 결합
    res = {}
    for cn, ks in COMBOS.items():
        sc = sum(z[k] for k in ks)
        tg = target(sc, uni)
        for lam in LAMS:
            o = run(smooth(tg, lam), r); res[(cn, lam)] = o
            for bp in COSTS:
                x = net(o, bp) if bp else o["gross"]
                for pn, per in [("학습", TRAIN), ("검증", TEST)]:
                    m = metrics(sl(x, per), o, p["spy"]); m.update(combo=cn, lam=lam, cost_bp=bp, period=pn)
                    rows.append(m)
    df = pd.DataFrame(rows)[["combo", "lam", "cost_bp", "period", "sharpe", "ret", "vol", "mdd", "turnover_yr",
                             "hold_days", "long_ret", "short_ret", "beta"]]
    df.to_csv(os.path.join(RES, "W3_etf.csv"), index=False, encoding="utf-8-sig")
    P("\n■ 결합 성과 Sharpe (학습 / 검증)")
    P("결합   λ     비용0          5bp           10bp          20bp        회전율(연) 보유일")
    for (cn, lam), o in res.items():
        g = lambda bp, pn: df[(df.combo == cn) & (df.lam == lam) & (df.cost_bp == bp) & (df.period == pn)].iloc[0]
        P(f"{cn:5s} {lam:.1f}  " + "  ".join(f"{g(bp, '학습').sharpe:+.2f}/{g(bp, '검증').sharpe:+.2f}" for bp in COSTS)
          + f"   {g(0, '검증').turnover_yr:6.0f}배  {g(0, '검증').hold_days:.1f}")

    # --- λ 선택(학습 Sharpe@10bp)과 판정
    lam = max(LAMS, key=lambda l: sharpe(sl(net(res[("C1", l)], 10), TRAIN)))
    lam5 = max(LAMS, key=lambda l: sharpe(sl(net(res[("C1", l)], 5), TRAIN)))
    o = res[("C1", lam)]
    P(f"\n■ 선택: C1, λ={lam} (학습 Sharpe@10bp 1위). 5bp 기준으로 골라도 λ={lam5}")
    st = {bp: sharpe(sl(net(o, bp) if bp else o["gross"], TEST)) for bp in COSTS}
    pb = {bp: boot_p(sl(net(o, bp), TEST)) for bp in [5, 10]}
    m = metrics(sl(net(o, 10), TEST), o, p["spy"])
    P(f"검증 Sharpe: 비용0 {st[0]:+.2f} / 5bp {st[5]:+.2f} / 10bp {st[10]:+.2f} / 20bp {st[20]:+.2f}")
    P(f"검증 @10bp: 연수익 {m['ret']:+.2%}, 변동성 {m['vol']:.2%}, MDD {m['mdd']:.1%}, 베타 {m['beta']:+.3f}, "
      f"회전율 연 {m['turnover_yr']:.0f}배, 평균 보유 {m['hold_days']:.1f}일, 롱 {m['long_ret']:+.2%} / 숏 {m['short_ret']:+.2%}")
    P(f"부트스트랩 P(Sharpe>0): @10bp {pb[10]:.3f}, @5bp {pb[5]:.3f}")
    def verdict(s_main, s_hi, pv):
        if s_main >= 1.0 and s_hi > 0 and pv >= 0.95: return "통과"
        if s_main > 0.3 and pv >= 0.90: return "보류"
        return "탈락"
    P(f"공식 판정(§9, 10bp/20bp): {verdict(st[10], st[20], pb[10])}")
    P(f"참고 판정(5bp/10bp로 한 단계 낮춤): {verdict(st[5], st[10], pb[5])}")
    P("\n■ 선택 모델 연도별 수익(@10bp)과 Sharpe")
    x = net(o, 10)["2003":]
    P("  ".join(f"{y}:{g.mean() * 252:+.1%}({sharpe(g):+.1f})" for y, g in x.groupby(x.index.year)))

    # --- 엔진 검증
    P("\n■ 엔진 검증")
    p2 = panel(end="2012-12-31"); s2, z2, r2, u2 = build(p2)
    wa = smooth(target(sum(z[k] for k in SIGS), uni), lam).loc[:"2012-12-31"]
    wb = smooth(target(sum(z2[k] for k in SIGS), u2), lam)
    P(f"1) 룩어헤드: 2012-12-31에서 자른 계산과 전체 계산의 비중 최대 차이 = {float((wa - wb).abs().max().max()):.2e}")
    rng = np.random.default_rng(1); s0, s10 = [], []
    for i in range(100):
        sc = pd.DataFrame(rng.normal(size=r.shape), index=r.index, columns=r.columns)
        oo = run(target(sc, uni), r); s0.append(sharpe(oo["gross"]["2003":])); s10.append(sharpe(net(oo, 10)["2003":]))
    P(f"2) 무작위 점수 100회: 비용 0 Sharpe 평균 {np.mean(s0):+.3f} (표준편차 {np.std(s0):.3f}), 10bp 평균 {np.mean(s10):+.2f}")
    P("3) 수작업 대조(원자료 CSV에서 다시 계산):")
    for d, t in [("2008-10-10", "XLF"), ("2015-08-24", "EWJ"), ("2020-03-16", "TLT")]:
        raw = pd.read_csv(os.path.join(DATA, f"W3_etf_{t}.csv"), index_col=0, parse_dates=True)
        i = raw.index.get_loc(pd.Timestamp(d)); q = raw.iloc[i]; a = raw["adj_close"]
        m1 = -(a.iloc[i] / a.iloc[i - 1] - 1); m2 = -(a.iloc[i] / a.iloc[i - 5] - 1)
        m12 = -(q["close"] - (q["high"] + q["low"]) / 2) / (q["high"] - q["low"])
        P(f"   {d} {t}: S1 {m1:+.5f} vs {s['S1'].loc[d, t]:+.5f} / S2 {m2:+.5f} vs {s['S2'].loc[d, t]:+.5f} / "
          f"S12 {m12:+.5f} vs {s['S12'].loc[d, t]:+.5f}")
    open(os.path.join(RES, "W3_summary.txt"), "w", encoding="utf-8").write("\n".join(L) + "\n")
