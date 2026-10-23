"""규칙 기반 매매 백테스터 (종목별 거래 생성 -> 포트폴리오 합성).

체결 규칙
- 진입: 신호일 t 종가 판정 -> t+1 시가 매수
- 청산: 청산조건이 d일 종가에 충족 -> d+1 시가 매도
        손절가가 있으면 장중 저가가 닿는 날 min(시가, 손절가)에 매도
        최대 보유일 도달 -> 다음날 시가 매도
- 비용: 편도 COST
포트폴리오: 최대 K개 슬롯, 슬롯당 자본 1/K (일별 재조정 근사), 미사용 현금 수익 0.
같은 날 후보가 슬롯보다 많으면 score 낮은 순으로 채택.
"""
import heapq
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from common import COST
from patterns import build_features, pattern_table


@dataclass
class Rule:
    name: str
    entry: Callable            # (df, f, pt) -> bool Series
    exit: Callable             # (df, f, pt) -> bool Series (종가 기준 청산 신호)
    max_hold: int = 20
    stop_atr: Optional[float] = None   # 진입가 - k*ATR 손절
    score: Optional[Callable] = None   # (df, f, pt) -> Series, 낮을수록 우선


def trades_for(ticker, df, rule, f=None, pt=None, overlap=False):
    if f is None:
        f = build_features(df)
    if pt is None:
        pt = pattern_table(df, f)
    ent = rule.entry(df, f, pt).fillna(False).values
    ext = rule.exit(df, f, pt).fillna(False).values
    sc = rule.score(df, f, pt).values if rule.score else np.zeros(len(df))
    o, l, c = df["open"].values, df["low"].values, df["close"].values
    a = f["atr14"].values
    idx = df.index
    n = len(df)
    out = []
    sig = np.flatnonzero(ent[: n - 1])
    nxt = 0  # 이 인덱스 이상의 신호만 유효(보유 중 신호 무시)
    for i in sig:
        if not overlap and i < nxt:
            continue
        e = i + 1
        epx = o[e]
        stop = epx - rule.stop_atr * a[i] if rule.stop_atr and not np.isnan(a[i]) else -np.inf
        d = e
        xpx, xi, why = None, None, None
        while d < n:
            if l[d] <= stop:
                xpx, xi, why = min(o[d], stop), d, "stop"
                break
            held = d - e + 1
            if (ext[d] or held >= rule.max_hold) and d + 1 < n:
                xpx, xi, why = o[d + 1], d + 1, "exit" if ext[d] else "time"
                break
            d += 1
        if xpx is None:  # 데이터 끝: 마지막 종가로 정리
            xpx, xi, why = c[n - 1], n - 1, "eod"
        # 장중 손절: 시가 시점엔 아직 보유 중이므로 그날 시가 진입에 슬롯을 내줄 수 없음
        intraday = why == "stop" and xpx != o[xi]
        out.append((ticker, idx[i], idx[e], idx[xi], epx, xpx, why, sc[i], e, xi, intraday))
        nxt = xi  # 청산 체결일(xi) 종가부터 신호 재판정 -> 보유 기간 중복 없음
    cols = ["ticker", "signal_date", "entry_date", "exit_date", "entry_px", "exit_px", "why", "score", "ei", "xi", "intraday"]
    t = pd.DataFrame(out, columns=cols)
    t["ret"] = t["exit_px"] / t["entry_px"] * (1 - COST) ** 2 - 1
    t["days"] = t["xi"] - t["ei"]
    return t


def run_trades(data, rule, cache=None, overlap=True):
    """overlap=True: 모든 신호의 후보 거래 생성(보유 중복 판정은 portfolio가 담당)."""
    res = []
    for tk, df in data.items():
        if cache is not None and tk in cache:
            f, pt = cache[tk]
        else:
            f = build_features(df)
            pt = pattern_table(df, f)
            if cache is not None:
                cache[tk] = (f, pt)
        res.append(trades_for(tk, df, rule, f, pt, overlap=overlap))
    t = pd.concat(res, ignore_index=True)
    return t


_CAL = {}


def portfolio(data, trades, K=10, start=None, end=None):
    """거래 목록을 슬롯 K개 포트폴리오로 합성 -> 일별 수익률, 채택 거래."""
    if trades.empty:
        return pd.Series(dtype=float), trades
    key = tuple(data)  # 같은 종목 구성이면 같은 달력
    if key not in _CAL:  # 합집합 달력 계산이 호출당 ~3초라 캐시
        _CAL[key] = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in data.values()])))
    cal = _CAL[key]
    if start is not None:
        cal = cal[cal >= start]
    if end is not None:
        cal = cal[cal <= end]
    tr = trades[(trades.entry_date >= cal[0]) & (trades.entry_date <= cal[-1])]
    tr = tr.sort_values(["entry_date", "score"])
    if "intraday" not in tr.columns:  # 외부에서 만든 거래 목록: 손절이면서 청산가 != 청산일 시가면 장중 청산
        tr = tr.assign(intraday=[w == "stop" and xp != data[t]["open"].values[x]
                                 for t, x, xp, w in zip(tr.ticker, tr.xi, tr.exit_px, tr.why)])
    port = pd.Series(0.0, index=cal)
    keep = np.zeros(len(tr), dtype=bool)
    open_pos = []    # heap of (청산일, 장중손절 여부, 종목)
    held = {}        # 종목 -> 보유 수(같은 종목 중복 보유 금지)
    eds = tr.entry_date.values
    xds = tr.exit_date.values
    intr = tr.intraday.values
    tks = tr.ticker.values
    for j in range(len(tr)):
        ed = eds[j]
        # 슬롯 해제: 청산일 < 진입일, 또는 같은 날 시가 청산(시가 매도 후 시가 매수). 장중 손절은 그날 시가에 해제 불가
        while open_pos and (open_pos[0][0] < ed or (open_pos[0][0] == ed and not open_pos[0][1])):
            _, _, t0 = heapq.heappop(open_pos)
            held[t0] -= 1
        if len(open_pos) < K and not held.get(tks[j]):
            heapq.heappush(open_pos, (xds[j], bool(intr[j]), tks[j]))
            held[tks[j]] = held.get(tks[j], 0) + 1
            keep[j] = True
    taken = tr[keep]
    if taken.empty:
        return port, taken
    acc = np.zeros(len(cal))
    for tk, g in taken.groupby("ticker"):
        df = data[tk]
        c = df["close"].values
        pos = cal.get_indexer(df.index)  # 종목 날짜 -> 달력 위치(-1: 범위 밖)
        for ei, xi, epx, xpx in zip(g.ei.values, g.xi.values, g.entry_px.values, g.exit_px.values):
            px = np.concatenate([[epx], c[ei:xi + 1]])
            px[-1] = xpx  # 마지막 날은 청산가(시가 or 손절가)
            daily = px[1:] / px[:-1] - 1
            daily[0] -= COST
            daily[-1] -= COST
            p = pos[ei:xi + 1]
            m = p >= 0
            np.add.at(acc, p[m], daily[m] / K)
    port = pd.Series(acc, index=cal)
    return port, taken


def stats(daily, trades=None):
    daily = daily.dropna()
    if daily.empty:
        return {}
    eq = (1 + daily).cumprod()
    yrs = (daily.index[-1] - daily.index[0]).days / 365.25  # 합집합 달력(연 ~259일) 대응
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    ppy = len(daily) / yrs if yrs > 0 else 252  # 연간 관측일 수
    sh = daily.mean() / daily.std() * np.sqrt(ppy) if daily.std() > 0 else np.nan
    out = {"CAGR": cagr, "MDD": mdd, "Sharpe": sh, "exposure": (daily != 0).mean()}
    if trades is not None and len(trades):
        w = trades.ret[trades.ret > 0]
        lo = trades.ret[trades.ret <= 0]
        out.update({
            "trades": len(trades), "win": (trades.ret > 0).mean(), "avg_ret": trades.ret.mean(),
            "payoff": w.mean() / -lo.mean() if len(lo) and lo.mean() < 0 else np.nan,
            "avg_days": trades.days.mean(),
        })
    return out
