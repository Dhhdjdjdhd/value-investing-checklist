import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
full = frame('SOX', '1996-01-01', '2026-12-31')
AM = np.array([161, 323, 645, 1290, 2581.])
df = full['2025-01-01':]; X = df.x.values; D = df.index; i = 0; n = 0; tot = 0
print('번호|시작일|시작가|청산일|보유일|단계|투입(만)|평단|청산가|최악평가손|손익(만)')
while i < len(X):
    sig = df.v.values[i]; lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[i]
    u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0; wp = 0; n += 1
    for j in range(i + 1, len(X)):
        px = X[j]
        while k < 5 and px <= p0 * (1 - lv[k - 1]): u += AM[k] / px; inv += AM[k]; k += 1
        worst = min(worst, u * px - inv); wp = min(wp, (u * px - inv) / inv)
        if px >= inv / u * (1 + tgt):
            g = u * px * 0.998 - inv; tot += g
            print(f'{n}|{D[i].date()}|{p0:,.0f}|{D[j].date()}|{(D[j]-D[i]).days}|{k}|{inv:,.0f}|{inv/u:,.0f}|{inv/u*(1+tgt):,.0f}|{worst:,.0f}|{wp*100:.1f}%|{g:+,.0f}'); i = j; break
    else:
        print(f'{n}|{D[i].date()}|{p0:,.0f}|진행중|{(D[-1]-D[i]).days}|{k}|{inv:,.0f}|{inv/u:,.0f}|{inv/u*(1+tgt):,.0f}|{worst:,.0f}|{wp*100:.1f}%|평가 {u*X[-1]-inv:+,.0f}')
        break
print('완료합계', round(tot), '마지막', D[-1].date(), X[-1])
