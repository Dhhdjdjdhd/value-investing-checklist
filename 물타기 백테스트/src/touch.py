import warnings; warnings.filterwarnings('ignore')
import json, urllib.request, numpy as np, pandas as pd
def get(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=-1000000000&period2=1800000000&interval=1d'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    return pd.Series(r['indicators']['quote'][0]['close'], index=pd.to_datetime(r['timestamp'], unit='s').normalize()).dropna().groupby(level=0).last()
sp = get('^GSPC'); fx = get('KRW=X'); fx = fx[(fx > 800) & (fx < 2000)]
krw = (sp * fx.reindex(sp.index).ffill()).dropna()
H = 105; TH = 20700 / 23805 - 1
for nm, s in [('S&P 달러 1950~', sp['1950':]), ('S&P 원화 2004~', krw['2004':])]:
    v = s.values; dd = s / s.cummax() - 1
    mins = np.array([v[i + 1:i + 1 + H].min() / v[i] - 1 for i in range(len(v) - H)])
    d = dd.values[:len(mins)]
    for lab, m in [('전체', np.ones(len(mins), bool)), ('고점 대비 -5~-12%일 때', (d <= -0.05) & (d >= -0.12))]:
        print(f'{nm} | {lab}: 5개월 안 {TH*100:.1f}% 터치 {np.mean(mins[m] <= TH)*100:.1f}% (n={m.sum()}) | -7.6%(22,000) 터치 {np.mean(mins[m] <= 22000/23805-1)*100:.1f}%')
    print('  현재 고점 대비', round(dd.iloc[-1] * 100, 1))
