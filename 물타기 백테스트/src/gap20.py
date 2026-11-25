import json, urllib.request, pandas as pd, numpy as np
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
AMT=[100,100,200,400,800,1600,3200,6400]
def lev(kind):
    if kind=='C': return [.10,.15,.20,.25,.30,.35,.40]
    if kind=='G1': return [.20,.40,.60,.80]
    if kind=='G2': return [1-0.8**k for k in range(1,8)]
def sim(X,S,kind,tgt,capital=40000,stats=None):
    lv=lev(kind); cap=len(lv)+1
    su=capital/S[0]; xu=0.; inv=0.
    def buy(i,a):
        nonlocal su,xu,inv
        su-=a/S[i]; xu+=a/X[i]; inv+=a
    p0=X[0]; buy(0,AMT[0]); k=1; cyc=0; ks=[]; maxinv=0
    for i in range(1,len(X)):
        p=X[i]
        if p>=inv/xu*(1+tgt):
            ks.append(k); su+=xu*p/S[i]; xu=0; inv=0; p0=p; buy(i,AMT[0]); k=1; cyc+=1; continue
        if k<cap and p<=p0*(1-lv[k-1]): buy(i,AMT[k]); k+=1; maxinv=max(maxinv,inv)
    return su*S[-1]+xu*X[-1]-capital*S[-1]/S[0], cyc, ks, maxinv
x=get('^SOX'); s=get('SPY'); df=pd.concat([x.rename('x'),s.rename('s')],axis=1).dropna()
rows=[]
for kind in ['C','G1','G2']:
    for tgt in (0.05,0.10):
        allks=[]; 
        for d in pd.date_range('1995-01-01','2021-10-01',freq='MS'):
            w=df[(df.index>=d)&(df.index<d+pd.Timedelta(days=5*365))]
            diff,cyc,ks,mi=sim(w.x.values,w.s.values,kind,tgt); allks+=ks
            rows.append(dict(kind=kind,tgt=tgt,diff=diff,cyc=cyc,maxinv=mi))
        ks=pd.Series(allks); print(kind,tgt,'평균 단계',round(ks.mean(),2),'단계 분포',(ks.value_counts(normalize=True).sort_index()*100).round(1).to_dict())
R=pd.DataFrame(rows)
print(R.groupby(['kind','tgt']).agg(win=('diff',lambda v:(v>0).mean()),mean=('diff','mean'),med=('diff','median'),worst=('diff','min'),best=('diff','max'),cyc=('cyc','mean'),maxinv=('maxinv','max')).to_string(float_format=lambda v:f'{v:,.2f}'))
