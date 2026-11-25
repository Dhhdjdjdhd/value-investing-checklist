import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
AM = np.array([161, 323, 645, 1290, 2581.])
for nm in ('SOX', 'NDX', 'XLK', 'KOSPI', '삼성전자'):
    df = frame(nm, '1996-01-01', '2026-12-31'); X = df.x.values; D = df.index; i = 0; cyc = []
    while i < len(X):
        sig = df.v.values[i]; lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[i]
        u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0; wp = 0; d5 = None; done = False
        for j in range(i + 1, len(X)):
            px = X[j]
            while k < 5 and px <= p0 * (1 - lv[k - 1]):
                u += AM[k] / px; inv += AM[k]; k += 1
                if k == 5: d5 = D[j]
            worst = min(worst, u * px - inv); wp = min(wp, (u * px - inv) / inv)
            if px >= inv / u * (1 + tgt):
                cyc.append((D[i].date(), d5.date() if d5 else None, D[j].date(), k, round(worst), wp, round(u * px * .998 - inv), (D[j] - d5).days if d5 else None)); i = j; done = True; break
        if not done:
            cyc.append((D[i].date(), d5.date() if d5 else None, '진행중', k, round(worst), wp, round(u * X[-1] - inv), (D[-1] - d5).days if d5 else None)); break
    f = [c for c in cyc if c[3] == 5]
    print(f'== {nm} 전체 사이클 {len(cyc)}, 5단계 도달 {len(f)}')
    for c in f: print(f'  시작 {c[0]} 5단계 {c[1]} 청산 {c[2]} | 5단계→청산 {c[7]}일 | 최대평가손 {c[4]:,}만 ({c[5]*100:.1f}%) | 손익 {c[6]:+,}만')
