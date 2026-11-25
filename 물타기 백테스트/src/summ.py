import sys, pandas as pd, numpy as np
R=pd.read_csv(sys.argv[1],parse_dates=['date','end'])
pd.set_option('display.width',250)
M=R[R.kind!='BH'].copy(); M['yrs']=M.days/365.25
M['lossbig']=(M.pnl< -0.3*M.inv)
def agg(g):
    yrs=g.yrs.clip(lower=1/52)
    return pd.Series(dict(
        n=len(g), win=g.win.mean(), med_days_win=g.loc[g.win==1,'days'].median(),
        hit_cap=(g.steps==g.name[2]).mean(), avg_inv=g.inv.mean(),
        avg_pnl=g.pnl.mean(), avg_loss_if_lose=g.loc[g.win==0,'pnl'].mean(),
        p1=g.pnl.quantile(0.01), worst=g.pnl.min(),
        loss30=g.lossbig.mean(),
        ann_on_reserve=g.pnl.sum()/(g.reserve*yrs).sum(),
        spy_ann_on_reserve=g.spy_on_reserve.sum()/(g.reserve*yrs).sum()))
S=M.groupby(['q','kind','cap','tgt']).apply(agg)
print(S.to_string(float_format=lambda x:f'{x:,.3f}'))
B=R[R.kind=='BH']
print('\nBuy&hold 5y (stock vs SPY), by q')
print(B.groupby('q').agg(n=('pnl','size'),stock_med=('pnl','median'),stock_mean=('pnl','mean'),stock_pos=('win','mean'),spy_mean=('spy_on_reserve','mean')).to_string(float_format=lambda x:f'{x:.3f}'))
print('\nworst episodes (quality, B, cap8, tgt .10)')
w=M[(M.q=='quality')&(M.kind=='B')&(M.cap==8)&(M.tgt==0.10)].nsmallest(8,'pnl')[['date','t','steps','inv','pnl','days']]
print(w.to_string())
w=M[(M.q=='quality')&(M.kind=='A')&(M.cap==8)&(M.tgt==0.10)].nsmallest(8,'pnl')[['date','t','steps','inv','pnl','days']]
print(w.to_string())
print('\nby start year (quality, A cap8 tgt.10): win, avg pnl')
x=M[(M.q=='quality')&(M.kind=='A')&(M.cap==8)&(M.tgt==0.10)]
print(x.groupby(x.date.dt.year).agg(n=('pnl','size'),win=('win','mean'),pnl=('pnl','mean'),hitcap=('steps',lambda s:(s==8).mean())).to_string(float_format=lambda v:f'{v:.2f}'))
