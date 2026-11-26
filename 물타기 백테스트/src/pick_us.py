# 물타기 시작 시점에 '그때 가장 탄탄한 회사'를 규칙으로 고르기 — 미국 (2026-11-26, pick_kr.py의 미국판)
# 사전 규칙(성과 보기 전 고정, 한국과 같게. 다른 점만 적음):
#  - 후보: us_data.py 목록(대형주 116개, 사후 작성) 중 가격·주식수 있는 회사. 버크셔·비자는 주식수가 클래스별로만 공시돼 시총 계산 불가 → 제외
#  - 시총 = 직전 월말 종가(분할 반영) × 그 시점까지 공시된 최근 희석주식수(오늘 분할 기준) → 상위 20개가 후보
#  - ROIC 5년 중앙값: 그 시점까지 공시된 최근 5개 회계연도 중 ROIC 있는 해가 3개 이상일 때 중앙값
#      (XBRL이 2010년 시작이라 5개 연속 요구 시 2014년부터만 가능 → 3개로 완화, 한국은 5개)
#  - 업종 제외: 체크리스트 검증 fundamentals.excluded_sector(SIC: 은행·보험·증권·에너지·소재 등), 자본 > 0
#  - 가격: Yahoo adjclose(배당 포함), 평소 자금: SPY(배당 포함), 달러 기준. 지수 참고: NDX에 같은 사다리
import sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / '체크리스트 검증' / 'src'))
import pick_kr as K  # noqa: E402  (sim·fixed·stats 엔진 재사용)
from fundamentals import excluded_sector  # noqa: E402

D = HERE.parent / 'data_us'
OUT = HERE.parent / 'results'
RULES = K.RULES
ann = pd.read_parquet(D / 'annual.parquet')
close = pd.read_parquet(D / 'close.parquet'); adj = pd.read_parquet(D / 'adj.parquet')
for c in ('BRK-B', 'V'):
    if c in close: close = close.drop(columns=c)
ann = ann[ann.ticker.isin(close.columns)].copy()
ann['excl'] = ann.sic.map(excluded_sector)
mcl = close.resample('ME').last()  # 월말 종가
K.NAME = pd.Series({t: t for t in close.columns})


def picks(t):
    a = ann[ann.avail < t].sort_values(['ticker', 'cy', 'avail'])
    last = a.groupby('ticker').tail(1).set_index('ticker')
    pe = t - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)
    p = mcl.loc[:pe].iloc[-1]
    mc = (p * last.sh_adj.reindex(p.index)).dropna().sort_values(ascending=False).head(K.TOPN)
    if len(mc) < K.TOPN: return None
    r5 = a.groupby('ticker').tail(5).groupby('ticker').roic.agg(['median', 'count'])
    q = last.reindex(mc.index).join(r5.reindex(mc.index))
    q = q[(~q.excl.fillna(True).astype(bool)) & (q['count'] >= 3) & q['median'].notna() & (q.equity > 0)]
    out = {'규칙3_시총1위': [mc.index[0]], '규칙4_시총상위5': list(mc.index[:5]), '규칙1_ROIC': [], '규칙2_ROIC저부채': []}
    if len(q):
        out['규칙1_ROIC'] = list(q['median'].sort_values(ascending=False).index)
        sc = q['median'].rank(ascending=False) + (q.debt.fillna(0) / q.equity).rank()
        out['규칙2_ROIC저부채'] = list(pd.DataFrame({'s': sc, 'r': -q['median']}).sort_values(['s', 'r']).index)
    out['_roic'] = q['median']
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
    months = pd.date_range('2011-01-01', '2026-11-01', freq='MS')
    PK = {t: v for t in months if (v := picks(t))}
    hist = pd.DataFrame([{'월': t.date(), **{r: ','.join(f'{c}' + (f'({v["_roic"][c]:.0%})' if r < '규칙3' else '') for c in v[r][:(5 if r == '규칙4_시총상위5' else 1)]) for r in RULES}}
                         for t, v in PK.items()])
    hist.to_csv(OUT / 'pick_us_history.csv', index=False, encoding='utf-8-sig')
    if len(sys.argv) > 1 and sys.argv[1] == 'picks':
        print(hist[hist.월.astype(str).str[5:7].isin(['01', '07'])].to_string(index=False)); sys.exit()

    spy, irx, ndx = K.yget('SPY'), K.yget('^IRX'), K.yget('^NDX')
    X = adj.copy(); X['NDX'] = ndx
    X = X[X.index >= '2005-01-01']
    S = spy.reindex(X.index).ffill().dropna(); X = X.loc[S.index]
    for c in X:
        s = X[c].dropna()
        if len(s): X[c] = X[c].ffill().where((X.index >= s.index[0]) & (X.index <= s.index[-1]))
    V = np.log(X).diff().rolling(252, min_periods=200).std() * np.sqrt(252)
    jr = X.pct_change(fill_method=None).abs()
    for c in X:
        bad = jr.index[jr[c] > 0.5]
        if len(bad): print('일간 50% 초과', c, [str(b.date()) for b in bad[:5]])

    def pf_(rule):
        return lambda d: PK.get(pd.Timestamp(d.year, d.month, 1), {}).get(rule, []) if rule != 'NDX' else ['NDX']
    rows, logs, rolls = [], [], []
    s0, s1 = pd.Timestamp('2011-01-03'), X.index[-1]
    for rule in RULES + ('NDX',):
        slots = 5 if rule == '규칙4_시총상위5' else 1
        pf = pf_(rule)
        v, w, lg = K.sim(S, X, V, pf, slots, s0, s1)
        sp = S.loc[v.index] / S.loc[v.index[0]]
        fx_ = K.fixed(S, X, pf, slots, w.mean(), v.index)
        st, sps, fxs = K.stats(v, irx), K.stats(sp, irx), K.stats(fx_, irx)
        done = lg[lg.끝.notna()]
        rows.append(dict(규칙=rule, CAGR=st['CAGR'], Sharpe=st['Sharpe'], MDD=st['MDD'], 고정CAGR=fxs['CAGR'], 고정Sharpe=fxs['Sharpe'],
                         SP_CAGR=sps['CAGR'], SP_Sharpe=sps['Sharpe'], 평균비중=w.mean(), 최대비중=w.max(), 사이클=len(done), 평균단계=done.단계.mean(),
                         vsSP_4억=(v.iloc[-1] - sp.iloc[-1]) * 4e8, vs고정_4억=(v.iloc[-1] - fx_.iloc[-1]) * 4e8))
        lg['규칙'] = rule; logs.append(lg)
        for yrs in (3, 5):
            for d in pd.date_range(s0, s1 - pd.DateOffset(years=yrs), freq='QS'):
                e = d + pd.DateOffset(years=yrs)
                vv, ww_, _ = K.sim(S, X, V, pf, slots, d, e)
                spp = S.loc[vv.index[-1]] / S.loc[vv.index[0]]
                fxx = K.fixed(S, X, pf, slots, ww_.mean(), vv.index).iloc[-1]
                rolls.append(dict(창=f'{yrs}년', 규칙=rule, 시작=d.date(), vsSP=(vv.iloc[-1] - spp) * 4e8, vs고정=(vv.iloc[-1] - fxx) * 4e8))
        print('완료', rule, flush=True)
    R = pd.DataFrame(rows); L = pd.concat(logs); RO = pd.DataFrame(rolls)
    R.to_csv(OUT / 'pick_us_summary.csv', index=False, encoding='utf-8-sig')
    L.to_csv(OUT / 'pick_us_cycles.csv', index=False, encoding='utf-8-sig')
    RO.to_csv(OUT / 'pick_us_roll.csv', index=False, encoding='utf-8-sig')
    print(R.to_string(float_format=lambda x: f'{x:,.3f}'))
    print(RO.groupby(['창', '규칙']).agg(n=('vsSP', 'size'), SP이김=('vsSP', lambda s: (s > 0).mean()), 평균=('vsSP', 'mean'), 최악=('vsSP', 'min'),
                                       고정이김=('vs고정', lambda s: (s > 0).mean()), 평균vs고정=('vs고정', 'mean')).to_string(float_format=lambda x: f'{x:,.2f}'))
