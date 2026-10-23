"""event_study.csv -> 02_사건연구_결과.md

선정 절차(과최적화 방지):
1) 미국(US) 학습구간(IS)에서만 후보 선정: n>=300, |t|>=3
2) 같은 (패턴, 필터, h)의 US-OOS, KR-IS, KR-OOS 결과를 나란히 표시
3) 부호가 IS와 같고 OOS |t|>=2 이면 '생존'
"""
import numpy as np
import pandas as pd

from common import RESULTS, ROOT

KEY = ["pattern", "filter", "h"]


def pct(x, d=2):
    return "" if pd.isna(x) else f"{x * 100:.{d}f}%"


def num(x, d=1):
    return "" if pd.isna(x) else f"{x:.{d}f}"


def main():
    es = pd.read_csv(RESULTS / "event_study.csv")
    piv = {}
    for mk, per in [("US", "IS"), ("US", "OOS"), ("KR", "IS"), ("KR", "OOS"), ("ALL", "OOS")]:
        piv[(mk, per)] = es[(es.market == mk) & (es.period == per)].set_index(KEY)

    is_us = piv[("US", "IS")]
    cand = is_us[(is_us.n >= 300) & (is_us.t.abs() >= 3)].copy()
    cand["dir"] = np.sign(cand["excess"])
    j = cand[["n", "win", "base_win", "excess", "t", "pct_tk_pos", "dir"]].add_prefix("IS_")
    for (mk, per), tab in piv.items():
        if (mk, per) == ("US", "IS"):
            continue
        tag = f"{mk}_{per}"
        j = j.join(tab[["n", "win", "excess", "t"]].add_prefix(f"{tag}_"), how="left")
    j["survive_US"] = (np.sign(j["US_OOS_excess"]) == j["IS_dir"]) & (j["US_OOS_t"].abs() >= 2)
    j["survive_KR"] = (np.sign(j["KR_OOS_excess"]) == j["IS_dir"]) & (j["KR_OOS_t"].abs() >= 2)
    j["abs_t"] = j["IS_t"].abs()
    j = j.reset_index().sort_values(["survive_US", "abs_t"], ascending=False).drop(columns="abs_t")
    j.to_csv(RESULTS / "event_candidates.csv", index=False, encoding="utf-8-sig")

    lines = ["# 02. 사건연구 결과", "",
             "- 수익 정의: 신호일 종가 판정 → 다음날 시가 매수 → h거래일째 종가 매도, 왕복비용 0.1% 차감",
             "- 초과수익(excess): 같은 종목·같은 기간의 '아무 날이나 샀을 때' 평균 대비 차이",
             "- t: 진입월 단위로 묶은 t-통계 (|t|≥3 을 의미 있는 기준으로 사용)",
             "- 후보 선정은 **미국 1993~2014(IS)** 에서만 했고, 2015~ (OOS) 와 한국은 사후 확인용",
             "",
             f"후보 {len(j)}개 중 미국 OOS 생존 {int(j.survive_US.sum())}개, 한국 OOS 생존 {int(j.survive_KR.sum())}개",
             "",
             "| 패턴 | 필터 | h | IS n | IS 승률(기준) | IS 초과 | IS t | 종목+% | US-OOS 초과 | US-OOS t | KR-OOS 초과 | KR-OOS t | 생존 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in j.iterrows():
        mark = ("US" if r.survive_US else "") + ("+KR" if r.survive_KR else "")
        lines.append(
            f"| {r.pattern} | {r['filter']} | {r.h} | {int(r.IS_n)} | {pct(r.IS_win, 1)} ({pct(r.IS_base_win, 1)}) | "
            f"{pct(r.IS_excess)} | {num(r.IS_t)} | {pct(r.IS_pct_tk_pos, 0)} | {pct(r.US_OOS_excess)} | {num(r.US_OOS_t)} | "
            f"{pct(r.KR_OOS_excess)} | {num(r.KR_OOS_t)} | {mark} |")
    (ROOT / "02_사건연구_결과.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"candidates={len(j)} survive_US={int(j.survive_US.sum())} survive_KR={int(j.survive_KR.sum())}")


if __name__ == "__main__":
    main()
