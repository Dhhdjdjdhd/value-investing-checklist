# 물타기 시작 시점에 '그때 가장 탄탄한 회사'를 규칙으로 고르기 — 한국 (2026-11-26, 사용자 아이디어)
# 사전 규칙(성과 보기 전 고정):
#  - 사이클 시작일이 속한 달의 후보 = 직전 월말 시총 상위 20개(시점별 패널 monthly_mcap_first, flags.csv 이상치 제외)
#  - 재무는 그 달 1일 이전 공시(avail < 월초)된 가장 최근 결산연도 값만 사용(annual_first = 최초 공시값)
#  - 규칙1 ROIC: 후보 중 금융업 제외·5년 이력 회사에서 ROIC 5년 중앙값 1위
#  - 규칙2 ROIC+저부채: 같은 후보에서 (ROIC 순위 + 차입금/자본 낮은 순위) 합 1위, 동점이면 ROIC 높은 쪽
#      ※ 처음엔 '차입금/자본 ≤ 50% 중 ROIC 1위'로 정했으나 선택 결과가 규칙1과 모든 달 같아서(성과 보기 전) 순위 합산으로 변경
#  - 규칙3 시총 1위 / 규칙4 시총 상위 5개에 사다리 한도를 5등분(업종 무관)
#  - 사다리: 추가 8 선택안 그대로(a .3, p 1, m 2, n 5, b .2), 한도 = 사이클 시작 시 포트폴리오의 12.5%, 비용 편도 0.1%×2
#  - 평소 자금: SPY(배당 포함) 원화 환산. 대상 종목은 네이버 수정주가(배당 미포함 → 전략에 불리)
#  - 비교: S&P만 / 같은 규칙 종목을 같은 평균 비중으로 월 리밸런스 고정 보유 / KOSPI 지수에 같은 사다리
import sys, json, urllib.request
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
KR = ROOT / '체크리스트 검증' / 'data' / 'kr'
OUT = Path(__file__).resolve().parents[1] / 'results'
TOPN = 20
A_, P_, M_, N_, B_ = 0.3, 1.0, 2.0, 5, 0.2
BUD, C = 0.125, 0.001
RULES = ('규칙1_ROIC', '규칙2_ROIC저부채', '규칙3_시총1위', '규칙4_시총상위5')

ann = pd.read_parquet(KR / 'panel' / 'annual_first.parquet'); ann['cik'] = ann.corp_code.astype(int)
mc = pd.read_parquet(KR / 'panel' / 'monthly_mcap_first.parquet'); mc.columns = mc.columns.astype(int)
BAD = set(pd.read_csv(KR / 'panel' / 'flags.csv').cik)
mc = mc[[c for c in mc.columns if c not in BAD]]
info = ann.drop_duplicates('cik', keep='last').set_index('cik')
NAME, CODE = info.name, info.stock_code


def picks(t):
    """t(월초) 기준 규칙별 선택 [cik, ...] (순위순). 후보 부족하면 None."""
    per = (t - pd.offsets.MonthBegin(1)).to_period('M')
    if per not in mc.index: return None
    p = mc.loc[per].dropna().sort_values(ascending=False).head(TOPN)
    if len(p) < TOPN: return None
    a = ann[(ann.avail < t) & ann.cik.isin(p.index)].sort_values(['cik', 'cy', 'avail']).groupby('cik').tail(1).set_index('cik')
    q = a[(~a.sector_excl.astype(bool)) & (a.n_years >= 5) & a.roic_med5.notna() & (a.equity > 0)]
    out = {'규칙3_시총1위': [p.index[0]], '규칙4_시총상위5': list(p.index[:5]), '규칙1_ROIC': [], '규칙2_ROIC저부채': []}
    if len(q):
        out['규칙1_ROIC'] = list(q.roic_med5.sort_values(ascending=False).index)
        sc = q.roic_med5.rank(ascending=False) + (q.debt.fillna(0) / q.equity).rank()
        out['규칙2_ROIC저부채'] = list(pd.DataFrame({'s': sc, 'r': -q.roic_med5}).sort_values(['s', 'r']).index)
    return out


def yget(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    q = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q, index=pd.to_datetime(r['timestamp'], unit='s').normalize()).dropna().sort_index().groupby(level=0).last()


def px(code):
    f = KR / 'prices' / 'naver' / f'{code}.csv'
    if not f.exists(): return None
    d = pd.read_csv(f, parse_dates=['date']).set_index('date').close
    return d[d > 0].sort_index()


def sim(S, X, V, pickday, slots, start, end):
    """S: S&P(원화) 일별, X/V: 종목별 가격·σ DataFrame, pickday(date)->[cik] 순위목록, slots: 동시 사다리 수."""
    idx = S.index[(S.index >= start) & (S.index <= end)]
    su = 1 / S[idx[0]]
    sl = [None] * slots  # 각 칸: dict(c, xu, inv, k, p0, lv, amts, tgt, t0)
    val, w, log = np.empty(len(idx)), np.empty(len(idx)), []
    def value(i, d):
        return su * S[d] + sum(s['xu'] * X.at[d, s['c']] for s in sl if s)
    for i, d in enumerate(idx):
        # 1) 청산·추가 매수
        for j, s in enumerate(sl):
            if not s: continue
            p = X.at[d, s['c']]
            if np.isnan(p):  # 상장폐지·합병 등으로 가격 끊김 → 마지막 가격에 청산
                p = X[s['c']].loc[:d].dropna().iloc[-1]; s['forced'] = True
            if s.get('forced') or p >= s['inv'] / s['xu'] * (1 + s['tgt']):
                su += s['xu'] * p * (1 - 2 * C) / S[d]
                log.append(dict(c=s['c'], 이름=NAME.get(s['c']), 시작=s['t0'], 끝=d, 단계=s['k'], 투입비율=s['inv'], 손익=s['xu'] * p * (1 - 2 * C) - s['inv'],
                                강제=bool(s.get('forced'))))
                sl[j] = None; continue
            while s['k'] < N_ and p <= s['p0'] * (1 - s['lv'][s['k'] - 1]):
                a = min(s['amts'][s['k']], su * S[d]); su -= a / S[d]; s['xu'] += a * (1 - 2 * C) / p; s['inv'] += a; s['k'] += 1
        # 2) 빈 칸이면 새 사이클: 그날 규칙 순위에서 다른 칸이 안 쓰는, σ 계산 가능한 첫 종목
        if any(s is None for s in sl):
            V_ = value(i, d); held = {s['c'] for s in sl if s}
            for j in range(slots):
                if sl[j] is not None: continue
                for c in pickday(d):
                    if c in held or c not in X.columns: continue
                    p, sig = X.at[d, c], V.at[d, c]
                    if np.isnan(p) or np.isnan(sig): continue
                    wts = M_ ** np.arange(N_); amts = BUD / slots * V_ * wts / wts.sum()
                    s = dict(c=c, xu=0.0, inv=0.0, k=0, p0=p, lv=[min(A_ * sig * k ** P_, .9) for k in range(1, N_)], amts=amts, tgt=B_ * sig, t0=d)
                    a = min(amts[0], su * S[d]); su -= a / S[d]; s['xu'] = a * (1 - 2 * C) / p; s['inv'] = a; s['k'] = 1
                    sl[j] = s; held.add(c); break
        v = value(i, d); val[i] = v; w[i] = 1 - su * S[d] / v
    for s in sl:
        if s:
            p = X[s['c']].loc[:idx[-1]].dropna().iloc[-1]
            log.append(dict(c=s['c'], 이름=NAME.get(s['c']), 시작=s['t0'], 끝=None, 단계=s['k'], 투입비율=s['inv'], 손익=s['xu'] * p - s['inv'], 강제=False))
    return pd.Series(val, index=idx), pd.Series(w, index=idx), pd.DataFrame(log)


def fixed(S, X, pickday, slots, wbar, idx):
    """같은 규칙 종목(월초 재선정, 상위 slots개 균등)을 평균 비중 wbar로 월 리밸런스 보유."""
    v, cur, ww = [1.0], None, None
    mo = idx.to_period('M')
    for i in range(1, len(idx)):
        d0, d = idx[i - 1], idx[i]
        if cur is None or mo[i] != mo[i - 1]:
            cur = [c for c in pickday(d0) if c in X.columns and not np.isnan(X.at[d0, c])][:slots]
            ww = {c: wbar / len(cur) for c in cur}; ws = 1 - wbar
        g = ws * S[d] / S[d0] + sum(ww[c] * (X.at[d, c] / X.at[d0, c] if not np.isnan(X.at[d, c]) else 1) for c in cur)
        ws = ws * S[d] / S[d0] / g
        ww = {c: ww[c] * (X.at[d, c] / X.at[d0, c] if not np.isnan(X.at[d, c]) else 1) / g for c in cur}
        v.append(v[-1] * g)
    return pd.Series(v, index=idx)


def stats(v, rf):
    r = v.pct_change().dropna(); ex = r - rf.reindex(r.index).ffill().fillna(2) / 100 / 252; yrs = len(r) / 252
    return dict(CAGR=(v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1, Sharpe=ex.mean() / ex.std() * np.sqrt(252), MDD=(v / v.cummax() - 1).min())


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
    months = pd.date_range('2016-04-01', '2026-11-01', freq='MS')
    PK = {t: picks(t) for t in months}
    PK = {t: v for t, v in PK.items() if v}
    # 선택 이력 저장
    hist = pd.DataFrame([{'월': t.date(), **{r: ','.join(str(NAME.get(c)) for c in v[r][:(5 if r == '규칙4_시총상위5' else 1)]) for r in RULES}} for t, v in PK.items()])
    hist.to_csv(OUT / 'pick_kr_history.csv', index=False, encoding='utf-8-sig')

    ciks = sorted({c for v in PK.values() for r in RULES for c in v[r][:8]})
    spy, fx, irx, ks = yget('SPY'), yget('KRW=X'), yget('^IRX'), yget('^KS11')
    fx = fx[(fx > 800) & (fx < 2000)]
    S = (spy * fx.reindex(spy.index).ffill()).dropna()
    cols = {}
    for c in ciks:
        p = px(CODE.get(c))
        if p is None: print('가격 없음', NAME.get(c), CODE.get(c)); continue
        cols[c] = p
    cols[-1] = ks  # KOSPI 지수
    kdays = ks.index
    for s in cols.values(): kdays = kdays.union(s.index)
    S = S.reindex(S.index.union(kdays)).ffill().dropna()
    S = S[S.index.isin(kdays)]  # 한국 거래일 기준
    X = pd.DataFrame({c: s.reindex(S.index) for c, s in cols.items()})
    # 끊긴 가격은 상장 기간 안에서만 앞값 채움(휴장 차이), 상장 전·폐지 후는 NaN 유지
    for c in X:
        s = cols[c]; X[c] = X[c].ffill().where((X.index >= s.index[0]) & (X.index <= s.index[-1]))
    V = np.log(X).diff().rolling(252, min_periods=200).std() * np.sqrt(252)
    # 하루 ±35% 넘는 변동(수정주가 누락 의심) 점검
    jr = X.pct_change(fill_method=None).abs()
    for c in X:
        bad = jr.index[jr[c] > 0.35]
        if len(bad): print('일간 35% 초과', NAME.get(c, c), [str(b.date()) for b in bad[:5]])

    def pickday_f(rule):
        return lambda d: PK.get(pd.Timestamp(d.year, d.month, 1), {}).get(rule, []) if rule != 'KOSPI' else [-1]
    rows, logs, rolls = [], [], []
    for per, s0, s1 in [('A 2018-07~ (규칙1~4 공통)', '2018-07-01', '2026-11-10'), ('B 2016-04~ (규칙3·4·KOSPI)', '2016-04-01', '2026-11-10')]:
        for rule in RULES + ('KOSPI',):
            if per.startswith('B') and rule in RULES[:2]: continue
            slots = 5 if rule == '규칙4_시총상위5' else 1
            pf = pickday_f(rule)
            v, w, lg = sim(S, X, V, pf, slots, pd.Timestamp(s0), pd.Timestamp(s1))
            sp = S.loc[v.index] / S.loc[v.index[0]]
            fx_ = fixed(S, X, pf, slots, w.mean(), v.index)
            st, sps, fxs = stats(v, irx), stats(sp, irx), stats(fx_, irx)
            done = lg[lg.끝.notna()] if len(lg) else lg
            rows.append(dict(기간=per, 규칙=rule, CAGR=st['CAGR'], Sharpe=st['Sharpe'], MDD=st['MDD'], 고정CAGR=fxs['CAGR'], 고정Sharpe=fxs['Sharpe'],
                             SP_CAGR=sps['CAGR'], SP_Sharpe=sps['Sharpe'], 평균비중=w.mean(), 최대비중=w.max(), 사이클=len(done),
                             평균단계=done.단계.mean() if len(done) else np.nan, vsSP_4억=(v.iloc[-1] - sp.iloc[-1]) * 4e8, vs고정_4억=(v.iloc[-1] - fx_.iloc[-1]) * 4e8))
            if len(lg): lg['기간'], lg['규칙'] = per, rule; logs.append(lg)
            # 3년 롤링(분기 시작)
            for d in pd.date_range(s0, pd.Timestamp(s1) - pd.DateOffset(years=3), freq='QS'):
                if per.startswith('B') and rule not in ('규칙3_시총1위', '규칙4_시총상위5', 'KOSPI'): continue
                e = d + pd.DateOffset(years=3)
                vv, ww_, _ = sim(S, X, V, pf, slots, d, e)
                spp = S.loc[vv.index[-1]] / S.loc[vv.index[0]]
                fxx = fixed(S, X, pf, slots, ww_.mean(), vv.index).iloc[-1]
                rolls.append(dict(기간=per, 규칙=rule, 시작=d.date(), vsSP=(vv.iloc[-1] - spp) * 4e8, vs고정=(vv.iloc[-1] - fxx) * 4e8))
            print('완료', per, rule, flush=True)
    R = pd.DataFrame(rows); L = pd.concat(logs); RO = pd.DataFrame(rolls)
    R.to_csv(OUT / 'pick_kr_summary.csv', index=False, encoding='utf-8-sig')
    L.to_csv(OUT / 'pick_kr_cycles.csv', index=False, encoding='utf-8-sig')
    RO.to_csv(OUT / 'pick_kr_roll3y.csv', index=False, encoding='utf-8-sig')
    print(R.to_string(float_format=lambda x: f'{x:,.3f}'))
    print(RO.groupby(['기간', '규칙']).agg(n=('vsSP', 'size'), SP이김=('vsSP', lambda s: (s > 0).mean()), 평균=('vsSP', 'mean'), 최악=('vsSP', 'min'),
                                         고정이김=('vs고정', lambda s: (s > 0).mean()), 평균vs고정=('vs고정', 'mean')).to_string(float_format=lambda x: f'{x:,.2f}'))
