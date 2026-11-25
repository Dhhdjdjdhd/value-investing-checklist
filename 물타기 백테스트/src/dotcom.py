import json, urllib.request, pandas as pd
def get(sym):
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2=1800000000&interval=1d'
    r=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))['chart']['result'][0]
    q=r['indicators'].get('adjclose',[{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    return pd.Series(q,index=pd.to_datetime(r['timestamp'],unit='s').normalize()).dropna().sort_index()
x=get('^SOX'); s=get('SPY'); df=pd.concat([x.rename('x'),s.rename('s')],axis=1).dropna()
df=df[(df.index>='2000-03-01')&(df.index<'2005-03-01')]
AMT=[100,100,200,400,800,1600,3200,6400]; lv=[.10,.15,.20,.25,.30,.35,.40]
X=df.x.values; S=df.s.values; ix=df.index
su=40000/S[0]; xu=0; inv=0
def buy(i,a):
    global su,xu,inv
    su-=a/S[i]; xu+=a/X[i]; inv+=a
p0=X[0]; t0=ix[0]; buy(0,100); k=1; cyc=[]
peak=x[:ix[0]].max()
for i in range(1,len(X)):
    p=X[i]
    if p>=inv/xu*1.05:
        pnl=xu*p-inv; cyc.append((t0.date(),ix[i].date(),k,inv,round(pnl),round(p),round(p/peak-1,2)))
        su+=xu*p/S[i]; xu=0; inv=0; p0=p; t0=ix[i]; buy(i,100); k=1; continue
    if k<8 and p<=p0*(1-lv[k-1]): buy(i,AMT[k]); k+=1
end=su*S[-1]+xu*X[-1]; bh=40000*S[-1]/S[0]
print('SOX 2000-03 → 2005-02. SOX 고점',round(peak),' 저점',round(df.x.min()),df.x.idxmin().date())
print('사이클 수',len(cyc),' 단계 4 이상인 사이클:')
for c in cyc:
    if c[2]>=4: print('  시작',c[0],'끝',c[1],'단계',c[2],'투입',c[3],'만, 이익',c[4],'만, 끝날 때 SOX',c[5],'(고점 대비',c[6],')')
print('합계 사이클 이익',sum(c[4] for c in cyc),'만 / 열린 사이클 단계',k,'투입',inv,'평가손익',round(xu*X[-1]-inv))
print('최종: 전략',round(end),'만, S&P만',round(bh),'만, 차이',round(end-bh),'만')
