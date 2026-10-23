"""공통: 경로, 데이터 로딩, 기간 분할 상수."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

IS_END = pd.Timestamp("2014-12-31")   # 학습 구간 끝
OOS_START = pd.Timestamp("2015-01-01")  # 검증 구간 시작
MIN_START = pd.Timestamp("1993-01-01")  # 너무 오래된 데이터는 품질 문제로 제외
DATA_END = pd.Timestamp("2026-10-20")   # 종목별 종료일(10-20~22) 통일

COST = 0.0005  # 편도 비용(수수료+슬리피지)


def load_universe():
    p = ROOT / "data" / "universe.csv"
    return pd.read_csv(p) if p.exists() else None


def load_ticker(ticker):
    """수정주가 OHLC로 변환한 DataFrame(index=date) 반환. 품질 불량 행은 제거."""
    df = pd.read_csv(RAW / f"{ticker}.csv", parse_dates=["date"]).set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna(subset=["open", "high", "low", "close", "adj_close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    f = df["adj_close"] / df["close"]
    out = pd.DataFrame({
        "open": df["open"] * f,
        "high": df["high"] * f,
        "low": df["low"] * f,
        "close": df["adj_close"],
        "volume": df["volume"].fillna(0),
    })
    # OHLC 논리 보정: 시가가 고저 범위 밖이면(데이터 오류) 범위 안으로 자름
    out["high"] = out[["high", "open", "close"]].max(axis=1)
    out["low"] = out[["low", "open", "close"]].min(axis=1)
    out = out[(out.index >= MIN_START) & (out.index <= DATA_END)]
    return out


EXCLUDE = {"069500.KS"}  # 2007~2024 결측 578일, 5일+ 공백 22곳 (04_엔진검증.md)


def load_all(tickers=None):
    if tickers is None:
        tickers = sorted(p.stem for p in RAW.glob("*.csv") if p.stem not in EXCLUDE)
    data = {}
    for t in tickers:
        try:
            d = load_ticker(t)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {t}: {e}")
            continue
        if len(d) > 300:
            data[t] = d
    return data


def market_of(ticker):
    return "KR" if ticker.endswith((".KS", ".KQ")) else "US"
