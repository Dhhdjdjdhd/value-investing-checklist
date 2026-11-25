import sys; sys.path.insert(0, r'E:/value-investing-checklist/대안전략 연구/src')
import pandas as pd, numpy as np
from alloc import build
D=build(); fx=D.fx; UN=D.un; HE=D.ru+D.carry
COST=0.001
def rule(enter=1500, exit_=1400, maxm=24):
    st=[]; c=0; n=0; locked=False
    for i in range(len(fx)):
        f=fx.iloc[i]
        if locked and f<exit_: locked=False
        if c==0 and not locked and f>=enter: c=1; n=0
        elif c==1:
            n+=1
            if f<exit_: c=0
            elif maxm and n>=maxm: c=0; locked=True
        st.append(c)
    return pd.Series(st,index=fx.index,dtype=float)
def sim(h,a,b,w_eq=1.0):
    w=h.shift(1).fillna(0); idx=list(D.loc[a:b].index); v=1.0; eq=[]; prev=None; sw=0
    for m in idx:
        s=w.loc[m]
        if prev is not None and s!=prev: v*=1-COST*2; sw+=1
        prev=s
        r=HE.loc[m] if s==1 else UN.loc[m]
        v*=1+r; eq.append(v)
    e=pd.Series(eq,index=idx); yrs=len(e)/12
    return dict(CAGR=e.iloc[-1]**(1/yrs)-1, MDD=(e/e.cummax()-1).min(), hedged=w.loc[a:b].mean(), switches=sw, final=e.iloc[-1]), e
H0=pd.Series(0.0,index=fx.index); H=rule()
for a,b,tag in [("1991-04","2026-10","전체 1991~"),("1999-01","2026-10","1999~"),("2009-01","2026-10","2009~")]:
    r0,_=sim(H0,a,b); r1,_=sim(H,a,b)
    print(tag, '환노출', f"{r0['CAGR']:.2%} / MDD {r0['MDD']:.1%} / 최종 {r0['final']:.2f}배", '| 규칙', f"{r1['CAGR']:.2%} / MDD {r1['MDD']:.1%} / 최종 {r1['final']:.2f}배 / 헤지 {r1['hedged']:.1%} / 전환 {r1['switches']}")
# episodes
w=H.shift(1).fillna(0); m=w.index
eps=[]; start=None
for i,k in enumerate(m):
    if w.iloc[i]==1 and start is None: start=k
    if w.iloc[i]==0 and start is not None: eps.append((start,m[i-1])); start=None
if start is not None: eps.append((start,m[-1]))
print('\n헤지 구간 (월말 신호 → 다음 달부터)')
for s,e in eps:
    seg=D.loc[s:e]; un=(1+UN.loc[s:e]).prod()-1; he=(1+HE.loc[s:e]).prod()-1
    print(f"  {s} ~ {e} ({len(seg)}개월) 환율 {fx.loc[s]:.0f}→{fx.loc[e]:.0f}  환노출 {un:+.1%}  헤지 {he:+.1%}  차이 {he-un:+.1%}p  4억 기준 {(he-un)*40000:+,.0f}만")
print('\n최근 환율', fx.tail(14).round(0).to_dict())
