"""한국(코스피) 백테스트 — 미국 엔진(backtest.simulate)을 그대로 쓰고 패널 경로만 data/kr/panel로 바꾼다.

미리 정한 규칙(결과를 보기 전에 고정):
- 기간: 5년 이력이 생기는 2018-04부터. 학습 2018-04~2022-12 / 검증 2023-01~
- 시총 하한: 1조·5천억·3천억 중 학습 구간 관문 통과 종목 수(월 중앙값) ≥ 30인 가장 높은 값
- 비용: 편도 0.2%(증권거래세·수수료·슬리피지), 민감도 0.4%
- 벤치마크: KODEX 200(069500, 배당 포함), 같은 우주(시총 하한 이상) 동일비중
실행: py src/kr_backtest.py  -> results/kr_*.csv, results/kr_equity.png
      py src/kr_backtest.py excl -> 이상치 회사(panel/flags.csv) 제외 실험, results/kr_excl_*
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest  # noqa: E402
from backtest import evaluate_rows, monthly_state, perf, simulate  # noqa: E402
from checklist import DEFAULT  # noqa: E402
from kr_fundamentals import KR  # noqa: E402
from robust import CAND, boot_sharpe_diff  # noqa: E402
from valuation import VDEFAULT  # noqa: E402

backtest.PANEL = KR / "panel"
RES = Path(__file__).resolve().parent.parent / "results"
IS = ("2018-04", "2022-12")
OOS = ("2023-01", None)
COST = 0.002
EXCL = len(sys.argv) > 1 and sys.argv[1] == "excl"
P = "kr_excl_" if EXCL else "kr_"
CAPS = (1e12, 5e11, 3e11)
FINAL = {**CAND, "rebalance": 3, "buffer": 1.5, "cost": COST, "start": IS[0]}
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def kodex200():
    s = pd.read_csv(KR / "prices" / "yahoo" / "069500.csv", parse_dates=["date"]).set_index("date").adj_close
    return s.groupby(s.index.to_period("M")).last().pct_change()


def ew(mc, tri, cap):
    ret = tri.pct_change(fill_method=None)
    return ret.where(mc.shift(1) >= cap).mean(axis=1)


def cut(r, a, b):
    return r[(r.index >= pd.Period(a, "M")) & ((r.index <= pd.Period(b, "M")) if b else True)]


def pass_counts(st, mc, cap):
    """월별 관문 통과(등급 S·A·일반, 제외 업종 아님, 시총 ≥ cap) 종목 수"""
    out = {}
    for m, s in st.groupby("m"):
        s = s[s.cik.isin(mc.columns)]
        cap_m = mc.loc[m, s.cik].values if m in mc.index else np.full(len(s), np.nan)
        ok = s.grade.isin(["S", "A", "G"]).values & ~s.sector_excl.astype("boolean").fillna(False).to_numpy(bool) & (cap_m >= cap)
        out[m] = ok.sum()
    return pd.Series(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ann, mc, tri, dd = backtest.load("first")
    if EXCL:  # ②금액 단위 ③감자 등 시총 의심 회사를 통째로 뺀다 (2026-11-19 A안)
        bad = set(pd.read_csv(KR / "panel" / "flags.csv").cik)
        ann = ann[~ann.cik.isin(bad)]
        keep = [c for c in mc.columns if c not in bad]
        mc, tri, dd = mc[keep], tri[keep], dd[keep]
        print(f"이상치 제외 {len(bad)}개사")
    rows = evaluate_rows(ann, DEFAULT, VDEFAULT)
    st = monthly_state(rows, mc.index)

    # 1) 시총 하한 결정 (수익률을 보기 전에, 학습 구간 통과 종목 수만)
    cnt = {cap: cut(pass_counts(st, mc, cap), *IS) for cap in CAPS}
    for cap, c in cnt.items():
        print(f"하한 {cap / 1e8:,.0f}억: 학습 구간 통과 종목 수 중앙 {c.median():.0f} (최소 {c.min()}, 최대 {c.max()})")
    cap = next((c for c in CAPS if cnt[c].median() >= 30), CAPS[-1])
    print(f"→ 채택 하한 {cap / 1e8:,.0f}억")
    pd.DataFrame({f"{c / 1e8:.0f}억": cut(pass_counts(st, mc, c), IS[0], None) for c in CAPS}).to_csv(
        RES / f"{P}pass_counts.csv", encoding="utf-8-sig")

    # 2) 전략 실행
    run = lambda S: simulate(ann, mc, tri, dd, DEFAULT, VDEFAULT, {**S, "min_mcap": cap}, rows=rows, state=st)
    v2, v2log, v2n = run(FINAL)
    doc, _, _ = run({"cost": COST, "start": IS[0]})  # 현행(목표가 대기·10종목)
    qual, _, _ = run({"use_price": None, "slots": 999, "cost": COST, "start": IS[0]})  # 품질 관문 통과 전부
    v2c, _, _ = run({**FINAL, "cost": 0.004})
    m = pd.DataFrame({"v2": v2, "현행": doc, "품질만 전부": qual, "KODEX200": kodex200(), "EW 동일비중": ew(mc, tri, cap),
                      "v2(비용0.4%)": v2c})
    m = m[m.index >= pd.Period(IS[0], "M")].iloc[1:].dropna(subset=["v2", "KODEX200"])
    out = []
    for tag, (a, b) in (("학습 2018.04~2022", IS), ("검증 2023~2026.10", OOS), ("전체", (IS[0], None))):
        sub = cut(m, a, b)
        for c in m.columns:
            out.append({"구간": tag, "전략": c, **perf(sub[c])})
    perf_df = pd.DataFrame(out)
    perf_df.to_csv(RES / f"{P}perf.csv", index=False, encoding="utf-8-sig")
    print(perf_df.round(3).to_string(index=False))
    b = []
    for nm in ("v2", "현행"):
        for bn in ("KODEX200", "EW 동일비중"):
            ci, p = boot_sharpe_diff(m[nm], m[bn])
            b.append({"전략": nm, "비교": bn, "Sharpe차 중앙": ci[1], "90% 구간": f"{ci[0]:+.2f} ~ {ci[2]:+.2f}", "P(차>0)": p})
    pd.DataFrame(b).to_csv(RES / f"{P}boot.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(b).round(3).to_string(index=False))
    yr = (1 + m).groupby(m.index.year).prod() - 1
    yr.to_csv(RES / f"{P}yearly.csv", encoding="utf-8-sig")
    print(yr.round(3).to_string())
    print("평균 보유", round(v2n.mean(), 1), "/ 연 회전율", round((v2log.act == "buy").sum() / (len(v2) / 12) / 20, 2))
    m.to_csv(RES / f"{P}monthly.csv", encoding="utf-8-sig")

    eq = (1 + m[["v2", "현행", "KODEX200", "EW 동일비중"]]).cumprod()
    fig, ax = plt.subplots(figsize=(10, 5))
    for c in eq.columns:
        ax.plot(eq.index.to_timestamp(), eq[c], label=c, lw=2.2 if c == "v2" else 1.3)
    ax.axvline(pd.Timestamp("2023-01-01"), color="gray", ls="--", lw=1)
    ax.set_title(f"코스피 누적 자산 (2018-04 = 1, 월간, 편도 비용 {COST:.1%}, 시총 ≥ {cap / 1e8:,.0f}억)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(RES / f"{P}equity.png", dpi=120)


if __name__ == "__main__":
    main()
