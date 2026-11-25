"""K. 국내주식 재설계 (00_연구계획 §K). 실행: py src/kr_redesign.py -> results/K_*.csv, K_summary.txt"""
import sys

import numpy as np
import pandas as pd

import kr_quant as Q
from alloc import DATA, RES, yahoo
from dipbuy import bench
from kr_data import CODES

COST = 0.003
END = "2026-10"
IS, OOS, ALL = ("2001-01", "2012-12"), ("2013-01", "2026-10"), ("2001-01", "2026-10")
pct = lambda x: f"{x:+.0%}"
q3 = lambda s: f"25% {s.quantile(.25):+.0%} / 중앙 {s.median():+.0%} / 75% {s.quantile(.75):+.0%}"


def fwd(r, t, n):
    i = r.index.get_loc(t)
    seg = r.iloc[i + 1:i + 1 + n]
    return float((1 + seg.fillna(0)).prod() - 1) if len(seg) == n else np.nan


# ── K1 ──────────────────────────────────────────────
def k1(C, R, B, ew):
    rows = []
    for code in C.columns:
        c = C[code].dropna()
        last = -99
        for i in range(12, len(c)):
            if i - last < 12:
                continue
            w = c.iloc[i - 6:i]
            pk = w.max()
            if c.iloc[i] > 0.7 * pk:
                continue
            ip = c.index.get_loc(w.idxmax())
            pre = c.iloc[max(0, ip - 6):ip]
            if len(pre) < 3:
                continue
            surge = pk >= 1.8 * pre.min()
            t = c.index[i]
            last = i
            rec = {"code": code, "name": CODES[code], "month": t, "year": t[:4], "surge": surge,
                   "dd": c.iloc[i] / pk - 1, "runup": pk / pre.min() - 1}
            for n in (12, 24, 36):
                rec[f"s{n}"], rec[f"k{n}"], rec[f"e{n}"] = fwd(R[code], t, n), fwd(B.K, t, n), fwd(ew, t, n)
            fut = c.iloc[i + 1:i + 25]
            rec["further"] = fut.min() / c.iloc[i] - 1 if len(fut) else np.nan
            rows.append(rec)
    E = pd.DataFrame(rows)
    E.to_csv(RES / "K1_events.csv", index=False, encoding="utf-8-sig")
    out = ["K1 급등 뒤 급락 국면"]
    for lab, G in (("사건군(직전 급등 있음)", E[E.surge]), ("대조군(급등 없음)", E[~E.surge])):
        F = G.dropna(subset=["s24", "k24"])
        d = F.s24 - F.k24
        ym = d.groupby(F.year).median().median()
        ok = d.median() > 0 and (d > 0).mean() >= 0.6 and ym > 0
        out.append(f"  {lab}: 사건 {len(G)}건(24개월 완료 {len(F)})")
        for n in (12, 24, 36):
            H = G.dropna(subset=[f"s{n}", f"k{n}"])
            out.append(f"    {n}개월: 종목 {q3(H[f's{n}'])} | 코스피 중앙 {H[f'k{n}'].median():+.0%} | 우주EW 중앙 {H[f'e{n}'].median():+.0%}"
                       f" | 손실 비율 {(H[f's{n}'] < 0).mean():.0%}")
        out.append(f"    24개월 대 코스피: 중앙값 {d.median():+.0%}, 이긴 비율 {(d > 0).mean():.0%}, 연도별 {ym:+.0%} → {'지지' if ok else '근거 부족'}")
        out.append(f"    매수 뒤 24개월 안 추가 하락: {q3(G.further.dropna())}, −20% 넘게 더 빠진 비율 {(G.further < -0.2).mean():.0%}")
    S = E[E.surge]
    for lab, G in (("2000~2008", S[S.year <= "2008"]), ("2009~", S[S.year >= "2009"])):
        F = G.dropna(subset=["s24", "k24"])
        if len(F):
            out.append(f"  (사후) 사건군 {lab}: {len(F)}건, 종목 {F.s24.median():+.0%} vs 코스피 {F.k24.median():+.0%}, 이긴 비율 {((F.s24 - F.k24) > 0).mean():.0%}")
    big = S[S.code.isin(["005930", "000660", "005380", "000270", "051910", "006400", "035420", "005490"])]
    out.append("  대형주 사례:\n" + big[["name", "month", "runup", "dd", "s12", "s24", "k24", "further"]]
               .to_string(index=False, float_format=pct))
    return "\n".join(out)


# ── K2 ──────────────────────────────────────────────
def k2(C, R, B):
    cash = B.cash
    rows = []
    for code in C.columns:
        c = C[code].dropna()
        r = R[code].reindex(c.index)
        hi = c.rolling(12, min_periods=12).max()
        ma = c.rolling(10, min_periods=10).mean()
        armed = True
        for i in range(12, len(c) - 36):
            dd = c.iloc[i] / hi.iloc[i] - 1
            if not armed and dd >= -0.10:
                armed = True
            if not (armed and dd <= -0.30):
                continue
            armed = False
            g = [1 + (r.iloc[i + k] if np.isfinite(r.iloc[i + k]) else 0) for k in range(1, 37)]
            cs = [1 + (cash.get(c.index[i + k], 0) or 0) for k in range(1, 37)]

            def path(buy):  # buy[k] = k개월째 말(0=사건 달)에 투입하는 비중
                sh, mo, vals = 0.0, 1.0, []
                for k in range(0, 37):
                    if k > 0:
                        sh *= g[k - 1]
                        mo *= cs[k - 1]
                    if buy.get(k):
                        amt = min(buy[k], 1.0) * 1.0
                        amt = min(amt, mo) if k < max(buy) else mo
                        sh += amt * (1 - COST)
                        mo -= amt
                    vals.append(sh + mo)
                v = pd.Series(vals)
                return v.iloc[-1] - 1, (v / v.cummax() - 1).min()

            kT = next((k for k in range(0, 13) if c.iloc[i + k] > ma.iloc[i + k]), 12)
            L, D, T = path({0: 1.0}), path({k: 1 / 12 for k in range(12)}), path({kT: 1.0})
            rows.append({"code": code, "name": CODES[code], "month": c.index[i], "dd": dd, "wait_T": kT,
                         "L": L[0], "D": D[0], "T": T[0], "L_mdd": L[1], "D_mdd": D[1], "T_mdd": T[1]})
    E = pd.DataFrame(rows)
    E.to_csv(RES / "K2_entry.csv", index=False, encoding="utf-8-sig")
    out = [f"K2 진입 방법 (사건 {len(E)}건, 36개월 뒤)"]
    for m, lab in (("L", "한 번에"), ("D", "12개월 분할"), ("T", "추세 확인 후")):
        out.append(f"  {lab}: 수익 {q3(E[m])} | 손실 비율 {(E[m] < 0).mean():.0%} | 보유 중 최대 낙폭 중앙 {E[m + '_mdd'].median():+.0%}, 하위 25% {E[m + '_mdd'].quantile(.25):+.0%}")
    for m, lab in (("D", "분할"), ("T", "추세 확인")):
        d = E[m] - E.L
        ok = d.median() > 0 and (d > 0).mean() >= 0.5
        out.append(f"  {lab} − 한 번에: 중앙값 {d.median():+.1%}, 이긴 비율 {(d > 0).mean():.0%} → {'낫다' if ok else '낫지 않다'}"
                   f" | 낙폭 개선 중앙 {(E[m + '_mdd'] - E.L_mdd).median():+.1%}p")
    out.append(f"  추세 확인까지 기다린 개월: 중앙 {E.wait_T.median():.0f}, 12개월 기한에 걸린 비율 {(E.wait_T == 12).mean():.0%}")
    s = E[E.code == "005930"][["month", "dd", "wait_T", "L", "D", "T", "L_mdd", "T_mdd"]]
    out.append("  삼성전자 사례:\n" + s.to_string(index=False, float_format=pct))
    return "\n".join(out)


# ── K3 ──────────────────────────────────────────────
def macro():
    k = pd.read_csv(DATA / "oecd_kei_kor.csv")
    ex = k[(k.MEASURE == "EX") & (k.TRANSFORMATION == "GY")].set_index("TIME_PERIOD").OBS_VALUE.sort_index()
    c = pd.read_csv(DATA / "oecd_cli_kor.csv").set_index("TIME_PERIOD").OBS_VALUE.sort_index()
    return ex, c


def k3(R, B):
    ex, cli = macro()
    idx = B.index
    px = yahoo("^KS11").reindex(idx)
    exl = ex.reindex(idx).shift(1)            # t월 말에 아는 수출 = t-1월분
    ex3 = ex.rolling(3).mean().reindex(idx).shift(1)
    cl = cli.reindex(idx).shift(2)            # CLI는 t-2월분
    sig = pd.DataFrame({
        "M1 수출 전년비>0": exl > 0,
        "M2 수출 모멘텀": ex3 > ex3.shift(3),
        "M3 CLI 상승": cl > cl.shift(1),
        "M4 10개월 평균 위": px > px.rolling(10).mean(),
    })
    sig["M5 수출 모멘텀+추세"] = sig["M2 수출 모멘텀"] & sig["M4 10개월 평균 위"]
    st = lambda s, p: Q.stats(s, B.cash, *p)
    out = ["K3 경기 신호 타이밍 (코스피)"]
    series, rec_a, rec_b = {}, [], []
    base = {tag: st(B.K, p) for tag, p in (("학습", IS), ("검증", OOS), ("전체", ALL))}
    sp = {tag: st(B.S, p) for tag, p in (("학습", IS), ("검증", OOS), ("전체", ALL))}
    out.append("  기준: 코스피 보유 " + " | ".join(f"{t} {v['CAGR']:.1%}/{v['MDD']:.0%}/S{v['Sharpe']:.2f}" for t, v in base.items()))
    out.append("  기준: S&P 100%   " + " | ".join(f"{t} {v['CAGR']:.1%}/{v['MDD']:.0%}/S{v['Sharpe']:.2f}" for t, v in sp.items()))
    for name in sig:
        pos = sig[name].astype(float).shift(1)
        sw = pos.diff().abs().fillna(0)
        a = pos * B.K + (1 - pos) * B.cash - sw * COST
        b = pos * B.K + (1 - pos) * B.S - sw * COST * 2
        series[name + " (a)"], series[name + " (b)"] = a, b
        A = {tag: st(a, p) for tag, p in (("학습", IS), ("검증", OOS), ("전체", ALL))}
        Bb = {tag: st(b, p) for tag, p in (("학습", IS), ("검증", OOS), ("전체", ALL))}
        d1, d2 = A["학습"]["Sharpe"] - base["학습"]["Sharpe"], A["검증"]["Sharpe"] - base["검증"]["Sharpe"]
        mdd_ok = A["학습"]["MDD"] >= base["학습"]["MDD"] and A["검증"]["MDD"] >= base["검증"]["MDD"]
        va = "추천" if d1 >= 0.10 and d2 > 0 and mdd_ok else "보류" if d1 >= 0.10 else "탈락"
        okb = all(Bb[t]["CAGR"] >= sp[t]["CAGR"] + 0.005 and Bb[t]["MDD"] >= sp[t]["MDD"] - 0.03 for t in ("학습", "검증"))
        on = pos.loc[ALL[0]:END].mean()
        n_sw = int(sw.loc[ALL[0]:END].sum())
        out.append(f"  {name} — 보유 비율 {on:.0%}, 전환 {n_sw}회")
        out.append("    (a) 대기=현금: " + " | ".join(f"{t} {v['CAGR']:.1%}/{v['MDD']:.0%}/S{v['Sharpe']:.2f}" for t, v in A.items())
                   + f" → ΔSharpe {d1:+.2f}/{d2:+.2f} {va}")
        out.append("    (b) 대기=S&P : " + " | ".join(f"{t} {v['CAGR']:.1%}/{v['MDD']:.0%}/S{v['Sharpe']:.2f}" for t, v in Bb.items())
                   + f" → {'추천' if okb else '근거 부족'}")
        rec_a.append((name, va))
        rec_b.append((name, okb))
    # 삼성전자 참고
    rs = R["005930"].reindex(idx)
    out.append("  참고 — 같은 신호를 삼성전자에 (대기=현금, 전체 CAGR/MDD): 보유 "
               f"{st(rs, ALL)['CAGR']:.1%}/{st(rs, ALL)['MDD']:.0%}")
    for name in sig:
        pos = sig[name].astype(float).shift(1)
        s = pos * rs + (1 - pos) * B.cash - pos.diff().abs().fillna(0) * COST
        out.append(f"    {name}: {st(s, ALL)['CAGR']:.1%}/{st(s, ALL)['MDD']:.0%} (검증 {st(s, OOS)['CAGR']:.1%}/{st(s, OOS)['MDD']:.0%})")
    now = sig.iloc[-1]
    out.append(f"  현재 신호({sig.index[-1]} 말): " + ", ".join(f"{k.split()[0]} {'켜짐' if v else '꺼짐'}" for k, v in now.items())
               + f" | 수출 전년비 {exl.iloc[-1]:+.1f}%, CLI {cl.iloc[-1]:.2f} (전월 {cl.shift(1).iloc[-1]:.2f})")
    pd.DataFrame(series).loc[ALL[0]:END].to_csv(RES / "K3_series.csv", encoding="utf-8-sig")
    return "\n".join(out), series, [n for n, v in rec_a if v == "추천"], [n for n, ok in rec_b if ok]


# ── K4 ──────────────────────────────────────────────
def k4(C, R, B):
    months = [m for m in R.index if "2002-12" <= m < END]
    w = we = pd.Series(dtype=float)
    o, oe = {}, {}
    for t in months:
        i = R.index.get_loc(t)
        nxt = R.index[i + 1]
        cost = 0.0
        if (t[5:] == "12" or w.empty) and i >= 60:
            win = R.iloc[i - 59:i - 11]
            lt = ((1 + win).prod() - 1)[win.notna().sum() >= 48]
            lt = lt[C.iloc[i].reindex(lt.index).notna()]
            if len(lt) >= 40:
                new = pd.Series(1 / 20, index=lt.nsmallest(20).index)
                cost = new.sub(w, fill_value=0).abs().sum() * COST
                w, we = new, pd.Series(1 / len(lt), index=lt.index)
        if w.empty:
            continue
        r = R.loc[nxt, w.index].fillna(0)
        o[nxt] = (1 - cost) * (1 + float((w * r).sum())) - 1
        w = w * (1 + r); w /= w.sum()
        re = R.loc[nxt, we.index].fillna(0)
        oe[nxt] = float((we * re).sum())
        we = we * (1 + re); we /= we.sum()
    s, e = pd.Series(o), pd.Series(oe)
    a0 = s.index[0]
    out = [f"K4 장기 소외주 (시작 {a0})"]
    d = {}
    for tag, p in (("학습", (a0, "2014-12")), ("검증", ("2015-01", END)), ("전체", (a0, END))):
        x, y = Q.stats(s, B.cash, *p), Q.stats(e, B.cash, *p)
        d[tag] = x["Sharpe"] - y["Sharpe"]
        out.append(f"  {tag}: 소외주 {x['CAGR']:.1%}/{x['MDD']:.0%}/S{x['Sharpe']:.2f} | 같은 후보 동일비중 {y['CAGR']:.1%}/{y['MDD']:.0%}/S{y['Sharpe']:.2f}")
    out.append(f"  ΔSharpe 학습 {d['학습']:+.2f} / 검증 {d['검증']:+.2f} → "
               f"{'추천' if d['학습'] >= 0.10 and d['검증'] > 0 else '보류' if d['학습'] >= 0.10 else '탈락'}")
    return "\n".join(out)


def k5(series, names, B):
    from mix import assets
    A = assets()
    out = ["K5 은퇴 플랜 혼합 (2001-01~2026-10, 연 1회 리밸런싱, CAGR / MDD)"]

    def run(w, extra=None):
        cols = {"eq": A["eq"], "b30h": A["b30h"]}
        if extra is not None:
            cols["x"] = extra
        Rr = pd.DataFrame(cols).loc[ALL[0]:END]
        v, eq = dict(w), []
        for m, r in Rr.iterrows():
            v = {k: v[k] * (1 + (r[k] if np.isfinite(r[k]) else 0)) for k in v}
            tot = sum(v.values()); eq.append(tot)
            if m.endswith("-12"):
                v = {k: tot * w[k] for k in w}
        e = pd.Series(eq, index=Rr.index)
        res = [e.iloc[-1] ** (12 / len(e)) - 1, (e / e.cummax() - 1).min()]
        for a, b in (("2007-11", "2009-02"), ("2022-01", "2022-10")):
            seg = e.loc[a:b]; res.append(seg.iloc[-1] / e.loc[:a].iloc[-2] - 1)
        return res

    f = lambda r: f"{r[0]:.1%} / {r[1]:.0%} | 금융위기 {r[2]:+.0%}, 2022 {r[3]:+.0%}"
    out.append("  80/20: " + f(run({"eq": .8, "b30h": .2})))
    out.append("  S&P70 / 코스피 보유 10 / 국채 20: " + f(run({"eq": .7, "x": .1, "b30h": .2}, B.K)))
    for n in names:
        out.append(f"  S&P70 / [{n}] 10 / 국채 20: " + f(run({"eq": .7, "x": .1, "b30h": .2}, series[n + " (a)"])))
    return "\n".join(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    C, R, D, _, _ = Q.panel()
    B = bench()
    sig = {t: Q.signals(C, R, D, t) for t in R.index if "2000-12" <= t < END}
    ew = R.mean(axis=1)  # 사건 연구 비교용: 그 달 자료가 있는 종목 단순 평균
    parts = [k1(C, R, B, ew), k2(C, R, B)]
    t3, series, rec_a, rec_b = k3(R, B)
    parts += [t3, k4(C, R, B)]
    parts.append(k5(series, rec_a, B) if rec_a else "K5: K3 (a)에 '추천' 없음 → 은퇴 플랜 혼합 비교 안 함(사전 등록).")
    txt = "\n\n".join(parts)
    (RES / "K_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
