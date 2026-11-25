import json, urllib.request, pandas as pd, numpy as np
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    s=pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index(); return s[s>0]
AMT=[100,100,200,400,800,1600,3200,6400]
def cycles(px,cap=8,tgt=0.05):
    X=px.values; ix=px.index; out=[]
    p0=X[0]; units=AMT[0]/p0; inv=AMT[0]; k=1; t0=ix[0]
    for i in range(1,len(X)):
        p=X[i]
        if p>=inv/units*(1+tgt):
            out.append(dict(steps=k,inv=inv,pnl=units*p-inv,days=(ix[i]-t0).days,start=t0)); p0=p; units=AMT[0]/p; inv=AMT[0]; k=1; t0=ix[i]; continue
        if k<cap and p<=p0*(1-(0.10+0.05*(k-1))):
            units+=AMT[k]/p; inv+=AMT[k]; k+=1
    open_=dict(steps=k,inv=inv,pnl=units*X[-1]-inv,days=(ix[-1]-t0).days,start=t0)
    return pd.DataFrame(out), open_
assets={'SOX':'^SOX','삼성전자':'005930.KS','POSCO':'005490.KS','국민은행(KB)':'105560.KS','현대차':'005380.KS','한국전력':'015760.KS','LG전자':'066570.KS','KT':'030200.KS','SK텔레콤':'017670.KS','LG디스플레이':'034220.KS','코스피':'^KS11'}
rows=[]
for nm,sym in assets.items():
    px=get(sym); px=px[px.index>='1995-01-01']
    c,o=cycles(px)
    dist=c.steps.value_counts(normalize=True).sort_index()
    rows.append(dict(name=nm,since=px.index[0].year,cycles=len(c),avg_steps=c.steps.mean(),
        s1=dist.get(1,0),s2=dist.get(2,0),s3=dist.get(3,0),s4_5=dist.get(4,0)+dist.get(5,0),s6_8=sum(dist.get(k,0) for k in (6,7,8)),
        max_steps=c.steps.max(),med_days=c.days.median(),max_days=c.days.max(),avg_inv=c.inv.mean(),
        open_steps=o['steps'],open_inv=o['inv'],open_pnl=round(o['pnl']),open_since=o['start'].date()))
R=pd.DataFrame(rows); pd.set_option('display.width',260)
print(R.to_string(index=False,float_format=lambda v:f'{v:,.2f}'))
