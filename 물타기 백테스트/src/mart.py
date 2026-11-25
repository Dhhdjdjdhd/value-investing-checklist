# 마틴게일식 물타기 백테스트 (빠른 확인용)
import sys, numpy as np, pandas as pd, json, urllib.request
ROOT=sys.argv[1]  # 체크리스트 검증 폴더
OUT=sys.argv[2]
ann=pd.read_parquet(f'{ROOT}/data/panel/annual_first.parquet')[['cik','ticker','avail','roic_med5']]
mcap=pd.read_parquet(f'{ROOT}/data/panel/monthly_mcap_first.parquet')
comp=pd.read_csv(f'{ROOT}/data/sec/companies.csv',dtype={'cik':int})
tick={c:str(t).split(',')[0].strip() for c,t in zip(comp.cik,comp.tickers) if isinstance(t,str)}
def load(t):
    try:
        d=pd.read_csv(f'{ROOT}/data/prices/{t}.csv',parse_dates=['date']).set_index('date').sort_index()
        d=d[~d.index.duplicated(keep='last')]; s=d.adj_close.dropna(); return s[s>0]
    except Exception: return None
# SPY
u='https://query1.finance.yahoo.com/v8/finance/chart/SPY?period1=725846400&period2=1800000000&interval=1d&events=div'
r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
spy=pd.Series(r['indicators']['adjclose'][0]['adjclose'],index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
print('spy',spy.index[0],spy.index[-1],len(spy),flush=True)
AMT=[20,20,40,80,160,320,640,1280]
def levels(kind,n=8):
    if kind=='A': return [0]+[0.10]*(n-1)            # 직전 매수가 대비
    if kind=='B': return [0]+[0.10+0.05*i for i in range(n-1)]
    if kind=='C': return None
def run(px,kind,cap,target,days_max):
    p0=px.iloc[0]; buys=[(0,p0)]; units=AMT[0]/p0; inv=AMT[0]
    last=p0; gaps=levels(kind)
    def trig(k):  # k번째(0부터) 추가매수 가격
        if kind=='C': return p0*(1-(0.10+0.05*(k-1)))
        return last*(1-gaps[k])
    k=1; vals=px.values; idx=px.index
    for i in range(1,len(vals)):
        p=vals[i]
        if p>=inv/units*(1+target):
            return dict(win=1,days=(idx[i]-idx[0]).days,steps=k,inv=inv,pnl=units*p-inv,end=idx[i])
        if k<cap and p<=trig(k):
            units+=AMT[k]/p; inv+=AMT[k]; last=p; k+=1
    return dict(win=0,days=(idx[-1]-idx[0]).days,steps=k,inv=inv,pnl=units*vals[-1]-inv,end=idx[-1])
dates=[pd.Timestamp(f'{y}-{m:02d}-01') for y in range(2010,2022) for m in (1,7)]
rows=[]
cache={}
for d in dates:
    a=ann[ann.avail<=d].sort_values('avail').groupby('cik').tail(1)
    per=pd.Period(d,'M')-1
    mc=mcap.loc[per] if per in mcap.index else None
    if mc is None: continue
    big=set(mc[mc>=10e9].index)
    for _,x in a.iterrows():
        if x.cik not in big: continue
        q='quality' if (pd.notna(x.roic_med5) and x.roic_med5>=0.15) else 'other'
        t=x.ticker if isinstance(x.ticker,str) else tick.get(x.cik)
        if not isinstance(t,str): continue
        if t not in cache: cache[t]=load(t)
        s=cache[t]
        if s is None: continue
        w=s[(s.index>=d)&(s.index<d+pd.Timedelta(days=5*365))]
        if len(w)<1000: continue
        sp=spy[(spy.index>=w.index[0])]
        rows.append(dict(date=d,t=t,q=q,kind='BH',cap=0,tgt=0,reserve=1,spy_on_reserve=spy.asof(w.index[-1])/spy.asof(w.index[0])-1,win=int(w.iloc[-1]>w.iloc[0]),days=(w.index[-1]-w.index[0]).days,steps=0,inv=1,pnl=w.iloc[-1]/w.iloc[0]-1,end=w.index[-1]))
        for kind in 'ABC':
            for cap in (6,8):
                for tgt in (0.05,0.10,0.20):
                    o=run(w,kind,cap,tgt,None)
                    res=sum(AMT[:cap])
                    spyret=spy.asof(o['end'])/spy.asof(w.index[0])-1
                    rows.append(dict(date=d,t=t,q=q,kind=kind,cap=cap,tgt=tgt,reserve=res,spy_on_reserve=res*spyret,**o))
    print('done',d.date(),len(rows),flush=True)
R=pd.DataFrame(rows); R.to_csv(OUT,index=False); print('saved',len(R))
