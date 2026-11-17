"""F. 강세장이면 주식 100%, 아니면 80/20 (원화 기준, 월간). 00_연구계획 §F.

실행: py src/timing.py -> results/F_timing.csv, F_crisis.csv
"""
import numpy as np
import pandas as pd

from alloc import RES, build

COST = 0.001
IS, OOS, ALL = ("1991-04", "2008-12"), ("2009-01", "2026-10"), ("1991-04", "2026-10")
CRISES = {"닷컴 00.09~03.02": ("2000-09", "2003-02"), "금융위기 07.11~09.02": ("2007-11", "2009-02"),
          "코로나 20.02~03": ("2020-02", "2020-03"), "금리급등 22.01~10": ("2022-01", "2022-10")}
NAMES = {"BASE": "80/20 연1회 (기준선)", "EQ100": "주식 100% (참고)", "T1": "10개월선 위면 100%",
         "T2": "12개월 수익률 > 단기금리면 100%", "T3": "T1·T2 모두 만족해야 100%"}


def signals(D):
    t1 = D.px > D.px.rolling(10).mean()
    t2 = (D.px / D.px.shift(12) - 1) > D.irx.rolling(12).mean() / 100
    return {"BASE": pd.Series(False, index=D.index), "EQ100": pd.Series(True, index=D.index),
            "T1": t1, "T2": t2, "T3": t1 & t2}


def sim(D, bull, a, b):
    """bull[t-1]이 True면 t월 주식 100%, 아니면 80/20."""
    idx = list(D.loc[a:b].index)
    pos = {m: i for i, m in enumerate(D.index)}
    v, prev, eq, sw, on = None, None, [], 0, 0
    for m in idx:
        up = bool(bull.iloc[pos[m] - 1])
        tgt = np.array([1.0, 0.0]) if up else np.array([0.8, 0.2])
        if v is None:
            v = tgt.copy()
        elif up != prev or (not up and D.index[pos[m] - 1].endswith("-12")):
            tot = v.sum()
            turn = np.abs(v / tot - tgt).sum() / 2
            v = tot * (1 - turn * COST * 2) * tgt
            sw += up != prev
        prev = up
        on += up
        r = D.loc[m, ["un", "bh"]].values.astype(float)
        v = v * (1 + r)
        eq.append(v.sum())
    e = pd.Series(eq, index=idx)
    yrs = len(e) / 12
    rr = e.pct_change().fillna(e.iloc[0] - 1)
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "MDD": (e / e.cummax() - 1).min(), "vol": rr.std() * np.sqrt(12),
            "worst_yr": yr.min(), "worst_at": yr.idxmin(), "switch_yr": sw / yrs, "eq100_ratio": on / len(e)}, e


def main():
    D = build()
    S = signals(D)
    rows, cr = [], []
    for k, s in S.items():
        rec = {"rule": k, "name": NAMES[k]}
        for tag, p in (("IS", IS), ("OOS", OOS), ("ALL", ALL)):
            rec.update({f"{tag}_{x}": y for x, y in sim(D, s, *p)[0].items()})
        rows.append(rec)
        cr.append({"rule": k, **{c: sim(D, s, *p)[1].iloc[-1] - 1 for c, p in CRISES.items()}})
    T = pd.DataFrame(rows)
    b = T.set_index("rule").loc["BASE"]
    ok = lambda r, t: (r[f"{t}_CAGR"] >= b[f"{t}_CAGR"] + 0.005) & (r[f"{t}_MDD"] >= b[f"{t}_MDD"] - 0.03)
    T["IS_pass"], T["OOS_pass"] = ok(T, "IS"), ok(T, "OOS")
    T["판정"] = np.where(T.rule.isin(["BASE", "EQ100"]), "-",
                       np.where(T.IS_pass & T.OOS_pass, "추천", np.where(T.IS_pass, "보류", "탈락")))
    T.to_csv(RES / "F_timing.csv", index=False, encoding="utf-8-sig")
    C = pd.DataFrame(cr)
    C.to_csv(RES / "F_crisis.csv", index=False, encoding="utf-8-sig")
    f = lambda x: f"{x:.1%}"
    for _, r in T.iterrows():
        print(f"{r['rule']:5} {r['name']:22} 학습 {f(r.IS_CAGR)} / {f(r.IS_MDD)} | 검증 {f(r.OOS_CAGR)} / {f(r.OOS_MDD)} | "
              f"전체 {f(r.ALL_CAGR)} / {f(r.ALL_MDD)} 최악 {f(r.ALL_worst_yr)}({r.ALL_worst_at}) 전환 {r.ALL_switch_yr:.2f}/년 "
              f"100%비율 {r.ALL_eq100_ratio:.0%} → {r['판정']}")
    print(C.set_index("rule").map(f).to_string())


if __name__ == "__main__":
    main()
