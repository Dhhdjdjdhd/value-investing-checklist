import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
best = (0.3, 1.0, 2.0, 5, 0.2)
full = frame('SOX', '1996-01-01', '2026-12-31')
# 사다리 평가손(포트폴리오 대비)을 재현: sim 내부 상태가 없으니 '전략-고정없음' 차이로 근사 대신 직접 계산
X, S, Vv = full.x.values, full.s.values, full.v.values
a, p, m, n, b = best
su, xu, inv = 1 / S[0], 0., 0.; worst = (0, None); k = 0
def start(i):
    global lv, amts, tgt, p0, k, su, xu, inv
    V = su * S[i] + xu * X[i]; sig = Vv[i]; lv = [min(a * sig * j, .9) for j in range(1, n)]; tgt = b * sig
    amts = B * V * m ** np.arange(n) / (m ** np.arange(n)).sum(); p0 = X[i]; k = 0; buy(i)
def buy(i):
    global k, su, xu, inv
    amt = min(amts[k], su * S[i]); su -= amt / S[i]; xu += amt * (1 - 2 * C) / X[i]; inv += amt; k += 1
start(0)
for i in range(1, len(X)):
    px = X[i]
    if px >= inv / xu * (1 + tgt):
        su += xu * px * (1 - 2 * C) / S[i]; xu = 0; inv = 0; start(i)
    elif k < n and px <= p0 * (1 - lv[k - 1]): buy(i)
    V = su * S[i] + xu * px; pl = (xu * px - inv) / V
    if pl < worst[0]: worst = (pl, full.index[i].date(), k, inv / V)
print('사다리 최악 평가손(포트폴리오 대비)', worst)
for nm, s0, s1 in [('전체', '1996', '2026-12-31'), ('2011~', '2011', '2026-12-31'), ('2020코로나', '2019-06', '2021-06'), ('2022', '2021-06', '2024-06'), ('2026', '2025-06', '2026-12-31'), ('닷컴', '1999-06', '2003-06'), ('2008', '2007-06', '2009-12')]:
    df = full[s0:s1]; v, *_ = sim(df, *best); sp = df.s / df.s.iloc[0]
    print(nm, '전략 MDD %.1f%%' % ((v / v.cummax() - 1).min() * 100), 'S&P만 %.1f%%' % ((sp / sp.cummax() - 1).min() * 100))
