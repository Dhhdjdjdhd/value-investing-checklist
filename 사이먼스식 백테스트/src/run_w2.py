"""W2: 결합 모델 C1~C3 × λ × 비용, 선택, 판정 (부록_W2).
사용: py -I src/run_w2.py [--surv-ret 연%p] [--surv-sharpe 차감폭]"""
import argparse
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as E  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--surv-ret", type=float, default=None, help="생존편향 보정: 연수익 차감폭(%%p)")
ap.add_argument("--surv-sharpe", type=float, default=None, help="생존편향 보정: Sharpe 차감폭")
ap.add_argument("--surv-note", type=str, default="")
args = ap.parse_args()

RES = E.ROOT / "results"
t0 = time.time()
P = E.load_panel()
ctx = E.Ctx(P)
with open(E.ROOT / "data" / "S_z.pkl", "rb") as fh:
    Z = pickle.load(fh)
lines = []
def say(s=""):
    print(s, flush=True)
    lines.append(s)

# ---------- 결합 점수 ----------
score = {"C1": sum(Z[k].astype(float) for k in E.SIGNALS), "C3": sum(Z[k].astype(float) for k in E.SHORT_SET)}

# C2: 확장 창 릿지
import warnings
T, N = ctx.r.shape
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    y2 = E.sector_demean(np.where(ctx.U, np.roll(ctx.r, -2, axis=0), np.nan), ctx)
y2[-2:] = np.nan
K = len(E.SIGNALS)
XtX = np.zeros((T, K, K))
Xty = np.zeros((T, K))
for t in range(T):
    ok = ctx.U[t] & ~np.isnan(y2[t])
    if ok.sum() < 50:
        continue
    X = np.column_stack([Z[k][t, ok] for k in E.SIGNALS]).astype(float)
    XtX[t] = X.T @ X
    Xty[t] = X.T @ y2[t, ok]
cXtX, cXty = XtX.cumsum(axis=0), Xty.cumsum(axis=0)
sc2 = np.zeros((T, N))
coefs = {}
years = sorted(set(ctx.dates.year))
for Y in [y for y in years if y >= 2003]:
    first = np.searchsorted(ctx.dates.values, np.datetime64(f"{Y}-01-01"))
    tcut = first - 3            # y(t)=r(t+2), t+2 < first  →  t ≤ first-3
    b = np.linalg.solve(cXtX[tcut] + 10.0 * np.eye(K), cXty[tcut])
    coefs[Y] = b
    idx = np.where(ctx.dates.year == Y)[0]
    sc2[idx] = sum(b[j] * Z[k][idx] for j, k in enumerate(E.SIGNALS))
score["C2"] = sc2
coef_df = pd.DataFrame(coefs, index=E.SIGNALS).T * 1e4
c4p = E.ROOT / "data" / "S_c4_score.pkl"
c4 = None
if c4p.exists():
    with open(c4p, "rb") as fh:
        c4 = pickle.load(fh)
    score["C4"] = c4["score"].astype(float)
MODELS = [c for c in ["C1", "C2", "C3", "C4"] if c in score]
print("scores", round(time.time() - t0), flush=True)

# ---------- 격자 ----------
LAMS, BPS = [1.0, 0.5, 0.2], [0, 5, 10, 20]
sims, rows = {}, []
for c in MODELS:
    tgt = E.target_weights(score[c], ctx)
    for lam in LAMS:
        w = E.smooth(tgt, lam)
        sim = E.simulate(w, ctx)
        sims[(c, lam)] = (sim, None)
        for name, (a, b) in {"학습": E.LEARN, "검증": E.VALID}.items():
            m = ctx.sl(a, b)
            tr = sim["trade"][m].mean()
            for bp in BPS:
                st = E.stats(E.net(sim, bp)[m])
                rows.append({"model": c, "lambda": lam, "cost_bp": bp, "period": name, **st,
                             "turnover_yr": tr * 252, "hold_days": 2 / tr})
    print(c, round(time.time() - t0), flush=True)
rules = pd.DataFrame(rows)
rules.to_csv(RES / "W2_rules.csv", index=False, encoding="utf-8-sig")

piv = rules.pivot_table(index=["model", "lambda"], columns=["period", "cost_bp"], values="sharpe").round(2)
say("== W2 결합 모델: Sharpe (t+1 종가 체결, 레버리지 1배, 대주 비용 연 0.5% 포함) ==")
say(piv[["학습", "검증"]].to_string())
say()
tv = rules[(rules.cost_bp == 0) & (rules.period == "학습")].set_index(["model", "lambda"])[["turnover_yr", "hold_days", "vol"]]
say("회전율(연, 편도 합계 / 총노출 1), 평균 보유일, 변동성 (학습 구간)")
say(tv.round(3).to_string())
say()
say("C2 릿지 계수 (bp/일, z 1단위당; 매년 재학습)")
say(coef_df.loc[[2003, 2007, 2011, 2016, 2021, 2026]].round(2).to_string())

# ---------- C4 대 C2 (참고) ----------
if c4 is not None:
    say()
    say("== 참고: C4(부스팅) 대 C2(릿지), 점수와 t+2일 섹터 중립 수익의 일별 IC ==")
    icd = {}
    for cc in ("C2", "C4"):
        a_ = pd.DataFrame(np.where(ctx.U, score[cc], np.nan)).rank(axis=1)
        b_ = pd.DataFrame(y2).rank(axis=1)
        ok_ = a_.notna() & b_.notna()
        a_, b_ = a_.where(ok_), b_.where(ok_)
        a_ = a_.sub(a_.mean(axis=1), axis=0); b_ = b_.sub(b_.mean(axis=1), axis=0)
        icd[cc] = pd.Series(((a_ * b_).sum(axis=1) / np.sqrt((a_ ** 2).sum(axis=1) * (b_ ** 2).sum(axis=1))).values, index=ctx.dates)
    for name, (a, b) in {"학습": E.LEARN, "검증": E.VALID}.items():
        m = ctx.sl(a, b)
        x2, x4 = icd["C2"][m].dropna(), icd["C4"][m].dropna()
        d = (icd["C4"] - icd["C2"])[m].dropna()
        tt = lambda x: x.mean() / x.std(ddof=1) * np.sqrt(len(x))
        say(f"  {name}: IC C2 {x2.mean():+.4f} (t {tt(x2):+.1f}), C4 {x4.mean():+.4f} (t {tt(x4):+.1f}), 차이 C4−C2 {d.mean():+.4f} (대응 t {tt(d):+.1f})")
        for lam in LAMS:
            g = lambda cc, bp: E.sharpe(E.net(sims[(cc, lam)][0], bp)[m])
            say(f"     λ={lam}: Sharpe 0bp C2 {g('C2',0):+.2f} / C4 {g('C4',0):+.2f} (차 {g('C4',0)-g('C2',0):+.2f}), 10bp C2 {g('C2',10):+.2f} / C4 {g('C4',10):+.2f} (차 {g('C4',10)-g('C2',10):+.2f})")
    imp = c4["importance"]
    say("  C4 변수 중요도(gain 비중 %, 2016년 모델 / 2026년 모델)")
    say("  " + ", ".join(f"{k} {100*imp[2016][k]/imp[2016].sum():.0f}/{100*imp[2026][k]/imp[2026].sum():.0f}" for k in imp.index))

# ---------- 선택 ----------
lr = rules[(rules.period == "학습") & (rules.cost_bp == 10)].sort_values("sharpe", ascending=False)
best = lr.iloc[0]
C, LAM = best["model"], float(best["lambda"])
sim = sims[(C, LAM)][0]
w = E.smooth(E.target_weights(score[C], ctx), LAM)
say()
say(f"== 선택 (학습 구간 Sharpe@10bp 1위): {C}, λ={LAM} (학습 Sharpe@10bp {best['sharpe']:.2f}) ==")

mv = ctx.sl(*E.VALID)
ml = ctx.sl(*E.LEARN)
mkt = E.market_ret(ctx)
V = {bp: E.stats(E.net(sim, bp)[mv]) for bp in BPS}
p10, q10 = E.boot_p(E.net(sim, 10)[mv])
p0, q0 = E.boot_p(E.net(sim, 0)[mv])
bt = E.beta(E.net(sim, 0)[mv], mkt[mv])
say("검증 구간(2016-01~2026-10)")
for bp in BPS:
    s = V[bp]
    say(f"  비용 {bp:>2}bp: Sharpe {s['sharpe']:+.2f}, 연수익 {s['ann_ret']*100:+.2f}%, 변동성 {s['vol']*100:.2f}%, MDD {s['mdd']*100:.1f}%")
say(f"  부트스트랩 P(Sharpe@10bp>0) = {p10:.3f} (5·50·95 분위 {q10[0]:+.2f}/{q10[1]:+.2f}/{q10[2]:+.2f}); 비용 0 기준 P = {p0:.3f}")
tr = sim["trade"][mv].mean()
say(f"  회전율 연 {tr*252:.0f}배, 평균 보유 {2/tr:.1f}일, 시장 베타 {bt:+.3f}")
say(f"  롱 기여 연 {sim['long'][mv].mean()*252*100:+.2f}%, 숏 기여 연 {sim['short'][mv].mean()*252*100:+.2f}% (비용 전)")
be = (sim["gross"][mv].mean() - (sim["short_gross"][mv] * E.BORROW / 252).mean()) / sim["trade"][mv].mean() * 1e4
say(f"  손익분기 비용(검증): 편도 {be:.1f}bp")

# ---------- 판정 ----------
s10, s20 = V[10]["sharpe"], V[20]["sharpe"]
adj = None
SURV = {'C1': 0.0, 'C2': 0.0, 'C3': 0.06, 'C4': 0.0}   # W3 보정치 (부록_W2)
if args.surv_ret is None and args.surv_sharpe is None:
    args.surv_sharpe = SURV[C]
    args.surv_note = f'W3 검증 구간 편향(Sharpe): C3 0.06, C1·C2·C4 0.00 → {C}에 {SURV[C]:.2f} 적용'
if args.surv_ret is not None:
    adj = (V[10]["ann_ret"] - args.surv_ret / 100) / V[10]["vol"]
elif args.surv_sharpe is not None:
    adj = s10 - args.surv_sharpe
if s10 >= 1.0 and s20 > 0 and p10 >= 0.95:
    if adj is None:
        verdict = "보정 대기 (보정 전 조건은 통과 수준)"
    else:
        verdict = "통과" if adj > 0.5 else ("보류" if s10 > 0.3 and p10 >= 0.90 else "탈락")
elif s10 > 0.3 and p10 >= 0.90:
    verdict = "보류"
else:
    verdict = "탈락"
say()
say(f"== 판정: {verdict} ==")
say(f"  Sharpe@10bp {s10:+.2f} (기준 ≥1.0), Sharpe@20bp {s20:+.2f} (기준 >0), P {p10:.3f} (기준 ≥0.95), "
    f"생존편향 보정 Sharpe@10bp {'미수령' if adj is None else f'{adj:+.2f}'} (기준 >0.5)")
if args.surv_note:
    say("  보정 근거: " + args.surv_note)
pd.DataFrame([{"model": C, "lambda": LAM, "learn_sharpe_10bp": best["sharpe"],
               "valid_sharpe_0bp": V[0]["sharpe"], "valid_sharpe_5bp": V[5]["sharpe"],
               "valid_sharpe_10bp": s10, "valid_sharpe_20bp": s20, "valid_ret_10bp": V[10]["ann_ret"],
               "valid_vol": V[10]["vol"], "valid_mdd_10bp": V[10]["mdd"], "boot_p_10bp": p10,
               "boot_q05": q10[0], "boot_q95": q10[2], "surv_adj_sharpe_10bp": adj, "breakeven_bp": be,
               "turnover_yr": tr * 252, "hold_days": 2 / tr, "beta": bt, "verdict": verdict}]
             ).to_csv(RES / "W2_verdict.csv", index=False, encoding="utf-8-sig")

# ---------- 참고판 ----------
say()
say("== 참고판 (판정 외), 선택 조합 ==")
for nm, fill in [("t+1 시가 체결", "open"), ("지연 없음(t 종가, 불가능)", "nodelay")]:
    s2 = E.simulate(w, ctx, fill=fill)
    say(f"  {nm}: 학습 Sharpe 0/10bp {E.sharpe(E.net(s2,0)[ml]):+.2f}/{E.sharpe(E.net(s2,10)[ml]):+.2f}, "
        f"검증 0/10/20bp {E.sharpe(E.net(s2,0)[mv]):+.2f}/{E.sharpe(E.net(s2,10)[mv]):+.2f}/{E.sharpe(E.net(s2,20)[mv]):+.2f}")
n10 = E.net(sim, 10)
rv = n10.rolling(60).std().shift(1) * np.sqrt(252)
lev = (0.10 / rv).clip(upper=5).fillna(1.0)
levret = lev * n10 - (lev - 1).clip(lower=0) * 0.01 / 252
for name, m in (("학습", ml), ("검증", mv)):
    st = E.stats(levret[m])
    say(f"  레버리지판({name}): 평균 {lev[m].mean():.1f}배(최대 5), Sharpe {st['sharpe']:+.2f}, 연수익 {st['ann_ret']*100:+.1f}%, 변동성 {st['vol']*100:.1f}%, MDD {st['mdd']*100:.1f}%")

# 연도별
yr = []
for Y in range(2003, 2027):
    m = ctx.dates.year == Y
    row = {"year": Y, "period": "학습" if Y <= 2015 else "검증"}
    for bp in (0, 10, 20):
        x = E.net(sim, bp)[m]
        row[f"ret_{bp}bp"] = x.sum()
        row[f"sharpe_{bp}bp"] = E.sharpe(x)
    row["lev_ret_10bp"] = levret[m].sum()
    row["market_ret"] = mkt[m].sum()
    yr.append(row)
yr = pd.DataFrame(yr)
regs = {"2008 전체": ("2008-01-01", "2008-12-31"), "2008-09~2009-03": ("2008-09-01", "2009-03-31"),
        "2020 전체": ("2020-01-01", "2020-12-31"), "2020-02-20~04-30": ("2020-02-20", "2020-04-30"),
        "2022 전체": ("2022-01-01", "2022-12-31")}
rg = []
for nm, (a, b) in regs.items():
    m = ctx.sl(a, b)
    x = E.net(sim, 10)[m]
    cum = x.cumsum()
    rg.append({"year": nm, "period": "국면", "ret_0bp": E.net(sim, 0)[m].sum(), "sharpe_0bp": E.sharpe(E.net(sim, 0)[m]),
               "ret_10bp": x.sum(), "sharpe_10bp": E.sharpe(x), "ret_20bp": E.net(sim, 20)[m].sum(),
               "sharpe_20bp": E.sharpe(E.net(sim, 20)[m]), "lev_ret_10bp": levret[m].sum(),
               "market_ret": mkt[m].sum(), "mdd_10bp": float((cum - cum.cummax()).min())})
out = pd.concat([yr, pd.DataFrame(rg)], ignore_index=True)
out.to_csv(RES / "W2_yearly.csv", index=False, encoding="utf-8-sig")
say()
say("연도별·국면별 (수익은 단순 합, 소수)")
say(out.round(3).to_string(index=False))
pd.DataFrame({"gross": sim["gross"], "net_10bp": n10, "net_20bp": E.net(sim, 20), "trade": sim["trade"],
              "lev": lev, "lev_net_10bp": levret, "market": mkt}).loc["2003":].to_csv(RES / "W2_daily.csv", encoding="utf-8-sig")
(RES / "W2_summary.txt").write_text("\n".join(lines), encoding="utf-8")
print("done", round(time.time() - t0))
