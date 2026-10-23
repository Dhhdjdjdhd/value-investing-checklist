"""추가 전략군: 평균회귀 단타가 OOS에서 Buy&Hold를 못 이긴 뒤 시험하는 대안들.

A) 추세 타이밍: 종가 > N일 이동평균일 때만 보유(아니면 현금). 다음날 시가 체결.
B) 횡단면 모멘텀: 매월 말 12-1개월 수익률 상위 N종목 동일비중 보유 (다음 거래일 시가 리밸런스 근사: 종가 기준).
C) 평균회귀 규칙을 다른 시장(한국)·ETF에 그대로 적용(파라미터 재조정 없음).

실행: py src/strategy2.py
"""
import numpy as np
import pandas as pd

import common
from common import IS_END, OOS_START, RESULTS, load_all, market_of
from indicators import sma
from strategy import Rule, portfolio, run_trades, stats

START = pd.Timestamp("1994-01-01")
ETF = "SPY QQQ DIA IWM MDY EFA EEM TLT GLD XLK XLF XLE XLV XLI XLY XLP XLU XLB".split()


def timing(df, n):
    """종가>SMA(n) 판정 다음날 시가부터 보유. 일별 수익(보유일은 시가->종가 등 정확 분해)."""
    c, o = df["close"], df["open"]
    sig = (c > sma(c, n)).astype(float)
    pos = sig.shift(1)       # 오늘 보유 여부(어제 종가 판정)
    prev = pos.shift(1).fillna(0)
    r_cc = c / c.shift() - 1
    r_oc = c / o - 1          # 진입일: 시가 매수
    r_co = o / c.shift() - 1  # 청산일: 시가 매도
    r = np.where((pos == 1) & (prev == 1), r_cc, 0.0)
    r = np.where((pos == 1) & (prev == 0), (1 + r_oc) * (1 - common.COST) - 1, r)
    r = np.where((pos == 0) & (prev == 1), (1 + r_co) * (1 - common.COST) - 1, r)
    return pd.Series(r, index=df.index).fillna(0)


def momentum(data, top=10, lookback=252, skip=21):
    close = pd.DataFrame({t: d["close"] for t, d in data.items()}).sort_index()
    close = close.ffill(limit=5)
    rets = close.pct_change(fill_method=None)
    mom = close.shift(skip) / close.shift(lookback) - 1
    month_end = close.index.to_series().groupby(close.index.to_period("M")).max()
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    cur = pd.Series(0.0, index=close.columns)
    me = set(month_end.values)
    turn = pd.Series(0.0, index=close.index)
    for d in close.index:
        if d in me:
            m = mom.loc[d].dropna()
            new = pd.Series(0.0, index=close.columns)
            if len(m) >= top:
                new[m.nlargest(top).index] = 1.0 / top
            turn[d] = (new - cur).abs().sum()
            cur = new
        w.loc[d] = cur
    port = (w.shift(1) * rets).sum(axis=1) - turn.shift(1).fillna(0) * common.COST
    return port


def mr_rule():
    """OOS에서 가장 나았던 IS 상위 규칙 중 하나 (down3|all|rsi2>70) 고정."""
    return Rule("down3|all|rsi2>70", entry=lambda df, f, pt: pt["down3"],
                exit=lambda df, f, pt: f["rsi2"] > 70, max_hold=10, score=lambda df, f, pt: f["rsi2"])


def row(name, d, period, tr=None):
    d = d.loc[START:IS_END] if period == "IS" else d.loc[OOS_START:]
    return {"strategy": name, "period": period, **stats(d, tr)}


def main():
    data = load_all()
    us = {t: d for t, d in data.items() if market_of(t) == "US"}
    kr = {t: d for t, d in data.items() if market_of(t) == "KR"}
    stocks_us = {t: d for t, d in us.items() if t not in ETF}
    rows = []
    # A) 추세 타이밍
    spy = us["SPY"]
    bh = spy["close"].pct_change().fillna(0)
    for per in ("IS", "OOS"):
        rows.append(row("SPY buy&hold", bh, per))
        for n in (50, 100, 200):
            rows.append(row(f"SPY timing SMA{n}", timing(spy, n), per))
    ew_t = pd.DataFrame({t: timing(d, 200) for t, d in stocks_us.items()}).loc[START:]
    ew_bh = pd.DataFrame({t: d["close"].pct_change() for t, d in stocks_us.items()}).loc[START:]
    for per in ("IS", "OOS"):
        rows.append(row("US stocks EW buy&hold", ew_bh.mean(axis=1).fillna(0), per))
        # 종목별 타이밍: 현금 비중 포함 동일비중(상장된 종목 수 기준)
        alive = ew_bh.notna()
        rows.append(row("US stocks EW timing SMA200", (ew_t.where(alive)).mean(axis=1).fillna(0), per))
    # B) 모멘텀
    mom = momentum(stocks_us).loc[START:]
    for per in ("IS", "OOS"):
        rows.append(row("US momentum 12-1 top10", mom, per))
    # C) 평균회귀 규칙 타 시장 적용
    r = mr_rule()
    for name, univ in (("MR down3 on KR stocks", kr), ("MR down3 on ETFs", {t: us[t] for t in ETF})):
        tr = run_trades(univ, r)
        for per, s, e in (("IS", START, IS_END), ("OOS", OOS_START, None)):
            d, tk = portfolio(univ, tr, K=10 if len(univ) > 10 else 5, start=s, end=e)
            rows.append({"strategy": name, "period": per, **stats(d, tk)})
    kr_bh = pd.DataFrame({t: d["close"].pct_change() for t, d in kr.items()}).loc[START:]
    for per in ("IS", "OOS"):
        rows.append(row("KR stocks EW buy&hold", kr_bh.mean(axis=1).fillna(0), per))
        rows.append(row("ETF EW buy&hold", pd.DataFrame({t: us[t]["close"].pct_change() for t in ETF}).loc[START:].mean(axis=1).fillna(0), per))
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "strategy2.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
