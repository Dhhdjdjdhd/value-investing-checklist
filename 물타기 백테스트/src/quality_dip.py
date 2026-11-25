# 초우량주 '빠지면 진입, 더 빠지면 더 진입' (2026-11-25, 사용자 아이디어)
# 규칙(사전 고정):
#  - 평소엔 전액 S&P. 종목이 52주 고점 대비 d1 하락하면 진입 시작(그 고점=기준). 이후 기준 대비 단계별 추가.
#  - 사다리: 기준 대비 −20/−30/−40/−50/−60%, 금액 1:1:2:4:8 (합계 = 종목당 한도 5,000만 = 4억의 12.5%)
#  - 청산 3안: 평단+20% / 기준 고점 회복 / 안 팔고 계속 보유
#  - 비교: S&P만(4억). 결과 = 최종 금액 차이(만원). 비용 편도 0.1%×2.
#  - 묶음 A(2000-01 시점 '초우량'으로 통하던 대형주) vs 묶음 B(지금 기준 초우량: 사후 선택이라 상한선)
#    ※ A에도 엔론·월드컴·루슨트처럼 상장폐지된 종목은 빠져 있어 실제보다 좋게 나옴
import json, urllib.request, numpy as np, pandas as pd
OUT = r'E:/value-investing-checklist/물타기 백테스트/results/'
def get(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    q = r['indicators'].get('adjclose', [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q, index=pd.to_datetime(r['timestamp'], unit='s').normalize()).dropna().sort_index().groupby(level=0).last()
spy = get('SPY')
BASK = {'A_2000우량': (['GE', 'MSFT', 'CSCO', 'INTC', 'WMT', 'XOM', 'PFE', 'KO', 'MRK', 'JNJ', 'IBM', 'ORCL', 'PG', 'C', 'AIG', 'HD', 'BAC', 'BMY'], '2000-01-03'),
        'B_현재우량(사후)': (['MSFT', 'GOOGL', 'MA', 'V', 'AAPL', 'COST', 'UNH', 'ADBE', 'ASML', 'SPGI'], '2009-01-02')}
LV = [0.20, 0.30, 0.40, 0.50, 0.60]; WT = np.array([1, 1, 2, 4, 8], float); CAP, TOT, C = 5000, 40000, 0.001  # 만원

def sim(df, exit_):
    X, S = df.x.values, df.s.values; hi = df.x.rolling(252, min_periods=1).max().values
    su = TOT / S[0]; xu = 0.0; inv = 0.0; k = 0; ref = None; amts = CAP * WT / WT.sum()
    trades = 0; worst = 0.0; maxinv = 0.0
    for i in range(len(X)):
        p = X[i]
        if ref is None:
            if p <= hi[i] * (1 - LV[0]): ref = hi[i]; k = 0
            else: continue
        if xu > 0:
            avg = inv / xu
            hit = (exit_ == 'avg20' and p >= avg * 1.2) or (exit_ == 'ref' and p >= ref)
            if hit:
                su += xu * p * (1 - 2 * C) / S[i]; xu = 0; inv = 0; ref = None; trades += 1; continue
        while k < len(LV) and p <= ref * (1 - LV[k]):
            a = min(amts[k], su * S[i]); su -= a / S[i]; xu += a * (1 - 2 * C) / p; inv += a; k += 1
        if xu > 0: worst = min(worst, xu * p - inv); maxinv = max(maxinv, inv)
    end = su * S[-1] + xu * X[-1]; sp = TOT * S[-1] / S[0]
    return end - sp, trades, worst, maxinv, (xu * X[-1] - inv) if xu > 0 else 0.0, k if xu > 0 else 0

rows = []
for bn, (tks, st) in BASK.items():
    for t in tks:
        x = get(t)
        df = pd.concat([x.rename('x'), spy.rename('s')], axis=1).dropna()
        df = df[df.index >= st]
        hold = TOT * 0 + (CAP * df.x.iloc[-1] / df.x.iloc[0] + (TOT - CAP) * df.s.iloc[-1] / df.s.iloc[0]) - TOT * df.s.iloc[-1] / df.s.iloc[0]
        for ex in ('avg20', 'ref', 'hold'):
            d, tr, worst, mi, open_pl, kk = sim(df, ex)
            rows.append(dict(묶음=bn, 종목=t, 청산=ex, vsSP=d, 완료사이클=tr, 최악평가손=worst, 최대투입=mi, 현재평가손익=open_pl, 현재단계=kk, 처음부터5천보유vsSP=hold))
R = pd.DataFrame(rows); R.to_csv(OUT + 'quality_dip.csv', index=False)
pd.set_option('display.width', 250)
print(R.to_string(float_format=lambda v: f'{v:,.0f}'))
print('\n== 묶음 요약 (만원, S&P만 대비)')
print(R.groupby(['묶음', '청산']).agg(종목수=('vsSP', 'size'), 이긴비율=('vsSP', lambda v: (v > 0).mean()), 평균=('vsSP', 'mean'), 중앙=('vsSP', 'median'),
                                   최악=('vsSP', 'min'), 최고=('vsSP', 'max'), 최악평가손=('최악평가손', 'min'), 처음부터보유평균=('처음부터5천보유vsSP', 'mean')).to_string(float_format=lambda v: f'{v:,.2f}'))
