"""메모리 절감판 패널: 한 번이라도 유니버스에 든 종목만, float32. 산출: data/S_panel_slim.pkl"""
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def slim(P, tickers=None):
    if tickers is None:
        tickers = P["universe"].columns[P["universe"].any(axis=0)]
    out = {}
    for k, v in P.items():
        if k == "sector":
            out[k] = v.reindex(tickers)
        elif k == "universe":
            out[k] = v.reindex(columns=tickers, fill_value=False)
        else:
            out[k] = v.reindex(columns=tickers).astype(np.float32)
    return out


if __name__ == "__main__":
    with open(ROOT / "data" / "S_panel.pkl", "rb") as fh:
        P = pickle.load(fh)
    n0 = P["close"].shape[1]
    S = slim(P)
    del P
    with open(ROOT / "data" / "S_panel_slim.pkl", "wb") as fh:
        pickle.dump(S, fh, protocol=4)
    print("tickers", n0, "->", S["close"].shape[1], "days", S["close"].shape[0])
