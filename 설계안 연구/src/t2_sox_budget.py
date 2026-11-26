# T2. SOX 사다리 한도 확대, 1996~2026 (2026-11-26, 세션 03)
#  - 설계서: 설계안 연구/00_연구설계서.md §T2. 규칙은 물타기 백테스트/src/design.py 선택안(a 0.3, p 1, m 2, n 5, b 0.2) 그대로.
#  - 한도 B ∈ {12.5, 25, 50, 100%}만 바꿈. 평소 자금 SPY, 비용 편도 0.1%×2. ^SOX·SPY·^IRX (Yahoo, design.py의 get).
#  - get / frame / sim / fixedw / stats 는 design.py에서 글자 그대로 복사(design.py는 import 하면 격자 전체가 돌아서 복사함).
#    sim_log 는 sim 에 사이클 기록만 덧붙인 사본이며, 실행 시 sim 과 가치곡선이 같은지 assert 로 확인한다.
import sys, json, urllib.request, datetime, pathlib, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
ROOT = pathlib.Path(__file__).resolve().parents[1]; OUT = ROOT / 'results'; OUT.mkdir(exist_ok=True)
PX = OUT / 't2_prices.csv'   # 받은 가격 자료(재실행 재현용)
LOG = open(OUT / 't2_log.txt', 'w', encoding='utf-8')
def pr(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); LOG.write(s + '\n')

# ---- design.py 그대로 (get / frame / sim / fixedw / stats) ----
def get(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    q = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q, index=pd.to_datetime(r['timestamp'], unit='s').normalize()).dropna().sort_index().groupby(level=0).last()

if PX.exists():
    P = pd.read_csv(PX, index_col=0, parse_dates=True); pr('가격 자료: 캐시 사용', PX)
else:
    P = pd.concat([get('^SOX').rename('SOX'), get('SPY').rename('SPY'), get('^IRX').rename('IRX')], axis=1, sort=True)
    P.to_csv(PX); pr('가격 자료: Yahoo 수신', datetime.date.today())
spy, irx = P.SPY.dropna(), P.IRX.dropna()
A = {'SOX': P.SOX.dropna()}
B, C = 0.125, 0.001

def frame(name, start, end):
    df = pd.concat([A[name].rename('x'), spy.rename('s')], axis=1, sort=True).dropna()
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
# ---- 여기까지 design.py 그대로 ----

# sim 과 같은 논리 + 사이클 기록(시작일·종료일·단계·투입액·최저 평가·시작 자산). 가치곡선이 sim 과 같아야 한다.
def sim_log(df, a, p, m, n, b, Bud=B):
    X, S, Vv = df.x.values, df.s.values, df.v.values; idx = df.index
    su, xu, inv = 1 / S[0], 0.0, 0.0
    val = np.empty(len(X)); w = np.empty(len(X)); rows = []; cur = None
    def start(i):
        nonlocal lv, amts, k, inv, xu, su, tgt, p0, cur
        V = su * S[i] + xu * X[i]; sig = Vv[i]
        lv = [min(a * sig * j ** p, 0.9) for j in range(1, n)]; tgt = b * sig
        wts = m ** np.arange(n); amts = Bud * V * wts / wts.sum(); p0 = X[i]; k = 0
        cur = dict(시작=idx[i], V0=V, σ=sig, 목표=tgt, 최저평가손=0.0, 최대비중=0.0); buy(i)
    def buy(i):
        nonlocal k, su, xu, inv
        amt = min(amts[k], su * S[i]); su -= amt / S[i]; xu += amt * (1 - 2 * C) / X[i]; inv += amt; k += 1
    def close(i, done):
        cur.update(종료=idx[i], 일수=(idx[i] - cur['시작']).days, 단계=k, 투입=inv, 투입비율=inv / cur['V0'], 종결=done); rows.append(cur)
    lv = amts = None; k = 0; tgt = 0; p0 = X[0]
    start(0)
    for i in range(len(X)):
        if i > 0:
            px = X[i]
            if px >= inv / xu * (1 + tgt):
                close(i, True); su += xu * px * (1 - 2 * C) / S[i]; xu = 0; inv = 0; start(i)
            elif k < len(amts) and px <= p0 * (1 - lv[k - 1]):
                buy(i)
        val[i] = su * S[i] + xu * X[i]; w[i] = xu * X[i] / val[i]
        cur['최저평가손'] = min(cur['최저평가손'], (xu * X[i] - inv) / cur['V0']); cur['최대비중'] = max(cur['최대비중'], w[i])
    close(len(X) - 1, False)
    return pd.Series(val, index=idx), w, pd.DataFrame(rows)

BEST = (0.3, 1.0, 2, 5, 0.2)   # design.py 선택안 a, p, m, n, b
BUDS = (0.125, 0.25, 0.5, 1.0)
WON = 4e4   # 4억 원 = 4e4 만 원
full = frame('SOX', '1996-01-01', '2026-12-31')
pr('자료 구간:', full.index[0].date(), '~', full.index[-1].date(), '거래일', len(full))

def summary(df, bud, roll=True):
    v, w, cyc, dp, kend = sim(df, *BEST, Bud=bud)
    v2, w2, cl = sim_log(df, *BEST, Bud=bud)
    assert np.allclose(v.values, v2.values) and np.allclose(w, w2), 'sim_log 가 sim 과 다름'
    sp = df.s / df.s.iloc[0]; fx = fixedw(df, w.mean())
    st, sps, fxs = stats(v), stats(sp), stats(fx)
    row = {'한도': f'{bud:.1%}', '4억일때_사다리총액(만)': bud * WON, '4억일때_최대칸(만)': bud * WON * 16 / 31,
           'CAGR': st['CAGR'], 'S&P CAGR': sps['CAGR'], '차이%p': (st['CAGR'] - sps['CAGR']) * 100,
           '고정보유CAGR': fxs['CAGR'], '고정보유대비%p': (st['CAGR'] - fxs['CAGR']) * 100,
           'Sharpe': st['Sharpe'], 'S&P Sharpe': sps['Sharpe'], '고정보유Sharpe': fxs['Sharpe'],
           'MDD': st['MDD'], 'S&P MDD': sps['MDD'], '고정보유MDD': fxs['MDD'], 'MDD차이%p': (st['MDD'] - sps['MDD']) * 100,
           '변동성': st['vol'], 'S&P 변동성': sps['vol'], '평균비중': w.mean(), '최대비중': w.max(), '사이클수': cyc, '평균단계': dp, '현재단계': kend,
           '최장사이클(일)': cl['일수'].max(), '최대투입비율': cl['투입비율'].max(), '최대투입(4억기준,만)': cl['투입비율'].max() * WON,
           '최저평가손(시작자산대비)': cl['최저평가손'].min(), '최종가치(4억→만)': v.iloc[-1] * WON, 'S&P최종(4억→만)': sp.iloc[-1] * WON}
    if roll:
        for yrs in (5, 3):
            acc = []
            for d in pd.date_range(df.index[0], df.index[-1] - pd.DateOffset(years=yrs), freq='MS'):
                dd = df[(df.index >= d) & (df.index < d + pd.DateOffset(years=yrs))]
                if len(dd) < yrs * 245: continue
                vv, _, _, _, _ = sim(dd, *BEST, Bud=bud)
                acc.append(dict(한도=f'{bud:.1%}', 창=yrs, 시작=d.date(), 전략=vv.iloc[-1], SP=dd.s.iloc[-1] / dd.s.iloc[0],
                                차이만=(vv.iloc[-1] - dd.s.iloc[-1] / dd.s.iloc[0]) * WON, MDD=stats(vv)['MDD']))
            R = pd.DataFrame(acc); ROLL.append(R); d_ = R.차이만
            row.update({f'{yrs}년 이김': (d_ > 0).mean(), f'{yrs}년 평균(만)': d_.mean(), f'{yrs}년 최악(만)': d_.min(), f'{yrs}년 최악시작': R.loc[d_.idxmin(), '시작'], f'{yrs}년 창수': len(R)})
    return row, v, w, cl

# 1) 전체 1996~2026 — budget_us.csv 와 같은 열 + 추가
ROLL = []; main = []; curves = {'S&P': full.s / full.s.iloc[0]}; cycles = []
for bud in BUDS:
    row, v, w, cl = summary(full, bud); main.append(row); curves[f'B{bud:.1%}'] = v
    cl.insert(0, '한도', f'{bud:.1%}'); cycles.append(cl); pr('완료 전체', bud)
M = pd.DataFrame(main); M.to_csv(OUT / 't2_budget_sox.csv', index=False, encoding='utf-8-sig')
pd.concat(ROLL).to_csv(OUT / 't2_roll.csv', index=False, encoding='utf-8-sig')
CY = pd.concat(cycles); CY.to_csv(OUT / 't2_cycles.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(curves).to_csv(OUT / 't2_curves.csv', encoding='utf-8-sig')
pr('== 1) 전체 1996~2026'); pr(M.T.to_string())

# 2) 구간별 1996~2010 / 2011~2026 (각 구간 처음부터 새로 시뮬레이션, design.py 와 같은 방식)
sub = []
for per, s0, s1 in [('1996~2010', '1996-01-01', '2010-12-31'), ('2011~2026', '2011-01-01', '2026-12-31')]:
    df = frame('SOX', s0, s1)
    for bud in BUDS:
        row, *_ = summary(df, bud, roll=False); sub.append({'구간': per, **row})
SUB = pd.DataFrame(sub); SUB.to_csv(OUT / 't2_subperiod.csv', index=False, encoding='utf-8-sig')
pr('== 2) 구간별'); pr(SUB.set_index(['구간', '한도'])[['CAGR', 'S&P CAGR', '차이%p', '고정보유대비%p', 'Sharpe', 'S&P Sharpe', 'MDD', 'S&P MDD', '평균비중', '최대비중', '사이클수', '최장사이클(일)', '최대투입비율']].to_string(float_format=lambda x: f'{x:.3f}'))

# 3) 가장 오래 묶인 사이클 — 한도별 상위 3 (미종결 포함)
pr('== 3) 가장 오래 묶인 사이클 (한도별 상위 3)')
top = CY.sort_values('일수', ascending=False).groupby('한도').head(3).sort_values(['한도', '일수'], ascending=[True, False])
top['투입(4억기준,만)'] = top.투입비율 * WON
pr(top[['한도', '시작', '종료', '일수', '단계', '투입비율', '투입(4억기준,만)', '최저평가손', '최대비중', '종결']].to_string(index=False, float_format=lambda x: f'{x:.3f}'))
pr('-- 한도별 최대 투입액 사이클')
mx = CY.sort_values('투입비율', ascending=False).groupby('한도').head(1)
mx['투입(4억기준,만)'] = mx.투입비율 * WON
pr(mx[['한도', '시작', '종료', '일수', '단계', '투입비율', '투입(4억기준,만)', '최저평가손', '최대비중', '종결']].to_string(index=False, float_format=lambda x: f'{x:.3f}'))

# 4) 2000-03 시작·2007-10 시작 5년 창
win = []
for s0 in ('2000-03-01', '2007-10-01'):
    d0 = pd.Timestamp(s0); df = full[(full.index >= d0) & (full.index < d0 + pd.DateOffset(years=5))]
    sp = df.s.iloc[-1] / df.s.iloc[0]; sox = df.x.iloc[-1] / df.x.iloc[0]
    for bud in BUDS:
        v, w, cyc, dp, kend = sim(df, *BEST, Bud=bud); v2, w2, cl = sim_log(df, *BEST, Bud=bud)
        assert np.allclose(v.values, v2.values)
        fx = fixedw(df, w.mean())
        win.append({'시작': s0, '종료': df.index[-1].date(), '한도': f'{bud:.1%}', '전략 최종(4억→만)': v.iloc[-1] * WON, 'S&P 최종(4억→만)': sp * WON, 'SOX 최종(4억→만)': sox * WON,
                    'vs S&P(만)': (v.iloc[-1] - sp) * WON, 'vs 고정보유(만)': (v.iloc[-1] - fx.iloc[-1]) * WON, 'CAGR': stats(v)['CAGR'], 'S&P CAGR': stats(df.s / df.s.iloc[0])['CAGR'],
                    'MDD': stats(v)['MDD'], 'S&P MDD': stats(df.s / df.s.iloc[0])['MDD'], '평균비중': w.mean(), '최대비중': w.max(), '사이클수': cyc,
                    '최장사이클(일)': cl['일수'].max(), '최대투입비율': cl['투입비율'].max(), '최저평가손': cl['최저평가손'].min(), '창끝단계': kend})
W = pd.DataFrame(win); W.to_csv(OUT / 't2_windows.csv', index=False, encoding='utf-8-sig')
pr('== 4) 2000-03 / 2007-10 시작 5년 창'); pr(W.set_index(['시작', '한도']).T.to_string())

# 5) 연도별 수익률 (한도별 vs S&P)
CV = pd.DataFrame(curves); yr = CV.resample('YE').last().pct_change(); yr.iloc[0] = CV.resample('YE').last().iloc[0] / CV.iloc[0] - 1
yr.index = yr.index.year; yr.to_csv(OUT / 't2_yearly.csv', encoding='utf-8-sig')
pr('== 5) 연도별 수익률'); pr(yr.to_string(float_format=lambda x: f'{x:+.1%}'))

# 6) "S&P보다 MDD가 나빠지지 않는 최대 한도" (전체 구간 기준, 네 한도 중)
ok = M[M.MDD >= M['S&P MDD']]
pr('== 6) 전체 구간에서 MDD ≤ S&P 인 한도:', list(ok.한도), '→ 최대:', ok.한도.iloc[-1] if len(ok) else '없음')
for per in SUB.구간.unique():
    s = SUB[SUB.구간 == per]; o = s[s.MDD >= s['S&P MDD']]
    pr(f'   {per}: MDD ≤ S&P 인 한도 {list(o.한도)} → 최대 {o.한도.iloc[-1] if len(o) else "없음"}')
LOG.close()
