"""전략 결과 CSV -> 03_전략백테스트.md + results/equity_*.png

실행: py src/report_strategy.py  (strategy_search, strategy2, run_robustness 실행 후)
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import RESULTS, ROOT

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def pct(x, d=1):
    return "" if pd.isna(x) else f"{x * 100:.{d}f}%"


def f2(x):
    return "" if pd.isna(x) else f"{x:.2f}"


def table(df, cols):
    head = "| " + " | ".join(c for c, _ in cols) + " |"
    sep = "|" + "---|" * len(cols)
    rows = [head, sep]
    for _, r in df.iterrows():
        rows.append("| " + " | ".join(fn(r) for _, fn in cols) + " |")
    return "\n".join(rows)


PERF = [
    ("CAGR", lambda r: pct(r.CAGR)), ("MDD", lambda r: pct(r.MDD)), ("Sharpe", lambda r: f2(r.Sharpe)),
    ("거래수", lambda r: "" if pd.isna(r.get("trades")) else f"{int(r.trades)}"),
    ("승률", lambda r: pct(r.get("win"))), ("평균/거래", lambda r: pct(r.get("avg_ret"), 2)),
]


def equity_png():
    y = pd.read_csv(RESULTS / "robust_yearly.csv", index_col=0)
    eq = (1 + y).cumprod()
    fig, ax = plt.subplots(figsize=(10, 5))
    for c in eq.columns:
        ax.plot(eq.index, eq[c], label=c, lw=2 if "buy" in c else 1.4)
    ax.axvline(2014.5, color="gray", ls="--", lw=1)
    ax.text(2014.7, ax.get_ylim()[1] * 0.6, "검증 구간(OOS) →", color="gray")
    ax.set_yscale("log")
    ax.set_title("연말 누적 자산 (1994=1, 로그축, 비용 차감)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "equity_yearly.png", dpi=120)


def main():
    grid = pd.read_csv(RESULTS / "strategy_grid.csv")
    oos = pd.read_csv(RESULTS / "strategy_oos.csv")
    s2 = pd.read_csv(RESULTS / "strategy2.csv")
    L = ["# 03. 전략 백테스트", "",
         "- 유니버스: 미국 대형주 77+ETF 18(생존편향 있음, 02·ETF 점검 참고), 슬롯 10개 동일비중, 편도 비용 0.05%",
         "- 체결: 신호일 종가 판정 → 다음날 시가 매수, 청산 신호 다음날 시가 매도, 손절은 장중 손절가",
         "- 절차: 144개 규칙을 **1994~2014(IS)** 에서만 Sharpe로 순위 → 상위 10개를 **2015~2026-10(OOS)** 에서 1회 검증",
         "", "## 1. IS 상위 15개 (학습 구간)", "",
         table(grid[~grid.rule.str.startswith("BENCH")].head(15), [("규칙", lambda r: f"`{r.rule}`")] + PERF), "",
         "IS 비교군:", "",
         table(grid[grid.rule.str.startswith("BENCH")], [("비교군", lambda r: r.rule)] + PERF[:3]), "",
         "## 2. 같은 규칙의 OOS 성과 (검증 구간)", "",
         table(oos, [("규칙", lambda r: f"`{r.rule}`"), ("IS Sharpe", lambda r: f2(r.get("IS_Sharpe")))] + PERF), "",
         "## 3. 대안 전략 (추세 타이밍·모멘텀·타 시장)", "",
         table(s2, [("전략", lambda r: r.strategy), ("구간", lambda r: r.period)] + PERF), ""]
    for nm, title in (("robust_mc.csv", "## 4. 무작위 진입 대비 (몬테카를로 300회)"),
                      ("robust_cost.csv", "## 5. 비용 민감도 (OOS)"),
                      ("robust_k.csv", "## 6. 슬롯 수 K 민감도 (OOS)")):
        p = RESULTS / nm
        if not p.exists():
            continue
        df = pd.read_csv(p)
        L += [title, ""]
        if nm == "robust_mc.csv":
            L.append(table(df, [("규칙", lambda r: f"`{r.rule}`"), ("구간", lambda r: r.period),
                                ("실제 평균", lambda r: pct(r.real_mean, 2)), ("무작위 평균", lambda r: pct(r.rand_mean, 2)),
                                ("p(평균)", lambda r: f2(r.p_mean)), ("실제 승률", lambda r: pct(r.real_win)),
                                ("무작위 승률", lambda r: pct(r.rand_win)), ("p(승률)", lambda r: f2(r.p_win))]))
        elif nm == "robust_cost.csv":
            L.append(table(df, [("규칙", lambda r: f"`{r.rule}`"), ("편도비용", lambda r: pct(r.cost_oneway, 2))] + PERF[:3]))
        else:
            L.append(table(df, [("규칙", lambda r: f"`{r.rule}`"), ("K", lambda r: str(int(r.K)))] + PERF[:3]))
        L.append("")
    if (RESULTS / "robust_yearly.csv").exists():
        equity_png()
        y = pd.read_csv(RESULTS / "robust_yearly.csv", index_col=0)
        L += ["## 7. 연도별 수익", "", "![누적 자산](results/equity_yearly.png)", "",
              "| 연도 | " + " | ".join(y.columns) + " |", "|" + "---|" * (len(y.columns) + 1)]
        for yr_, r in y.iterrows():
            L.append(f"| {yr_} | " + " | ".join(pct(v) for v in r.values) + " |")
        L.append("")
    (ROOT / "03_전략백테스트.md").write_text("\n".join(L), encoding="utf-8")
    print("written 03_전략백테스트.md")


if __name__ == "__main__":
    main()
