"""실험 CSV -> 03_실험결과.md (표 자동 생성)

실행: py src/report.py
"""
import pandas as pd

from optimize import RES, ROOT


def pct(x):
    return "" if pd.isna(x) else f"{x * 100:.1f}%"


def f2(x):
    return "" if pd.isna(x) else f"{x:.2f}"


def main():
    e = pd.read_csv(RES / "exp_oneatatime_first.csv")
    L = ["# 03. 실험 결과 (자동 생성: src/report.py)", "",
         "- 학습(IS) 2011.01~2018.12 / 검증(OOS) 2019.01~2026.10, 월간, 편도 비용 0.1%, 시점 정확한 SEC 최초 공시값(first)",
         "- 기준 = 문서 규칙 그대로(등급별 목표가 S×0.9·A×0.85·일반×0.8, 10종목, 갈아타기 +15%p). 한 번에 한 요소만 바꿈",
         "- 판단은 학습 구간으로 하고 검증 구간은 확인용으로만 본다", "",
         "## 1. 한 요소씩 바꾸기", "",
         "| 묶음 | 실험 | IS CAGR | IS Sharpe | IS MDD | OOS CAGR | OOS Sharpe | OOS MDD | 평균 보유 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in e.itertuples():
        L.append(f"| {r.group} | {r.name} | {pct(r.IS_CAGR)} | {f2(r.IS_Sharpe)} | {pct(r.IS_MDD)} | {pct(r.OOS_CAGR)} | "
                 f"{f2(r.OOS_Sharpe)} | {pct(r.OOS_MDD)} | {'' if pd.isna(getattr(r, 'OOS_avg_hold', None)) else f'{r.OOS_avg_hold:.1f}'} |")
    g = pd.read_csv(RES / "robust_grid.csv")
    L += ["", "## 2. 후보 규칙 이웃 격자 (품질 관문 + qv 순위 상위 N, k개월 재구성) — 전체 기간 Sharpe", ""]
    piv = g.pivot(index="N", columns="rebal", values="ALL_Sharpe")
    L.append("| N \\ 재구성(개월) | " + " | ".join(map(str, piv.columns)) + " |")
    L.append("|---|" + "---|" * len(piv.columns))
    for n, row in piv.iterrows():
        L.append(f"| {n} | " + " | ".join(f2(v) for v in row.values) + " |")
    b = pd.read_csv(RES / "robust_buffer.csv")
    L += ["", "## 3. 완충(보유 종목은 순위 buffer×N 안이면 유지) — N=20", "",
          "| 완충 | 재구성 | 전체 CAGR | 전체 Sharpe | 전체 MDD | IS Sharpe | OOS Sharpe | 연 회전율 |", "|---|---|---|---|---|---|---|---|"]
    for r in b.itertuples():
        L.append(f"| {'없음' if pd.isna(r.buffer) else r.buffer} | {r.rebal} | {pct(r.ALL_CAGR)} | {f2(r.ALL_Sharpe)} | {pct(r.ALL_MDD)} | "
                 f"{f2(r.IS_Sharpe)} | {f2(r.OOS_Sharpe)} | {pct(r.turnover_pct_yr)} |")
    c = pd.read_csv(RES / "robust_cost.csv")
    L += ["", "## 4. 비용 민감도 (편도)", "", "| 규칙 | 비용 | 전체 CAGR | 전체 Sharpe |", "|---|---|---|---|"]
    for r in c.itertuples():
        L.append(f"| {'현행' if getattr(r, 'rule', '') == 'doc' else 'qv N20 R3'} | {pct(r.cost)} | {pct(r.ALL_CAGR)} | {f2(r.ALL_Sharpe)} |")
    lm = pd.read_csv(RES / "robust_lastmode.csv")
    L += ["", "## 5. 재작성 공시값(last)으로 다시 계산", "", "| 규칙 | 전체 CAGR | 전체 Sharpe | IS Sharpe | OOS Sharpe |", "|---|---|---|---|---|"]
    for r in lm.itertuples():
        L.append(f"| {'v2' if r.rule == 'final' else '현행'} | {pct(r.ALL_CAGR)} | {f2(r.ALL_Sharpe)} | {f2(r.IS_Sharpe)} | {f2(r.OOS_Sharpe)} |")
    fp = pd.read_csv(RES / "final_perf.csv")
    fb = pd.read_csv(RES / "final_boot.csv")
    L += ["", "## 6. 최종 비교", "", "| 구간 | 전략 | CAGR | 변동성 | Sharpe | MDD |", "|---|---|---|---|---|---|"]
    for r in fp.itertuples():
        L.append(f"| {r.구간} | {r.전략} | {pct(r.CAGR)} | {pct(r.vol)} | {f2(r.Sharpe)} | {pct(r.MDD)} |")
    L += ["", "블록 부트스트랩(6개월 블록, 2,000회) — Sharpe 차이:", "", "| 전략 | 비교 | 중앙 | 90% 구간 | P(차>0) |", "|---|---|---|---|---|"]
    for r in fb.itertuples():
        L.append(f"| {r.전략} | {r.비교} | {f2(r._3)} | {r._4} | {f2(r._5)} |")
    y = pd.read_csv(RES / "robust_yearly.csv", index_col=0)
    L += ["", "## 7. 연도별 수익", "", "| 연도 | " + " | ".join(y.columns) + " |", "|---|" + "---|" * len(y.columns)]
    for yr, r in y.iterrows():
        L.append(f"| {yr} | " + " | ".join(pct(v) for v in r.values) + " |")
    L += ["", "![누적 자산](results/final_equity.png)", ""]
    (ROOT / "03_실험결과.md").write_text("\n".join(L), encoding="utf-8")
    print("written 03_실험결과.md")


if __name__ == "__main__":
    main()
