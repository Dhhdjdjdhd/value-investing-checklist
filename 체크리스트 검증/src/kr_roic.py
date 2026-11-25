"""한국 ROIC 관문 선택지 A·B·C 비교 — 00_연구계획 §4 (2026-11-23 사전 등록).

A: ROIC 5년 중앙값 ≥ 15% / B: 10·12·15% 중 학습 통과 중앙 ≥ 20인 가장 높은 문턱 / C: 결산연도별 상위 30%
선택: 학습 구간 v2 Sharpe 1위. 나머지 조건은 kr_backtest.py와 같다.
실행: py src/kr_roic.py [excl]  -> results/kr_roic_*.csv (excl: panel/flags.csv 이상치 회사 제외)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest  # noqa: E402
from backtest import evaluate_rows, monthly_state, perf, simulate  # noqa: E402
from checklist import DEFAULT  # noqa: E402
from kr_backtest import CAPS, FINAL, IS, OOS, RES, cut, ew, kodex200, pass_counts  # noqa: E402
from kr_fundamentals import KR  # noqa: E402
from robust import boot_sharpe_diff  # noqa: E402
from valuation import VDEFAULT  # noqa: E402

backtest.PANEL = KR / "panel"
EXCL = len(sys.argv) > 1 and sys.argv[1] == "excl"
P_ = "kr_roic_excl_" if EXCL else "kr_roic_"


def c_threshold(ann, cap):
    """C: 결산연도별 후보(제외 업종 아님·결산일 시총 ≥ cap·5년 이력) ROIC 5년 중앙값의 70번째 백분위."""
    pool = ann[~ann.sector_excl.astype(bool) & (ann.mcap_fy >= cap) & (ann.n_years >= 5) & ann.roic_med5.notna()]
    q = pool.groupby("cy").roic_med5.quantile(0.70)
    return ann.cy.map(q).fillna(np.inf), q


def setup(ann, mc, roic):
    """roic: 숫자(절대 문턱) 또는 'C'. 시총 하한 규칙까지 적용해 (P, rows, state, cap, 통과수, C문턱) 반환."""
    for cap in CAPS:
        if roic == "C":
            thr, q = c_threshold(ann, cap)
        else:
            thr, q = roic, None
        P = {**DEFAULT, "roic_min": thr}
        rows = evaluate_rows(ann, P, VDEFAULT)
        st = monthly_state(rows, mc.index)
        cnt = cut(pass_counts(st, mc, cap), *IS)
        if cnt.median() >= 30 or cap == CAPS[-1]:
            return P, rows, st, cap, cnt, q


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ann, mc, tri, dd = backtest.load("first")
    if EXCL:
        bad = set(pd.read_csv(KR / "panel" / "flags.csv").cik)
        ann = ann[~ann.cik.isin(bad)]
        keep = [c for c in mc.columns if c not in bad]
        mc, tri, dd = mc[keep], tri[keep], dd[keep]
        print(f"이상치 제외 {len(bad)}개사")
    names = ann.drop_duplicates("cik").set_index("cik").name
    big = {n: ann.loc[ann.name == n, "cik"].iloc[0] for n in ("삼성전자", "SK하이닉스") if (ann.name == n).any()}

    # B: 문턱 고르기 (종목 수만 보고)
    b_cnt = {}
    for t in (0.15, 0.12, 0.10):
        b_cnt[t] = setup(ann, mc, t)[4].median()
        print(f"B 후보 ROIC {t:.0%}: 학습 통과 중앙 {b_cnt[t]:.0f}")
    b_pick = next((t for t in (0.15, 0.12, 0.10) if b_cnt[t] >= 20), 0.10)
    print(f"→ B 문턱 {b_pick:.0%}")

    variants = {"A (15%)": 0.15, f"B ({b_pick:.0%})": b_pick, "C (상위 30%)": "C"}
    rets, rows_out, holds = {}, [], {}
    for name, spec in variants.items():
        P, rows, st, cap, cnt, q = setup(ann, mc, spec)
        r, log, n = simulate(ann, mc, tri, dd, P, VDEFAULT, {**FINAL, "min_mcap": cap}, rows=rows, state=st)
        rets[name] = r
        bought = set(log[log.act == "buy"].cik)
        holds[name] = bought
        extra = f" / C 문턱(연도별) {', '.join(f'{k}:{v:.1%}' for k, v in q.items() if k >= 2016)}" if q is not None else ""
        print(f"{name}: 하한 {cap / 1e8:,.0f}억, 학습 통과 중앙 {cnt.median():.0f}, 평균 보유 {n.mean():.1f}, "
              f"편입 {', '.join(k for k, c in big.items() if c in bought) or '삼성전자·하이닉스 없음'}{extra}")
        rows_out.append({"선택지": name, "하한(억)": cap / 1e8, "학습 통과 중앙": cnt.median(), "평균 보유": n.mean(),
                         "삼성·하이닉스 편입": ", ".join(k for k, c in big.items() if c in bought)})
    cap0 = setup(ann, mc, 0.15)[3]
    m = pd.DataFrame({**rets, "KODEX200": kodex200(), "EW 동일비중": ew(mc, tri, cap0)})
    m = m[m.index >= pd.Period(IS[0], "M")].iloc[1:].dropna(subset=["A (15%)", "KODEX200"])

    out = []
    for tag, (a, b) in (("학습", IS), ("검증", OOS), ("전체", (IS[0], None))):
        sub = cut(m, a, b)
        for c in m.columns:
            out.append({"구간": tag, "전략": c, **perf(sub[c])})
    pf = pd.DataFrame(out)
    isr = pf[(pf.구간 == "학습") & pf.전략.isin(variants)].set_index("전략").Sharpe
    pick = isr.idxmax()
    print(pf.round(3).to_string(index=False))
    print(f"\n→ 학습 Sharpe 1위(사전 규칙): {pick}  ({', '.join(f'{k} {v:.2f}' for k, v in isr.items())})")

    b = []
    for nm in variants:
        for bn in ("KODEX200", "EW 동일비중"):
            ci, p = boot_sharpe_diff(m[nm], m[bn])
            b.append({"전략": nm, "비교": bn, "Sharpe차 중앙": ci[1], "90% 구간": f"{ci[0]:+.2f} ~ {ci[2]:+.2f}", "P(차>0)": p})
    bd = pd.DataFrame(b)
    print(bd.round(3).to_string(index=False))
    yr = (1 + m).groupby(m.index.year).prod() - 1
    print(yr.round(3).to_string())

    pf.to_csv(RES / f"{P_}perf.csv", index=False, encoding="utf-8-sig")
    bd.to_csv(RES / f"{P_}boot.csv", index=False, encoding="utf-8-sig")
    yr.to_csv(RES / f"{P_}yearly.csv", encoding="utf-8-sig")
    m.to_csv(RES / f"{P_}monthly.csv", encoding="utf-8-sig")
    pd.DataFrame(rows_out).assign(선택=lambda d: d.선택지 == pick).to_csv(RES / f"{P_}summary.csv", index=False,
                                                                       encoding="utf-8-sig")
    hold_names = {k: sorted(names.get(c, str(c)) for c in v) for k, v in holds.items()}
    pd.DataFrame([{"선택지": k, "편입 종목": ", ".join(v)} for k, v in hold_names.items()]).to_csv(
        RES / f"{P_}holdings.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
