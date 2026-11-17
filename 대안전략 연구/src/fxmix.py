"""G. 80:20 + 주식 몫 환헤지 전환 (원화, 월간). 00_연구계획 §G.

실행: py src/fxmix.py -> results/G_fxmix.csv, G_crisis.csv
"""
import numpy as np
import pandas as pd

from alloc import RES, build

COST = 0.001
IS, OOS, ALL, EX = ("1991-04", "2008-12"), ("2009-01", "2026-10"), ("1991-04", "2026-10"), ("1999-01", "2026-10")
CRISES = {"닷컴 00.09~03.02": ("2000-09", "2003-02"), "금융위기 07.11~09.02": ("2007-11", "2009-02"),
          "코로나 20.02~03": ("2020-02", "2020-03"), "금리급등 22.01~10": ("2022-01", "2022-10")}

D = build()
fx = D.fx
UN, HE = D.un, D.ru + D.carry
ma = {k: fx.rolling(k * 12, min_periods=k * 12).mean() for k in (3, 5)}


def state_rule(enter, exit_, maxm=None):
    """enter(i)가 참이면 헤지 시작, exit_(i)가 참이거나 maxm개월 지나면 복귀. (fxswitch.py와 같은 방식)"""
    st, c, n = [], 0.0, 0
    for i in range(len(fx)):
        if c == 0 and enter(i):
            c, n = 1.0, 0
        elif c == 1:
            n += 1
            if exit_(i) or (maxm and n >= maxm):
                c = 0.0
        st.append(c)
    return pd.Series(st, index=fx.index)


def rel(k, up, dn, maxm=None):
    dev = fx / ma[k] - 1
    return state_rule(lambda i: dev.iloc[i] >= up, lambda i: dev.iloc[i] < dn, maxm)


RULES = {
    "G0": ("80/20 환노출 (기준선)", pd.Series(0.0, index=fx.index)),
    "G1": ("80/20 주식 늘 헤지 (참고)", pd.Series(1.0, index=fx.index)),
    "G2": ("5년평균 +7% 헤지 / 평균 아래 복귀", rel(5, 0.07, 0.0)),
    "G3": ("5년평균 +10% 헤지 / +3% 아래 복귀", rel(5, 0.10, 0.03)),
    "G4": ("3년평균 +7% 헤지 / 평균 아래 복귀", rel(3, 0.07, 0.0)),
    "G5": ("5년평균 +7% 헤지 / 평균 아래·12개월 복귀", rel(5, 0.07, 0.0, 12)),
    "G6": ("현재 규칙 1,450 / 1,350·12개월 (참고)", state_rule(lambda i: fx.iloc[i] >= 1450, lambda i: fx.iloc[i] < 1350, 12)),
}


def sim(h, a, b):
    """주식 80%(h=1이면 헤지 수익) + 30년 국채 헤지 20%, 12월 말 리밸런싱."""
    w = h.shift(1)  # 월말 신호 → 다음 달
    idx = list(D.loc[a:b].index)
    ve, vb = 0.8, 0.2
    eq, prev, sw, hed = [], None, 0, 0
    for m in idx:
        s = w.loc[m]
        if prev is not None and s != prev:
            ve *= 1 - COST * 2
            sw += 1
        prev = s
        hed += s
        ve *= 1 + (HE.loc[m] if s == 1 else UN.loc[m])
        vb *= 1 + D.bh.loc[m]
        tot = ve + vb
        eq.append(tot)
        if m.endswith("-12"):
            turn = abs(ve / tot - 0.8)
            tot *= 1 - turn * COST * 2
            ve, vb = tot * 0.8, tot * 0.2
    e = pd.Series(eq, index=idx)
    yrs = len(e) / 12
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "MDD": (e / e.cummax() - 1).min(), "worst_yr": yr.min(),
            "worst_at": yr.idxmin(), "hedge_ratio": hed / len(e), "switch_n": sw}, e


def main():
    rows, cr = [], []
    for k, (name, h) in RULES.items():
        assert not h.shift(1).loc[ALL[0]:ALL[1]].isna().any()
        rec = {"rule": k, "name": name}
        for tag, p in (("IS", IS), ("OOS", OOS), ("ALL", ALL), ("EX99", EX)):
            rec.update({f"{tag}_{x}": y for x, y in sim(h, *p)[0].items()})
        rows.append(rec)
        cr.append({"rule": k, **{c: sim(h, *p)[1].iloc[-1] - 1 for c, p in CRISES.items()}})
    T = pd.DataFrame(rows)
    b = T.set_index("rule").loc["G0"]
    ok = lambda t: (T[f"{t}_CAGR"] >= b[f"{t}_CAGR"] + 0.005) & (T[f"{t}_MDD"] >= b[f"{t}_MDD"] - 0.03)
    T["IS_pass"], T["OOS_pass"] = ok("IS"), ok("OOS")
    T["판정"] = np.where(T.rule.isin(["G0", "G1", "G6"]), "-",
                       np.where(T.IS_pass & T.OOS_pass, "추천", np.where(T.IS_pass, "보류", "탈락")))
    T.to_csv(RES / "G_fxmix.csv", index=False, encoding="utf-8-sig")
    C = pd.DataFrame(cr)
    C.to_csv(RES / "G_crisis.csv", index=False, encoding="utf-8-sig")
    f = lambda x: f"{x:.1%}"
    for _, r in T.iterrows():
        print(f"{r['rule']} {r['name']:28} 학습 {f(r.IS_CAGR)}/{f(r.IS_MDD)} | 검증 {f(r.OOS_CAGR)}/{f(r.OOS_MDD)} | "
              f"전체 {f(r.ALL_CAGR)}/{f(r.ALL_MDD)} | 99~ {f(r.EX99_CAGR)}/{f(r.EX99_MDD)} | 최악 {f(r.ALL_worst_yr)}({r.ALL_worst_at}) "
              f"헤지 {r.ALL_hedge_ratio:.0%} 전환 {r.ALL_switch_n} → {r['판정']}")
    print(C.set_index("rule").map(f).to_string())


if __name__ == "__main__":
    main()
