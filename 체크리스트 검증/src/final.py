"""최종 규칙 성과 정리 + 현재(최신 월말) 종목 선정.

최종 규칙(개정 체크리스트 v2):
  관문: 3단계 정량 통과(ROIC 5년 중앙값 ≥15%, 순이익>0, EPS·매출 5년 증가, 장기부채÷순이익 ≤6),
        경기순환(섹터·숫자) 제외, 시총 ≥ $10B
  순위: ROIC 5년 중앙값 백분위 + (FCF−SBC)/시총 백분위
  보유: 상위 20 동일비중, 3개월마다 점검, 보유 종목은 30위 안이면 유지
실행: py src/final.py -> results/final_*.csv, results/final_equity.png, results/screen_now.csv
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest import perf
from optimize import IS, OOS, RES, Runner, ew_universe, spy_monthly
from prices import load_companies, load_price
from robust import CAND, boot_sharpe_diff

FINAL = {**CAND, "rebalance": 3, "buffer": 1.5}  # buffer.py에서 학습 구간 Sharpe 1위
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def main():
    R = Runner("first")
    fin, flog, _ = R.run("개정 체크리스트 v2", S=FINAL, group="final")
    doc, dlog, _ = R.run("현행 체크리스트", group="final")
    spy, ew = spy_monthly(), ew_universe(R.mc, R.tri)
    m = pd.DataFrame({"개정 v2": fin, "현행": doc, "SPY": spy, "EW 대형주": ew})
    m = m[m.index >= pd.Period(IS[0], "M")].dropna()
    rows = []
    for tag, (a, b) in (("2011~2018", IS), ("2019~2026.10", OOS), ("전체", (IS[0], None))):
        sub = m[(m.index >= pd.Period(a, "M")) & ((m.index <= pd.Period(b, "M")) if b else True)]
        for c in m.columns:
            rows.append({"구간": tag, "전략": c, **perf(sub[c])})
    pd.DataFrame(rows).to_csv(RES / "final_perf.csv", index=False, encoding="utf-8-sig")
    b = []
    for nm in ("개정 v2", "현행"):
        for bn in ("SPY", "EW 대형주"):
            ci, p = boot_sharpe_diff(m[nm], m[bn])
            b.append({"전략": nm, "비교": bn, "Sharpe차 중앙": ci[1], "90% 구간": f"{ci[0]:+.2f} ~ {ci[2]:+.2f}", "P(차>0)": p})
    pd.DataFrame(b).to_csv(RES / "final_boot.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print(pd.DataFrame(b).round(3).to_string(index=False))
    turnover = (flog.act == "buy").sum() / (len(fin) / 12) / FINAL["slots"]
    print("turnover/yr", round(turnover, 2))
    eq = (1 + m).cumprod()
    fig, ax = plt.subplots(figsize=(10, 5))
    for c in eq.columns:
        ax.plot(eq.index.to_timestamp(), eq[c], label=c, lw=2.2 if c == "개정 v2" else 1.3)
    ax.axvline(pd.Timestamp("2019-01-01"), color="gray", ls="--", lw=1)
    ax.set_title("누적 자산 (2011-01 = 1, 월간, 편도 비용 0.1%)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(RES / "final_equity.png", dpi=120)

    # ---- 현재 선정
    rows_, st = R.state({**__import__("checklist").DEFAULT}, {**__import__("valuation").VDEFAULT})
    last_m = R.mc.index[-1]
    s = st[st.m == last_m].set_index("cik")
    s = s[s.index.isin(R.mc.columns)]
    s["mcap"] = R.mc.loc[last_m, s.index].values
    s = s.dropna(subset=["mcap"])
    s = s[~s.sector_excl.fillna(False).astype(bool) & (s.mcap >= 10e9) & s.grade.isin(["S", "A", "G"])]
    s["fcf_yield"] = s.fcf_sbc / s.mcap
    s["qv"] = s.roic_med5.rank(pct=True) + s.fcf_yield.rank(pct=True)
    s = s.sort_values("qv", ascending=False)
    s["rank"] = np.arange(1, len(s) + 1)
    comp = load_companies().drop_duplicates("cik").set_index("cik")
    s["company"] = comp.reindex(s.index)["name"].values
    s["sic"] = comp.reindex(s.index)["sicDescription"].values
    px = []
    for tk in s.ticker:
        p = load_price(tk)
        px.append((p.close.iloc[-1], p.index[-1].date()) if p is not None else (np.nan, None))
    s["price"], s["price_date"] = [x[0] for x in px], [x[1] for x in px]
    s["iv_ps"] = s.iv / s.mcap * s.price
    s["pe"] = s.mcap / s.ni
    out = s[["rank", "ticker", "company", "sic", "grade", "cy", "roic_med5", "fcf_yield", "pe", "mcap", "price", "price_date", "iv_ps", "qv"]]
    out.to_csv(RES / "screen_now.csv", encoding="utf-8-sig")
    print(f"passers {len(s)} as of {last_m}")
    print(out.head(30).round(3).to_string())


if __name__ == "__main__":
    main()
