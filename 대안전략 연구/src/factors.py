"""A. 종목 선택: 품질 관문 + 모멘텀·주식수 감소·주주환원 (00_연구계획 §A).

엔진은 `체크리스트 검증/src` 를 그대로 쓰고, 순위만 S["score"] 훅으로 바꾼다.
실행: py src/factors.py           -> results/A_rules.csv, A_series.csv, A_boot.csv
      py src/factors.py robust    -> results/A_robust.csv (채택 후보 견고성)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ENG = ROOT.parent / "체크리스트 검증" / "src"
sys.path.insert(0, str(ENG))
from backtest import evaluate_rows, load, monthly_state, perf, simulate  # noqa: E402
from checklist import DEFAULT  # noqa: E402
from optimize import IS, OOS, ew_universe, spy_monthly  # noqa: E402
from robust import CAND, boot_sharpe_diff, split_perf  # noqa: E402
from valuation import VDEFAULT  # noqa: E402

RES = ROOT / "results"
RES.mkdir(exist_ok=True)
V2 = {**CAND, "rebalance": 3, "buffer": 1.5, "rank": "score"}


def add_signals(ann, rows, st, mc, tri):
    # B: 주식 수 감소 (연속 연도만, 극단값은 단위 오류로 보고 제외)
    a = ann[["cik", "cy", "sh_adj", "div", "buyback"]].sort_values(["cik", "cy"]).copy()
    prev = a.groupby("cik").shift(1)
    chg = a.sh_adj / prev.sh_adj - 1
    chg = chg.where((a.cy - prev.cy) == 1)
    chg = chg.where(chg.abs() < 0.5)
    a["shr"] = -chg
    a["payout"] = a["div"].fillna(0).clip(lower=0) + a["buyback"].fillna(0).clip(lower=0)
    st = st.merge(a[["cik", "cy", "shr", "payout"]], on=["cik", "cy"], how="left")
    # M: 12-1 모멘텀 (월말 m 에서 tri[m-1]/tri[m-12]-1)
    mom = tri.shift(1) / tri.shift(12) - 1
    mom = mom.stack().rename("mom").reset_index()
    mom.columns = ["m", "cik", "mom"]
    st = st.merge(mom, on=["m", "cik"], how="left")
    return st


def pct(x, okq):
    return x.where(okq).rank(pct=True)


def make_score(kind):
    def f(s, okq):
        q = pct(s.roic_med5, okq) + pct(s.fcf_sbc / s.mcap, okq)
        m = pct(s.mom, okq)
        if kind == "QV":
            return q
        if kind.startswith("QV+M*"):
            w = float(kind.split("*")[1])
            return q + w * m
        if kind == "QV|Mfilter":
            return q.where(m > 1 / 3)
        if kind == "M":
            return m
        if kind == "QV+B":
            return q + pct(s.shr, okq)
        if kind == "QV+Y":
            return q + pct(s.payout / s.mcap, okq)
        if kind == "QV+M+B":
            return q + m + pct(s.shr, okq)
        raise ValueError(kind)
    return f


RULES = [
    ("A0", "v2 기준 (Q+V)", "QV", {}),
    ("A1", "Q+V+M", "QV+M*1", {}),
    ("A2", "Q+V+0.5M", "QV+M*0.5", {}),
    ("A3", "Q+V+2M", "QV+M*2", {}),
    ("A4", "Q+V, M 하위 1/3 제외", "QV|Mfilter", {}),
    ("A5", "관문 + M만", "M", {}),
    ("A6", "관문 없음 + M만 (순수 모멘텀)", "M", {"allow_grades": ("S", "A", "G", "X")}),
    ("A7", "Q+V+B (주식수 감소)", "QV+B", {}),
    ("A8", "Q+V+Y (주주환원, 근사)", "QV+Y", {}),
    ("A9", "Q+V+M+B", "QV+M+B", {}),
]


class R:
    def __init__(self, mode="first"):
        self.ann, self.mc, self.tri, self.dd = load(mode)
        P, V = {**DEFAULT}, {**VDEFAULT}
        self.P, self.V = P, V
        self.rows = evaluate_rows(self.ann, P, V)
        st = monthly_state(self.rows, self.mc.index)
        self.st = add_signals(self.ann, self.rows, st, self.mc, self.tri)

    def run(self, kind, extra=None):
        S = {**V2, "score": make_score(kind), "start": IS[0], "end": None, **(extra or {})}
        r, log, nh = simulate(self.ann, self.mc, self.tri, self.dd, self.P, self.V, S, rows=self.rows, state=self.st)
        return r, log


def main():
    R0 = R("first")
    spy, ew = spy_monthly(), ew_universe(R0.mc, R0.tri)
    out, ser = [], {}
    for code, name, kind, extra in RULES:
        r, log = R0.run(kind, extra)
        yrs = len(r) / 12
        rec = {"code": code, "rule": name, **split_perf(r), "turnover_yr": (log.act == "buy").sum() / yrs / 20}
        out.append(rec)
        ser[code] = r
        print(f"{code} {name:28s} IS Sh {rec['IS_Sharpe']:.2f} CAGR {rec['IS_CAGR']:.1%} | OOS Sh {rec['OOS_Sharpe']:.2f} "
              f"CAGR {rec['OOS_CAGR']:.1%} | ALL {rec['ALL_CAGR']:.1%} MDD {rec['ALL_MDD']:.0%} TO {rec['turnover_yr']:.0%}", flush=True)
    for nm, s in (("SPY", spy), ("EW 대형주", ew)):
        s = s[s.index >= pd.Period(IS[0], "M")]
        out.append({"code": nm, "rule": nm, **split_perf(s)})
        ser[nm] = s
    d = pd.DataFrame(out)
    d.to_csv(RES / "A_rules.csv", index=False, encoding="utf-8-sig")
    S = pd.DataFrame(ser)
    S.index = S.index.astype(str)
    S.to_csv(RES / "A_series.csv", encoding="utf-8-sig")
    # 사전 등록 선택 규칙
    cand = d[d.code.isin([f"A{i}" for i in range(1, 10)])].sort_values("IS_Sharpe", ascending=False).iloc[0]
    a0 = d[d.code == "A0"].iloc[0]
    adopt = (cand.IS_Sharpe - a0.IS_Sharpe >= 0.05) and (cand.OOS_Sharpe >= a0.OOS_Sharpe)
    print(f"\n학습 1위 후보: {cand.code} {cand.rule}  IS {cand.IS_Sharpe:.2f} vs A0 {a0.IS_Sharpe:.2f} | "
          f"OOS {cand.OOS_Sharpe:.2f} vs A0 {a0.OOS_Sharpe:.2f}  -> {'채택' if adopt else 'v2 유지'}")
    b = []
    S2 = pd.DataFrame(ser).dropna()
    for c in ["A0", cand.code]:
        for bn in ("SPY", "EW 대형주"):
            ci, p = boot_sharpe_diff(S2[c], S2[bn])
            b.append({"rule": c, "vs": bn, "median": ci[1], "lo": ci[0], "hi": ci[2], "P>0": p})
    bd = pd.DataFrame(b)
    bd.to_csv(RES / "A_boot.csv", index=False, encoding="utf-8-sig")
    print(bd.round(3).to_string(index=False))
    (RES / "A_choice.txt").write_text(f"{cand.code}\t{'adopt' if adopt else 'keep_v2'}", encoding="utf-8")


def robust():
    code = (RES / "A_choice.txt").read_text(encoding="utf-8").split("\t")[0]
    kind, extra = {c: (k, e) for c, _, k, e in RULES}[code]
    rows = []
    R0 = R("first")
    for n in (15, 20, 30):
        for rb in (1, 3, 6):
            for c in (code, "A0"):
                k, e = {cc: (kk, ee) for cc, _, kk, ee in RULES}[c]
                r, _ = R0.run(k, {**e, "slots": n, "rebalance": rb})
                rows.append({"rule": c, "N": n, "rebal": rb, "cost": 0.001, "data": "first", **split_perf(r)})
                print(rows[-1]["rule"], n, rb, round(rows[-1]["ALL_Sharpe"], 3), flush=True)
    for c in (code, "A0"):
        k, e = {cc: (kk, ee) for cc, _, kk, ee in RULES}[c]
        r, _ = R0.run(k, {**e, "cost": 0.003})
        rows.append({"rule": c, "N": 20, "rebal": 3, "cost": 0.003, "data": "first", **split_perf(r)})
    del R0
    L = R("last")
    for c in (code, "A0"):
        k, e = {cc: (kk, ee) for cc, _, kk, ee in RULES}[c]
        r, _ = L.run(k, e)
        rows.append({"rule": c, "N": 20, "rebal": 3, "cost": 0.001, "data": "last", **split_perf(r)})
    pd.DataFrame(rows).to_csv(RES / "A_robust.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(rows)[["rule", "N", "rebal", "cost", "data", "IS_Sharpe", "OOS_Sharpe", "ALL_Sharpe", "ALL_CAGR"]].round(3).to_string(index=False))


if __name__ == "__main__":
    robust() if "robust" in sys.argv else main()
