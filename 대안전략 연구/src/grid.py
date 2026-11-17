"""E. 자산배분 조합 확장 (원화 기준, 월간). 00_연구계획 §E.

자산: sp/nq/ks 주식, b30h/b10h 국채 환헤지, gold 금, krw 원화 현금, usd 달러 현금 (+ 참고: reit, cmd)
격자: 주식 50~100% × 주식 내부 3가지 × 나머지 5자산 10%p 배분 × 리밸런싱 3가지 = 2,268개
실행: py src/grid.py -> results/E_grid.csv, E_ref.csv, E_summary.txt
"""
import itertools

import numpy as np
import pandas as pd

from alloc import RES, yahoo
from mix import assets as base_assets

COST = 0.001
IS, OOS, ALL = ("2000-09", "2012-12"), ("2013-01", "2026-10"), ("2000-09", "2026-10")
COLS = ["sp", "nq", "ks", "b30h", "b10h", "gold", "krw", "usd", "reit", "cmd"]
DEF = ["b30h", "b10h", "gold", "krw", "usd"]
SLEEVES = {"S&P": {"sp": 1.0}, "S&P+나스닥": {"sp": .5, "nq": .5}, "S&P+코스피": {"sp": .7, "ks": .3}}
MODES = ["연1회", "반기", "밴드10"]
CRISES = {"닷컴 00.09~03.02": ("2000-09", "2003-02"), "금융위기 07.11~09.02": ("2007-11", "2009-02"),
          "코로나 20.02~03": ("2020-02", "2020-03"), "금리급등 22.01~10": ("2022-01", "2022-10")}
KS_DIV = 0.019


def assets():
    B = base_assets()  # eq, b30h, b10h, gold, cash (+ 내부적으로 원/달러)
    from alloc import build
    D = build()
    dfx = D.fx.pct_change()
    fxc = lambda s: (1 + s.reindex(D.index).pct_change(fill_method=None)) * (1 + dfx) - 1  # 달러 자산 → 원화
    A = pd.DataFrame(index=D.index)
    A["sp"] = B["eq"]
    A["nq"] = fxc(yahoo("QQQ", True))
    k11 = yahoo("^KS11").reindex(D.index).pct_change(fill_method=None) + KS_DIV / 12
    k200 = yahoo("069500.KS", True).reindex(D.index).pct_change(fill_method=None)
    A["ks"] = k200.where(D.index >= "2009-05", k11)  # 069500 Yahoo 2007-03~2009-04 결측
    A["b30h"], A["b10h"], A["gold"], A["krw"] = B.b30h, B.b10h, B.gold, B.cash
    A["usd"] = (1 + D.irx.shift(1) / 1200) * (1 + dfx) - 1
    A["reit"] = fxc(yahoo("VNQ", True))
    A["cmd"] = fxc(yahoo("DBC", True))
    return A[COLS]


def run(R, idx, w, eq_mask, mode):
    """R: (T, n) 월수익, w: 목표 비중(n). 첫 달 목표 비중으로 시작."""
    v = w.copy()
    weq = w[eq_mask].sum()
    eq, n_reb = np.empty(len(R)), 0
    for t in range(len(R)):
        v = v * (1 + R[t])
        tot = v.sum()
        eq[t] = tot
        mm = idx[t][5:]
        if mode == "연1회":
            do = mm == "12"
        elif mode == "반기":
            do = mm in ("06", "12")
        else:
            do = abs(v[eq_mask].sum() / tot - weq) > 0.10
        if do:
            turn = np.abs(v / tot - w).sum() / 2
            tot *= 1 - turn * COST * 2
            v = tot * w
            n_reb += 1
    return eq, n_reb


def stats(eq, idx, n_reb):
    yrs = len(eq) / 12
    e = pd.Series(eq, index=idx)
    r = e.pct_change().fillna(e.iloc[0] - 1)
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    return {"CAGR": eq[-1] ** (1 / yrs) - 1, "MDD": (e / e.cummax() - 1).min(), "vol": r.std() * np.sqrt(12),
            "worst_yr": yr.min(), "worst_at": yr.idxmin(), "reb_yr": n_reb / yrs}


def window(A, a, b, cols):
    S = A.loc[a:b, cols]
    assert not S.isna().any().any(), S.columns[S.isna().any()].tolist()
    return S.values, list(S.index)


def combos():
    out = []
    for eq_u in range(5, 11):  # 주식 50~100%
        k = 10 - eq_u
        for split in itertools.product(range(k + 1), repeat=len(DEF)):
            if sum(split) != k:
                continue
            for sl in SLEEVES:
                for mode in MODES:
                    out.append((sl, eq_u, split, mode))
    return out


def weights(sl, eq_u, split, cols):
    w = dict.fromkeys(cols, 0.0)
    for a, f in SLEEVES[sl].items():
        w[a] += eq_u / 10 * f
    for a, u in zip(DEF, split):
        w[a] += u / 10
    return np.array([w[c] for c in cols])


def label(sl, eq_u, split, mode):
    parts = [f"{sl} {eq_u * 10}"] + [f"{a} {u * 10}" for a, u in zip(DEF, split) if u]
    return " / ".join(parts) + f" [{mode}]"


def main():
    A = assets()
    cols = COLS[:8]
    eq_mask = np.array([c in ("sp", "nq", "ks") for c in cols])
    W = {p: window(A, *p, cols) for p in (IS, OOS, ALL)}
    rows = []
    for sl, eq_u, split, mode in combos():
        w = weights(sl, eq_u, split, cols)
        rec = {"label": label(sl, eq_u, split, mode), "sleeve": sl, "eq": eq_u * 10,
               **{a: u * 10 for a, u in zip(DEF, split)}, "mode": mode}
        for tag, p in (("IS", IS), ("OOS", OOS), ("ALL", ALL)):
            R, idx = W[p]
            e, n = run(R, idx, w, eq_mask, mode)
            rec.update({f"{tag}_{k}": v for k, v in stats(e, idx, n).items()})
        for ck, p in CRISES.items():
            R, idx = window(A, *p, cols)
            rec[ck] = run(R, idx, w, eq_mask, mode)[0][-1] - 1
        rows.append(rec)
    G = pd.DataFrame(rows)
    G.to_csv(RES / "E_grid.csv", index=False, encoding="utf-8-sig")

    # 판정 (00_연구계획 §E — 미리 고정)
    base = G[(G.sleeve == "S&P") & (G["eq"] == 80) & (G.b30h == 20) & (G["mode"] == "연1회")].iloc[0]
    ok = lambda g, t: (g[f"{t}_MDD"] >= base[f"{t}_MDD"] + 0.03) & (g[f"{t}_CAGR"] >= base[f"{t}_CAGR"] - 0.005)
    G["IS_pass"], G["OOS_pass"] = ok(G, "IS"), ok(G, "OOS")
    C = G[G.IS_pass].sort_values(["IS_MDD", "IS_CAGR"], ascending=[False, False])
    L = []
    p = lambda s: L.append(s)
    f = lambda x: f"{x:.1%}"
    p(f"기준선 {base.label}: 학습 CAGR {f(base.IS_CAGR)} MDD {f(base.IS_MDD)} / 검증 CAGR {f(base.OOS_CAGR)} MDD {f(base.OOS_MDD)}"
      f" / 전체 CAGR {f(base.ALL_CAGR)} MDD {f(base.ALL_MDD)}")
    p(f"학습 후보: {len(C)}개 / 2,268개, 그중 검증도 통과: {int(C.OOS_pass.sum())}개 ({C.OOS_pass.mean():.0%})" if len(C) else "학습 후보 없음")
    if len(C):
        s = C.iloc[0]
        verdict = "추천" if s.OOS_pass else "보류"
        p(f"선택: {s.label} → {verdict}")
        p(f"  학습 CAGR {f(s.IS_CAGR)} MDD {f(s.IS_MDD)} / 검증 CAGR {f(s.OOS_CAGR)} MDD {f(s.OOS_MDD)} / 전체 CAGR {f(s.ALL_CAGR)} MDD {f(s.ALL_MDD)}")
        # 이웃: 6칸(주식 합계 + 5자산) 중 한 칸에서 10%p를 다른 칸으로
        slots = ["eq"] + DEF
        key = lambda r: (r.sleeve, r["mode"]) + tuple(int(r[c]) for c in slots)
        idx = {key(r): i for i, r in G.iterrows()}
        nb = []
        for i, j in itertools.permutations(range(6), 2):
            v = [int(s[c]) for c in slots]
            v[i] -= 10; v[j] += 10
            if v[i] < 0 or v[0] < 50 or v[0] > 100:
                continue
            k = (s.sleeve, s["mode"]) + tuple(v)
            if k in idx:
                nb.append(idx[k])
        N = G.loc[nb]
        rate = N.OOS_pass.mean()
        p(f"  이웃 {len(N)}개 검증 통과 비율 {rate:.0%}" + (" → 견고성 약함" if rate < 0.5 else ""))
    else:
        p("판정: 80/20 유지")
    txt = "\n".join(L)
    (RES / "E_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)

    # 참고 실험: 리츠·원자재 (2006-03~2026-10, 연 1회)
    ref = {"80 / b30h 20": {"sp": .8, "b30h": .2}, "80 / b30h 10 / 리츠 10": {"sp": .8, "b30h": .1, "reit": .1},
           "80 / b30h 10 / 원자재 10": {"sp": .8, "b30h": .1, "cmd": .1}}
    R, idx = window(A, "2006-03", "2026-10", COLS)
    m = np.array([c == "sp" for c in COLS])
    rr = []
    for nme, d in ref.items():
        w = np.array([d.get(c, 0.0) for c in COLS])
        e, n = run(R, idx, w, m, "연1회")
        rr.append({"mix": nme, **stats(e, idx, n)})
    pd.DataFrame(rr).to_csv(RES / "E_ref.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(rr).to_string(index=False))
    print(A.loc[ALL[0]:ALL[1]].corr().round(2).to_string())


if __name__ == "__main__":
    main()
