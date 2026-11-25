# S&P에 전액 → SOX 하락 시 S&P를 팔아 물타기 → 평단+목표면 SOX 팔아 S&P 복귀, 즉시 새 사이클
import json, urllib.request, numpy as np, pandas as pd
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
import sys as _s
sox=get('^KS11'); spy=get('SPY')
if _s.argv[1]=='fx':
    fx=get('KRW=X'); fx=fx[(fx>800)&(fx<2000)]
    spy=(spy*fx.reindex(spy.index).ffill()).dropna()
print('kospi',sox.index[0].date(),'spy',spy.index[0].date(),flush=True)
df=pd.concat([sox.rename('x'),spy.rename('s')],axis=1).dropna()
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
for d in pd.date_range(max(df.index[0],pd.Timestamp('1995-01-01')),'2021-10-01',freq='MS'):
    w=df[(df.index>=d)&(df.index<d+pd.Timedelta(days=5*365))]
    if len(w)<1000: continue
    for kind in 'C':
        for cap in (6,8):
            for tgt in (0.03,0.05,0.10):
                for capital in (40000,):  # 예비금=사다리 총액 / 4억 전체
                    end,spyend,soxend,cyc,maxx,sf=sim(w,kind,cap,tgt,capital)
                    rows.append(dict(date=d,kind=kind,cap=cap,tgt=tgt,capital=capital,end=end,spy=spyend,diff=end-spyend,cycles=cyc,maxsox=maxx,short=sf))
R=pd.DataFrame(rows)
R['diff_pct']=R['diff']/R['capital']
pd.set_option('display.width',250)
g=R.groupby(['capital','kind','cap','tgt']).agg(n=('diff','size'),win_vs_spy=('diff',lambda v:(v>0).mean()),mean_diff=('diff','mean'),med_diff=('diff','median'),p5=('diff',lambda v:v.quantile(.05)),worst=('diff','min'),best=('diff','max'),diff_pct=('diff_pct','mean'),cycles=('cycles','mean'),shortfall=('short','mean'))
print(g.to_string(float_format=lambda x:f'{x:,.3f}'))
x=R[(R.capital==40000)&(R.kind=='C')&(R.cap==8)&(R.tgt==0.05)]
print(x.groupby(x.date.dt.year).agg(diff=('diff','mean'),worst=('diff','min'),cyc=('cycles','mean'),maxsox=('maxsox','max')).to_string(float_format=lambda v:f'{v:,.1f}'))
print(R[(R.cap==8)&(R.tgt==0.05)].nsmallest(5,'diff')[['date','diff','cycles','maxsox']].to_string())
R.to_csv(r'E:/value-investing-checklist/물타기 백테스트/results/swap100_C_kospi_'+_s.argv[1]+'.csv',index=False)
