# 시작 조건 실험: 매 사이클 시작을 'SOX가 52주 고점 대비 d0 이상 빠졌을 때'로 미루면? (나머지는 design.py 선택안 그대로)
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, importlib.util, sys, io
src = open('design.py', encoding='utf-8').read().split('# 1) 학습')[0]
exec(src)
best = (0.3, 1.0, 2.0, 5, 0.2)
def simw(df, d0, a, p, m, n, b, Bud=B):
    X, S, Vv = df.x.values, df.s.values, df.v.values
    hi = df.x.rolling(252, min_periods=1).max().values
    su, xu, inv = 1 / S[0], 0.0, 0.0; val = np.empty(len(X)); w = np.empty(len(X))
    on = False; k = 0; cyc = 0
    for i in range(len(X)):
        px = X[i]
        if on and px >= inv / xu * (1 + tgt):
            su += xu * px * (1 - 2 * C) / S[i]; xu = 0; inv = 0; on = False; cyc += 1
        if not on and px <= hi[i] * (1 - d0):
            V = su * S[i] + xu * px; sig = Vv[i]; lv = [min(a * sig * j ** p, .9) for j in range(1, n)]; tgt = b * sig
            amts = Bud * V * m ** np.arange(n) / (m ** np.arange(n)).sum(); p0 = px; k = 0; on = True
            amt = min(amts[0], su * S[i]); su -= amt / S[i]; xu += amt * (1 - 2 * C) / px; inv += amt; k = 1
        elif on and k < n and px <= p0 * (1 - lv[k - 1]):
            amt = min(amts[k], su * S[i]); su -= amt / S[i]; xu += amt * (1 - 2 * C) / px; inv += amt; k += 1
        val[i] = su * S[i] + xu * px; w[i] = xu * px / val[i]
    return pd.Series(val, index=df.index), w, cyc
full = frame('SOX', '1996-01-01', '2026-12-31')
rows = []
for d0 in (0, 0.10, 0.20, 0.30):
    for per, s0, s1 in [('1996~2010', '1996', '2010-12-31'), ('2011~2026', '2011', '2026-12-31'), ('전체', '1996', '2026-12-31')]:
        df = full[s0:s1]; v, w, c = simw(df, d0, *best); st = stats(v)
        rows.append(dict(시작조건=f'고점-{int(d0*100)}%', 기간=per, CAGR=st['CAGR'], Sharpe=st['Sharpe'], MDD=st['MDD'], 사이클=c, 평균비중=w.mean()))
    rl = []
    for d in pd.date_range(full.index[0], '2021-11-01', freq='MS'):
        df = full[(full.index >= d) & (full.index < d + pd.Timedelta(days=1826))]
        if len(df) < 1100: continue
        v, w, c = simw(df, d0, *best); rl.append((v.iloc[-1] - df.s.iloc[-1] / df.s.iloc[0]) * 4e8)
    rl = np.array(rl); rows.append(dict(시작조건=f'고점-{int(d0*100)}%', 기간='5년롤링(4억)', 이긴비율=(rl > 0).mean(), 평균=rl.mean(), 최악=rl.min()))
pd.set_option('display.width', 200)
print(pd.DataFrame(rows).to_string(float_format=lambda x: f'{x:,.3f}'))
