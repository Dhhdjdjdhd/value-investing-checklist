"""엔진 검증 (설계서 §10, 부록_W1 §6). 산출: results/W1_verify.txt"""
import gc
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as E  # noqa: E402
from build_panel import build  # noqa: E402
from slim_panel import slim  # noqa: E402

RES = E.ROOT / "results"
t0 = time.time()
lines = []
def say(s=""):
    print(s, flush=True)
    lines.append(s)

say("== 엔진 검증 ==")
# 1) 룩어헤드: 자른 패널을 먼저 처음부터 만들어 계산해 둔다
CUT = "2012-12-31"
P = E.load_panel()
tick = P["close"].columns
sec_full = P["sector"].copy()
del P
Pc = slim(build(end=CUT, verbose=False), tick)
Pc["sector"] = sec_full   # 섹터는 고정 속성(2012년 뒤 상장 종목은 자른 패널에서 값이 전부 결측)
gc.collect()
ctxc = E.Ctx(Pc)
Zc = E.all_z(Pc, ctxc)
wc = E.smooth(E.target_weights(sum(Zc[k].astype(float) for k in E.SIGNALS), ctxc), 0.5)
Uc, dc = ctxc.U.copy(), ctxc.dates
del Pc, ctxc
gc.collect()
print("cut done", round(time.time() - t0), flush=True)

P = E.load_panel()
ctx = E.Ctx(P)
with open(E.ROOT / "data" / "S_z.pkl", "rb") as fh:
    Z = pickle.load(fh)
n = len(dc)
assert (ctx.dates[:n] == dc).all()
du = int((ctx.U[:n] != Uc).sum())
dz = max(float(np.abs(Z[k][:n].astype(float) - Zc[k].astype(float)).max()) for k in E.SIGNALS)
wf = E.smooth(E.target_weights(sum(Z[k].astype(float) for k in E.SIGNALS), ctx), 0.5)[:n]
dw = float(np.abs(wf - wc).max())
say(f"[룩어헤드] {CUT}에서 자른 원자료로 처음부터 다시 만든 패널 대 전체: 유니버스 불일치 {du}칸, 신호 z 최대차 {dz:.2e}, 비중(C1, λ=0.5) 최대차 {dw:.2e} → {'통과' if du == 0 and dz < 1e-9 and dw < 1e-9 else '실패'}")
del Zc, wc, wf
gc.collect()
# 2) 무작위 신호
rng = np.random.default_rng(E.SEED)
m = ctx.sl("2003-01-01", "2026-12-31")
s0, s10, to = [], [], []
for i in range(100):
    sc = rng.standard_normal(ctx.r.shape)
    sim = E.simulate(E.target_weights(sc, ctx), ctx)
    s0.append(E.sharpe(sim["gross"][m]))
    s10.append(E.sharpe(E.net(sim, 10)[m]))
    to.append(sim["trade"][m].mean() * 252)
s0, s10 = np.array(s0), np.array(s10)
ok = abs(s0.mean()) < 0.2 and s10.mean() < 0
say(f"[무작위 100회, 2003~] 비용 0(대주 비용도 제외) Sharpe 평균 {s0.mean():+.3f} (표준편차 {s0.std():.3f}, 이론값 약 {1/np.sqrt(m.sum()/252):.3f}), 10bp Sharpe 평균 {s10.mean():+.2f}, 회전율 연 {np.mean(to):.0f}배 → {'통과' if ok else '실패'}")

# 3) 수작업 대조
close, opn, high, low, adj = (P[k] for k in ["close", "open", "high", "low", "adj_close"])
sec = P["sector"]
worst = 0.0
for d in ["2005-06-15", "2014-03-03", "2022-09-20"]:
    i = ctx.dates.searchsorted(pd.Timestamp(d))
    day = ctx.dates[i]
    tks = [t for t in ctx.tickers if P["universe"].at[day, t]]
    man = {"S1": {}, "S5": {}, "S12": {}}
    r5 = {}
    for t in tks:
        a = adj[t]
        man["S1"][t] = -(a.iloc[i] / a.iloc[i - 1] - 1)
        r5[t] = a.iloc[i] / a.iloc[i - 5] - 1
        h, l, c = float(high[t].iloc[i]), float(low[t].iloc[i]), float(close[t].iloc[i])
        man["S12"][t] = -((c - (h + l) / 2) / (h - l)) if h > l else np.nan
    for t in tks:
        peers = [r5[u] for u in tks if sec[u] == sec[t] and not np.isnan(r5[u])]
        man["S5"][t] = -(r5[t] - np.mean(peers))
    for k in man:
        s = pd.Series(man[k])
        for g in sec[tks].unique():      # 섹터 평균 차감
            idx = [t for t in tks if sec[t] == g]
            s[idx] = s[idx] - s[idx].mean()
        rk = s.rank()
        zman = ((rk - rk.mean()) / rk.std(ddof=0)).fillna(0)
        zeng = pd.Series(Z[k][i], index=ctx.tickers)[tks]
        diff = float((zman - zeng).abs().max())
        worst = max(worst, diff)
        say(f"[수작업] {day.date()} {k}: 종목 {len(tks)}개, 엔진과 최대차 {diff:.2e}")
say(f"[수작업] 최대차 {worst:.2e} → {'통과' if worst < 1e-6 else '실패'}")

(RES / "W1_verify.txt").write_text(chr(10).join(lines), encoding="utf-8")
print("done", round(time.time() - t0))
