"""L. 밸류에이션(CAPE)에 따라 국채 비중 조절 (00_연구계획 §L).

실행: py src/valuation.py -> results/L_summary.txt, L_rules.csv, L_crisis.csv
"""
import re
import sys
import warnings

import numpy as np
import pandas as pd

from alloc import CRISES, DATA, RES, bond_ret, build, yahoo

warnings.filterwarnings("ignore")
SH = DATA / "shiller"
COST = 0.001


def cape_series():
    t = (SH / "multpl.html").read_text(encoding="utf-8", errors="ignore")
    rows = re.findall(r"<td>([A-Z][a-z]{2} \d+, \d{4})</td>\s*<td>\s*(?:&#x2002;)?\s*([\d.]+)", t)
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in rows})
    s = s[s.index.day == 1].sort_index()
    s.index = s.index.strftime("%Y-%m")
    s.to_frame("cape").to_csv(DATA / "cape_multpl.csv")
    return s


def shiller():
    d = pd.read_excel(SH / "ie_data.xls", sheet_name="Data", header=7)
    d = d[pd.to_numeric(d.Date, errors="coerce").notna()].copy()
    d["m"] = d.Date.astype(float).map(lambda x: f"{int(x)}-{round((x - int(x)) * 100):02d}")
    d = d.set_index("m")
    for c in ["P", "D", "CAPE", "Rate GS10"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.loc[:"2023-08"]


def targets(cape, y10):
    """월말 m 에 정한 국채 목표 비중(다음 달 적용). t−1월 CAPE 사용."""
    c = cape.shift(1)
    p = c.expanding(120).apply(lambda x: (x[:-1] < x[-1]).mean() if len(x) > 1 else np.nan, raw=True)
    g = 1 / c - y10 / 100
    gp = g.expanding(120).apply(lambda x: (x[:-1] < x[-1]).mean() if len(x) > 1 else np.nan, raw=True)
    T = pd.DataFrame(index=cape.index)
    T["L0"] = 0.2
    T["L1"] = np.where(p >= 0.8, 0.3, np.where(p <= 0.2, 0.1, 0.2))
    T["L2"] = 0.1 + 0.2 * p
    T["L3"] = np.where(c > 30, 0.3, np.where(c < 20, 0.1, 0.2))
    T["L4"] = np.where(p >= 0.8, 0.4, np.where(p <= 0.2, 0.0, 0.2))
    T["L5"] = np.where(gp <= 0.2, 0.3, np.where(gp >= 0.8, 0.1, 0.2))
    T.loc[p.isna(), ["L1", "L2", "L4"]] = np.nan
    T.loc[gp.isna(), "L5"] = np.nan
    return T, p


def simulate(req, rbd, tgt, rule, a, b):
    idx = req.index
    sub = idx[(idx >= a) & (idx <= b)]
    eqv, bdv, out, prev, changes = None, None, [], None, 0
    for m in sub:
        pm = idx[idx.get_loc(m) - 1]
        w = tgt.at[pm]
        if not np.isfinite(w):
            w = 0.2
        if eqv is None:
            eqv, bdv = 1 - w, w
        else:
            tot = eqv + bdv
            if (rule != "L0" and w != prev) or pm.endswith("-12"):
                turn = abs(bdv / tot - w)
                tot *= 1 - turn * COST * 2
                eqv, bdv = tot * (1 - w), tot * w
            if prev is not None and w != prev:
                changes += 1
        prev = w
        eqv *= 1 + (req.at[m] if np.isfinite(req.at[m]) else 0)
        bdv *= 1 + (rbd.at[m] if np.isfinite(rbd.at[m]) else 0)
        out.append(eqv + bdv)
    e = pd.Series(out, index=sub)
    r = e.pct_change().fillna(e.iloc[0] - 1)
    yrs = len(e) / 12
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "Sharpe": r.mean() / r.std() * np.sqrt(12),
            "MDD": (e / e.cummax() - 1).min(), "bond_avg": tgt.reindex(sub).shift(0).mean(),
            "chg_per_yr": changes / yrs}, e


def better(s, b):
    return (s["Sharpe"] >= b["Sharpe"] + 0.03 and s["MDD"] >= b["MDD"] - 0.01) or \
           (s["MDD"] >= b["MDD"] + 0.03 and s["CAGR"] >= b["CAGR"] - 0.003)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = []
    cape = cape_series()
    sh = shiller()
    ov = pd.concat([cape, sh.CAPE], axis=1, keys=["multpl", "shiller"]).dropna()
    out.append(f"CAPE 출처 대조(겹치는 {len(ov)}개월): 상관 {ov.corr().iloc[0, 1]:.4f}, 평균 절대차 {(ov.multpl - ov.shiller).abs().mean():.2f}")

    # 시험 A: 원화 실전
    D = build()
    y30 = D.tyx
    TA, pA = targets(cape.reindex(cape.index), yahoo("^TNX").reindex(cape.index).fillna(sh["Rate GS10"].reindex(cape.index)))
    TA = TA.reindex(D.index)
    # 시험 B: 달러 장기
    tr = (sh.P + sh.D / 12).div(sh.P.shift(1)) - 1
    spy = yahoo("SPY", True)
    tr = pd.concat([tr, spy.pct_change().loc["2023-09":"2026-10"]])
    tr = tr[~tr.index.duplicated()]
    y10 = pd.concat([sh["Rate GS10"], yahoo("^TNX").loc["2023-09":"2026-10"]])
    y10 = y10[~y10.index.duplicated()].astype(float)
    bd10 = bond_ret(y10 / 100, n=10)
    TB, pB = targets(cape.loc[:"2026-10"], y10.reindex(cape.loc[:"2026-10"].index))
    rows, crisis = [], []
    tests = {"A학습": (D.un, D.bh, TA, "1991-01", "2008-12"), "A검증": (D.un, D.bh, TA, "2009-01", "2026-10"),
             "B학습": (tr, bd10, TB.reindex(tr.index), "1921-01", "1989-12"),
             "B검증": (tr, bd10, TB.reindex(tr.index), "1990-01", "2026-10")}
    res = {}
    for tn, (re_, rb, T, a, b) in tests.items():
        for rule in ["L0", "L1", "L2", "L3", "L4", "L5"]:
            s, e = simulate(re_, rb, T[rule], rule, a, b)
            res[(tn, rule)] = s
            rows.append({"test": tn, "rule": rule, **s})
            if tn.startswith("A"):
                for cn, (ca, cb) in CRISES.items():
                    if ca >= a and cb <= b:
                        seg = e.loc[ca:cb]
                        pre = e.shift(1).loc[ca]
                        crisis.append({"rule": rule, "crisis": cn, "ret": seg.iloc[-1] / (pre if np.isfinite(pre) else 1) - 1})
    R = pd.DataFrame(rows)
    R.to_csv(RES / "L_rules.csv", index=False, encoding="utf-8-sig")
    C = pd.DataFrame(crisis).pivot(index="rule", columns="crisis", values="ret")
    C.to_csv(RES / "L_crisis.csv", encoding="utf-8-sig")
    for tn in tests:
        out.append(f"\n[{tn}] {tests[tn][3]}~{tests[tn][4]}")
        b0 = res[(tn, "L0")]
        for rule in ["L0", "L1", "L2", "L3", "L4", "L5"]:
            s = res[(tn, rule)]
            mark = "" if rule == "L0" else ("  개선" if better(s, b0) else "")
            out.append(f"  {rule}: 연 {s['CAGR']:6.2%}  Sharpe {s['Sharpe']:.3f}  MDD {s['MDD']:6.1%}  국채평균 {s['bond_avg']:.0%}  변경/년 {s['chg_per_yr']:.2f}{mark}")
    out.append("\n판정 (A학습·A검증·B검증 개선 수):")
    for rule in ["L1", "L2", "L3", "L4", "L5"]:
        k = sum(better(res[(t, rule)], res[(t, "L0")]) for t in ["A학습", "A검증", "B검증"])
        out.append(f"  {rule}: {k}/3 → {'추천' if k == 3 else '보류' if k == 2 else '탈락'}  (B학습 참고: {'개선' if better(res[('B학습', rule)], res[('B학습', 'L0')]) else '-'})")
    out.append("\n위기 구간 수익 (시험 A):\n" + C.to_string(float_format=lambda x: f"{x:+.1%}"))
    last = TA.dropna(how="all").iloc[-1]
    out.append(f"\n현재 신호 (2026-10 말 판단, 9월 CAPE {cape.get('2026-09')}, 분위 {pA.dropna().iloc[-1]:.0%}): " +
               ", ".join(f"{k} 국채 {v:.0%}" for k, v in last.items()))
    yrs_hi = (pA.loc["1991-01":] >= 0.8).mean()
    out.append(f"1991~2026 중 CAPE 분위 ≥80%였던 달 비율 {yrs_hi:.0%}, ≤20% {(pA.loc['1991-01':] <= 0.2).mean():.0%}")
    txt = "\n".join(out)
    (RES / "L_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
