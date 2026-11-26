# 규칙4(시총 상위 5 분산) 사다리 한도만 바꿔 보기 — 미국 (2026-11-26). 나머지는 pick_us.py와 같음
import sys; sys.argv = ['x']
import numpy as np, pandas as pd
import pick_us as U, pick_kr as K
sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
PK = {t: v for t in pd.date_range('2011-01-01', '2026-11-01', freq='MS') if (v := U.picks(t))}
spy, irx = K.yget('SPY'), K.yget('^IRX')
X = U.adj.copy(); X = X[X.index >= '2005-01-01']; S = spy.reindex(X.index).ffill().dropna(); X = X.loc[S.index]
for c in X:
    s = X[c].dropna()
    if len(s): X[c] = X[c].ffill().where((X.index >= s.index[0]) & (X.index <= s.index[-1]))
V = np.log(X).diff().rolling(252, min_periods=200).std() * np.sqrt(252)
pf = lambda d: PK.get(pd.Timestamp(d.year, d.month, 1), {}).get('규칙4_시총상위5', [])
s0, s1 = pd.Timestamp('2011-01-03'), X.index[-1]
rows = []
for bud in (0.125, 0.25, 0.5, 1.0):
    K.BUD = bud
    v, w, lg = K.sim(S, X, V, pf, 5, s0, s1)
    sp = S.loc[v.index] / S.loc[v.index[0]]; fx = K.fixed(S, X, pf, 5, w.mean(), v.index)
    st, sps, fxs = K.stats(v, irx), K.stats(sp, irx), K.stats(fx, irx)
    r5, r3 = [], []
    for yrs, acc in ((5, r5), (3, r3)):
        for d in pd.date_range(s0, s1 - pd.DateOffset(years=yrs), freq='QS'):
            vv, _, _ = K.sim(S, X, V, pf, 5, d, d + pd.DateOffset(years=yrs))
            acc.append((vv.iloc[-1] - S.loc[vv.index[-1]] / S.loc[vv.index[0]]) * 4e4)
    r5, r3 = np.array(r5), np.array(r3)
    rows.append({'한도': f'{bud:.1%}', '4억일때_칸당(만)': bud * 4e4 / 5, 'CAGR': st['CAGR'], 'S&P CAGR': sps['CAGR'], '차이%p': (st['CAGR'] - sps['CAGR']) * 100,
                 '고정보유CAGR': fxs['CAGR'], 'Sharpe': st['Sharpe'], 'S&P Sharpe': sps['Sharpe'], 'MDD': st['MDD'], 'S&P MDD': sps['MDD'],
                 '평균비중': w.mean(), '최대비중': w.max(), '5년 이김': (r5 > 0).mean(), '5년 평균(만)': r5.mean(), '5년 최악(만)': r5.min(),
                 '3년 이김': (r3 > 0).mean(), '3년 최악(만)': r3.min()})
    print('완료', bud, flush=True)
R = pd.DataFrame(rows); R.to_csv(U.OUT / 'budget_us.csv', index=False, encoding='utf-8-sig')
print(R.T.to_string())
