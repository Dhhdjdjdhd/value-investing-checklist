import sys; sys.path.insert(0, r'E:/value-investing-checklist/대안전략 연구/src')
import pandas as pd, numpy as np
from alloc import build
D=build(); fx=D.fx; UN=D.un; HE=D.ru+D.carry; COST=0.001
ma={k:fx.rolling(k*12,min_periods=k*12).mean() for k in (5,10)}
def rule(enter_f, exit_f, maxm=24):
    st=[]; c=0; n=0; locked=False
    for i in range(len(fx)):
        en=enter_f(i); ex=exit_f(i)
        if en is None: st.append(0); continue
        f=fx.iloc[i]
        if locked and f<ex: locked=False
        if c==0 and not locked and f>=en: c=1; n=0
        elif c==1:
            n+=1
            if f<ex: c=0
            elif maxm and n>=maxm: c=0; locked=True
        st.append(c)
    return pd.Series(st,index=fx.index,dtype=float)
def cagr(h,a,b):
    w=h.shift(1).fillna(0); v=1.; prev=None
    idx=list(D.loc[a:b].index)
    for m in idx:
        s=w.loc[m]
        if prev is not None and s!=prev: v*=1-COST*2
        prev=s; v*=1+(HE.loc[m] if s==1 else UN.loc[m])
    return v**(12/len(idx))-1, w.loc[a:b].mean()
P=[("1991-04","2008-12","91~08"),("2009-01","2026-10","09~26"),("1991-04","2026-10","전체")]
base={t:cagr(pd.Series(0.,index=fx.index),a,b)[0] for a,b,t in P}
def row(name,h):
    r={'rule':name}
    for a,b,t in P:
        c,hr=cagr(h,a,b); r[t]=(c-base[t])*100
    r['헤지%']=cagr(h,"1991-04","2026-10")[1]*100
    return r
rows=[]
for en in range(1400,1701,50):
    for ex in range(1300,1451,50):
        if ex>=en: continue
        rows.append(row(f'절대 {en}/{ex}',rule(lambda i,e=en:e, lambda i,x=ex:x)))
A=pd.DataFrame(rows)
piv=A.assign(en=A.rule.str.split().str[1].str.split('/').str[0],ex=A.rule.str.split('/').str[1]).pivot(index='en',columns='ex',values='전체')
print('== 절대 기준: 전체(1991~2026) 연수익 차이 %p (행=진입, 열=복귀)'); print(piv.round(2).to_string())
piv2=A.assign(en=A.rule.str.split().str[1].str.split('/').str[0],ex=A.rule.str.split('/').str[1]).pivot(index='en',columns='ex',values='09~26')
print('== 절대 기준: 2009~2026'); print(piv2.round(2).to_string())
rows=[]
for k in (5,10):
    for up in (0.10,0.15,0.20,0.25,0.30):
        for dn in (0.0,0.05,0.10):
            if dn>=up: continue
            h=rule(lambda i,k=k,u=up: None if np.isnan(ma[k].iloc[i]) else ma[k].iloc[i]*(1+u), lambda i,k=k,d=dn: None if np.isnan(ma[k].iloc[i]) else ma[k].iloc[i]*(1+d))
            rows.append(row(f'{k}년평균 +{int(up*100)}% / +{int(dn*100)}%',h))
B=pd.DataFrame(rows)
print('== 상대 기준 (연수익 차이 %p)'); print(B.round(2).to_string(index=False))
print('\n현재 5년 평균',round(ma[5].iloc[-1]),' 10년 평균',round(ma[10].iloc[-1]), ' 최근',round(fx.iloc[-1]))
