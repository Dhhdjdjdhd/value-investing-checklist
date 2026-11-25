"""C4: LightGBM 결합 점수 (부록_W2 'C4 추가'). 산출: data/S_c4_score.pkl"""
import pickle
import sys
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as E  # noqa: E402

t0 = time.time()
P = E.load_panel()
ctx = E.Ctx(P)
with open(E.ROOT / "data" / "S_z.pkl", "rb") as fh:
    Z = pickle.load(fh)
T, N = ctx.r.shape
U = ctx.U

# 목표: t+2 섹터 중립 수익의 횡단면 순위 → [-0.5, 0.5]
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    y2 = E.sector_demean(np.where(U, np.roll(ctx.r, -2, axis=0), np.nan), ctx)
y2[-2:] = np.nan
yr = pd.DataFrame(y2).rank(axis=1, pct=True).values - 0.5

# 시장 상태
mkt = E.market_ret(ctx)
m20 = mkt.rolling(20).sum().values
v20 = mkt.rolling(20).std().values
adj = P["adj_close"]
r5 = (adj / adj.shift(5) - 1).values
sec_id = np.zeros(N, dtype=np.int32)
sec5 = np.full((T, N), np.nan, dtype=np.float32)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for j, idx in enumerate(ctx.sec_idx):
        sec_id[idx] = j
        sec5[:, idx] = np.nanmean(np.where(U[:, idx], r5[:, idx], np.nan), axis=1, keepdims=True)

FEATS = E.SIGNALS + ["sector", "mkt20", "vol20", "sec5"]
ti, ni = np.where(U)                     # 유니버스 관측 (행 우선 → 날짜순)
X = np.empty((len(ti), len(FEATS)), dtype=np.float32)
for j, k in enumerate(E.SIGNALS):
    X[:, j] = Z[k][ti, ni]
X[:, 12] = sec_id[ni]
X[:, 13] = m20[ti]
X[:, 14] = v20[ti]
X[:, 15] = sec5[ti, ni]
y = yr[ti, ni]
print("rows", len(ti), round(time.time() - t0), flush=True)

PARAMS = dict(num_leaves=15, max_depth=4, learning_rate=0.03, n_estimators=300, min_child_samples=2000,
              colsample_bytree=0.8, subsample=0.5, subsample_freq=1, reg_lambda=10, random_state=0,
              deterministic=True, n_jobs=4, verbose=-1, force_col_wise=True)
score = np.zeros((T, N))
imp = {}
for Y in range(2003, int(ctx.dates.year.max()) + 1):
    first = np.searchsorted(ctx.dates.values, np.datetime64(f"{Y}-01-01"))
    tr = (ti <= first - 3) & ~np.isnan(y)
    te = np.isin(ti, np.where(ctx.dates.year == Y)[0])
    t1 = time.time()
    mdl = lgb.LGBMRegressor(**PARAMS)
    mdl.fit(pd.DataFrame(X[tr], columns=FEATS), y[tr], categorical_feature=["sector"])
    score[ti[te], ni[te]] = mdl.predict(pd.DataFrame(X[te], columns=FEATS))
    imp[Y] = mdl.booster_.feature_importance(importance_type="gain")
    print(Y, "train rows", int(tr.sum()), "fit sec", round(time.time() - t1), flush=True)

with open(E.ROOT / "data" / "S_c4_score.pkl", "wb") as fh:
    pickle.dump({"score": score.astype("float32"),
                 "importance": pd.DataFrame(imp, index=FEATS)}, fh, protocol=4)
print("done", round(time.time() - t0))
