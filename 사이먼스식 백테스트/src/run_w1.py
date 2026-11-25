"""W1: 신호 12개 단독 성과 + 엔진 검증 (부록_W1 §6~§7)."""
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as E  # noqa: E402

RES = E.ROOT / "results"
RES.mkdir(exist_ok=True)
t0 = time.time()
P = E.load_panel()
ctx = E.Ctx(P)
Z = E.all_z(P, ctx)
with open(E.ROOT / "data" / "S_z.pkl", "wb") as fh:
    pickle.dump(Z, fh, protocol=4)
print("z done", round(time.time() - t0), flush=True)

lines = []
def say(s=""):
    print(s, flush=True)
    lines.append(s)

mkt = E.market_ret(ctx)
rows = []
for k in E.SIGNALS:
    sn = k != "S9"
    w = E.target_weights(Z[k], ctx, sector_neutral=sn)
    sim = E.simulate(w, ctx)
    sim_nd = E.simulate(w, ctx, fill="nodelay")
    ic1, ic2 = E.ic_series(Z[k], ctx, 1), E.ic_series(Z[k], ctx, 2)
    for name, (a, b) in {"학습": E.LEARN, "검증": E.VALID}.items():
        m = ctx.sl(a, b)
        row = {"signal": k, "period": name, "sector_neutral": sn}
        row.update(E.perf_row(sim, ctx, a, b))
        row["sharpe_0bp_nodelay"] = E.sharpe(E.net(sim_nd, 0)[m])
        for nm, ic in (("ic_t1", ic1), ("ic_t2", ic2)):
            x = ic[m].dropna()
            row[nm] = x.mean()
            row[nm + "_t"] = x.mean() / x.std(ddof=1) * np.sqrt(len(x))
        row["beta"] = E.beta(E.net(sim, 0)[m], mkt[m])
        p, _ = E.boot_p(E.net(sim, 10)[m])
        row["boot_p_10bp"] = p
        rows.append(row)
    print(k, round(time.time() - t0), flush=True)
df = pd.DataFrame(rows)
df.to_csv(RES / "W1_signals.csv", index=False, encoding="utf-8-sig")

say("== W1 신호 단독 성과 (λ=1, t+1 종가 체결, 레버리지 1배) ==")
say("S9는 섹터 중립을 끈 달러 중립. 나머지는 섹터 중립.")
show = ["signal", "period", "sharpe_0bp_nodelay", "sharpe_0bp", "sharpe_10bp", "ret_0bp", "ret_10bp", "vol",
        "turnover_yr", "hold_days", "ic_t1", "ic_t1_t", "ic_t2", "ic_t2_t", "beta", "boot_p_10bp"]
say(df[show].round(4).to_string(index=False))

# 데이터 점검
U = ctx.U
big = (np.abs(ctx.r) > 0.5) & U
say()
say(f"유니버스 안 |일간 수익|>50% 관측: {int(big.sum())}건 / {int(U.sum())} (2003년 이후 {int(big[ctx.dates >= '2003-01-01'].sum())}건)")
say(f"패널: {ctx.dates[0].date()}~{ctx.dates[-1].date()}, {len(ctx.dates)}일 × {len(ctx.tickers)}종목")

(RES / "W1_summary.txt").write_text("\n".join(lines), encoding="utf-8")
print("done", round(time.time() - t0))
