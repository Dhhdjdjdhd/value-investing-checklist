import json, urllib.request, numpy as np, pandas as pd, sys
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=725846400&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
sox=get('^SOX'); spy=get('SPY')
print('sox',sox.index[0].date(),sox.index[-1].date(),len(sox),'last',sox.iloc[-1],'peak',sox.max())
AMT=[20,20,40,80,160,320,640,1280]
def run(px,kind,cap,target):
    p0=px.iloc[0]; units=AMT[0]/p0; inv=AMT[0]; last=p0; k=1
    v=px.values; ix=px.index
    for i in range(1,len(v)):
        p=v[i]
        if p>=inv/units*(1+target): return 1,(ix[i]-ix[0]).days,k,inv,units*p-inv,ix[i]
        if k<cap:
            t = p0*(1-(0.10+0.05*(k-1))) if kind=='C' else last*(1-(0.10 if kind=='A' else 0.10+0.05*(k-1)))
            if p<=t: units+=AMT[k]/p; inv+=AMT[k]; last=p; k+=1
    return 0,(ix[-1]-ix[0]).days,k,inv,units*v[-1]-inv,ix[-1]
starts=pd.date_range('1995-01-01','2021-10-01',freq='MS')
rows=[]
for d in starts:
    w=sox[(sox.index>=d)&(sox.index<d+pd.Timedelta(days=5*365))]
    if len(w)<1000: continue
    for kind in 'ABC':
        for cap in (6,8):
            for tgt in (0.05,0.10,0.20):
                win,days,k,inv,pnl,end=run(w,kind,cap,tgt)
                res=sum(AMT[:cap]); sr=spy.asof(end)/spy.asof(w.index[0])-1
                rows.append(dict(date=d,kind=kind,cap=cap,tgt=tgt,win=win,days=days,steps=k,inv=inv,pnl=pnl,reserve=res,spy=res*sr,bh=res*(w.asof(end)/w.iloc[0]-1)))
R=pd.DataFrame(rows); R.to_csv(sys.argv[1],index=False)
R['yrs']=(R.days/365.25).clip(lower=1/52)
def agg(g):
    ry=(g.reserve*g.yrs).sum()
    return pd.Series(dict(n=len(g),win=g.win.mean(),med_days_win=g.loc[g.win==1,'days'].median(),hit_cap=(g.steps==g.name[1]).mean(),
        avg_inv=g.inv.mean(),avg_pnl=g.pnl.mean(),avg_loss_if_lose=g.loc[g.win==0,'pnl'].mean(),worst=g.pnl.min(),
        ann_on_reserve=g.pnl.sum()/ry, sox_bh_ann=g.bh.sum()/ry, spy_ann=g.spy.sum()/ry))
pd.set_option('display.width',250)
print(R.groupby(['kind','cap','tgt']).apply(agg).to_string(float_format=lambda x:f'{x:,.3f}'))
x=R[(R.kind=='A')&(R.cap==8)&(R.tgt==0.10)]
print(x.groupby(x.date.dt.year).agg(win=('win','mean'),pnl=('pnl','mean'),inv=('inv','mean'),hitcap=('steps',lambda s:(s==8).mean())).to_string(float_format=lambda v:f'{v:.2f}'))
print(x.nsmallest(5,'pnl')[['date','steps','inv','pnl','days']].to_string())
