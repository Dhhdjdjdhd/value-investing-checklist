# 선택안 사다리(최대 5,000만)를 마이크로소프트에 적용 — 사후 선택 종목이라 상한선으로 볼 것
import warnings; warnings.filterwarnings('ignore')
exec(open('design.py', encoding='utf-8').read().split('# 1) 학습')[0])
import numpy as np
A['MSFT'] = get('MSFT')
best = (0.3, 1.0, 2.0, 5, 0.2); AM = np.array([161, 323, 645, 1290, 2581.])
for nm in ('MSFT', 'SOX'):
    print('=====', nm)
    for per, s0, s1 in [('1996~2010', '1996', '2010-12-31'), ('2011~', '2011', '2026-12-31'), ('전체', '1996', '2026-12-31')]:
        df = frame(nm, '1996-01-01', '2026-12-31')[s0:s1]; v, w, c, dp, k = sim(df, *best); st = stats(v)
        sp = stats(df.s / df.s.iloc[0]); fx = stats(fixedw(df, w.mean()))
        print(f'{per}: CAGR {st["CAGR"]*100:.2f}% (S&P {sp["CAGR"]*100:.2f}%, 고정 {fx["CAGR"]*100:.2f}%) 샤프 {st["Sharpe"]:.3f} (S&P {sp["Sharpe"]:.3f}, 고정 {fx["Sharpe"]:.3f}) MDD {st["MDD"]*100:.1f}% 사이클 {c}')
    full = frame(nm, '1996-01-01', '2026-12-31'); rl = []
    for d in pd.date_range(full.index[0], '2021-11-01', freq='MS'):
        df = full[(full.index >= d) & (full.index < d + pd.Timedelta(days=1826))]
        if len(df) < 1100: continue
        v, w, *_ = sim(df, *best); rl.append((v.iloc[-1] - df.s.iloc[-1] / df.s.iloc[0]) * 4e8)
    rl = np.array(rl); print(f'5년 롤링(4억): 이긴 비율 {(rl>0).mean()*100:.0f}%, 평균 {rl.mean()/1e4:+,.0f}만, 최악 {rl.min()/1e4:+,.0f}만')
    X = full.x.values; D = full.index; i = 0; cyc = []
    while i < len(X):
        sig = full.v.values[i]; lv = [0.3 * sig * j for j in range(1, 5)]; tgt = 0.2 * sig; p0 = X[i]
        u = AM[0] / p0; inv = AM[0]; k = 1; worst = 0; wp = 0
        for j in range(i + 1, len(X)):
            px = X[j]
            while k < 5 and px <= p0 * (1 - lv[k - 1]): u += AM[k] / px; inv += AM[k]; k += 1
            worst = min(worst, u * px - inv); wp = min(wp, (u * px - inv) / inv)
            if px >= inv / u * (1 + tgt):
                cyc.append(((D[j] - D[i]).days, D[i].date(), D[j].date(), k, round(worst), wp, round(u * px * .998 - inv))); i = j; break
        else:
            cyc.append(((D[-1] - D[i]).days, D[i].date(), '진행중', k, round(worst), wp, round(u * X[-1] - inv))); break
    d = np.array([c[0] for c in cyc]); ks = np.array([c[3] for c in cyc])
    print(f'사이클 {len(cyc)}, 보유일 중앙 {np.median(d):.0f}, 90% {np.percentile(d,90):.0f}, 1년 초과 {(d>365).sum()}, 5단계 {(ks==5).sum()}, 합계 손익 {sum(c[6] for c in cyc):+,}만')
    print('가장 긴 5개:'); [print('  ', c[0], '일', c[1], '→', c[2], '단계', c[3], f'최대평가손 {c[4]:,}만 ({c[5]*100:.1f}%)', f'손익 {c[6]:+,}만') for c in sorted(cyc, key=lambda c: -c[0])[:5]]
    print('5단계 사이클:'); [print('  ', c) for c in cyc if c[3] == 5]
    if nm == 'MSFT':
        print('2025년~:'); [print('  ', c[1], '→', c[2], c[0], '일 단계', c[3], f'MDD {c[5]*100:.1f}%', f'{c[6]:+,}만') for c in cyc if str(c[1]) >= '2025']
        print('현재 MSFT', X[-1], '1년 σ', round(full.v.values[-1], 3))
