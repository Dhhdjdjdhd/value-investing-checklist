import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
full = frame('SOX', '1996-01-01', '2026-12-31')
AM = np.array([161, 323, 645, 1290, 2581.])
def one(start):
    df = full[start:]; X = df.x.values; sig = df.v.values[0]
    lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[0]
    u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0; wd = None
    for i in range(1, len(X)):
        px = X[i]
        while k < 5 and px <= p0 * (1 - lv[k - 1]): u += AM[k] / px; inv += AM[k]; k += 1
        pl = u * px - inv
        if pl < worst: worst, wd = pl, df.index[i].date()
        if px >= inv / u * (1 + tgt):
            return dict(start=start, 단계=k, 투입=inv, 최악평가손=round(worst), 최악일=wd, 청산일=df.index[i].date(), 걸린일=(df.index[i] - df.index[0]).days, 익=round(u * px * 0.998 - inv), 시작σ=round(sig, 2), 매수선=[round(-x * 100, 1) for x in lv], 목표=round(tgt * 100, 1))
    return dict(start=start, 단계=k, 투입=inv, 최악평가손=round(worst), 최악일=wd, 청산일='진행중', 현재평가손=round(u * X[-1] - inv), 평단=round(inv / u), 청산가=round(inv / u * (1 + tgt)), 현재가=round(X[-1]), 시작가=round(p0), 매수선=[round(-x * 100, 1) for x in lv], 목표=round(tgt * 100, 1))
for nm, d in [('닷컴 고점', '2000-03-13'), ('2008 직전', '2007-07-16'), ('2011', '2011-02-18'), ('2018 고점', '2018-03-12'), ('2020 코로나 전', '2020-02-19'), ('2022 하락장', '2021-12-27'), ('2024 고점', '2024-07-10'), ('2026 고점', '2026-06-22'), ('2026-09-01', '2026-09-01')]:
    print(nm, one(d))
print('--- 연속 운용 (사이클 끝나면 바로 재시작)')
def cont(start, end=None):
    df = full[start:end]; X = df.x.values; i = 0; tot = 0; out = []
    while i < len(X):
        sig = df.v.values[i]; lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[i]
        u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0; s = i
        for j in range(i + 1, len(X)):
            px = X[j]
            while k < 5 and px <= p0 * (1 - lv[k - 1]): u += AM[k] / px; inv += AM[k]; k += 1
            worst = min(worst, u * px - inv)
            if px >= inv / u * (1 + tgt):
                g = u * px * 0.998 - inv; tot += g; out.append((df.index[s].date(), df.index[j].date(), k, round(inv), round(worst), round(g))); i = j; break
        else:
            out.append((df.index[s].date(), '진행중', k, round(inv), round(worst), round(u * X[-1] - inv), '시작가', round(p0), '평단', round(inv / u), '청산가', round(inv / u * (1 + tgt)), '현재', round(X[-1]), '다음매수선', [round(p0 * (1 - x)) for x in lv[k - 1:]])); break
    for o in out: print(o)
    print('완료 사이클 합계', round(tot))
cont('2026-06-22')
print('--- 닷컴 2000-03 ~ 2003-03')
cont('2000-03-13', '2003-03-31')
