import json, urllib.request, pandas as pd, numpy as np
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
x=get('^SOX'); s=get('SPY'); irx=get('^IRX')
df=pd.concat([x.rename('x'),s.rename('s')],axis=1).dropna(); df=df[df.index>='1995-01-01']
rf=(irx.reindex(df.index).ffill().fillna(3)/100/252)
def run(base,lv,tgt=0.05,capital=40000):
    AMT=[base*m for m in [1,1,2,4,8,16,32,64]]
    X=df.x.values; S=df.s.values; su=capital/S[0]; xu=0.; inv=0.; val=np.empty(len(X)); sox_w=np.empty(len(X))
    p0=X[0]; su-=AMT[0]/S[0]; xu+=AMT[0]/X[0]; inv+=AMT[0]; k=1
    for i in range(len(X)):
        p=X[i]
        if i>0:
            if p>=inv/xu*(1+tgt):
                su+=xu*p/S[i]; xu=0; inv=0; p0=p; su-=AMT[0]/S[i]; xu+=AMT[0]/p; inv=AMT[0]; k=1
            elif k<len(lv)+1 and p<=p0*(1-lv[k-1]):
                su-=AMT[k]/S[i]; xu+=AMT[k]/p; inv+=AMT[k]; k+=1
        val[i]=su*S[i]+xu*p; sox_w[i]=xu*p/val[i]
    return pd.Series(val,index=df.index), sox_w
def stats(v):
    r=v.pct_change().dropna(); ex=r-rf.reindex(r.index)
    yrs=len(r)/252; cagr=(v.iloc[-1]/v.iloc[0])**(1/yrs)-1
    sh=ex.mean()/ex.std()*np.sqrt(252); vol=r.std()*np.sqrt(252); mdd=(v/v.cummax()-1).min()
    return cagr,vol,sh,mdd
C=[.10,.15,.20,.25,.30,.35,.40]; G2=[1-0.8**k for k in range(1,8)]
spy=df.s/df.s.iloc[0]*40000
rows=[('S&P만',)+stats(spy)+(0,)]
for nm,b,lv in [('C 20만',20,C),('C 40만',40,C),('C 100만',100,C),('직전대비 −20% 100만',100,G2)]:
    v,w=run(b,lv); rows.append((nm,)+stats(v)+(w.max(),))
# 비교: 같은 평균 반도체 비중을 고정 보유(매년 리밸런스 없이 고정 비중 근사: 일간 리밸런스)
for wt in (0.02,0.05,0.10):
    r=(1-wt)*df.s.pct_change()+wt*df.x.pct_change(); v=(1+r.fillna(0)).cumprod()*40000
    rows.append((f'SOX 고정 {int(wt*100)}% + S&P',)+stats(v)+(wt,))
R=pd.DataFrame(rows,columns=['전략','연수익','변동성','샤프','최대낙폭','최대 SOX 비중'])
print('기간',df.index[0].date(),'~',df.index[-1].date())
print(R.to_string(index=False,float_format=lambda v:f'{v:.4f}'))
