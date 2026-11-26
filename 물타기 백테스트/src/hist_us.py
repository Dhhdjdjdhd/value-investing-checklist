# 2000·2008년 포함 시험 — 규칙3(시총 1위)·규칙4(시총 상위 5 분산), 미국 1997~2026 (2026-11-26)
# 사전 규칙(성과 보기 전 고정):
#  - 시총: companiesmarketcap.com 월별 시총 이력(1996~, 당시 값). 직전 월말 기준 상위 5개 / 1위
#    (SEC XBRL은 2010년부터라 2000·2008 시험 불가 → 외부 자료 사용. GE 1999말 509.9B·2000말 476.2B로 위키 FT 표와 일관 확인)
#  - 후보: us_data.py 116개 + 버크셔·비자 중 companiesmarketcap에 페이지가 있는 회사(지금 상장된 회사만)
#    → 루슨트·월드컴·옛 AT&T 등 상장폐지 회사는 빠짐(상위 5위권에 든 적은 없는 것으로 봄, 미검증)
#  - 사다리·한도·비용: pick_us.py와 같음(추가 8 선택안). 한도 12.5 / 25 / 50 / 100% 비교
#  - 가격: Yahoo adjclose(배당 포함), 평소 자금 SPY
import sys, json, re, time, urllib.request
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pick_kr as K  # noqa: E402
from us_data import CIKS  # noqa: E402

D = HERE.parent / 'data_us'; OUT = HERE.parent / 'results'
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
ALIAS = {'GOOGL': 'GOOG'}


def fetch_cmc(slugs):
    rows = {}
    for t, s in slugs.items():
        b = urllib.request.urlopen(urllib.request.Request(f'https://companiesmarketcap.com/{s}/marketcap/', headers=H), timeout=30).read().decode('utf-8', 'ignore')
        m = re.search(r'data\s*=\s*(\[\{"d".*?\}\])', b, flags=re.S)
        if not m: print('시총 이력 없음', t, s); continue
        d = json.loads(m.group(1))
        rows[t] = pd.Series([x['m'] * 1e5 for x in d], index=pd.to_datetime([x['d'] for x in d], unit='s').to_period('M'))
        time.sleep(0.7)
    return pd.DataFrame(rows).groupby(level=0).last()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
    f = D / 'cmc_mcap.parquet'
    if not f.exists():
        allslug = json.loads((HERE.parent / 'data_us' / 'cmc_slugs.json').read_text())
        want = list(CIKS) + ['V']
        slugs = {t: allslug.get(ALIAS.get(t, t)) for t in want}
        print('slug 없음:', [t for t, s in slugs.items() if not s])
        mc = fetch_cmc({t: s for t, s in slugs.items() if s}); mc.index = mc.index.astype(str); mc.to_parquet(f)
    mc = pd.read_parquet(f); mc.index = pd.PeriodIndex(mc.index, freq='M')
    # 점검: 연말 상위 5
    for y in (1996, 1999, 2000, 2002, 2007, 2008, 2010, 2015, 2020, 2025):
        s = mc.loc[pd.Period(f'{y}-12', 'M')].dropna().sort_values(ascending=False).head(6) / 1e9
        print(y, ', '.join(f'{k}:{v:,.0f}' for k, v in s.items()))

    # 가격
    px_f = D / 'adj_full.parquet'
    if not px_f.exists():
        P = {}
        for t in mc.columns:
            try: P[t] = K.yget(t)
            except Exception as e: print('가격 실패', t, e)
        pd.DataFrame(P).to_parquet(px_f)
    X = pd.read_parquet(px_f)
    spy, irx = K.yget('SPY'), K.yget('^IRX')
    X = X[X.index >= '1995-01-01']; S = spy.reindex(X.index).ffill().dropna(); X = X.loc[S.index]
    for c in X:
        s = X[c].dropna()
        if len(s): X[c] = X[c].ffill().where((X.index >= s.index[0]) & (X.index <= s.index[-1]))
    V = np.log(X).diff().rolling(252, min_periods=200).std() * np.sqrt(252)
    K.NAME = pd.Series({t: t for t in X.columns})

    rank = {}
    for per in mc.index:
        s = mc.loc[per].dropna(); s = s[s.index.isin(X.columns)]
        rank[per] = list(s.sort_values(ascending=False).index[:5])
    pf3 = lambda d: rank.get((pd.Timestamp(d.year, d.month, 1) - pd.offsets.MonthBegin(1)).to_period('M'), [])[:1]
    pf4 = lambda d: rank.get((pd.Timestamp(d.year, d.month, 1) - pd.offsets.MonthBegin(1)).to_period('M'), [])
    hist = pd.DataFrame([{'월': str(p), '상위5': ','.join(v)} for p, v in rank.items()]); hist.to_csv(OUT / 'hist_us_top5.csv', index=False)

    s0, s1 = pd.Timestamp('1997-01-02'), X.index[-1]
    rows, logs = [], []
    for rule, pf, slots in (('규칙3_시총1위', pf3, 1), ('규칙4_시총상위5', pf4, 5)):
        for bud in (0.125, 0.25, 0.5, 1.0):
            K.BUD = bud
            v, w, lg = K.sim(S, X, V, pf, slots, s0, s1)
            sp = S.loc[v.index] / S.loc[v.index[0]]; fx = K.fixed(S, X, pf, slots, w.mean(), v.index)
            st, sps, fxs = K.stats(v, irx), K.stats(sp, irx), K.stats(fx, irx)
            rr = {}
            for yrs in (5, 3):
                acc = []
                for d in pd.date_range(s0, s1 - pd.DateOffset(years=yrs), freq='QS'):
                    vv, _, _ = K.sim(S, X, V, pf, slots, d, d + pd.DateOffset(years=yrs))
                    acc.append(((vv.iloc[-1] - S.loc[vv.index[-1]] / S.loc[vv.index[0]]) * 4e4, d))
                a = np.array([x[0] for x in acc]); rr[yrs] = (a, [x[1] for x in acc])
            a5, a3 = rr[5][0], rr[3][0]
            # 기간별: 1997~2010 / 2011~
            sub = {}
            for nm, (b0, b1) in {'97~10': ('1997-01-01', '2010-12-31'), '11~': ('2011-01-01', '2026-12-31')}.items():
                vv = v.loc[b0:b1]; ss = S.loc[vv.index]
                sub[nm] = ((vv.iloc[-1] / vv.iloc[0]) ** (252 / len(vv)) - (ss.iloc[-1] / ss.iloc[0]) ** (252 / len(ss))) * 100
            rows.append({'규칙': rule, '한도': f'{bud:.1%}', 'CAGR': st['CAGR'], 'S&P CAGR': sps['CAGR'], '차이%p': (st['CAGR'] - sps['CAGR']) * 100,
                         '97~10 차이%p': sub['97~10'], '11~ 차이%p': sub['11~'], '고정보유 차이%p': (fxs['CAGR'] - sps['CAGR']) * 100,
                         'Sharpe': st['Sharpe'], 'S&P Sharpe': sps['Sharpe'], 'MDD': st['MDD'], 'S&P MDD': sps['MDD'], '평균비중': w.mean(), '최대비중': w.max(),
                         '5년 이김': (a5 > 0).mean(), '5년 평균(만)': a5.mean(), '5년 최악(만)': a5.min(), '5년 최악 시작': rr[5][1][a5.argmin()].date(),
                         '3년 이김': (a3 > 0).mean(), '3년 최악(만)': a3.min(), '3년 최악 시작': rr[3][1][a3.argmin()].date()})
            lg['규칙'], lg['한도'] = rule, bud; logs.append(lg)
            print('완료', rule, bud, flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / 'hist_us_summary.csv', index=False, encoding='utf-8-sig')
    pd.concat(logs).to_csv(OUT / 'hist_us_cycles.csv', index=False, encoding='utf-8-sig')
    print(R.T.to_string())
