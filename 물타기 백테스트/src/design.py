# 물타기 재설계 (2026-11-25) — 사전 규칙
#  - 자금은 전부 S&P(SPY)에 있고, 대상 자산이 빠질 때 S&P를 팔아 물타기, 평단+목표면 전량 S&P 복귀 후 즉시 새 사이클
#  - 간격·목표를 '대상 자산의 최근 1년 변동성(σ)'에 비례: k번째 추가 매수선 = 사이클 시작가 × (1 − a·σ·k^p), 목표 = b·σ
#  - 금액: 사다리 전체 = 사이클 시작 시 포트폴리오의 B(12.5% = 4억 중 5,000만), k단계 금액 ∝ m^k  → 포트폴리오 크기와 무관
#  - 비용: 매매 1회당 편도 0.1% × 2(S&P 매도 + 대상 매수)
#  - 선택: 학습 1996~2010(SOX·NDX 평균 샤프)로 한 세트만 고름 → 검증 2011~2026, 그리고 학습에 안 쓴 자산(XLK, KOSPI, 삼성전자; 원화자산은 달러 환산)
#  - 공정 비교: 같은 평균 비중을 '고정 보유(월 리밸런스)'한 포트폴리오. 이걸 못 이기면 물타기 타이밍의 가치는 없음
import json, urllib.request, itertools, numpy as np, pandas as pd
OUT = r'E:/value-investing-checklist/물타기 백테스트/results/'
def get(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    q = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q, index=pd.to_datetime(r['timestamp'], unit='s').normalize()).dropna().sort_index().groupby(level=0).last()
spy = get('SPY'); irx = get('^IRX'); krw = get('KRW=X')
krw = krw[(krw > 800) & (krw < 2000)]
A = {'SOX': get('^SOX'), 'NDX': get('^NDX'), 'XLK': get('XLK')}
for k, s in [('KOSPI', '^KS11'), ('삼성전자', '005930.KS')]:
    x = get(s); A[k] = (x / krw.reindex(x.index).ffill()).dropna()
B, C = 0.125, 0.001  # 사다리 최대 = 4억 중 5,000만(12.5%), 사용자 지정 2026-11-25

def frame(name, start, end):
    df = pd.concat([A[name].rename('x'), spy.rename('s')], axis=1).dropna()
    vol = np.log(df.x).diff().rolling(252).std() * np.sqrt(252)
    df['v'] = vol
    return df[(df.index >= start) & (df.index <= end)].dropna()

def sim(df, a, p, m, n, b, Bud=B, fixed=None):
    X, S, Vv = df.x.values, df.s.values, df.v.values
    su, xu, inv = 1 / S[0], 0.0, 0.0
    val = np.empty(len(X)); w = np.empty(len(X)); cyc = 0; deep = []
    def start(i):
        nonlocal lv, amts, k, inv, xu, su, tgt, p0
        V = su * S[i] + xu * X[i]; sig = Vv[i]
        if fixed:  # 사용자 원안 C: 10/15/…/40%, 2배, 목표 5%
            lv = fixed; tgt = 0.05
        else:
            lv = [min(a * sig * j ** p, 0.9) for j in range(1, n)]; tgt = b * sig
        wts = np.array([1] + [m ** j for j in range(n - 1)], float) if fixed else m ** np.arange(n)
        amts = Bud * V * wts / wts.sum(); p0 = X[i]; k = 0; buy(i)
    def buy(i):
        nonlocal k, su, xu, inv
        amt = min(amts[k], su * S[i]); su -= amt / S[i]; xu += amt * (1 - 2 * C) / X[i]; inv += amt; k += 1
    lv = amts = None; k = 0; tgt = 0; p0 = X[0]
    start(0)
    for i in range(len(X)):
        if i > 0:
            px = X[i]
            if px >= inv / xu * (1 + tgt):
                su += xu * px * (1 - 2 * C) / S[i]; deep.append(k); xu = 0; inv = 0; cyc += 1; start(i)
            elif k < len(amts) and px <= p0 * (1 - lv[k - 1]):
                buy(i)
        val[i] = su * S[i] + xu * X[i]; w[i] = xu * X[i] / val[i]
    return pd.Series(val, index=df.index), w, cyc, (np.mean(deep) if deep else np.nan), k

def fixedw(df, wt):
    r = df[['x', 's']].pct_change().fillna(0); v = [1.0]; ww = wt
    mo = df.index.to_period('M')
    for i in range(1, len(df)):
        g = ww * (1 + r.x.iat[i]) + (1 - ww) * (1 + r.s.iat[i]); v.append(v[-1] * g)
        ww = ww * (1 + r.x.iat[i]) / g
        if mo[i] != mo[i - 1]: ww = wt
    return pd.Series(v, index=df.index)

def stats(v):
    r = v.pct_change().dropna(); rf = (irx.reindex(r.index).ffill().fillna(2) / 100 / 252)
    ex = r - rf; yrs = len(r) / 252
    return dict(CAGR=(v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1, vol=r.std() * np.sqrt(252),
                Sharpe=ex.mean() / ex.std() * np.sqrt(252), MDD=(v / v.cummax() - 1).min())

GRID = list(itertools.product([0.3, 0.5, 0.7], [1.0, 1.3], [1.5, 2.0], [5, 7], [0.1, 0.2, 0.3]))
USER = [.10, .15, .20, .25, .30, .35, .40]

# 1) 학습
rows = []
tr = {nm: frame(nm, '1996-01-01', '2010-12-31') for nm in ('SOX', 'NDX')}
for g in GRID:
    d = dict(zip('apmnb', g))
    for nm, df in tr.items():
        v, w, cyc, dp, _ = sim(df, *g)
        st = stats(v); fw = stats(fixedw(df, w.mean()))
        rows.append(dict(**d, asset=nm, **st, avg_w=w.mean(), max_w=w.max(), cycles=cyc, depth=dp,
                         fixSharpe=fw['Sharpe'], fixCAGR=fw['CAGR'], fixMDD=fw['MDD']))
T = pd.DataFrame(rows); T['dSh'] = T.Sharpe - T.fixSharpe
T.to_csv(OUT + 'design_train.csv', index=False)
agg = T.groupby(list('apmnb')).agg(Sharpe=('Sharpe', 'mean'), dSh=('dSh', 'mean'), CAGR=('CAGR', 'mean'), MDD=('MDD', 'mean'),
                                     avg_w=('avg_w', 'mean'), cycles=('cycles', 'mean')).sort_values('Sharpe', ascending=False)
pd.set_option('display.width', 250)
print('== 학습 상위 10 (SOX·NDX 평균)'); print(agg.head(10).to_string(float_format=lambda x: f'{x:.3f}'))
print('== 학습 하위 5'); print(agg.tail(5).to_string(float_format=lambda x: f'{x:.3f}'))
best = agg.index[0]; print('선택:', dict(zip('apmnb', best)))

# 2) 검증 + 학습 밖 자산 + 전체 기간
out = []
for per, s0, s1 in [('학습 1996~2010', '1996-01-01', '2010-12-31'), ('검증 2011~2026', '2011-01-01', '2026-12-31'), ('전체', '1996-01-01', '2026-12-31')]:
    for nm in A:
        df = frame(nm, s0, s1)
        if len(df) < 1000: continue
        spy_v = df.s / df.s.iloc[0]
        for lab, args, kw in [('선택안', best, {}), ('원안C(같은 5,000만)', (0, 0, 2, 8, 0), dict(fixed=USER, Bud=0.125))]:
            v, w, cyc, dp, kend = sim(df, *args, **kw)
            st = stats(v); fw = stats(fixedw(df, w.mean()))
            out.append(dict(기간=per, 자산=nm, 전략=lab, 시작=df.index[0].date(), **{k: st[k] for k in st}, 평균비중=w.mean(), 최대비중=w.max(),
                            사이클=cyc, 평균단계=dp, 고정Sharpe=fw['Sharpe'], 고정CAGR=fw['CAGR'], 고정MDD=fw['MDD'],
                            SP_Sharpe=stats(spy_v)['Sharpe'], SP_CAGR=stats(spy_v)['CAGR'], SP_MDD=stats(spy_v)['MDD'], 현재단계=kend))
O = pd.DataFrame(out); O.to_csv(OUT + 'design_test.csv', index=False)
print(O.to_string(float_format=lambda x: f'{x:.3f}'))

# 3) 이웃 파라미터 안정성(검증 구간, SOX·NDX): 선택안 주변 1칸씩
nb = []
for g in GRID:
    if sum(x != y for x, y in zip(g, best)) <= 1:
        for nm in ('SOX', 'NDX', 'XLK', 'KOSPI', '삼성전자'):
            df = frame(nm, '2011-01-01', '2026-12-31'); v, w, *_ = sim(df, *g)
            nb.append(dict(zip('apmnb', g), asset=nm, Sharpe=stats(v)['Sharpe'], fix=stats(fixedw(df, w.mean()))['Sharpe']))
N = pd.DataFrame(nb); N['dSh'] = N.Sharpe - N.fix
print('== 이웃 안정성(검증)'); print(N.pivot_table(index=list('apmnb'), columns='asset', values='dSh').to_string(float_format=lambda x: f'{x:+.3f}'))
N.to_csv(OUT + 'design_neighbors.csv', index=False)

# 4) 5년 롤링(선택안 vs S&P만 vs 고정비중), 원금 4억 가정 금액
roll = []
for nm in A:
    full = frame(nm, '1996-01-01', '2026-12-31')
    for d in pd.date_range(full.index[0], '2021-11-01', freq='MS'):
        df = full[(full.index >= d) & (full.index < d + pd.Timedelta(days=1826))]
        if len(df) < 1100: continue
        v, w, cyc, dp, _ = sim(df, *best)
        sp = df.s.iloc[-1] / df.s.iloc[0]; fx = fixedw(df, w.mean()).iloc[-1]
        roll.append(dict(asset=nm, date=d, diff_sp=(v.iloc[-1] - sp) * 4e8, diff_fix=(v.iloc[-1] - fx) * 4e8, maxw=w.max()))
R = pd.DataFrame(roll); R.to_csv(OUT + 'design_roll.csv', index=False)
print('== 5년 롤링 (4억 기준, 원)')
print(R.groupby('asset').agg(n=('diff_sp', 'size'), SP이김=('diff_sp', lambda v: (v > 0).mean()), 평균vsSP=('diff_sp', 'mean'), 최악vsSP=('diff_sp', 'min'),
                             고정이김=('diff_fix', lambda v: (v > 0).mean()), 평균vs고정=('diff_fix', 'mean'), 최대비중=('maxw', 'max')).to_string(float_format=lambda x: f'{x:,.3f}'))
