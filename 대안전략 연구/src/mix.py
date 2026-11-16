"""섞는 방법 비교 (원화 기준, 월간, 연 1회 12월 말 리밸런싱 — 밴드형은 매월 점검).

자산: eq = S&P500 환노출(360750 성격) / b30h = 30년 국채 환헤지(453850) / b30u = 30년 국채 환노출(476760 성격)
      b10h = 10년 국채 환헤지(^TNX 합성) / gold = 금(달러 금값 × 원/달러) / cash = 원화 CD91
실행: py src/mix.py -> results/C_mix.csv
"""
import numpy as np
import pandas as pd

from alloc import RES, bond_ret, build, yahoo

COST = 0.001


def assets():
    D = build()
    tnx = (yahoo("^TNX") / 100).reindex(D.index).ffill()
    gold = yahoo("GC=F").reindex(D.index)
    dfx = D.fx.pct_change()
    A = pd.DataFrame(index=D.index)
    A["eq"] = D.un
    A["b30h"] = D.bh
    A["b30u"] = (1 + (D.bh - D.carry)) * (1 + dfx) - 1
    A["b10h"] = bond_ret(tnx, 10) + D.carry
    A["gold"] = (1 + gold.pct_change()) * (1 + dfx) - 1
    A["cash"] = D.cash
    return A


MIXES = {
    "M1 주식80 / 30년헤지20 (현재 계획)": {"eq": .8, "b30h": .2},
    "M2 주식80 / 30년환노출20": {"eq": .8, "b30u": .2},
    "M3 주식80 / 10년헤지20": {"eq": .8, "b10h": .2},
    "M4 주식80 / 30년헤지10 / 금10": {"eq": .8, "b30h": .1, "gold": .1},
    "M5 주식80 / 금20": {"eq": .8, "gold": .2},
    "M6 주식80 / 원화현금20": {"eq": .8, "cash": .2},
    "M7 주식80 / 30년헤지10 / 원화현금10": {"eq": .8, "b30h": .1, "cash": .1},
    "M8 주식70 / 30년헤지30": {"eq": .7, "b30h": .3},
    "M9 주식70 / 30년헤지15 / 금15": {"eq": .7, "b30h": .15, "gold": .15},
    "M10 주식60 / 30년헤지40": {"eq": .6, "b30h": .4},
    "M11 영구포트폴리오 (주식·30년헤지·금·현금 25씩)": {"eq": .25, "b30h": .25, "gold": .25, "cash": .25},
    "M0 주식100": {"eq": 1.0},
}


def run(A, w, a, b, band=None):
    """band=None: 12월 말 리밸런싱. band=x: 매월 점검, 주식 비중이 목표±x 벗어나면 리밸런싱."""
    R = A.loc[a:b, list(w)]
    v = {k: w[k] for k in w}
    eq, n_reb = [], 0
    for m, r in R.iterrows():
        v = {k: v[k] * (1 + (r[k] if np.isfinite(r[k]) else 0.0)) for k in v}
        tot = sum(v.values())
        eq.append(tot)
        cur = {k: v[k] / tot for k in v}
        do = (band is None and m.endswith("-12")) or (band is not None and abs(cur["eq"] - w["eq"]) > band)
        if do:
            turn = sum(abs(cur[k] - w[k]) for k in w) / 2
            tot *= 1 - turn * COST * 2
            v = {k: tot * w[k] for k in w}
            n_reb += 1
    e = pd.Series(eq, index=R.index)
    r = e.pct_change().fillna(e.iloc[0] - 1)
    yrs = len(e) / 12
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * np.sqrt(12), "MDD": (e / e.cummax() - 1).min(),
            "worst_yr": yr.min(), "worst_at": yr.idxmin(), "reb_per_yr": n_reb / yrs}, e


CRISES = {"금융위기 07.11~09.02": ("2007-11", "2009-02"), "코로나 20.02~03": ("2020-02", "2020-03"),
          "금리급등 22.01~10": ("2022-01", "2022-10")}


def main():
    A = assets()
    start = A.dropna().index[0]
    print("공통 시작(금 포함):", start)
    rows = []
    for name, w in MIXES.items():
        rec = {"mix": name}
        for tag, (a, b) in (("2001~", (start, "2026-10")), ("2009~", ("2009-01", "2026-10")), ("2015~", ("2015-01", "2026-10"))):
            p, _ = run(A, w, a, b)
            rec.update({f"{tag} CAGR": p["CAGR"], f"{tag} MDD": p["MDD"]})
            if tag == "2001~":
                rec.update({"최악연도": p["worst_yr"], "최악연도_시점": p["worst_at"], "변동성": p["vol"]})
        for k, (a, b) in CRISES.items():
            _, e = run(A, w, a, b)
            rec[k] = e.iloc[-1] - 1
        rows.append(rec)
    for band in (0.05, 0.10):
        w = MIXES["M1 주식80 / 30년헤지20 (현재 계획)"]
        p, _ = run(A, w, start, "2026-10", band=band)
        p2, _ = run(A, w, "2009-01", "2026-10", band=band)
        p3, _ = run(A, w, "2015-01", "2026-10", band=band)
        rows.append({"mix": f"M1b 80/20 밴드 ±{int(band * 100)}%p (벗어날 때만)", "2001~ CAGR": p["CAGR"], "2001~ MDD": p["MDD"],
                     "2009~ CAGR": p2["CAGR"], "2009~ MDD": p2["MDD"], "2015~ CAGR": p3["CAGR"], "2015~ MDD": p3["MDD"],
                     "최악연도": p["worst_yr"], "최악연도_시점": p["worst_at"], "변동성": p["vol"],
                     **{k: run(A, w, a, b, band=band)[1].iloc[-1] - 1 for k, (a, b) in CRISES.items()},
                     "리밸런싱/년": p["reb_per_yr"]})
    d = pd.DataFrame(rows)
    d.to_csv(RES / "C_mix.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    show = d.copy()
    for c in show.columns:
        if c not in ("mix", "최악연도_시점", "리밸런싱/년"):
            show[c] = show[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "")
    print(show.to_string(index=False))
    # 상관 (2001~)
    print(A.loc[start:].corr().round(2))


if __name__ == "__main__":
    main()
