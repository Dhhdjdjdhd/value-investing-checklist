"""I. 국내주식 전략 여러 개 (00_연구계획 §I). 가격·배당만 사용.

실행: py src/kr_quant.py -> results/I_cross.csv, I_series.csv, I_cases.txt, I_summary.txt
"""
import numpy as np
import pandas as pd

from alloc import RES, yahoo
from dipbuy import bench
from kr_data import CODES, load_all

COST = 0.003
N = 20
IS, OOS, ALL = ("2003-01", "2014-12"), ("2015-01", "2026-10"), ("2003-01", "2026-10")
END = "2026-10"


def panel():
    raw = load_all()
    C, R, D = {}, {}, {}
    bad = []
    for code, m in raw.items():
        m = m.loc[:END]
        ok = (m.adj > 0) & (m.adj.shift(1) > 0)
        r = m.adj.pct_change().where(ok, m.close.pct_change())
        if (~ok).iloc[1:].any():
            bad.append(f"{code}:{int((~ok).iloc[1:].sum())}")
        C[code], R[code], D[code] = m.close, r, m["div"]
    C, R, D = pd.DataFrame(C).sort_index(), pd.DataFrame(R).sort_index(), pd.DataFrame(D).sort_index().fillna(0)
    ext = R.stack()
    ext = ext[(ext > 2) | (ext < -0.8)]
    R = R.mask(R > 2)  # 합병·분할 기록 오류(하이트진로 2009-10 +1349% 등) — 그 달은 수익 없음으로 처리
    return C, R, D, bad, ext


def signals(C, R, D, t):
    i = R.index.get_loc(t)
    if i < 12:
        return None
    win = R.iloc[i - 11:i + 1]
    elig = win.notna().sum() >= 12
    elig &= C.iloc[i].notna()
    s = pd.DataFrame(index=R.columns)
    s["vol"] = win.std()
    s["r1"] = R.iloc[i]
    s["r3"] = (1 + R.iloc[i - 2:i + 1]).prod() - 1
    s["mom"] = (1 + R.iloc[i - 11:i]).prod() - 1
    s["hi"] = C.iloc[i] / C.iloc[i - 11:i + 1].max()
    s["dy"] = D.iloc[i - 11:i + 1].sum() / C.iloc[i]
    return s[elig]


def pick(rule, s):
    if rule == "C1":
        return s.vol.nsmallest(N).index
    if rule == "C2":
        return s[s.vol <= s.vol.quantile(0.7)].index
    if rule == "C3":
        return s.r1.nsmallest(N).index
    if rule == "C3b":
        return s.r3.nsmallest(N).index
    if rule == "C4":
        return s.mom.nlargest(N).index
    if rule == "C5":
        return s.hi.nlargest(N).index
    if rule == "C6":
        return s.dy.nlargest(N).index
    if rule == "C7":
        sc = s.dy.rank(ascending=False) + s.vol.rank()
        return sc.nsmallest(N).index
    raise ValueError(rule)


REB = {"C1": "Q", "C2": "Q", "C3": "M", "C3b": "Q", "C4": "Q", "C5": "H", "C6": "Q", "C7": "Q"}
NAMES = {"C1": "저변동성", "C2": "고변동성 제외", "C3": "단기 반전 1개월", "C3b": "단기 반전 3개월",
         "C4": "모멘텀 12-1 (대조군)", "C5": "52주 고점 근접", "C6": "고배당", "C7": "배당+저변동성"}


def is_reb(m, freq):
    mm = m[5:]
    return freq == "M" or (freq == "Q" and mm in ("03", "06", "09", "12")) or (freq == "H" and mm in ("06", "12"))


def run_rule(rule, C, R, D, sig):
    months = [m for m in R.index if "2002-12" <= m < END]
    w = pd.Series(dtype=float)
    out, turn = {}, 0.0
    for k, t in enumerate(months):
        nxt = R.index[R.index.get_loc(t) + 1]
        cost = 0.0
        if (rule == "EW" or is_reb(t, REB.get(rule, "M")) or w.empty) and sig.get(t) is not None:
            s = sig[t]
            names = s.index if rule == "EW" else pick(rule, s)
            new = pd.Series(1 / len(names), index=names)
            dw = new.sub(w, fill_value=0).abs().sum()
            if rule != "EW":
                cost = dw * COST
                turn += dw / 2
            w = new
        r = R.loc[nxt, w.index].fillna(0)
        pr = float((w * r).sum())
        out[nxt] = (1 - cost) * (1 + pr) - 1
        w = w * (1 + r)
        w = w / w.sum()
    s = pd.Series(out)
    return s, turn / (len(s) / 12)


def stats(r, cash, a, b):
    r = r.loc[a:b].dropna()
    e = (1 + r).cumprod()
    ex = r - cash.reindex(r.index).fillna(0)
    return {"CAGR": e.iloc[-1] ** (12 / len(r)) - 1, "vol": r.std() * np.sqrt(12),
            "Sharpe": ex.mean() / ex.std() * np.sqrt(12), "MDD": (e / e.cummax() - 1).min()}


def main():
    C, R, D, bad, ext = panel()
    B = bench()
    lines = [f"종목 {R.shape[1]}개, 수정주가 이상 대체: {', '.join(bad) or '없음'}",
             f"월수익 +200% 초과 또는 −80% 미만 {len(ext)}건(데이터 확인용): " +
             ", ".join(f"{c}@{m} {v:+.0%}" for (m, c), v in ext.items())[:600]]
    sig = {t: signals(C, R, D, t) for t in R.index if "2002-12" <= t < END}
    n_el = pd.Series({t: len(s) for t, s in sig.items() if s is not None})
    lines.append(f"후보 종목 수: 2003-01 {n_el.iloc[0]}, 2010-01 {n_el.get('2010-01')}, 2026-10 직전 {n_el.iloc[-1]}")

    series, rows = {}, []
    ew, _ = run_rule("EW", C, R, D, sig)
    series["EW"] = ew
    for rule in ["C1", "C2", "C3", "C3b", "C4", "C5", "C6", "C7"]:
        s, to = run_rule(rule, C, R, D, sig)
        series[rule] = s
        rec = {"code": rule, "name": NAMES[rule], "회전율/년": to}
        for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", ALL)):
            st, se = stats(s, B.cash, a, b), stats(ew, B.cash, a, b)
            rec.update({f"{tag} CAGR": st["CAGR"], f"{tag} Sharpe": st["Sharpe"], f"{tag} MDD": st["MDD"],
                        f"{tag} ΔSharpe": st["Sharpe"] - se["Sharpe"]})
        rec["판정"] = ("추천" if rec["학습 ΔSharpe"] >= 0.10 and rec["검증 ΔSharpe"] > 0 else
                     "보류" if rec["학습 ΔSharpe"] >= 0.10 else "탈락")
        rows.append(rec)
    T = pd.DataFrame(rows)
    ref = []
    for nm, s in (("같은 우주 EW", ew), ("코스피", B.K), ("S&P500 원화", B.S)):
        rec = {"name": nm}
        for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", ALL)):
            st = stats(s, B.cash, a, b)
            rec.update({f"{tag} CAGR": st["CAGR"], f"{tag} Sharpe": st["Sharpe"], f"{tag} MDD": st["MDD"]})
        ref.append(rec)
    T = pd.concat([T, pd.DataFrame(ref)], ignore_index=True)
    T.to_csv(RES / "I_cross.csv", index=False, encoding="utf-8-sig")
    S = pd.DataFrame(series)
    S["K"], S["S"] = B.K, B.S
    S.loc["2003-01":END].to_csv(RES / "I_series.csv", encoding="utf-8-sig")

    show = T.copy()
    for c in show.columns:
        if c not in ("code", "name", "판정"):
            show[c] = show[c].map(lambda x: "" if pd.isna(x) else (f"{x:+.2f}" if "Sharpe" in c else f"{x:.1%}"))
    pd.set_option("display.width", 300)
    lines += ["", "종목 선택 전략 (기준선 = 같은 우주 EW):", show.to_string(index=False)]
    corr = S.loc["2003-01":END, ["C1", "C2", "C6", "C7", "EW", "K", "S"]].corr().round(2)
    lines += ["", "상관 (2003~):", corr.to_string()]

    lines += ["", cases(C, R, B)]
    rec = T[T.판정 == "추천"]
    if len(rec):
        lines += ["", mix(series, rec.code.tolist(), B)]
    else:
        lines += ["", "추천 전략 없음 → 은퇴 플랜 혼합 비교는 하지 않음(사전 등록)."]
    txt = "\n".join(lines)
    (RES / "I_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


def cases(C, R, B):
    out = []
    # T1 삼성 우선주 스위칭
    rc, rp = R["005930"], R["005935"]
    disc = 1 - C["005935"] / C["005930"]
    m36 = disc.rolling(36, min_periods=36).mean()
    hold = (disc > m36).astype(float).where(m36.notna())
    h = hold.shift(1)
    sw = h.diff().abs().fillna(0)
    t1 = (h * rp + (1 - h) * rc - sw * COST * 2).where(h.notna())
    out.append("T1 삼성 우선주 스위칭 (연수익 / MDD):")
    for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", ALL)):
        st = {k: stats(s, B.cash, a, b) for k, s in (("스위칭", t1), ("보통주", rc), ("우선주", rp))}
        out.append(f"  {tag}: " + " | ".join(f"{k} {v['CAGR']:.1%} / {v['MDD']:.0%}" for k, v in st.items()))
    a_ok = all(stats(t1, B.cash, a, b)["CAGR"] > stats(rc, B.cash, a, b)["CAGR"] for a, b in (IS, OOS))
    out.append(f"  우선주 보유 비율 {h.loc[ALL[0]:END].mean():.0%}, 전환 {int(sw.loc[ALL[0]:END].sum())}회 → "
               f"{'추천' if a_ok else '근거 부족'}")
    out.append(f"  현재 괴리율 {disc.iloc[-1]:.1%}, 36개월 평균 {m36.iloc[-1]:.1%}")

    # T2 반도체 바닥 진입
    sox = yahoo("^SOX").loc[:END]
    ath = sox.cummax()
    dd = sox / ath - 1
    basket = (R["005930"] + R["000660"]) / 2
    ev, armed = [], True
    for m in sox.index:
        if m < "2000-07":
            continue
        if not armed and sox[m] >= 0.8 * ath[m]:
            armed = True
        if armed and dd[m] <= -0.3:
            armed = False
            i = R.index.get_loc(m) if m in R.index else None
            g = lambda s: float((1 + s.loc[m:].iloc[1:25].fillna(0)).prod() - 1) if len(s.loc[m:]) > 24 else np.nan
            ev.append({"month": m, "SOX dd": dd[m], "삼성+하닉 24개월": g(basket), "코스피": g(B.K), "S&P": g(B.S)})
    E = pd.DataFrame(ev)
    out += ["", "T2 반도체 바닥 진입 (SOX 고점 대비 −30%, 24개월 보유):",
            E.to_string(index=False, float_format=lambda x: f"{x:+.0%}")]
    F = E.dropna()
    if len(F):
        d = F["삼성+하닉 24개월"] - F["코스피"]
        ymed = d.groupby(F.month.str[:4]).median().median()
        ok = d.median() > 0 and (d > 0).mean() >= 0.6 and ymed > 0
        out.append(f"  대 코스피: 중앙값 {d.median():+.0%}, 이긴 비율 {(d > 0).mean():.0%}, 연도별 {ymed:+.0%} → "
                   f"{'지지' if ok else '근거 부족'} (사건 {len(F)}건)")

    # T3 코스피 ↔ S&P 상대 모멘텀
    k12 = (1 + B.K).rolling(12).apply(np.prod, raw=True)
    s12 = (1 + B.S).rolling(12).apply(np.prod, raw=True)
    pos = (k12 > s12).astype(float).where(k12.notna() & s12.notna()).shift(1)  # 1 = 코스피
    sw = pos.diff().abs().fillna(0)
    t3 = (pos * B.K + (1 - pos) * B.S - sw * COST * 2).where(pos.notna())
    half = (B.K + B.S) / 2
    out += ["", "T3 코스피↔S&P 상대 모멘텀 (CAGR / MDD):"]
    verdict = True
    for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", ALL)):
        st = {k: stats(s, B.cash, a, b) for k, s in (("전환", t3), ("S&P", B.S), ("코스피", B.K), ("50:50(매월)", half))}
        out.append(f"  {tag}: " + " | ".join(f"{k} {v['CAGR']:.1%} / {v['MDD']:.0%}" for k, v in st.items()))
        if tag != "전체":
            verdict &= st["전환"]["CAGR"] >= st["S&P"]["CAGR"] + 0.005 and st["전환"]["MDD"] >= st["S&P"]["MDD"] - 0.03
    out.append(f"  코스피 보유 비율 {pos.loc[ALL[0]:END].mean():.0%}, 전환 {int(sw.loc[ALL[0]:END].sum())}회 → "
               f"{'추천' if verdict else '근거 부족'}")
    return "\n".join(out)


def mix(series, codes, B):
    from mix import assets
    A = assets()
    out = ["은퇴 플랜 혼합 (2003-01~2026-10, 연 1회 12월 말 리밸런싱, CAGR / MDD):"]

    def run(w):
        R = pd.DataFrame({k: (A["eq"] if k == "eq" else A["b30h"] if k == "b30h" else series[k]) for k in w}).loc[ALL[0]:END]
        v = dict(w)
        eq = []
        for m, r in R.iterrows():
            v = {k: v[k] * (1 + (r[k] if np.isfinite(r[k]) else 0)) for k in v}
            tot = sum(v.values())
            eq.append(tot)
            if m.endswith("-12"):
                v = {k: tot * w[k] for k in w}
        e = pd.Series(eq, index=R.index)
        return e.iloc[-1] ** (12 / len(e)) - 1, (e / e.cummax() - 1).min()

    base = run({"eq": .8, "b30h": .2})
    out.append(f"  80/20: {base[0]:.1%} / {base[1]:.0%}")
    for c in codes:
        r = run({"eq": .7, c: .1, "b30h": .2})
        out.append(f"  S&P70 / {c} 10 / 국채 20: {r[0]:.1%} / {r[1]:.0%}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
