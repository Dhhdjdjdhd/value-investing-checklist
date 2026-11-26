"""T7 백테스트: 금 10~20% 장기 검증 (1971-01~2026-10, 달러 기준 주 결과 / 원화 1990~ 보조).

네 조합(사전 고정, 격자 아님): ① S&P80/국채20(현재) ② S&P80/국채10/금10 ③ S&P70/국채10/금20 ④ S&P70/국채30
연 1회(12월 말) 리밸런스, 매매 편도 0.1%. 학습 1971-01~1999-12 / 검증 2000-01~2026-10.
판정(검증, ②·③ 각각 ① 대비): 채택 = MDD 3%p 이상 개선 & CAGR −0.3%p 안 / 보류 = 둘 중 하나 / 기각 = 그 외.
  추가: 학습 구간 CAGR이 ① 대비 −1.0%p보다 나쁘면 검증을 통과해도 보류.
입력: results/t7_assets_usd.csv, t7_assets_krw.csv (t7_data.py)
출력: results/t7_main.csv, t7_crisis.csv, t7_goldbear.csv, t7_corr.csv, t7_decade.csv, t7_annual.csv,
      t7_krw.csv, t7_gold_source_check.csv, t7_series.csv, t7_tables.md
실행: py src/t7_run.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
COST = 0.001
IS, OOS = ("1971-01", "1999-12"), ("2000-01", "2026-10")

PORTS = {
    "① S&P80/국채20 (현재)": {"sp": .8, "b30": .2},
    "② S&P80/국채10/금10": {"sp": .8, "b30": .1, "gold": .1},
    "③ S&P70/국채10/금20": {"sp": .7, "b30": .1, "gold": .2},
    "④ S&P70/국채30": {"sp": .7, "b30": .3},
}
REFS = {"참고 S&P 100": {"sp": 1.0}, "참고 30년국채 100": {"b30": 1.0}, "참고 금 100": {"gold": 1.0}}
CRISES = {
    "1973~74 (73.01~74.09)": ("1973-01", "1974-09"),
    "1987 블랙먼데이 (87.09~87.11)": ("1987-09", "1987-11"),
    "닷컴 (00.09~03.02)": ("2000-09", "2003-02"),
    "금융위기 (07.11~09.02)": ("2007-11", "2009-02"),
    "코로나 (20.02~20.03)": ("2020-02", "2020-03"),
    "금리급등 2022 (22.01~22.10)": ("2022-01", "2022-10"),
}
DECADES = {"1971~79": ("1971-01", "1979-12"), "1980~89": ("1980-01", "1989-12"), "1990~99": ("1990-01", "1999-12"),
           "2000~09": ("2000-01", "2009-12"), "2010~19": ("2010-01", "2019-12"), "2020~26.10": ("2020-01", "2026-10")}


def run(A, w, a, b):
    """mix.run 과 같은 방식: 매월 수익 반영, 12월 말에 목표 비중으로 리밸런스(회전율×편도비용×2)."""
    R = A.loc[a:b, list(w)]
    v = dict(w)
    eq = []
    for m, r in R.iterrows():
        v = {k: v[k] * (1 + (r[k] if np.isfinite(r[k]) else 0.0)) for k in v}
        tot = sum(v.values())
        eq.append(tot)
        if m.endswith("-12"):
            cur = {k: v[k] / tot for k in v}
            turn = sum(abs(cur[k] - w[k]) for k in w) / 2
            tot *= 1 - turn * COST * 2
            v = {k: tot * w[k] for k in w}
    e = pd.Series(eq, index=R.index)
    return stats(e), e


def stats(e):
    r = e.pct_change().fillna(e.iloc[0] - 1)
    yrs = len(e) / 12
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    dd = e / e.cummax() - 1
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * np.sqrt(12), "Sharpe_like": r.mean() / r.std() * np.sqrt(12),
            "MDD": dd.min(), "MDD_at": dd.idxmin(), "worst_yr": yr.min(), "worst_at": yr.idxmin(), "cum": e.iloc[-1] - 1}


def verdict(d_cagr_oos, d_mdd_oos, d_cagr_is):
    ok_mdd, ok_cagr = d_mdd_oos >= 0.03, d_cagr_oos >= -0.003
    v = "채택" if (ok_mdd and ok_cagr) else ("보류" if (ok_mdd or ok_cagr) else "기각")
    note = [f"검증 MDD {'O' if ok_mdd else 'X'}({d_mdd_oos:+.1%}p, 기준 +3.0%p)",
            f"검증 CAGR {'O' if ok_cagr else 'X'}({d_cagr_oos:+.2%}p, 기준 −0.30%p)"]
    if v == "채택" and d_cagr_is < -0.01:
        v = "보류"
        note.append(f"학습 CAGR {d_cagr_is:+.2%}p < −1.0%p → 보류로 강등")
    else:
        note.append(f"학습 CAGR {'O' if d_cagr_is >= -0.01 else 'X'}({d_cagr_is:+.2%}p, 기준 −1.0%p)")
    return v, " / ".join(note)


def pct(x, d=1):
    if isinstance(x, (float, np.floating)):
        return f"{x:.{d}%}" if np.isfinite(x) else ""
    return "" if x is None else str(x)


def pp(x):
    return f"{x:+.2%}p" if np.isfinite(x) else ""


def md_table(df, fmt):
    """df → 마크다운 표. fmt: 열별 포맷 함수(없으면 str)."""
    cols = list(df.columns)
    out = ["| " + " | ".join([df.index.name or ""] + cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for i, row in df.iterrows():
        out.append("| " + " | ".join([str(i)] + [fmt.get(c, str)(row[c]) for c in cols]) + " |")
    return "\n".join(out)


def main():
    A = pd.read_csv(RES / "t7_assets_usd.csv", index_col=0)
    ALLP = {**PORTS, **REFS}
    md = ["# T7 결과 표 (자동 생성: src/t7_run.py)", ""]

    # 1. 주 결과 + 판정
    rows, ser = [], {}
    for name, w in ALLP.items():
        rec = {"포트폴리오": name}
        for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", (IS[0], OOS[1]))):
            p, e = run(A, w, a, b)
            rec.update({f"{tag} {k}": v for k, v in p.items()})
            if tag == "전체":
                ser[name] = e
        rows.append(rec)
    M = pd.DataFrame(rows).set_index("포트폴리오")
    base = M.loc["① S&P80/국채20 (현재)"]
    M["검증 ΔCAGR"] = M["검증 CAGR"] - base["검증 CAGR"]
    M["검증 ΔMDD"] = M["검증 MDD"] - base["검증 MDD"]
    M["학습 ΔCAGR"] = M["학습 CAGR"] - base["학습 CAGR"]
    M["학습 ΔMDD"] = M["학습 MDD"] - base["학습 MDD"]
    M["판정"], M["판정 근거"] = "", ""
    for name in ("② S&P80/국채10/금10", "③ S&P70/국채10/금20"):
        v, n = verdict(M.at[name, "검증 ΔCAGR"], M.at[name, "검증 ΔMDD"], M.at[name, "학습 ΔCAGR"])
        M.at[name, "판정"], M.at[name, "판정 근거"] = v, n
    M.at["④ S&P70/국채30", "판정 근거"] = "비교용(판정 대상 아님)"
    M.to_csv(RES / "t7_main.csv", encoding="utf-8-sig")
    pd.DataFrame(ser).to_csv(RES / "t7_series.csv", encoding="utf-8-sig")

    M["전체 배수"] = M["전체 cum"] + 1
    M["검증 4억→억"] = (M["검증 cum"] + 1) * 4
    show = M[["학습 CAGR", "학습 MDD", "학습 worst_yr", "검증 CAGR", "검증 MDD", "검증 worst_yr", "검증 4억→억", "전체 CAGR", "전체 MDD", "전체 vol",
              "전체 배수", "검증 ΔCAGR", "검증 ΔMDD", "학습 ΔCAGR", "학습 ΔMDD", "판정"]].copy()
    f1 = {c: pct for c in show.columns}
    f1.update({c: pp for c in ("검증 ΔCAGR", "검증 ΔMDD", "학습 ΔCAGR", "학습 ΔMDD")})
    f1.update({"전체 배수": lambda x: f"{x:.0f}배", "검증 4억→억": lambda x: f"{x:.1f}억"})
    md += ["## 1. 주 결과 (달러, 연 1회 리밸런스) — 학습 1971-01~1999-12 / 검증 2000-01~2026-10 / 전체 1971-01~2026-10", "",
           md_table(show, f1), "", "판정 근거:", *[f"- {n}: {M.at[n, '판정 근거']}" for n in PORTS if M.at[n, "판정 근거"]], ""]
    mdd_at = M[["학습 MDD_at", "학습 worst_at", "검증 MDD_at", "검증 worst_at"]]
    md += ["MDD·최악연도 시점:", "", md_table(mdd_at, {}), ""]

    # 2. 위기 구간 손실
    rows = []
    for k, (a, b) in CRISES.items():
        rec = {"위기": k}
        for name, w in ALLP.items():
            _, e = run(A, w, a, b)
            rec[name] = e.iloc[-1] - 1
        rows.append(rec)
    C = pd.DataFrame(rows).set_index("위기")
    C.to_csv(RES / "t7_crisis.csv", encoding="utf-8-sig")
    md += ["## 2. 위기 구간 누적 수익 (구간 시작에 목표 비중, 구간 내 12월 리밸런스)", "", md_table(C, {c: pct for c in C.columns}), ""]

    # 3. 금 20년 약세(1980~1999) 구간
    rows = []
    for tag, (a, b) in (("1980-01~1999-12", ("1980-01", "1999-12")), ("1980-01~1989-12", ("1980-01", "1989-12")),
                        ("1990-01~1999-12", ("1990-01", "1999-12")), ("금 고점 이후 1980-02~1985-02", ("1980-02", "1985-02"))):
        for name, w in ALLP.items():
            p, _ = run(A, w, a, b)
            rows.append({"구간": tag, "포트폴리오": name, "CAGR": p["CAGR"], "MDD": p["MDD"], "최악연도": p["worst_yr"], "누적": p["cum"]})
    G = pd.DataFrame(rows)
    G.to_csv(RES / "t7_goldbear.csv", index=False, encoding="utf-8-sig")
    gb = G[G["구간"] == "1980-01~1999-12"].set_index("포트폴리오")[["CAGR", "MDD", "최악연도", "누적"]]
    gb["80년대 CAGR"] = G[G["구간"] == "1980-01~1989-12"].set_index("포트폴리오")["CAGR"]
    gb["90년대 CAGR"] = G[G["구간"] == "1990-01~1999-12"].set_index("포트폴리오")["CAGR"]
    gb["80.02~85.02 누적"] = G[G["구간"] == "금 고점 이후 1980-02~1985-02"].set_index("포트폴리오")["누적"]
    gb = gb.rename(columns={"CAGR": "80~99 CAGR", "MDD": "80~99 MDD", "최악연도": "80~99 최악연도", "누적": "80~99 누적"})
    md += ["## 3. 금 20년 약세 구간 (1980-01~1999-12) 의 ①~④", "", md_table(gb, {c: pct for c in gb.columns}), ""]

    # 4. 10년 구간별 상관 (월 수익률) + 자산별 CAGR
    def cg(s):
        return (1 + s).prod() ** (12 / len(s)) - 1

    rows = []
    for tag, (a, b) in {**DECADES, "전체 1971~2026.10": (IS[0], OOS[1])}.items():
        X = A.loc[a:b, ["sp", "b30", "gold"]]
        c = X.corr()
        rows.append({"구간": tag, "금-S&P": c.at["gold", "sp"], "금-국채": c.at["gold", "b30"], "S&P-국채": c.at["sp", "b30"],
                     "S&P CAGR": cg(X.sp), "국채 CAGR": cg(X.b30), "금 CAGR": cg(X.gold), "금 변동성": X.gold.std() * np.sqrt(12)})
    R = pd.DataFrame(rows).set_index("구간")
    R.to_csv(RES / "t7_corr.csv", encoding="utf-8-sig")
    f4 = {c: (lambda x: f"{x:+.2f}") for c in ("금-S&P", "금-국채", "S&P-국채")}
    f4.update({c: pct for c in ("S&P CAGR", "국채 CAGR", "금 CAGR", "금 변동성")})
    md += ["## 4. 10년 구간별 상관(월 수익률) 과 자산별 CAGR", "", md_table(R, f4), ""]

    # 5. 10년 구간별 ①~④ CAGR / MDD
    rows = []
    for tag, (a, b) in DECADES.items():
        rec = {"구간": tag}
        for name, w in PORTS.items():
            p, _ = run(A, w, a, b)
            rec[f"{name[0]} CAGR"], rec[f"{name[0]} MDD"] = p["CAGR"], p["MDD"]
        rows.append(rec)
    Dd = pd.DataFrame(rows).set_index("구간")
    Dd.to_csv(RES / "t7_decade.csv", encoding="utf-8-sig")
    md += ["## 5. 10년 구간별 ①~④ CAGR / MDD", "", md_table(Dd, {c: pct for c in Dd.columns}), ""]

    # 6. 연간 수익률
    S = pd.DataFrame(ser)
    S["S&P"], S["국채"], S["금"] = (1 + A.sp).cumprod(), (1 + A.b30).cumprod(), (1 + A.gold).cumprod()
    Y = S.groupby(S.index.str[:4]).last()
    Y = Y / Y.shift(1).fillna(1) - 1
    Y.index.name = "연도"
    Y.to_csv(RES / "t7_annual.csv", encoding="utf-8-sig")
    Ysh = Y[list(PORTS) + ["S&P", "국채", "금"]].copy()
    Ysh.columns = [c[0] if c in PORTS else c for c in Ysh.columns]
    md += ["## 6. 연간 수익률 (달러)", "", md_table(Ysh, {c: pct for c in Ysh.columns}), ""]

    # 7. 원화 보조 (1990~)
    K = pd.read_csv(RES / "t7_assets_krw.csv", index_col=0).dropna()
    k0 = K.index[0]
    KP = {n: {{"sp": "eq", "b30": "b30h"}.get(k, k): v for k, v in w.items()} for n, w in {**PORTS, "참고 S&P 100": {"sp": 1.0}}.items()}
    rows = []
    for name, w in KP.items():
        rec = {"포트폴리오": name}
        for tag, (a, b) in ((f"{k0}~99.12", (k0, "1999-12")), ("00.01~26.10", OOS), (f"{k0}~26.10", (k0, OOS[1]))):
            p, _ = run(K, w, a, b)
            rec[f"{tag} CAGR"], rec[f"{tag} MDD"] = p["CAGR"], p["MDD"]
        rows.append(rec)
    KR = pd.DataFrame(rows).set_index("포트폴리오")
    KR.to_csv(RES / "t7_krw.csv", encoding="utf-8-sig")
    md += [f"## 7. 원화 보조 (환노출 S&P / 30년 국채 환헤지 / 금×원달러, {k0}~)", "", md_table(KR, {c: pct for c in KR.columns}), ""]

    # 8. 금 자료 점검: 월평균(datahub) vs 월말(GC=F), 2000-09~2026-10
    a, b = "2000-09", "2026-10"
    A2 = A.copy()
    A2["gold"] = A2["gold_gcf"]
    rows = []
    for name, w in {**PORTS, "참고 금 100": {"gold": 1.0}}.items():
        p1, _ = run(A, w, a, b)
        p2, _ = run(A2, w, a, b)
        rows.append({"포트폴리오": name, "월평균 CAGR": p1["CAGR"], "월말(GC=F) CAGR": p2["CAGR"], "ΔCAGR": p2["CAGR"] - p1["CAGR"],
                     "월평균 MDD": p1["MDD"], "월말(GC=F) MDD": p2["MDD"], "ΔMDD": p2["MDD"] - p1["MDD"],
                     "월평균 vol": p1["vol"], "월말 vol": p2["vol"]})
    GS = pd.DataFrame(rows).set_index("포트폴리오")
    GS.to_csv(RES / "t7_gold_source_check.csv", encoding="utf-8-sig")
    f8 = {c: pct for c in GS.columns}
    f8.update({c: pp for c in ("ΔCAGR", "ΔMDD")})
    md += ["## 8. 금 자료 점검 — 월평균(datahub, 주 결과) vs 월말(Yahoo GC=F), 2000-09~2026-10", "", md_table(GS, f8), ""]

    # 9. 롤링 10년 창(월 단위 시작, 1971-01~2016-11 시작) — ②·③·④ 가 ① 보다 CAGR 높은/MDD 작은 창의 비율 (판정과 무관, 참고)
    rows = []
    idx = list(A.index)
    starts = [m for m in idx if idx.index(m) + 120 <= len(idx)]
    roll = {n: [] for n in PORTS}
    for s in starts:
        e_ = idx[idx.index(s) + 119]
        for n, w in PORTS.items():
            p, _ = run(A, w, s, e_)
            roll[n].append((s, p["CAGR"], p["MDD"]))
    base_r = pd.DataFrame(roll["① S&P80/국채20 (현재)"], columns=["s", "cagr", "mdd"]).set_index("s")
    for n in PORTS:
        if n.startswith("①"):
            continue
        r_ = pd.DataFrame(roll[n], columns=["s", "cagr", "mdd"]).set_index("s")
        d = r_ - base_r
        rows.append({"포트폴리오": n, "창 수": len(d), "CAGR 우위 비율": (d.cagr > 0).mean(), "MDD 개선 비율": (d.mdd > 0).mean(),
                     "MDD 3%p↑개선 비율": (d.mdd >= 0.03).mean(), "ΔCAGR 중앙값": d.cagr.median(), "ΔCAGR 최악": d.cagr.min(),
                     "ΔCAGR 최악 시작": d.cagr.idxmin(), "ΔMDD 중앙값": d.mdd.median()})
    RW = pd.DataFrame(rows).set_index("포트폴리오")
    RW.to_csv(RES / "t7_roll10y.csv", encoding="utf-8-sig")
    f9 = {c: pct for c in RW.columns}
    f9.update({"창 수": str, "ΔCAGR 최악 시작": str, "ΔCAGR 중앙값": pp, "ΔCAGR 최악": pp, "ΔMDD 중앙값": pp})
    md += ["## 9. 롤링 10년 창에서 ① 대비 (참고, 판정과 무관)", "", md_table(RW, f9), ""]

    (RES / "t7_tables.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
