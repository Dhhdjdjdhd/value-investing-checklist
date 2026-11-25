import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
AM = np.array([161, 323, 645, 1290, 2581.])
df = frame('SOX', '1996-01-01', '2026-12-31'); X = df.x.values; D = df.index; i = 0; cyc = []
while i < len(X):
    sig = df.v.values[i]; lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[i]
    u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0
    for j in range(i + 1, len(X)):
        px = X[j]
        while k < 5 and px <= p0 * (1 - lv[k - 1]): u += AM[k] / px; inv += AM[k]; k += 1
        worst = min(worst, u * px - inv)
        if px >= inv / u * (1 + tgt):
            cyc.append(((D[j] - D[i]).days, D[i].date(), D[j].date(), k, round(worst), round(u * px * .998 - inv))); i = j; break
    else:
        cyc.append(((D[-1] - D[i]).days, D[i].date(), '진행중', k, round(worst), round(u * X[-1] - inv))); break
for c in sorted(cyc, reverse=True)[:8]: print(c)
d = np.array([c[0] for c in cyc]); print('n', len(d), 'median', np.median(d), 'p90', np.percentile(d, 90), '>365', (d > 365).sum())
