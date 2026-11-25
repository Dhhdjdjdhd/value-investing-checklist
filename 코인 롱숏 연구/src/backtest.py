"""코인 롱/숏 판단 연구 (00_연구설계서).

실행: py src/backtest.py -> results/rules.csv, verdict.csv, alts.csv, summary.txt
"""
import json
import sys
import time
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
DATA.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-script)"}
END = "2026-11-20"
IS = ("2017-09-01", "2022-12-31")
OOS = ("2023-01-01", END)
COST = 0.0007
STD_FUND = 0.0003  # 하루 (8시간 0.01% × 3)
H = (1, 3, 7)
rng = np.random.default_rng(20261121)


def get(url):
    for k in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
        except Exception:  # noqa: BLE001
            time.sleep(2 * (k + 1))
    raise RuntimeError(url)


def klines(sym):
    p = DATA / f"{sym}_1d.csv"
    if p.exists():
        return pd.read_csv(p, index_col=0, parse_dates=True)
    rows, start = [], 1500000000000
    while True:
        r = get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&startTime={start}&limit=1000")
        if not r:
            break
        rows += r
        start = r[-1][0] + 86400000
        if len(r) < 1000:
            break
        time.sleep(0.3)
    d = pd.DataFrame(rows).iloc[:, :6]
    d.columns = ["t", "open", "high", "low", "close", "vol"]
    d.index = pd.to_datetime(d.t, unit="ms")
    d = d.drop(columns="t").astype(float)
    d.to_csv(p)
    return d


def funding(sym):
    p = DATA / f"{sym}_funding.csv"
    if p.exists():
        return pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0]
    rows, start = [], 1560000000000
    while True:
        r = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={start}&limit=1000")
        if not r:
            break
        rows += r
        start = r[-1]["fundingTime"] + 1
        if len(r) < 1000:
            break
        time.sleep(0.3)
    s = pd.Series({pd.to_datetime(x["fundingTime"], unit="ms"): float(x["fundingRate"]) for x in rows})
    s = s.groupby(s.index.normalize()).sum()  # 하루 합계
    s.to_frame("funding").to_csv(p)
    return s


# ---------------------------------------------------------------- 신호
def features(c, f):
    X = pd.DataFrame(index=c.index)
    for L in (7, 14, 28, 56):
        X[f"mom{L}"] = c / c.shift(L) - 1
    for N in (20, 50, 200):
        X[f"dist{N}"] = c / c.rolling(N).mean() - 1
    X["vol20"] = np.log(c).diff().rolling(20).std()
    X["fund7"] = f.reindex(c.index).rolling(7).mean().fillna(STD_FUND) if f is not None else STD_FUND
    dow = pd.get_dummies(pd.Series((c.index + pd.Timedelta(days=1)).dayofweek, index=c.index), prefix="d").astype(float)
    return pd.concat([X, dow.iloc[:, 1:]], axis=1)


def sgn(x):
    return pd.Series(np.where(x > 0, 1.0, -1.0), index=x.index).where(x.notna())


def signals(c, f, dow_means=None):
    S = {}
    for L in (7, 14, 28, 56):
        S[f"T1-{L}"] = sgn(c / c.shift(L) - 1)
    for N in (20, 50, 100, 200):
        S[f"T2-{N}"] = sgn(c - c.rolling(N).mean())
    S["T3"] = sgn(c.rolling(20).mean() - c.rolling(100).mean())
    r = c.pct_change()
    S["R1"] = sgn(-r)
    S["R3"] = sgn(-(c / c.shift(3) - 1))
    if f is not None:
        f7 = f.reindex(c.index).rolling(7).mean()
        med = f7.rolling(180, min_periods=180).median()
        S["F1"] = sgn(med - f7).where(med.notna())
        q90 = f7.rolling(365, min_periods=365).quantile(0.9)
        base = S["T2-50"].copy()
        S["F2"] = base.where(~(f7 > q90), -1.0).where(q90.notna())
    if dow_means is not None:
        nd = (c.index + pd.Timedelta(days=1)).dayofweek
        S["D1"] = pd.Series([1.0 if dow_means[d] > 0 else -1.0 for d in nd], index=c.index)
    return S


def model_signals(c, f, h):
    X = features(c, f)
    y = (c.shift(-h) / c - 1 > 0).astype(float).where(c.shift(-h).notna())
    ok = X.notna().all(axis=1)
    out = {}
    # M1: 학습 구간(라벨이 학습 구간 안에서 끝나는 날만)으로 한 번
    tr = ok & y.notna() & (X.index >= IS[0]) & (X.index <= pd.Timestamp(IS[1]) - pd.Timedelta(days=h))
    sc = StandardScaler().fit(X[tr])
    m = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(X[tr]), y[tr])
    p = pd.Series(np.nan, index=X.index)
    p[ok] = m.predict_proba(sc.transform(X[ok]))[:, 1]
    out["M1"] = sgn(p - 0.5).where(p.notna())
    # M2: 매년 1월 1일 확장 재학습 (검증 구간만)
    p2 = pd.Series(np.nan, index=X.index)
    for yr in range(2023, int(END[:4]) + 1):
        cut = pd.Timestamp(f"{yr}-01-01")
        tr2 = ok & y.notna() & (X.index >= IS[0]) & (X.index < cut - pd.Timedelta(days=h))
        sc2 = StandardScaler().fit(X[tr2])
        m2 = LogisticRegression(C=1.0, max_iter=2000).fit(sc2.transform(X[tr2]), y[tr2])
        sel = ok & (X.index >= cut) & (X.index < pd.Timestamp(f"{yr + 1}-01-01"))
        if sel.any():
            p2[sel] = m2.predict_proba(sc2.transform(X[sel]))[:, 1]
    out["M2"] = sgn(p2 - 0.5).where(p2.notna())
    return out


# ---------------------------------------------------------------- 성과
def pnl(c, s, h, fund, cost=COST, perp=True):
    """s_t: t일 종가 신호 → t+1일부터 h일 분할 보유."""
    r = c.pct_change()
    pos = s.rolling(h, min_periods=h).mean().shift(1)
    turn = pos.diff().abs().fillna(pos.abs())
    fd = fund.reindex(c.index).fillna(STD_FUND) if perp else 0.0
    out = pos * r - cost * turn - (pos * fd if perp else 0.0)
    return out.where(pos.notna()), pos


def stats(x):
    x = x.dropna()
    if len(x) < 30:
        return dict(CAGR=np.nan, Sharpe=np.nan, MDD=np.nan, days=len(x))
    e = (1 + x).cumprod()
    yrs = len(x) / 365
    return dict(CAGR=e.iloc[-1] ** (1 / yrs) - 1, Sharpe=x.mean() / x.std() * np.sqrt(365),
                MDD=(e / e.cummax() - 1).min(), days=len(x))


def boot(a, b, n=1000, blk=30):
    d = pd.concat([a, b], axis=1).dropna().values
    T = len(d)
    if T < 2 * blk:
        return np.nan
    k = T // blk + 1
    wins = 0
    for _ in range(n):
        st = rng.integers(0, T - blk, k)
        idx = (st[:, None] + np.arange(blk)).ravel()[:T]
        x = d[idx]
        sa = x[:, 0].mean() / x[:, 0].std()
        sb = x[:, 1].mean() / x[:, 1].std()
        wins += sa > sb
    return wins / n


def hit(c, s, h, a, b):
    fr = (c.shift(-h) / c - 1)
    d = pd.concat([s, fr], axis=1, keys=["s", "f"]).loc[a:b].dropna()
    d = d[d.f != 0]
    if len(d) < 30:
        return {}
    up, dn = d.f > 0, d.f < 0
    tpr = (d.s[up] > 0).mean()
    tnr = (d.s[dn] < 0).mean()
    return dict(BA=0.5 * (tpr + tnr), acc=(np.sign(d.s) == np.sign(d.f)).mean(),
                long_hit=(d.f[d.s > 0] > 0).mean() if (d.s > 0).any() else np.nan,
                short_hit=(d.f[d.s < 0] < 0).mean() if (d.s < 0).any() else np.nan,
                long_share=(d.s > 0).mean(), up_rate=up.mean())


def evaluate(sym, c, f, S_all, periods, cost=COST):
    r = c.pct_change()
    bh = r.copy()
    tf = (c > c.rolling(200).mean()).astype(float).where(c.rolling(200).mean().notna())
    tfp = tf.shift(1)
    tfr = tfp * r - cost * tfp.diff().abs().fillna(0)
    rows = []
    for (name, h), s in S_all.items():
        x, _ = pnl(c, s, h, f if f is not None else pd.Series(dtype=float), cost)
        for pn, (a, b) in periods.items():
            xs = x.loc[a:b].dropna()
            if len(xs) < 60:
                continue
            days = xs.index
            st = stats(xs)
            sb = stats(bh.reindex(days))
            stf = stats(tfr.reindex(days))
            hh = hit(c, s, h, a, b)
            rows.append(dict(asset=sym, period=pn, rule=name, h=h, **{k: st[k] for k in ("CAGR", "Sharpe", "MDD", "days")},
                             BH_Sharpe=sb["Sharpe"], BH_CAGR=sb["CAGR"], TF_Sharpe=stf["Sharpe"], **hh,
                             boot=boot(xs, bh.reindex(days))))
    R = pd.DataFrame(rows)
    R["pass"] = (R.BA >= 0.53) & (R.Sharpe > R.BH_Sharpe) & (R.Sharpe > R.TF_Sharpe) & (R.boot >= 0.90)
    return R


def build(sym, c, f, dow_means):
    S = signals(c, f, dow_means)
    S_all = {}
    for h in H:
        for k, v in S.items():
            if k == "D1" and h != 1:
                continue
            S_all[(k, h)] = v
        for k, v in model_signals(c, f, h).items():
            S_all[(k, h)] = v
    return S_all


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    log = []
    data = {}
    for sym in ["BTCUSDT", "ETHUSDT"]:
        k = klines(sym)
        data[sym] = (k.close.loc[:END], funding(sym).loc[:END])
    btc, fb = data["BTCUSDT"]
    # 엔진 검증 1: 룩어헤드
    cut = "2021-12-31"
    S_full = signals(btc, fb)
    S_cut = signals(btc.loc[:cut], fb.loc[:cut])
    for k in S_cut:
        a, b = S_full[k].loc[:cut], S_cut[k]
        assert ((a == b) | (a.isna() & b.isna())).all(), f"룩어헤드 의심 {k}"
    Xf, Xc = features(btc, fb).loc[:cut], features(btc.loc[:cut], fb.loc[:cut])
    assert np.allclose(Xf.fillna(0).values, Xc.fillna(0).values), "특징 룩어헤드 의심"
    log.append("엔진 검증 1 통과: 2021-12-31 절단 신호·특징 = 전체 계산")
    # 엔진 검증 2: 무조건 롱, 비용 0, 현물 = 보유
    one = pd.Series(1.0, index=btc.index)
    x, _ = pnl(btc, one, 1, fb, cost=0.0, perp=False)
    e = (1 + x.dropna()).prod()
    assert abs(e - btc.iloc[-1] / btc.iloc[0]) / e < 1e-9
    log.append("엔진 검증 2 통과: 무조건 롱(비용 0) = 현물 보유")

    # 요일 평균 (학습 구간, BTC) — ETH에도 BTC에서 배운 값을 그대로
    rb = btc.pct_change().loc[IS[0]:IS[1]]
    dow_means = rb.groupby(rb.index.dayofweek).mean().to_dict()
    periods = {"학습": IS, "검증": OOS}
    allR = []
    for sym, (c, f) in data.items():
        S_all = build(sym, c, f, dow_means)
        allR.append(evaluate(sym, c, f, S_all, periods))
        allR.append(evaluate(sym, c, f, S_all, periods, cost=COST * 2).assign(cost="x2"))
    R = pd.concat(allR)
    R["cost"] = R.get("cost", pd.Series(index=R.index)).fillna("x1")
    R.to_csv(RES / "rules.csv", index=False, encoding="utf-8-sig")

    base = R[R.cost == "x1"]
    V = []
    for (rule, h), g in base.groupby(["rule", "h"]):
        def ok(a, p):
            q = g[(g.asset == a) & (g.period == p)]
            return bool(q["pass"].iloc[0]) if len(q) else None
        bi, bo, eo = ok("BTCUSDT", "학습"), ok("BTCUSDT", "검증"), ok("ETHUSDT", "검증")
        if rule == "M2":
            v = "보류" if (bo and eo) else "탈락"
        elif not bo:
            v = "탈락"
        elif bi and bo and eo:
            v = "추천"
        elif bi and bo:
            v = "보류"
        else:
            v = "탈락(학습 실패)"
        V.append(dict(rule=rule, h=h, BTC학습=bi, BTC검증=bo, ETH검증=eo, 판정=v))
    V = pd.DataFrame(V).sort_values(["판정", "rule", "h"])
    V.to_csv(RES / "verdict.csv", index=False, encoding="utf-8-sig")

    # 알트 참고 (판정 아님): 모든 규칙, 검증 구간
    alts = []
    for sym in ["BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT"]:
        try:
            c = klines(sym).close.loc[:END]
            f = funding(sym).loc[:END]
            S_all = build(sym, c, f, dow_means)
            alts.append(evaluate(sym, c, f, S_all, {"검증": OOS}))
        except Exception as ex:  # noqa: BLE001
            log.append(f"알트 {sym} 실패: {ex}")
    A = pd.concat(alts) if alts else pd.DataFrame()
    A.to_csv(RES / "alts.csv", index=False, encoding="utf-8-sig")

    # 요약
    o = log + [""]
    for (a, p), g in base.groupby(["asset", "period"], sort=False):
        o.append(f"[{a} {p}] B&H Sharpe {g.BH_Sharpe.median():.2f} / 연 {g.BH_CAGR.median():.1%}, TF200 Sharpe {g.TF_Sharpe.median():.2f}, 상승비율(h=1) {g[g.h == 1].up_rate.median():.1%}")
        g = g.sort_values("BA", ascending=False)
        for _, r in g.iterrows():
            o.append(f"  {r.rule:<6} h{r.h} BA {r.BA:.3f} 적중 {r.acc:.3f} (롱 {r.long_hit:.3f} 숏 {r.short_hit:.3f}, 롱비중 {r.long_share:.0%}) | "
                     f"연 {r.CAGR:7.1%} Sharpe {r.Sharpe:5.2f} MDD {r.MDD:6.1%} | 부트 {r.boot:.2f} {'통과' if r['pass'] else ''}")
        o.append("")
    o.append("[판정]")
    o.append(V.to_string(index=False))
    o.append("")
    x2 = R[(R.cost == "x2") & R["pass"]]
    o.append(f"[비용 2배에서 통과한 (자산·구간·규칙)] {len(x2)}개: " + ", ".join(f"{r.asset[:3]} {r.period} {r.rule} h{r.h}" for _, r in x2.iterrows()))
    if len(A):
        o.append("")
        o.append("[알트 참고 — 검증 구간, 판정 아님] 규칙별 5개 알트 중 통과 수 / 평균 BA")
        ga = A.groupby(["rule", "h"]).agg(n_pass=("pass", "sum"), BA=("BA", "mean"), Sharpe=("Sharpe", "mean"), BHS=("BH_Sharpe", "mean")).reset_index()
        o.append(ga.sort_values("BA", ascending=False).round(3).to_string(index=False))
    txt = "\n".join(o)
    (RES / "summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
