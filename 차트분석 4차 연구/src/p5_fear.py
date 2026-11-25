"""P5. 공포 국면 신호 (00_연구설계서 §7, 부록 A).

실행: py src/p5_fear.py -> results/P5_events.csv, P5_event_stats.csv, P5_F6.csv, P5_summary.txt
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
RES.mkdir(exist_ok=True)
ALT = ROOT.parent / "대안전략 연구" / "src"
sys.path.insert(0, str(ALT))
import alloc  # noqa: E402
import valuation  # noqa: E402

HZ = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}
IS, OOS = ("1950-01-01", "1999-12-31"), ("2000-01-01", "2026-11-20")


def load(n):
    r = json.load(open(DATA / f"{n}.json"))["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    return s.dropna().groupby(level=0).last()


def rearm(cond):
    """조건이 꺼졌다가 켜지는 첫날만 True."""
    c = cond.fillna(False).astype(bool)
    return c & ~c.shift(1, fill_value=False)


def signals(g, v):
    ath = g.cummax()
    dd = g / ath - 1
    vv = v.reindex(g.index)
    S = {}
    S["F1 VIX≥30"] = rearm(vv >= 30)
    S["F2 VIX≥40"] = rearm(vv >= 40)
    S["F3 VIX급등(20일평균×1.5)"] = rearm(vv / vv.rolling(20).mean() >= 1.5)
    # F4: 하락 국면(고점 갱신 사이)마다 단계별 첫 도달
    ep = (g >= ath).cumsum()  # 새 고점마다 국면 번호 증가
    for lv in (10, 20, 30):
        hit = dd <= -lv / 100
        first = hit & (hit.groupby(ep).cumsum() == 1)
        S[f"F4 고점대비-{lv}%"] = first
    low52 = g <= g.rolling(252, min_periods=252).min()
    S["F5 52주신저가"] = rearm(low52)
    for k in S:
        S[k] = S[k] & vv.notna() if k.startswith(("F1", "F2", "F3")) else S[k]
    return pd.DataFrame(S), dd, ath


def fwd(s):
    """진입 = 다음날 종가. h일 뒤 수익, 12개월 안 추가 최저, 직전 고점 회복 일수."""
    a = s.values
    n = len(a)
    out = {}
    for k, h in HZ.items():
        r = np.full(n, np.nan)
        r[: n - 1 - h] = a[1 + h:] / a[1: n - h] - 1
        out[k] = r
    return pd.DataFrame(out, index=s.index)


def cluster_t(vals, groups):
    d = pd.DataFrame({"x": vals, "g": groups}).dropna()
    if len(d) < 3 or d.g.nunique() < 3:
        return np.nan
    m = d.x.mean()
    G = d.g.nunique()
    s = d.assign(e=d.x - m).groupby("g").e.sum()
    var = (s ** 2).sum() / len(d) ** 2 * G / (G - 1)
    return m / np.sqrt(var)


def event_study(g, v, S, dd, ath, tag, out):
    F = fwd(g)
    a = g.values
    rows, stats = [], []
    for name in S.columns:
        idx = np.where(S[name].values)[0]
        for i in idx:
            if i + 1 >= len(a):
                continue
            d = g.index[i]
            e = a[i + 1]
            j = min(len(a), i + 1 + 252)
            mn = a[i + 1: j].min() / e - 1 if j > i + 1 else np.nan
            pk = ath.iloc[i]
            rec = np.where(a[i + 1:] >= pk)[0]
            rows.append({"set": tag, "signal": name, "date": d.date(), "dd": dd.iloc[i],
                         "vix": v.reindex([d]).iloc[0] if d in v.index else np.nan,
                         **{k: F[k].iloc[i] for k in HZ}, "maxdown12M": mn,
                         "recover_days": int(rec[0] + 1) if len(rec) else np.nan})
    E = pd.DataFrame(rows)
    for (pn, (a0, b0)) in {"학습": IS, "검증": OOS}.items():
        mask = (F.index >= a0) & (F.index <= b0)
        if tag == "원화":
            mask &= F.index >= "2004-01-01"
        base = F[mask].mean()
        for name in S.columns:
            sub = E[(E.signal == name) & (pd.to_datetime(E.date) >= a0) & (pd.to_datetime(E.date) <= b0)]
            if tag == "원화":
                sub = sub[pd.to_datetime(sub.date) >= "2004-01-01"]
            rec = {"set": tag, "period": pn, "signal": name, "N": len(sub),
                   "years": pd.to_datetime(sub.date).dt.year.nunique() if len(sub) else 0}
            for k in HZ:
                x = sub[k] - base[k]
                rec[f"{k}_mean"] = sub[k].mean()
                rec[f"{k}_base"] = base[k]
                rec[f"{k}_excess"] = x.mean()
                rec[f"{k}_win"] = (sub[k] > 0).mean() if sub[k].notna().any() else np.nan
                rec[f"{k}_t"] = cluster_t(x.values, pd.to_datetime(sub.date).dt.year.values)
            rec["maxdown12M_med"] = sub.maxdown12M.median()
            rec["recover_med"] = sub.recover_days.median()
            stats.append(rec)
    return E, pd.DataFrame(stats)


def fear_state(g, sig, ath):
    """신호일부터 직전 고점(신호일 기준 ath) 종가 회복일 전까지 True."""
    st = np.zeros(len(g), bool)
    a = g.values
    on, target = False, None
    sv = sig.values
    for i in range(len(a)):
        if on and a[i] >= target:
            on = False
        if sv[i] and not on:
            on, target = True, ath.iloc[i]
        st[i] = on
    return pd.Series(st, index=g.index)


def f6(g, S, ath, out):
    sh = valuation.shiller()
    tr = (sh.P + sh.D / 12).div(sh.P.shift(1)) - 1
    spy = alloc.yahoo("SPY", True)
    tr = pd.concat([tr.loc[:"2023-08"], spy.pct_change().loc["2023-09":"2026-10"]])
    tr = tr[~tr.index.duplicated()]
    y10 = pd.concat([sh["Rate GS10"], alloc.yahoo("^TNX").loc["2023-09":"2026-10"]])
    y10 = y10[~y10.index.duplicated()].astype(float)
    bd10 = alloc.bond_ret(y10 / 100, n=10)
    D = alloc.build()
    rules = ["F1 VIX≥30", "F3 VIX급등(20일평균×1.5)", "F4 고점대비-10%", "F4 고점대비-20%", "F5 52주신저가"]
    tgt = {"80/20": None}
    for r in rules:
        st = fear_state(g, S[r], ath)
        m = st.groupby(st.index.strftime("%Y-%m")).last()
        tgt[r] = m
    rows = []
    tests = {"B학습 1950~1999": (tr, bd10, "1950-01", "1999-12"),
             "B검증 2000~2026.10": (tr, bd10, "2000-01", "2026-10"),
             "A원화 1991~2026.10": (D.un, D.bh, "1991-01", "2026-10")}
    for tn, (req, rbd, a0, b0) in tests.items():
        for r, m in tgt.items():
            if m is None:
                w = pd.Series(0.2, index=req.index)
                rule = "L0"
            else:
                w = pd.Series(np.where(m.reindex(req.index).fillna(False).astype(bool), 0.1, 0.2), index=req.index)
                rule = "F6"
            s, e = valuation.simulate(req, rbd, w, rule, a0, b0)
            sub = w.loc[a0:b0]
            rows.append({"test": tn, "rule": r, "CAGR": s["CAGR"], "MDD": s["MDD"], "Sharpe": s["Sharpe"],
                         "fear_share": (sub < 0.2).mean(), "chg_per_yr": s["chg_per_yr"]})
    R = pd.DataFrame(rows)
    verdict = []
    for r in rules:
        ok = {}
        for tn in tests:
            b = R[(R.test == tn) & (R.rule == "80/20")].iloc[0]
            x = R[(R.test == tn) & (R.rule == r)].iloc[0]
            ok[tn] = (x.CAGR - b.CAGR >= 0.003) and (x.MDD >= b.MDD - 0.02)
        k = list(tests)
        if not ok[k[1]]:
            v = "탈락"
        elif ok[k[0]] and ok[k[1]]:
            v = "추천" if ok[k[2]] else "보류(추천 후보, 원화 미통과)"
        else:
            v = "보류(검증만 통과)"
        verdict.append({"rule": r, **{f"통과_{t}": ok[t] for t in tests}, "판정": v})
    return R, pd.DataFrame(verdict)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    g, v, fx = load("GSPC"), load("VIX"), load("KRW")
    fx = fx[(fx > 800) & (fx < 2000)]
    S, dd, ath = signals(g, v)
    # 룩어헤드 점검: 2010-12-31까지만 잘라서 계산한 신호가 전체 계산과 같아야 한다
    S2, _, _ = signals(g.loc[:"2010-12-31"], v.loc[:"2010-12-31"])
    assert (S2 == S.loc[:"2010-12-31"]).all().all(), "룩어헤드 의심"
    E1, T1 = event_study(g, v, S, dd, ath, "달러", None)
    k = (g * fx.reindex(g.index).ffill()).dropna()
    k = k[k.index >= "2003-12-01"]
    Sk = S.reindex(k.index).fillna(False)
    E2, T2 = event_study(k, v, Sk, dd.reindex(k.index), k.cummax(), "원화", None)  # 회복은 원화 자체 고점 기준
    T2 = T2[T2.period == "검증"].assign(period="2004~")
    E = pd.concat([E1, E2])
    T = pd.concat([T1, T2])
    E.to_csv(RES / "P5_events.csv", index=False, encoding="utf-8-sig")
    T.to_csv(RES / "P5_event_stats.csv", index=False, encoding="utf-8-sig")
    R, V = f6(g, S, ath, None)
    R.to_csv(RES / "P5_F6.csv", index=False, encoding="utf-8-sig")
    V.to_csv(RES / "P5_F6_verdict.csv", index=False, encoding="utf-8-sig")

    o = ["룩어헤드 점검 통과 (2010-12-31 절단 신호 = 전체 신호)", ""]
    for (st, pn), grp in T.groupby(["set", "period"], sort=False):
        o.append(f"[사건연구 {st} {pn}] (수익=다음날 종가 진입, 초과=같은 구간 모든 날 평균 대비, t=연도 군집)")
        for _, r in grp.iterrows():
            cells = " | ".join(f"{k} {r[f'{k}_mean']:+.1%} (초과 {r[f'{k}_excess']:+.1%}, t {r[f'{k}_t']:.1f}, 승 {r[f'{k}_win']:.0%})"
                               if r.N else f"{k} -" for k in HZ)
            o.append(f"  {r.signal:<22} N{r.N:>4} ({r.years}년) | {cells} | 12M내 추가최저 중앙 {r.maxdown12M_med:+.1%} | 고점회복 중앙 {r.recover_med:.0f}일")
        o.append("")
    o.append("[F6 80/20 → 공포 시 90/10]")
    for tn, grp in R.groupby("test", sort=False):
        o.append(f"  {tn}")
        for _, r in grp.iterrows():
            o.append(f"    {r.rule:<22} 연 {r.CAGR:6.2%}  MDD {r.MDD:6.1%}  Sharpe {r.Sharpe:.3f}  공포상태 {r.fear_share:4.0%}  변경/년 {r.chg_per_yr:.2f}")
    o.append("")
    o.append(V.to_string(index=False))
    o.append("")
    o.append("[지금] 2026-11-20 S&P 고점대비 {:+.1%}, VIX {:.1f}".format(dd.iloc[-1], v.iloc[-1]))
    last = {c: S.index[S[c]].max().date() if S[c].any() else None for c in S.columns}
    o.append("  각 신호 마지막 발생일: " + ", ".join(f"{c}={d}" for c, d in last.items()))
    txt = "\n".join(o)
    (RES / "P5_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
