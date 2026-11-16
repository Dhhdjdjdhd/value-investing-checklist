"""B. 자산배분 (원화 기준) + A의 현실 점검(팩터 ETF). 00_연구계획 §B.

주식 = S&P500 총수익(1993-02 이전 ^GSPC + 배당 2.8%/년) × 원/달러 → 환노출 (360750 성격)
채권 = 미국 30년 국채 합성(^TYX 금리로 가격 계산) + 환헤지 이득(CD91 − 미 3개월) → 453850 성격
현금 = 원화 CD91
실행: py src/alloc.py        -> results/B_rules.csv, B_crisis.csv, B_series.csv
      py src/alloc.py etf    -> results/A_etf_check.csv
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
RES.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (compatible; research-script)"
IS, OOS = ("1991-01", "2008-12"), ("2009-01", "2026-10")
COST = 0.001


def yahoo(sym, adj=False):
    p = DATA / f"y_{sym.replace('^', '')}_{'adj' if adj else 'c'}.csv"
    if p.exists():
        s = pd.read_csv(p, index_col=0).iloc[:, 0]
        return s
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^', '%5E')}?period1=600000000&period2=9999999999&interval=1d"
    for k in range(3):
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=90).read())
            break
        except Exception:
            time.sleep(3 * (k + 1))
    r = r["chart"]["result"][0]
    v = r["indicators"]["adjclose"][0]["adjclose"] if adj else r["indicators"]["quote"][0]["close"]
    s = pd.Series(v, index=pd.to_datetime(r["timestamp"], unit="s")).dropna()
    s = s.groupby(s.index.strftime("%Y-%m")).last()
    s.to_frame("v").to_csv(p)
    return s


def bond_ret(y, n=30):
    """만기 n년 국채를 매달 새로 사는 합성 수익: 월초 금리 y0 쿠폰, 월말 금리 y1로 평가."""
    def px(c, yy, yrs):
        k = round(yrs * 2)
        v = (1 + yy / 2) ** -k
        return c / 2 * (1 - v) / (yy / 2) + v
    out = [np.nan]
    for i in range(1, len(y)):
        y0, y1 = y.iloc[i - 1], y.iloc[i]
        out.append(px(y0, y1, n - 1 / 12) + y0 / 12 - 1)
    return pd.Series(out, index=y.index)


def build():
    E = pd.read_csv(DATA / "ecos_krw.csv", index_col=0)
    gs, spy, irx, tyx = yahoo("^GSPC"), yahoo("SPY", True), yahoo("^IRX"), yahoo("^TYX")
    D = pd.DataFrame({"fx": E.fx_end, "cd": E.cd91, "gs": gs, "spy": spy, "irx": irx, "tyx": tyx}).loc["1989-01":"2026-10"]
    ru = D.spy.pct_change()
    D["ru"] = ru.where(D.index >= "1993-03", D.gs.pct_change() + 0.028 / 12)  # 달러 총수익
    D["un"] = (1 + D.ru) * (1 + D.fx.pct_change()) - 1                         # 원화 환노출 주식
    D["carry"] = (D.cd.shift(1) - D.irx.shift(1)) / 1200
    y = (D.tyx / 100).ffill()
    D["bh"] = bond_ret(y) + D.carry                                            # 30년 국채 환헤지
    D["cash"] = D.cd.shift(1) / 1200
    D["px"] = D.gs                                                              # 추세 신호용 지수(달러, 가격)
    return D.loc["1990-01":]


def weights(D, rule):
    """월말 t 에 정한 비중 (다음 달에 적용). 열: eq, bond, cash"""
    idx = D.index
    W = pd.DataFrame(0.0, index=idx, columns=["eq", "bond", "cash"])
    sma10 = D.px.rolling(10).mean()
    up = D.px > sma10
    if rule == "B0":
        W["eq"] = 1.0
    elif rule == "B1":
        W["eq"], W["bond"] = 0.8, 0.2
    elif rule == "B2":
        W["eq"] = up.astype(float); W["bond"] = 1 - W["eq"]
    elif rule == "B3":
        W["eq"] = up.astype(float); W["cash"] = 1 - W["eq"]
    elif rule == "B4":
        W["eq"] = 0.8 * up.astype(float); W["bond"] = 1 - W["eq"]
    elif rule == "B5":
        r12 = D.px / D.px.shift(12) - 1 + 0.0  # 가격 기준 12개월
        rf12 = D.irx.rolling(12).mean() / 100
        W["eq"] = (r12 > rf12).astype(float); W["bond"] = 1 - W["eq"]
    elif rule == "B6":
        vol = D.un.rolling(6).std() * np.sqrt(12)
        W["eq"] = (0.15 / vol).clip(upper=1.0).fillna(1.0); W["bond"] = 1 - W["eq"]
    return W


NAMES = {"B0": "주식 100%", "B1": "80/20 연1회 (현재 계획)", "B2": "추세(10개월선) → 국채",
         "B3": "추세(10개월선) → 현금", "B4": "80/20 + 주식몫 추세", "B5": "절대 모멘텀 → 국채",
         "B6": "변동성 15% 맞추기 → 국채"}


def simulate(D, rule, a, b):
    W = weights(D, rule)
    R = D[["un", "bh", "cash"]].rename(columns={"un": "eq", "bh": "bond"})
    sub = D.loc[a:b].index
    v = {"eq": 0.0, "bond": 0.0, "cash": 0.0}
    eq, switches = [], 0
    prev = None
    for i, m in enumerate(sub):
        pm = D.index[D.index.get_loc(m) - 1]  # 직전 월말 신호
        tgt = W.loc[pm].to_dict()
        tot = sum(v.values()) if i else 1.0
        if i == 0:
            v = {k: tot * w for k, w in tgt.items()}
        else:
            rebal = (rule != "B1") or pm.endswith("-12")
            if rebal:
                cur = {k: v[k] / tot for k in v}
                turn = sum(abs(tgt[k] - cur[k]) for k in v) / 2
                if rule != "B1" and prev is not None and abs(tgt["eq"] - prev["eq"]) > 0.5:
                    switches += 1
                tot *= 1 - turn * COST * 2
                v = {k: tot * w for k, w in tgt.items()}
        prev = tgt
        v = {k: v[k] * (1 + (R.at[m, k] if np.isfinite(R.at[m, k]) else 0.0)) for k in v}
        eq.append(sum(v.values()))
    e = pd.Series(eq, index=sub)
    r = e.pct_change().fillna(e.iloc[0] - 1)
    yrs = len(e) / 12
    yr = e.groupby(e.index.str[:4]).last()
    yr = yr / yr.shift(1).fillna(1) - 1
    return {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * np.sqrt(12), "Sharpe_like": r.mean() / r.std() * np.sqrt(12),
            "MDD": (e / e.cummax() - 1).min(), "worst_yr": yr.min(), "worst_yr_at": yr.idxmin(),
            "switch_per_yr": switches / yrs, "eq_avg": W.loc[sub, "eq"].mean()}, e


CRISES = {"닷컴 2000.09~2003.02": ("2000-09", "2003-02"), "금융위기 2007.11~2009.02": ("2007-11", "2009-02"),
          "코로나 2020.02~2020.03": ("2020-02", "2020-03"), "금리급등 2022.01~2022.10": ("2022-01", "2022-10")}


def main():
    D = build()
    rows, crisis, ser = [], [], {}
    for rule in NAMES:
        rec = {"rule": rule, "name": NAMES[rule]}
        for tag, (a, b) in (("IS", IS), ("OOS", OOS), ("ALL", (IS[0], OOS[1]))):
            p, e = simulate(D, rule, a, b)
            rec.update({f"{tag}_{k}": v for k, v in p.items()})
            if tag == "ALL":
                ser[rule] = e
        rows.append(rec)
        c = {"rule": rule}
        for k, (a, b) in CRISES.items():
            _, e = simulate(D, rule, a, b)
            c[k] = e.iloc[-1] - 1
        crisis.append(c)
        print(f"{rule} {NAMES[rule]:22s} IS {rec['IS_CAGR']:.1%}/{rec['IS_MDD']:.0%} | OOS {rec['OOS_CAGR']:.1%}/{rec['OOS_MDD']:.0%} "
              f"| ALL {rec['ALL_CAGR']:.1%}/{rec['ALL_MDD']:.0%} worst {rec['ALL_worst_yr']:.0%}({rec['ALL_worst_yr_at']}) sw/yr {rec['ALL_switch_per_yr']:.1f}", flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(RES / "B_rules.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(crisis).to_csv(RES / "B_crisis.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ser).to_csv(RES / "B_series.csv", encoding="utf-8-sig")
    print(pd.DataFrame(crisis).set_index("rule").map(lambda x: f"{x:.0%}").to_string())
    b1 = d.set_index("rule").loc["B1"]
    print("\n사전 등록 판정 (B1 대비: MDD 5%p 이상 개선 & 연수익 1%p 넘게 줄지 않음)")
    for _, x in d.iterrows():
        if x.rule in ("B0", "B1"):
            continue
        ok_is = (x.IS_MDD - b1.IS_MDD >= 0.05) and (x.IS_CAGR - b1.IS_CAGR >= -0.01)
        ok_oos = (x.OOS_MDD - b1.OOS_MDD >= 0.05) and (x.OOS_CAGR - b1.OOS_CAGR >= -0.01)
        verdict = "추천" if ok_is and ok_oos else ("보류" if ok_is else "탈락")
        print(f"  {x.rule} {x['name']:22s} 학습 {'O' if ok_is else 'X'} 검증 {'O' if ok_oos else 'X'} -> {verdict}")


def etf_check():
    """생존편향 없는 현실 점검: 실제 팩터 ETF vs SPY (상장 후 공통 구간)."""
    tick = {"MTUM": "모멘텀(MSCI)", "SPMO": "모멘텀(S&P500)", "QUAL": "품질(MSCI)", "SPHQ": "품질(S&P500)", "SPY": "S&P500"}
    S = pd.DataFrame({t: yahoo(t, True) for t in tick}).loc[:"2026-10"]
    R = S.pct_change()
    rows = []
    for t in tick:
        if t == "SPY":
            continue
        x = R[[t, "SPY"]].dropna()
        x = x.iloc[1:]
        for nm, col in ((t, t), ("SPY 같은 구간", "SPY")):
            r = x[col]
            e = (1 + r).cumprod()
            yrs = len(r) / 12
            rows.append({"etf": t, "series": nm, "from": x.index[0], "CAGR": e.iloc[-1] ** (1 / yrs) - 1,
                         "Sharpe_like": r.mean() / r.std() * np.sqrt(12), "MDD": (e / e.cummax() - 1).min()})
    d = pd.DataFrame(rows)
    d.to_csv(RES / "A_etf_check.csv", index=False, encoding="utf-8-sig")
    print(d.round(3).to_string(index=False))


if __name__ == "__main__":
    etf_check() if "etf" in sys.argv else main()
