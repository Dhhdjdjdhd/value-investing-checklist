import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
best = (0.3, 1.0, 2.0, 5, 0.2)
for t in ('INTC', 'CSCO', 'GE', 'C', 'AIG'):
    A[t] = get(t); full = frame(t, '1996-01-01', '2026-12-31'); rl = []
    v, w, c, dp, k = sim(full, *best); st = stats(v); sp = stats(full.s / full.s.iloc[0])
    for d in pd.date_range(full.index[0], '2021-11-01', freq='MS'):
        df = full[(full.index >= d) & (full.index < d + pd.Timedelta(days=1826))]
        if len(df) < 1100: continue
        vv, *_ = sim(df, *best); rl.append((vv.iloc[-1] - df.s.iloc[-1] / df.s.iloc[0]) * 4e8)
    rl = np.array(rl)
    print(f'{t}: 전체 CAGR {st["CAGR"]*100:.2f}% vs S&P {sp["CAGR"]*100:.2f}% | 5년롤링 이김 {(rl>0).mean()*100:.0f}% 평균 {rl.mean()/1e4:+,.0f}만 최악 {rl.min()/1e4:+,.0f}만 | 현재단계 {k}')
