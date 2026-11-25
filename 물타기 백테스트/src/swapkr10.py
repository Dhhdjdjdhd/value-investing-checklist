# S&P에 전액 → SOX 하락 시 S&P를 팔아 물타기 → 평단+목표면 SOX 팔아 S&P 복귀, 즉시 새 사이클
import json, urllib.request, numpy as np, pandas as pd
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()

import sys as _s
NAMES={'005930.KS':'삼성전자','015760.KS':'한국전력','005490.KS':'POSCO','017670.KS':'SK텔레콤','105560.KS':'국민은행(KB)','034220.KS':'LG필립스LCD','005380.KS':'현대차','030200.KS':'KT','066570.KS':'LG전자'}
spy=get('SPY'); fx=get('KRW=X'); fx=fx[(fx>800)&(fx<2000)]
spy=(spy*fx.reindex(spy.index).ffill()).dropna()
AMT=[100,100,200,400,800,1600,3200,6400]
def sim(w,kind,cap,tgt,capital):
    X=w.x.values; S=w.s.values
    su=capital/S[0]; xu=0.0; inv=0.0; k=0; last=None; p0=None; cycles=0; maxx=0; shortfall=0
    def buy(i,amt):
        nonlocal su,xu,inv,shortfall
        need=amt/S[i]
        if need>su: shortfall+=1; amt=su*S[i]; need=su
        su-=need; xu+=amt/X[i]; inv+=amt
    p0=X[0]; last=X[0]; buy(0,AMT[0]); k=1
    for i in range(1,len(X)):
        p=X[i]
        if xu>0 and p>=inv/xu*(1+tgt):
            su+=xu*p/S[i]; xu=0; inv=0; cycles+=1
            p0=p; last=p; buy(i,AMT[0]); k=1; continue
        if k<cap:
            t=p0*(1-(0.10+0.05*(k-1))) if kind=='C' else last*(1-(0.10 if kind=='A' else 0.10+0.05*(k-1)))
            if p<=t: buy(i,AMT[k]); last=p; k+=1
        maxx=max(maxx,xu*p)
    end=su*S[-1]+xu*X[-1]
    return end, capital*S[-1]/S[0], capital*X[-1]/X[0], cycles, maxx, shortfall
rows=[]
for sym,nm in NAMES.items():
    x=get(sym); x=x[x>0]
    df=pd.concat([x.rename('x'),spy.rename('s')],axis=1).dropna()
    for d in pd.date_range('2005-01-01','2021-10-01',freq='MS'):
        w=df[(df.index>=d)&(df.index<d+pd.Timedelta(days=5*365))]
        if len(w)<1000: continue
        for cap in (6,8):
            for tgt in (0.05,0.10):
                end,spyend,xend,cyc,maxx,sf=sim(w,'C',cap,tgt,40000)
                rows.append(dict(name=nm,date=d,cap=cap,tgt=tgt,diff=end-spyend,bh_vs_spy=xend-spyend,cycles=cyc,maxx=maxx))
    print('done',nm,flush=True)
R=pd.DataFrame(rows)
R.to_csv(r'E:/value-investing-checklist/물타기 백테스트/results/swap100_C_kr2004top10.csv',index=False)
pd.set_option('display.width',250)
def agg(g): return pd.Series(dict(n=len(g),win=(g['diff']>0).mean(),mean=g['diff'].mean(),med=g['diff'].median(),worst=g['diff'].min(),best=g['diff'].max(),bh_vs_spy=g.bh_vs_spy.mean(),cyc=g.cycles.mean()))
for cap,tgt in [(8,0.05),(8,0.10),(6,0.05)]:
    x=R[(R.cap==cap)&(R.tgt==tgt)]
    print('== cap',cap,'tgt',tgt)
    print(x.groupby('name').apply(agg).sort_values('mean').to_string(float_format=lambda v:f'{v:,.2f}'))
    print('ALL', agg(x).round(2).to_dict())
    ex=x[x.name!='삼성전자']; print('ALL ex-Samsung', agg(ex).round(2).to_dict())
