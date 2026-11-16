"""S&P500 100% — 환율 수준에 따라 환노출(360750) / 환헤지(449180·448290) 전환 비교. 원화, 월간.

신호는 월말 환율 -> 다음 달 적용, 전환 1회당 비용 0.1%.
실행: py src/fxswitch.py -> results/D_fxswitch.csv
"""
import numpy as np
import pandas as pd

from alloc import RES, build

D = build()
fx = D.fx
UN, HE = D.un, D.ru + D.carry  # 환노출, 환헤지


def state_rule(enter, exit_, maxm=None):
    """enter(x)가 참이면 헤지 시작, exit_(x)가 참이거나 maxm개월 지나면 복귀."""
    st, c, n = [], 0.0, 0
    for i, x in enumerate(fx):
        if c == 0 and enter(i):
            c, n = 1.0, 0
        elif c == 1:
            n += 1
            if exit_(i) or (maxm and n >= maxm):
                c = 0.0
        st.append(c)
    return pd.Series(st, index=fx.index)


ma = {k: fx.rolling(k * 12, min_periods=k * 12).mean() for k in (3, 5)}


def rel(k, up, dn, hedge_when_high=True):
    dev = fx / ma[k] - 1
    if hedge_when_high:
        return state_rule(lambda i: dev.iloc[i] >= up, lambda i: dev.iloc[i] < dn)
    return state_rule(lambda i: dev.iloc[i] <= -up, lambda i: dev.iloc[i] > -dn)


RULES = {
    "환노출 계속 (360750 그대로)": pd.Series(0.0, index=fx.index),
    "환헤지 계속": pd.Series(1.0, index=fx.index),
    "제안 그대로: 5년평균보다 높으면 노출, 낮으면 헤지": (fx < ma[5]).astype(float),
    "반대: 5년평균보다 높으면 헤지, 낮으면 노출": (fx > ma[5]).astype(float),
    "5년평균 +7% 이상 헤지, 평균 아래로 오면 복귀": rel(5, 0.07, 0.0),
    "5년평균 +10% 이상 헤지, +3% 아래면 복귀": rel(5, 0.10, 0.03),
    "3년평균 +7% 이상 헤지, 평균 아래로 오면 복귀": rel(3, 0.07, 0.0),
    "현재 규칙: 1,450 이상 헤지, 1,350 미만·12개월 복귀": state_rule(lambda i: fx.iloc[i] >= 1450,
                                                        lambda i: fx.iloc[i] < 1350, 12),
}
PER = {"1991~": ("1991-01", "2026-10"), "1999~ (IMF 제외)": ("1999-01", "2026-10"),
       "2008.7~": ("2008-07", "2026-10"), "2015~": ("2015-01", "2026-10")}


def run(h, a, b):
    w = h.shift(1).fillna(0)
    r = (1 - w) * UN + w * HE - w.diff().abs().fillna(0) * 0.001
    r = r.loc[a:b].dropna()
    e = (1 + r).cumprod()
    return e.iloc[-1] ** (12 / len(r)) - 1, (e / e.cummax() - 1).min()


rows = []
for name, h in RULES.items():
    rec = {"규칙": name}
    for k, (a, b) in PER.items():
        c, m = run(h, a, b)
        rec[f"{k} 연수익"], rec[f"{k} MDD"] = c, m
    hh = h.loc["1999-01":]
    rec["헤지 기간 비율(1999~)"] = hh.mean()
    rec["전환 횟수(1999~)"] = int((hh.diff().abs() > 0).sum())
    rows.append(rec)
d = pd.DataFrame(rows)
d.to_csv(RES / "D_fxswitch.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250)
s = d.copy()
for c in s.columns[1:]:
    if "횟수" not in c:
        s[c] = s[c].map(lambda x: f"{x:.1%}")
print(s.to_string(index=False))
print("현재 환율", fx.iloc[-1], "5년평균", round(ma[5].iloc[-1]), "3년평균", round(ma[3].iloc[-1]),
      "헤지 비용(연)", f"{-D.carry.iloc[-1] * 12:.2%}")
