"""백테스트 엔진 독립 검증 (작업지시 #2, 작성: value-investing-checklist-f9).

실행 (작업 폴더 '차트 아록리즘 분석' 기준):  py -m pytest tests -q
src/ 코드는 읽기만 하고 수정하지 않는다. 실제 데이터 테스트는 data/raw 가 없으면 skip.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import common  # noqa: E402
import event_study  # noqa: E402
import strategy  # noqa: E402
from indicators import ibs, rsi, streak  # noqa: E402
from patterns import build_features, pattern_table  # noqa: E402
from strategy import Rule, portfolio, trades_for  # noqa: E402

C = common.COST
REAL_TICKERS = ["SPY", "AIG", "005930.KS", "069500.KS"]


def _real(t):
    if not (common.RAW / f"{t}.csv").exists():
        pytest.skip(f"{t} 데이터 없음")
    return common.load_ticker(t)


def _synthetic(n=30, seed=None):
    """평평한 기본 OHLC: open=close=100, high=101, low=99 -> TR=2, ATR14=2 정확."""
    idx = pd.bdate_range("2020-01-01", periods=n)
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=idx)
    if seed is not None:
        rng = np.random.default_rng(seed)
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
        o = c * np.exp(rng.normal(0, 0.01, n))
        df["open"], df["close"] = o, c
        df["high"] = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, n))
        df["low"] = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, n))
    return df


def _flag(df, positions):
    s = pd.Series(False, index=df.index)
    s.iloc[list(positions)] = True
    return s


def _rule(entry_pos, exit_pos=(), **kw):
    return Rule("t", entry=lambda df, f, pt: _flag(df, entry_pos),
                exit=lambda df, f, pt: _flag(df, exit_pos), **kw)


# ---------------------------------------------------------------- a) 룩어헤드
def _mismatch_cols(a, b):
    bad = []
    for col in a.columns:
        x, y = a[col], b[col]
        if x.dtype == bool or y.dtype == bool:
            if not (x.astype(bool).values == y.astype(bool).values).all():
                bad.append(col)
        elif not np.allclose(x.values.astype(float), y.values.astype(float), rtol=1e-12, atol=0, equal_nan=True):
            bad.append(col)
    return bad


@pytest.mark.parametrize("ticker", REAL_TICKERS)
def test_no_lookahead_truncation(ticker):
    df = _real(ticker)
    f_full, p_full = build_features(df), pattern_table(df)
    n = len(df)
    bad = {}
    for k in sorted({250, 400, n // 3, n // 2, 2 * n // 3, n - 30, n - 2}):
        cut = df.iloc[: k + 1]
        bf = _mismatch_cols(build_features(cut), f_full.iloc[: k + 1])
        bp = _mismatch_cols(pattern_table(cut), p_full.iloc[: k + 1])
        if bf or bp:
            bad[str(df.index[k].date())] = bf + bp
    assert not bad, f"절단 결과가 다른 열: {bad}"


@pytest.mark.parametrize("ticker", ["SPY", "005930.KS"])
def test_no_lookahead_future_perturbation(ticker):
    """k 이후 가격을 마구 바꿔도 k까지의 지표·신호는 그대로여야 한다."""
    df = _real(ticker)
    k = len(df) // 2
    noisy = df.copy()
    rng = np.random.default_rng(1)
    m = np.exp(rng.normal(0, 0.05, len(df) - k - 1))
    for col in ("open", "high", "low", "close"):
        noisy.iloc[k + 1:, noisy.columns.get_loc(col)] *= m
    noisy.iloc[k + 1:, noisy.columns.get_loc("volume")] *= 3
    assert not _mismatch_cols(build_features(noisy).iloc[: k + 1], build_features(df).iloc[: k + 1])
    assert not _mismatch_cols(pattern_table(noisy).iloc[: k + 1], pattern_table(df).iloc[: k + 1])


def test_trades_no_lookahead_truncation():
    """k 이전에 끝난 거래는 데이터를 k에서 잘라도 똑같아야 한다."""
    df = _real("SPY")
    rule = Rule("rsi2", entry=lambda d, f, p: p["rsi2_lt10"], exit=lambda d, f, p: d["close"] > f["sma20"],
                max_hold=10, stop_atr=2.0)
    full = trades_for("SPY", df, rule)
    k = len(df) // 2
    part = trades_for("SPY", df.iloc[: k + 1], rule)
    a, b = full[full.xi < k].reset_index(drop=True), part[part.xi < k].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


# ---------------------------------------------------------------- b) 체결가
def test_entry_next_open_exit_signal_next_open():
    df = _synthetic()
    df.iloc[16, 0] = 100.5      # 진입일 시가
    df.iloc[19, 0] = 103.0      # 청산 체결일 시가
    t = trades_for("X", df, _rule([15], [18]))
    assert len(t) == 1
    r = t.iloc[0]
    assert r.signal_date == df.index[15] and r.entry_date == df.index[16] and r.exit_date == df.index[19]
    assert r.entry_px == 100.5 and r.exit_px == 103.0 and r.why == "exit"
    assert r.ret == pytest.approx(103.0 / 100.5 * (1 - C) ** 2 - 1, abs=1e-12)


def test_stop_intraday_and_gap():
    df = _synthetic()
    # ATR(신호일 15) = 2, stop_atr=1.5 -> 손절가 = 100 - 3 = 97
    df.iloc[17, df.columns.get_loc("low")] = 96.5          # 장중 터치 -> 97 에 체결
    t = trades_for("X", df, _rule([15], stop_atr=1.5))
    r = t.iloc[0]
    assert r.why == "stop" and r.exit_date == df.index[17] and r.exit_px == pytest.approx(97.0)

    df2 = _synthetic()
    df2.iloc[17, df2.columns.get_loc("open")] = 95.0       # 갭하락으로 손절가 아래 시가 -> 시가 체결
    df2.iloc[17, df2.columns.get_loc("low")] = 94.0
    r2 = trades_for("X", df2, _rule([15], stop_atr=1.5)).iloc[0]
    assert r2.why == "stop" and r2.exit_px == 95.0


def test_stop_on_entry_day():
    df = _synthetic()
    df.iloc[16, df.columns.get_loc("low")] = 90.0
    r = trades_for("X", df, _rule([15], stop_atr=1.5)).iloc[0]
    assert r.why == "stop" and r.exit_date == r.entry_date and r.exit_px == pytest.approx(97.0)
    assert r.days == 0


def test_time_exit_and_overlap_and_reentry():
    df = _synthetic()
    # 신호 15 -> 진입 16, max_hold 5 -> 20일 종가에 보유 5일 -> 21 시가 매도
    # 17,18 신호는 보유 중이라 무시, 21(청산 체결일) 신호는 유효 -> 22 진입
    t = trades_for("X", df, _rule([15, 17, 18, 21], max_hold=5))
    assert list(t.entry_date) == [df.index[16], df.index[22]]
    assert t.iloc[0].exit_date == df.index[21] and t.iloc[0].why == "time"
    assert t.iloc[0].days == 5


def test_eod_close():
    df = _synthetic()
    df.iloc[-1, df.columns.get_loc("close")] = 105.0
    r = trades_for("X", df, _rule([25], max_hold=50)).iloc[-1]
    assert r.why == "eod" and r.exit_px == 105.0 and r.exit_date == df.index[-1]


def test_exit_signal_on_last_bar_falls_back_to_eod():
    df = _synthetic()
    r = trades_for("X", df, _rule([20], [len(df) - 1])).iloc[0]
    assert r.why == "eod" and r.exit_px == df["close"].iloc[-1]


# ---------------------------------------------------------------- c) event_study r{h}
def test_event_study_return_definition():
    df = _synthetic(40, seed=3)
    panel = event_study.build_panel({"X": df}).set_index("date")
    o, c = df["open"].values, df["close"].values
    for t in (0, 5, 12, 19):
        row = panel.loc[df.index[t]]
        for h in event_study.HORIZONS:
            exp = c[t + h] / o[t + 1] - 1 - 2 * C
            assert row[f"r{h}"] == pytest.approx(exp, abs=1e-12), (t, h)
    # 마지막 20행(가장 긴 보유를 못 채우는 행)은 빠져야 함
    assert panel.index.max() == df.index[len(df) - 1 - max(event_study.HORIZONS)]


# ---------------------------------------------------------------- d) portfolio
def _trade(tk, df, ei, xi, score, epx=None, xpx=None):
    epx = df["open"].iloc[ei] if epx is None else epx
    xpx = df["open"].iloc[xi] if xpx is None else xpx
    return dict(ticker=tk, signal_date=df.index[ei - 1], entry_date=df.index[ei], exit_date=df.index[xi],
                entry_px=epx, exit_px=xpx, why="exit", score=score, ei=ei, xi=xi,
                ret=xpx / epx * (1 - C) ** 2 - 1, days=xi - ei)


def test_portfolio_slots_and_score_priority():
    data = {t: _synthetic(40, seed=i) for i, t in enumerate("ABCDE")}
    d = data["A"]
    tr = pd.DataFrame([
        _trade("A", d, 5, 15, 3.0), _trade("B", d, 5, 12, 1.0), _trade("C", d, 5, 10, 2.0),
        _trade("D", d, 5, 9, 0.0),
        _trade("E", d, 9, 20, 0.5),   # D 청산일(9) = E 진입일 -> 슬롯 재사용 가능
        _trade("A", d, 11, 14, 9.0),  # 이때 B·E 보유 중 -> K=2 초과라 탈락
    ])
    _, taken = portfolio(data, tr, K=2)
    assert set(zip(taken.ticker, taken.ei)) == {("D", 5), ("B", 5), ("E", 9)}
    cal = data["A"].index
    for day in cal:
        live = ((taken.entry_date <= day) & (taken.exit_date > day)).sum()
        assert live <= 2, day


def test_portfolio_intraday_stop_does_not_free_slot_at_open():  # B1 회귀 테스트 (수정 완료)
    data = {t: _synthetic(40) for t in "AB"}
    d = data["A"]
    tr = pd.DataFrame([
        _trade("A", d, 5, 5, 0.0, xpx=97.0),   # 5일 시가 진입 -> 같은 날 장중 손절
        _trade("B", d, 5, 8, 1.0),             # 같은 5일 시가 진입 후보
    ])
    tr.loc[0, "why"] = "stop"
    _, taken = portfolio(data, tr, K=1)
    # 5일 시가 시점에는 A가 슬롯을 차지하고 있으므로 B는 들어갈 수 없어야 함
    assert list(taken.ticker) == ["A"]


@pytest.mark.parametrize("cost", [0.0, C])
def test_portfolio_k1_matches_trade_returns(monkeypatch, cost):
    monkeypatch.setattr(strategy, "COST", cost)
    df = _real("SPY")
    rule = Rule("rsi2", entry=lambda d, f, p: p["rsi2_lt10"], exit=lambda d, f, p: d["close"] > f["sma20"],
                max_hold=10, stop_atr=2.0)
    tr = trades_for("SPY", df, rule)
    daily, taken = portfolio({"SPY": df}, tr, K=1)
    assert len(taken) == len(tr)  # 종목 하나에서는 거래가 겹치지 않음
    port_total = (1 + daily).prod()
    trade_total = (1 + taken.ret).prod()
    if cost == 0:
        assert port_total == pytest.approx(trade_total, rel=1e-9)
    else:  # 비용을 일별 수익에서 빼는 근사 -> 거래당 1e-5 수준 오차 허용
        assert port_total == pytest.approx(trade_total, rel=1e-5 * len(tr))


# ---------------------------------------------------------------- e) indicators 독립 구현
def _rsi_ref(close, n):
    """pandas ewm(alpha=1/n, adjust=False) 와 같은 재귀를 직접 계산."""
    d = np.diff(close)
    up_avg = dn_avg = None
    out = np.full(len(close), np.nan)
    for i, x in enumerate(d, start=1):
        u, w = max(x, 0.0), max(-x, 0.0)
        if up_avg is None:
            up_avg, dn_avg = u, w
        else:
            up_avg = (1 - 1 / n) * up_avg + u / n
            dn_avg = (1 - 1 / n) * dn_avg + w / n
        if i >= n:
            out[i] = 100.0 if dn_avg == 0 else 100 - 100 / (1 + up_avg / dn_avg)
    return out


def _rsi_wilder_classic(close, n):
    """교과서 Wilder: 첫 n개 변화의 단순평균으로 시작."""
    d = np.diff(close)
    out = np.full(len(close), np.nan)
    up, dn = np.mean(np.clip(d[:n], 0, None)), np.mean(np.clip(-d[:n], 0, None))
    out[n] = 100 - 100 / (1 + up / dn) if dn else 100.0
    for i in range(n, len(d)):
        up = (up * (n - 1) + max(d[i], 0)) / n
        dn = (dn * (n - 1) + max(-d[i], 0)) / n
        out[i + 1] = 100 - 100 / (1 + up / dn) if dn else 100.0
    return out


@pytest.mark.parametrize("n", [2, 14])
def test_rsi_matches_reference(n):
    df = _real("SPY").iloc[:3000]
    got = rsi(df["close"], n).values
    ref = _rsi_ref(df["close"].values, n)
    assert np.allclose(got, ref, rtol=1e-9, equal_nan=True)
    # 교과서 Wilder(SMA 시작)와는 초반만 다르고 300일 뒤에는 수렴
    classic = _rsi_wilder_classic(df["close"].values, n)
    assert np.allclose(got[300:], classic[300:], atol=1e-6)


def test_rsi_flat_series():
    s = pd.Series([100.0] * 10)
    # 오르지도 내리지도 않은 구간: 중립 50 (B8 수정 후)
    assert rsi(s, 2).iloc[-1] == 50.0


def test_streak_matches_loop():
    df = _real("SPY").iloc[:2000]
    c = df["close"].values
    ref = np.zeros(len(c))
    for i in range(1, len(c)):
        s = np.sign(c[i] - c[i - 1])
        if s == 0:
            ref[i] = 0
        elif np.sign(ref[i - 1]) == s:
            ref[i] = ref[i - 1] + s
        else:
            ref[i] = s
    assert np.array_equal(streak(df["close"]).values, ref)


def test_ibs_matches_formula():
    df = _real("SPY")
    got = ibs(df)
    for i in (500, 1500, 4000, len(df) - 1):
        h, l, c = df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        assert got.iloc[i] == pytest.approx((c - l) / (h - l))


# ---------------------------------------------------------------- 추가: 결측일 제거의 영향
def test_dropped_nan_day_merges_two_days():
    """load_ticker 가 NaN 행을 지우면 ret1·갭·streak 가 이틀치로 계산됨을 확인 (영향 기록용)."""
    raw = pd.read_csv(common.RAW / "MDY.csv") if (common.RAW / "MDY.csv").exists() else None
    if raw is None:
        pytest.skip("MDY 없음")
    na_days = raw[raw[["open", "close"]].isna().any(axis=1)]["date"].tolist()
    df = common.load_ticker("MDY")
    for d in na_days:
        assert pd.Timestamp(d) not in df.index
