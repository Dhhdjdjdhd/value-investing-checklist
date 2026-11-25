"""패널 구축: data/S_panel.pkl (부록_W1 §1)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CHK = ROOT.parent / "체크리스트 검증"
sys.path.insert(0, str(CHK / "src"))
from prices import PR, WIN_RESERVED, load_companies, load_splits  # noqa: E402

START = "1999-01-04"
N_UNIV = 500
EXCLUDE_TK = {"BXSL", "MSDL"}

FF12 = {
    "NoDur": [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)],
    "Durbl": [(2500, 2519), (2590, 2599), (3630, 3659), (3710, 3711), (3714, 3714), (3716, 3716),
              (3750, 3751), (3792, 3792), (3900, 3939), (3990, 3999)],
    "Manuf": [(2520, 2589), (2600, 2699), (2750, 2769), (3000, 3099), (3200, 3569), (3580, 3629),
              (3700, 3709), (3712, 3713), (3715, 3715), (3717, 3749), (3752, 3791), (3793, 3799),
              (3830, 3839), (3860, 3899)],
    "Enrgy": [(1200, 1399), (2900, 2999)],
    "Chems": [(2800, 2829), (2840, 2899)],
    "BusEq": [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)],
    "Telcm": [(4800, 4899)],
    "Utils": [(4900, 4949)],
    "Shops": [(5000, 5999), (7200, 7299), (7600, 7699)],
    "Hlth": [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)],
    "Money": [(6000, 6999)],
}


def ff12(sic):
    if pd.isna(sic):
        return "Other"
    s = int(sic)
    for k, rs in FF12.items():
        for a, b in rs:
            if a <= s <= b:
                return k
    return "Other"


def build(end=None, verbose=True):
    t0 = time.time()
    comp = load_companies()
    comp = comp[(comp.ticker != "") & (comp.sic != 6221) & (~comp.ticker.isin(EXCLUDE_TK))]
    comp = comp.drop_duplicates("ticker")
    sic = dict(zip(comp.ticker, comp.sic))
    splits = load_splits()
    sp_by = {k: v for k, v in splits.groupby("ticker")}

    cols = {c: {} for c in ["open", "high", "low", "close", "adj_close", "volume", "raw_close"]}
    for i, tk in enumerate(comp.ticker):
        if tk.upper() in WIN_RESERVED:
            continue
        p = PR / f"{tk}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, usecols=["date", "open", "high", "low", "close", "adj_close", "volume"],
                         parse_dates=["date"])
        df = df[df.date >= START]
        if end is not None:
            df = df[df.date <= end]
        df = df.set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["close", "adj_close"])
        df = df[(df.close > 0) & (df.adj_close > 0)]
        if len(df) < 2:
            continue
        f = pd.Series(1.0, index=df.index)
        if tk in sp_by:
            for d, r in zip(sp_by[tk].date, sp_by[tk].ratio):
                f[df.index < d] *= r
        df["raw_close"] = df["close"] * f
        for c in cols:
            cols[c][tk] = df[c]
        if verbose and i % 400 == 0:
            print(i, tk, round(time.time() - t0), flush=True)

    P = {c: pd.DataFrame(v) for c, v in cols.items()}
    cnt = P["close"].notna().sum(axis=1)
    days = cnt.index[cnt >= 300]
    for c in P:
        P[c] = P[c].loc[days].sort_index(axis=1)
    close, adj, opn, vol = P["close"], P["adj_close"], P["open"], P["volume"]
    bad_o = ~(opn > 0)
    for c in ["open", "high", "low"]:
        P[c] = P[c].where(~bad_o)
    opn = P["open"]

    P["ret_cc"] = adj / adj.shift(1) - 1
    P["ret_oc"] = close / opn - 1
    P["ret_co"] = opn / close.shift(1) - 1
    dv = close * vol
    P["adv60"] = dv.rolling(60, min_periods=40).median()

    hist = close.notna().cumsum()
    elig = (hist >= 252) & (P["raw_close"].shift(1) >= 5) & close.notna() & (vol > 0) & P["adv60"].notna()
    rk = P["adv60"].where(elig).rank(axis=1, ascending=False, method="first")
    P["universe"] = rk <= N_UNIV
    P["sector"] = pd.Series({tk: ff12(sic.get(tk)) for tk in close.columns})
    for c in ["open", "high", "low", "volume", "adv60", "raw_close"]:
        P[c] = P[c].astype("float32")
    if verbose:
        print("days", len(days), days[0], days[-1], "tickers", close.shape[1], "sec", round(time.time() - t0))
        print("universe count: min/median/max", P["universe"].sum(axis=1).loc["2000-06":].describe()[["min", "50%", "max"]].to_dict())
        print(P["sector"].value_counts().to_dict())
    return P


if __name__ == "__main__":
    P = build()
    out = ROOT / "data" / "S_panel.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump(P, fh, protocol=4)
    print("saved", out, out.stat().st_size // 2**20, "MB")
