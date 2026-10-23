"""체크리스트 검증·최적화 실험.

1) 기준선: 문서 규칙 그대로 / 품질만(가격 무시, 통과 종목 전부 동일비중) / 동일비중 대형주 / SPY
2) 한 번에 한 요소씩 흔들기 (학습 2011~2018에서 평가, 검증 2019~ 결과도 함께 기록하되 선택엔 안 씀)
3) 학습 구간에서 개선된 요소만 결합 -> 검증 구간 1회 확인

실행: py src/optimize.py [first|last]
산출: results/exp_*.csv
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import SDEFAULT, evaluate_rows, load, monthly_state, perf, simulate
from checklist import DEFAULT
from valuation import VDEFAULT

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RES.mkdir(exist_ok=True)
IS = ("2011-04", "2018-12")  # 시총은 첫 연간 공시 후에 생기므로 2011-03까지는 우주가 얇다
OOS = ("2019-01", None)
SPY_CSV = ROOT.parent / "차트 아록리즘 분석" / "data" / "raw" / "SPY.csv"


def spy_monthly():
    s = pd.read_csv(SPY_CSV, parse_dates=["date"]).set_index("date").adj_close
    m = s.groupby(s.index.to_period("M")).last()
    return m.pct_change()


def ew_universe(mc, tri, min_mcap=10e9):
    ret = tri.pct_change(fill_method=None)
    big = mc.shift(1) >= min_mcap  # 전월말 시총 기준
    return ret.where(big).mean(axis=1)


class Runner:
    def __init__(self, mode):
        self.ann, self.mc, self.tri, self.dd = load(mode)
        self.cache = {}
        self.rows_out = []

    def state(self, P, V):
        key = (tuple(sorted(P.items())), tuple(sorted(V.items())))
        if key not in self.cache:
            rows = evaluate_rows(self.ann, P, V)
            self.cache = {key: (rows, monthly_state(rows, self.mc.index))}  # 메모리 절약: 최근 1개만
        return self.cache[key]

    def run(self, name, P=None, V=None, S=None, group=""):
        P = {**DEFAULT, **(P or {})}
        V = {**VDEFAULT, **(V or {})}
        S = {**SDEFAULT, **(S or {})}
        rows, st = self.state(P, V)
        t0 = time.time()
        S2 = {**S, "start": IS[0], "end": None}
        r, log, nh = simulate(self.ann, self.mc, self.tri, self.dd, P, V, S2, rows=rows, state=st)
        rec = {"group": group, "name": name}
        for tag, (a, b) in (("IS", IS), ("OOS", OOS)):
            rr = r[(r.index >= pd.Period(a, "M")) & ((r.index <= pd.Period(b, "M")) if b else True)]
            p = perf(rr)
            rec.update({f"{tag}_{k}": v for k, v in p.items()})
            nhh = nh[nh.index.isin(rr.index)]
            rec[f"{tag}_avg_hold"] = nhh.mean()
        rec["trades"] = (log.act == "buy").sum()
        rec["turnover_yr"] = rec["trades"] / (len(r) / 12)
        rec["secs"] = round(time.time() - t0, 1)
        self.rows_out.append(rec)
        print(f"{group:10s} {name:40s} IS CAGR={rec.get('IS_CAGR', np.nan):6.1%} Sh={rec.get('IS_Sharpe', np.nan):5.2f} | "
              f"OOS CAGR={rec.get('OOS_CAGR', np.nan):6.1%} Sh={rec.get('OOS_Sharpe', np.nan):5.2f} hold={rec.get('OOS_avg_hold', np.nan):4.1f}", flush=True)
        return r, log, nh


def bench_rows(R):
    spy = spy_monthly()
    ew = ew_universe(R.mc, R.tri)
    out = []
    for nm, s in (("SPY", spy), ("EW 대형주(>=$10B)", ew)):
        rec = {"group": "bench", "name": nm}
        for tag, (a, b) in (("IS", IS), ("OOS", OOS)):
            rr = s[(s.index >= pd.Period(a, "M")) & ((s.index <= pd.Period(b, "M")) if b else True)]
            rec.update({f"{tag}_{k}": v for k, v in perf(rr).items()})
        out.append(rec)
        print(f"bench      {nm:40s} IS CAGR={rec['IS_CAGR']:6.1%} Sh={rec['IS_Sharpe']:5.2f} | OOS CAGR={rec['OOS_CAGR']:6.1%} Sh={rec['OOS_Sharpe']:5.2f}", flush=True)
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "first"
    R = Runner(mode)
    bench = bench_rows(R)
    # --- 1) 기준
    R.run("문서 규칙 그대로", group="base")
    R.run("품질만(가격 무시, 통과 전부)", S={"use_price": None, "slots": 1000, "swap_gap": None}, group="base")
    R.run("품질만 S·A", S={"use_price": None, "slots": 1000, "swap_gap": None, "allow_grades": ("S", "A")}, group="base")
    # --- 2) 가격 규칙
    for nm, mult in (("IV에 매수(배수 1.0)", {"S": 1.0, "A": 1.0, "G": 1.0}),
                     ("문서보다 깐깐(0.8/0.75/0.7)", {"S": 0.8, "A": 0.75, "G": 0.7}),
                     ("매우 깐깐(0.7/0.65/0.6)", {"S": 0.7, "A": 0.65, "G": 0.6}),
                     ("등급 무관 일률 0.8", {"S": 0.8, "A": 0.8, "G": 0.8})):
        R.run(nm, S={"mult": mult}, group="price")
    R.run("스크린B식: 52주 −30%", S={"use_price": "dd", "rank": "dd"}, group="price")
    R.run("스크린B식: 52주 −20%", S={"use_price": "dd", "dd_th": 0.20, "rank": "dd"}, group="price")
    R.run("가격 무시 + 싼 순 10개", S={"use_price": None, "rank": "cheap"}, group="price")
    # --- 3) 등급·품질 문턱
    R.run("S·A만", S={"allow_grades": ("S", "A")}, group="grade")
    for th in (0.10, 0.20, 0.25):
        R.run(f"ROIC 문턱 {th:.0%}", P={"roic_min": th}, group="grade")
    R.run("경기순환 숫자판정 끔", P={"use_cyclical": False}, group="grade")
    R.run("ROIC 미달 = 경고(탈락 아님)", P={"roic_mode": "warn"}, group="grade")
    R.run("섹터 제외 끔", S={"excl_sector": False}, group="grade")
    # --- 4) 내재가치 가정
    for tm in (0.8, 1.0):
        R.run(f"종료PER 배수 {tm}", V={"tpe_mult": tm}, group="value")
    for cap in (30.0, 99.0):
        R.run(f"종료PER 상한 {cap:.0f}", V={"tpe_cap": cap}, group="value")
    for hc in (0.6, 1.0):
        R.run(f"성장률 haircut {hc}", V={"haircut": hc}, group="value")
    for gc in (0.10, 0.12):
        R.run(f"성장률 상한 {gc:.0%}", V={"g_cap": gc}, group="value")
    R.run("기준이익 = FCF−SBC", V={"base": "fcf_sbc"}, group="value")
    R.run("기준이익 = min(순이익, FCF−SBC)", V={"base": "min"}, group="value")
    for d in (0.08, 0.10):
        R.run(f"할인율 {d:.0%}", V={"disc": d}, group="value")
    # --- 5) 포트폴리오·청산
    for n in (5, 20):
        R.run(f"슬롯 {n}", S={"slots": n}, group="port")
    for gap in (None, 0.05, 0.30):
        R.run(f"갈아타기 격차 {gap}", S={"swap_gap": gap}, group="exit")
    for tm in (1.0, 1.3):
        R.run(f"낙관IV×{tm} 넘으면 매도", S={"trim_mult": tm}, group="exit")
    R.run("시총 문턱 $2B", S={"min_mcap": 2e9}, group="port")
    # --- 6) 판 뒤집기 후보: 목표가 대기 대신 '품질 통과 + 복합 순위 상위 N, 정기 재구성'
    for rk in ("qv", "fcf_yield", "earn_yield", "roic_med5"):
        for n, rb in ((20, 12), (20, 3), (10, 12)):
            R.run(f"재구성 {rk} 상위{n} {rb}개월", S={"use_price": None, "rank": rk, "slots": n, "rebalance": rb,
                                                   "swap_gap": None}, group="overhaul")
    R.run("재구성 qv 상위20 12개월 S·A만", S={"use_price": None, "rank": "qv", "slots": 20, "rebalance": 12,
                                       "swap_gap": None, "allow_grades": ("S", "A")}, group="overhaul")
    R.run("재구성 qv 상위20 12개월 IV이하만", S={"use_price": "iv", "mult": {"S": 1.0, "A": 1.0, "G": 1.0},
                                         "rank": "qv", "slots": 20, "rebalance": 12, "swap_gap": None}, group="overhaul")
    out = pd.DataFrame(bench + R.rows_out)
    out.to_csv(RES / f"exp_oneatatime_{mode}.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
