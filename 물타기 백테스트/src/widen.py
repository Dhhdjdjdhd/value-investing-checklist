import json, urllib.request, pandas as pd, numpy as np
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    s=pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index(); return s[s>0]
AMT=[100,100,200,400,800,1600,3200,6400]
SCHED={
 'C  10/15/20/25/30/35/40':[.10,.15,.20,.25,.30,.35,.40],
 'D1 10/15/22/30/40/50/60':[.10,.15,.22,.30,.40,.50,.60],
 'D2 10/20/30/40/50/60/70':[.10,.20,.30,.40,.50,.60,.70],
 'D3 10/15/25/35/45/55/65':[.10,.15,.25,.35,.45,.55,.65],
 'D4 10/20/30/45/60/70/80':[.10,.20,.30,.45,.60,.70,.80]}
def sim(X,S,lv,tgt=0.05,capital=40000):
    su=capital/S[0]; xu=0.; inv=0.
    def buy(i,a):
        nonlocal su,xu,inv
        su-=a/S[i]; xu+=a/X[i]; inv+=a
    p0=X[0]; buy(0,AMT[0]); k=1
    for i in range(1,len(X)):
        p=X[i]
        if p>=inv/xu*(1+tgt):
            su+=xu*p/S[i]; xu=0; inv=0; p0=p; buy(i,AMT[0]); k=1; continue
        if k<8 and p<=p0*(1-lv[k-1]): buy(i,AMT[k]); k+=1
    return su*S[-1]+xu*X[-1]-capital*S[-1]/S[0], k, inv, xu*X[-1]-inv
spy=get('SPY'); fx=get('KRW=X'); fx=fx[(fx>800)&(fx<2000)]; spyk=(spy*fx.reindex(spy.index).ffill()).dropna()
A={'SOX':('^SOX',spy,'1995-01-01'),'코스피':('^KS11',spyk,'2004-01-01'),'삼성전자':('005930.KS',spyk,'2004-01-01')}
for nm,c in {'한국전력':'015760.KS','POSCO':'005490.KS','SK텔레콤':'017670.KS','국민은행':'105560.KS','LG디스플레이':'034220.KS','현대차':'005380.KS','KT':'030200.KS','LG전자':'066570.KS'}.items():
    A[nm]=(c,spyk,'2005-01-01')
rows=[]; now=[]
for nm,(sym,base,st) in A.items():
    df=pd.concat([get(sym).rename('x'),base.rename('s')],axis=1).dropna()
    for sn,lv in SCHED.items():
        for d in pd.date_range(st,'2021-10-01',freq='MS'):
            w=df[(df.index>=d)&(df.index<d+pd.Timedelta(days=5*365))]
            if len(w)<1000: continue
            diff,_,_,_=sim(w.x.values,w.s.values,lv)
            rows.append(dict(name=nm,sched=sn,diff=diff))
        full=df[df.index>=st]; _,k,inv,op=sim(full.x.values,full.s.values,lv)
        now.append(dict(name=nm,sched=sn,steps_now=k,inv_now=inv,pnl_now=round(op)))
R=pd.DataFrame(rows); N=pd.DataFrame(now); pd.set_option('display.width',250)
R['grp']=np.where(R.name.isin(['SOX','코스피']),R.name,'한국 대형주 9')
g=R.groupby(['grp','sched'])['diff'].agg(win=lambda v:(v>0).mean(),mean='mean',p5=lambda v:v.quantile(.05),worst='min')
print(g.to_string(float_format=lambda v:f'{v:,.2f}'))
print(N.pivot(index='name',columns='sched',values='pnl_now').to_string())
print(N.pivot(index='name',columns='sched',values='steps_now').to_string())
R.to_csv(r'E:/value-investing-checklist/물타기 백테스트/results/widen_episodes.csv',index=False)
