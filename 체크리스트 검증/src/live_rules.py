"""실제 운용 규칙 점검 — 백테스트(final.py v2)와 자동 재점검(rebalance.py)의 차이 3가지를 시험한다.

backtest.simulate 의 v2 경로는 (a) 매달 비중을 1/20로 공짜로 되돌리고 (b) 관문 탈락을 매달 확인하며
(c) 1·4·7·10월 말에 재구성한다. 실제로는 비중이 움직이고, 되돌리는 매매에는 비용과 세금이 붙는다.

여기서는 금액을 직접 굴린다: 종목별 평가액·매입원가, 현금, 편도 비용(매매 금액 × 0.1%),
해외주식 양도세(연간 실현 순이익 − 250만 원 공제 × 22%, 시작 자본 1억 원 기준 공제 = 자본의 2.5%).
세후 결과는 끝에 전부 판다고 가정해 남은 평가익에도 세금을 매긴다.

시험 축
  weight : fixed(백테스트 그대로 — 매달 공짜 1/20) · monthly(매달 1/20, 비용·세금 반영)
           · reset(분기마다 1/20) · trim10(10% 넘을 때만 5%로, 현행 rebalance.py) · band(3~7.5% 밖만 5%로)
  fail   : monthly(매달 탈락 확인 → 현금) · replace(매달 확인 → 다음 순위로 바로 채움) · quarter(분기 점검 때만)
  phase  : 0 = 1·4·7·10월 말, 1 = 2·5·8·11월 말, 2 = 3·6·9·12월 말
실행: py src/live_rules.py -> results/live_rules.csv
"""
import numpy as np
import pandas as pd

from backtest import perf
from optimize import RES, Runner, spy_monthly
from robust import CAND

N, KEEP = 20, 30
COST, TAX, EXEMPT = 0.001, 0.22, 0.025
START = "2011-07"  # 세 phase 모두 첫 재구성이 끝난 뒤부터 비교


def prep(R):
    from checklist import DEFAULT
    from valuation import VDEFAULT
    rows, st = R.state({**DEFAULT}, {**VDEFAULT})
    months = [m for m in R.mc.index if m >= pd.Period("2011-04", "M")]
    by_m = dict(tuple(st.groupby("m")))
    ranks, grades = {}, {}
    for m in months:
        s = by_m.get(m)
        if s is None:
            continue
        s = s.set_index("cik")
        grades[m] = s.grade
        s = s[s.index.isin(R.mc.columns)]
        s = s.assign(mcap=R.mc.loc[m, s.index].values).dropna(subset=["mcap"])
        s = s[~s.sector_excl.fillna(False).astype(bool) & (s.mcap >= 10e9)]
        okq = s.grade.isin(["S", "A", "G"])
        qv = s.roic_med5.where(okq).rank(pct=True) + (s.fcf_sbc / s.mcap).where(okq).rank(pct=True)
        ranks[m] = list(qv[okq].sort_values(ascending=False).index)
    return months, ranks, grades, R.tri.pct_change(fill_method=None)


def run(months, ranks, grades, ret, tri, weight="trim10", fail="quarter", phase=0, tax_rate=TAX, harvest=None):
    V, B = {}, {}  # 평가액, 매입원가
    cash, gains, taxpaid, traded = 1.0, 0.0, 0.0, 0.0
    out = []

    def sell(c, amt):
        nonlocal cash, gains, traded
        amt = min(amt, V[c])
        if amt <= 0:
            return
        g = amt * (1 - B[c] / V[c]) if V[c] > 0 else 0.0
        B[c] *= 1 - amt / V[c]
        V[c] -= amt
        gains += g
        cash += amt * (1 - COST)
        traded += amt
        if V[c] <= 1e-12:
            V.pop(c); B.pop(c)

    def buy(c, amt):
        nonlocal cash, traded
        amt = min(amt, cash / (1 + COST))
        if amt <= 0:
            return
        V[c] = V.get(c, 0.0) + amt
        B[c] = B.get(c, 0.0) + amt
        cash -= amt * (1 + COST)
        traded += amt

    def to_target(T, names):
        # 목표 금액 T로 맞추기: 넘치는 쪽을 먼저 팔고 모자란 쪽을 산다
        for c in names:
            if V.get(c, 0) > T:
                sell(c, V[c] - T)
        for c in names:
            if V.get(c, 0) < T:
                buy(c, T - V.get(c, 0))

    for k, m in enumerate(months[:-1]):
        nxt = months[k + 1]
        rk = ranks.get(m, [])
        reb = k % 3 == phase
        total = cash + sum(V.values())
        # 관문 탈락 (등급 X) — 시총이 줄었다는 이유로는 팔지 않음
        if fail != "quarter" or reb:
            g = grades.get(m)
            for c in list(V):
                if g is not None and c in g.index and g[c] == "X":
                    sell(c, V[c])
                    if fail == "replace" and not reb:
                        nc = next((x for x in rk[:N] if x not in V), None) or next((x for x in rk if x not in V), None)
                        if nc is not None:
                            buy(nc, cash)
        if reb and rk:
            kept = [c for c in V if c in set(rk[:KEEP])]
            new = kept + [c for c in rk if c not in kept][:max(0, N - len(kept))]
            for c in list(V):
                if c not in new:
                    sell(c, V[c])
            total = cash + sum(V.values())
            T = total / N
            if weight in ("fixed", "monthly", "reset"):
                to_target(T, new)
            else:
                lo, hi = (0.035, 0.075) if weight == "band" else (0, 0.10)
                for c in new:
                    if c in V and (V[c] > hi * total or V[c] < lo * total):
                        if V[c] > T:
                            sell(c, V[c] - T)
                adds = [c for c in new if c not in V] + [c for c in new if c in V and V[c] < lo * total]
                need = sum(T - V.get(c, 0) for c in adds) * (1 + COST)
                if need > cash:  # 현금이 모자라면 5% 넘는 종목을 넘는 만큼 비례로 줄임
                    over = {c: V[c] - T for c in V if V[c] > T}
                    tot_over = sum(over.values())
                    for c, o in over.items():
                        sell(c, min(o, (need - cash) * o / tot_over * 1.002))
                for c in adds:
                    buy(c, T - V.get(c, 0))
                # 남는 현금은 가장 모자란 종목부터 5.5%까지
                for c in sorted(new, key=lambda c: V.get(c, 0)):
                    room = 0.055 * total - V.get(c, 0)
                    if cash > 1e-9 and room > 0:
                        buy(c, room)
        elif weight == "monthly" and V:
            to_target((cash + sum(V.values())) / N, list(V))
        # 다음 달 수익
        dead = []
        for c in list(V):
            x = ret.at[nxt, c] if c in ret.columns else np.nan
            if np.isnan(x):
                if c not in tri.columns or tri.loc[nxt:, c].notna().sum() == 0:
                    dead.append(c)
                x = 0.0
            V[c] *= 1 + x
        for c in dead:
            sell(c, V[c])
        if weight == "fixed" and V:  # 백테스트 그대로: 비용·세금 없이 1/20로 되돌림
            tot = cash + sum(V.values())
            for c in V:
                V[c] = B[c] = tot / N
            cash = tot - tot / N * len(V)
            gains = 0.0
        if nxt.month == 12 and harvest and weight != "fixed":
            gains, cash = harvest_year(V, B, gains, cash, harvest)
        if nxt.month == 12 or k == len(months) - 2:  # 연말 양도세
            tax = tax_rate * max(0.0, gains - EXEMPT) if weight != "fixed" else 0.0
            if k == len(months) - 2 and weight != "fixed":  # 끝에 전부 청산 가정
                unreal = sum(V[c] - B[c] for c in V)
                tax = tax_rate * max(0.0, gains + unreal - EXEMPT)
            if tax > 0:
                tot = sum(V.values())
                if cash >= tax:
                    cash -= tax
                else:
                    f = (tax - cash) / tot
                    for c in V:
                        V[c] *= 1 - f; B[c] *= 1 - f
                    cash = 0.0
                taxpaid += tax
            gains = 0.0
        out.append((nxt, cash + sum(V.values()), traded))
    s = pd.DataFrame(out, columns=["m", "nav", "traded"]).set_index("m")
    return s


def harvest_year(V, B, gains, cash, mode):
    """연말 절세(한국은 같은 해 손익을 합산하고 되사기 제한이 없다): 팔고 같은 날 되산다.
    loss: 실현이익이 공제를 넘으면 평가손 종목을 실현해 공제선까지 상쇄
    both: 거기에 더해 실현이익이 공제에 못 미치면 평가익 종목을 공제선까지 실현(취득가 올리기)"""
    for c in sorted(V, key=lambda c: V[c] - B[c]):
        if gains <= EXEMPT:
            break
        loss = V[c] - B[c]
        if loss < 0:
            use = min(1.0, (gains - EXEMPT) / -loss)
            gains += loss * use
            B[c] += loss * use
            cash -= 2 * COST * V[c] * use
    if mode == "both":
        for c in sorted(V, key=lambda c: B[c] - V[c]):
            if gains >= EXEMPT:
                break
            gain = V[c] - B[c]
            if gain > 0:
                use = min(1.0, (EXEMPT - gains) / gain)
                gains += gain * use
                B[c] += gain * use
                cash -= 2 * COST * V[c] * use
    return gains, cash


def spy_after_tax(spy, harvest=None):
    v, b, gains = 1.0, 1.0, 0.0
    for m, r in spy.items():
        v *= 1 + r
        if m.month == 12 and harvest == "both":
            g = min(max(0.0, v - b), EXEMPT)
            b += g
            v -= 2 * COST * v * (g / max(v - b + g, 1e-12))
    return v - TAX * max(0.0, v - b - EXEMPT)


def summarize(s, start=START):
    s = s[s.index >= pd.Period(start, "M")]
    r = s.nav.pct_change().dropna()
    p = perf(r)
    eq0, eq1 = s.nav.iloc[0], s.nav.iloc[-1]
    yrs = len(r) / 12
    p["traded/yr"] = (s.traded.iloc[-1] - s.traded.iloc[0]) / s.nav.mean() / yrs
    p["wealth"] = eq1 / eq0
    return p


def main():
    R = Runner("first")
    months, ranks, grades, ret = prep(R)
    rows = []
    grid = [("fixed", "monthly", 0)]
    grid += [(w, "monthly", 0) for w in ("monthly", "reset", "trim10", "band")]
    grid += [(w, f, 0) for w in ("reset", "trim10") for f in ("replace", "quarter")]
    grid += [(w, "quarter", p) for w in ("reset", "trim10") for p in (1, 2)]
    grid = [(w, f, p, None) for w, f, p in grid] + [("trim10", "quarter", p, h) for p in (0, 2) for h in ("loss", "both")]
    for w, f, p, h in grid:
        s = run(months, ranks, grades, ret, R.tri, w, f, p, harvest=h)
        s0 = run(months, ranks, grades, ret, R.tri, w, f, p, tax_rate=0.0)
        rows.append({"weight": w, "fail": f, "phase": p, "harvest": h or "", **summarize(s),
                     "pre_tax_CAGR": summarize(s0)["CAGR"]})
        print(rows[-1])
    spy = spy_monthly()
    spy = spy[(spy.index > pd.Period(START, "M"))].dropna()
    ps = perf(spy)
    w_spy = (1 + spy).prod()
    # SPY 그대로 보유: 끝에 한 번 청산할 때만 세금
    for h in ("", "both"):
        rows.append({"weight": "SPY 보유", "fail": "", "phase": "", "harvest": h, **ps, "traded/yr": 0.0,
                     "wealth": spy_after_tax(spy, h or None), "pre_tax_CAGR": ps["CAGR"]})
    df = pd.DataFrame(rows)
    yrs = len(spy) / 12
    df["after_tax_CAGR"] = df.wealth ** (1 / yrs) - 1
    df.to_csv(RES / "live_rules.csv", index=False, encoding="utf-8-sig")
    print(df.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
