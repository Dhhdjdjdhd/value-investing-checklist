"""T1. 변동성 목표화 + 레버리지 (설계안 연구/00_연구설계서.md §T1).

실행: py -I "설계안 연구/src/t1_levtarget.py"
재사용: 시장상태 예측 연구/src/A_vol.py 의 데이터(S&P 1950~, 배당, TB3MS)·GARCH 예측(V3)·체결 규칙(LAG=1).
산출: 설계안 연구/results/t1_*.csv, t1_summary.txt, 설계안 연구/data/y_SSO_adj.csv
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent            # 설계안 연구
RES, DATA = ROOT / "results", ROOT / "data"
RES.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT.parent / "시장상태 예측 연구" / "src"))
import A_vol  # noqa: E402  (p5_fear, alloc, valuation 경로도 함께 잡힘)

UA = "Mozilla/5.0 (compatible; research-script)"
IS = ("1952-01-01", "1999-12-31")          # GARCH 예열 때문에 A와 같이 1952부터
OOS = ("2000-01-01", "2026-10-31")
SIG_STAR, THR, LAG = 0.15, 0.20, 1
LS = [1.0, 1.25, 1.5, 2.0]
COST, SPREAD, FEE, ETF_LEV = 0.001, 0.005, 0.009, 2.0  # 편도 매매비용, 차입 가산, 레버리지 ETF 보수, ETF 배수
FIXED = [1.25, 1.5]
BLOCK, NBOOT, SEED = 63, 1000, 20261126
CRISES = {"1987-10 (1987-08-25~1987-12-04)": ("1987-08-25", "1987-12-04", "학습"),
          "닷컴 (2000-03-24~2002-10-09)": ("2000-03-24", "2002-10-09", "검증"),
          "금융위기 (2007-10-09~2009-03-09)": ("2007-10-09", "2009-03-09", "검증"),
          "코로나 (2020-02-19~2020-03-23)": ("2020-02-19", "2020-03-23", "검증"),
          "2022 (2022-01-03~2022-10-12)": ("2022-01-03", "2022-10-12", "검증")}


# ---------------------------------------------------------------- 데이터
def yahoo_daily(sym, adj=True):
    p = DATA / f"y_{sym.replace('^', '')}_{'adj' if adj else 'c'}.csv"
    if p.exists():
        s = pd.read_csv(p, index_col=0).iloc[:, 0]
        s.index = pd.to_datetime(s.index)
        return s
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^', '%5E')}?period1=600000000&period2=9999999999&interval=1d"
    for k in range(3):
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=90).read())
            break
        except Exception:
            time.sleep(3 * (k + 1))
    r = r["chart"]["result"][0]
    v = r["indicators"]["adjclose"][0]["adjclose"] if adj else r["indicators"]["quote"][0]["close"]
    s = pd.Series(v, index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna().groupby(level=0).last()
    s.to_frame("v").to_csv(p)
    return s


# ---------------------------------------------------------------- 엔진
def simulate(R, tgt, a, b, mode, cm, thr=THR):
    """3 슬리브 엔진. I = 1배 지수(총수익 re), C = 현금(rc; 음수면 차입 rc+SPREAD), X = 2배 ETF.
    cm 'margin': 노출 w>1 → I=w, C=1-w(차입).   cm 'etf': w>1 → X=w-1, I=2-w, C=0.  w≤1은 두 모형 같음(I=w, C=1-w).
    2배 ETF 일간 수익 = 2·re − (rc+SPREAD) − FEE/252 (매일 2배로 재조정되는 ETF 내부 모형).
    체결: t일 종가 신호 → t+LAG일 종가. mode 'M' = 월말마다, 'D' = |목표−현재 노출|>thr 일 때.
    매매비용 = COST × (|ΔI| + |ΔX|) (거래한 증권의 비중 변화 합).
    반환: 일간수익, 하루 시작 노출, 매매 횟수 Series(날짜별 1), 회전(Σ|Δ|), 종료 노출."""
    idx = R.index
    i0, i1 = idx.searchsorted(pd.Timestamp(a)), idx.searchsorted(pd.Timestamp(b), side="right")
    re, rc, mon = R.re.values, R.rc.values, R.month.values
    raw = tgt.reindex(idx)
    tg = raw.shift(LAG).values
    w0 = tg[i0 - 1]
    if not np.isfinite(w0):
        w0 = raw.values[i0 - 1]
    assert np.isfinite(w0), "시작 비중 없음"

    def split(w):
        if cm == "etf" and w > 1:
            x = (w - 1) / (ETF_LEV - 1)
            return 1 - x, 0.0, x
        return w, 1 - w, 0.0

    wi, wc, wx = split(w0)
    tot = 1.0 - COST * (abs(wi) + abs(wx))
    I, C, X = tot * wi, tot * wc, tot * wx
    prev_tot = 1.0
    n = i1 - i0
    rets, held, trades = np.empty(n), np.empty(n), np.zeros(n)
    turn = abs(wi) + abs(wx)
    for j, i in enumerate(range(i0, i1)):
        tot = I + C + X
        held[j] = (I + ETF_LEV * X) / tot
        I *= 1 + re[i]
        C *= 1 + (rc[i] if C >= 0 else rc[i] + SPREAD / 252)
        X *= 1 + ETF_LEV * re[i] - (ETF_LEV - 1) * (rc[i] + SPREAD / 252) - FEE / 252
        tot = I + C + X
        cur = (I + ETF_LEV * X) / tot
        t = tg[i]
        k = i - LAG
        last_day = (k + 1 >= len(idx)) or (mon[k + 1] != mon[k])
        do = np.isfinite(t) and ((mode == "M" and last_day) or (mode == "D" and abs(t - cur) > thr))
        if do and i + 1 < len(idx):
            wi, wc, wx = split(t)
            d = abs(wi - I / tot) + abs(wx - X / tot)
            tot *= 1 - COST * d
            turn += d
            trades[j] = 1 if d > 1e-9 else 0   # 비중 변화가 없는 월말 점검은 매매로 세지 않음
            I, C, X = tot * wi, tot * wc, tot * wx
        rets[j] = tot / prev_tot - 1
        prev_tot = tot
    ix = idx[i0:i1]
    return pd.Series(rets, index=ix), pd.Series(held, index=ix), pd.Series(trades, index=ix), turn, (I + ETF_LEV * X) / (I + C + X)


def stats(ret, rc, held=None, trades=None, turn=None):
    e = (1 + ret).cumprod()
    yrs = len(ret) / 252
    x = ret - rc.reindex(ret.index)
    out = {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "vol": ret.std() * np.sqrt(252),
           "Sharpe": x.mean() / x.std() * np.sqrt(252), "MDD": (e / np.maximum(e.cummax(), 1.0) - 1).min()}
    if held is not None:
        out["w_avg"], out["w_min"], out["w_max"] = held.mean(), held.min(), held.max()
        out["w_max_date"] = held.idxmax().date()
        out["days_over_1"] = (held > 1.0 + 1e-9).mean()
    if trades is not None:
        out["trades_per_yr"] = trades.sum() / yrs
    if turn is not None:
        out["turn_per_yr"] = turn / yrs
    return out


def boot(ra, rb, rc, n=NBOOT, block=BLOCK):
    """원형 블록 부트스트랩(블록 3개월=63일). 반환: P(CAGR_a−CAGR_b>0), CAGR차 5/50/95%, P(Sharpe_a−Sharpe_b>0)."""
    rng = np.random.default_rng(SEED)
    la, lb = np.log1p(ra.values), np.log1p(rb.values)
    xa, xb = (ra - rc).values, (rb - rc).values
    T = len(la)
    nb = int(np.ceil(T / block))
    off = np.arange(block)
    dc, ds = np.empty(n), np.empty(n)
    for k in range(n):
        st = rng.integers(0, T, nb)
        ii = ((st[:, None] + off[None, :]) % T).ravel()[:T]
        dc[k] = np.exp(la[ii].mean() * 252) - np.exp(lb[ii].mean() * 252)
        a_, b_ = xa[ii], xb[ii]
        ds[k] = (a_.mean() / a_.std() - b_.mean() / b_.std()) * np.sqrt(252)
    return (dc > 0).mean(), np.percentile(dc, [5, 50, 95]), (ds > 0).mean()


# ---------------------------------------------------------------- 실행
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    o = []
    g = A_vol.p5_fear.load("GSPC").loc[:OOS[1]]
    vix = A_vol.p5_fear.load("VIX")
    R, dm, tb = A_vol.build_returns(g)
    rc = R.rc
    F, P = A_vol.forecasts(g, vix)
    sig = F.V3
    sig_star_A = F.V1.loc["1950-01-01":"1999-12-31"].mean()   # A의 D1.0 σ*
    o.append(f"[설정] σ* {SIG_STAR:.0%}, 예측 = V3(GARCH 21일, 매년 재추정), 상한 L {LS}, 밴드 {THR:.0%}p, 체결 t+{LAG}일 종가")
    o.append(f"  비용: 매매 편도 {COST:.1%}, 차입 = TB3MS + {SPREAD:.1%}p, 2x ETF 보수 {FEE:.1%} + 일간 재조정(차입 TB3MS+{SPREAD:.1%}p)")
    o.append(f"  학습 {IS[0]}~{IS[1]} / 검증 {OOS[0]}~{OOS[1]} (S&P 마지막 거래일 {g.index[-1].date()})")
    o.append(f"  A의 D1.0 σ* = {sig_star_A:.2%} (비교용)")
    o.append("")

    # --- 엔진 검증
    o.append("[엔진 검증]")
    one = pd.Series(1.0, index=g.index)
    T_A = (sig_star_A / sig).clip(upper=1.0)
    for nm, (a, b) in (("학습", IS), ("검증", OOS)):
        r1, h1, _, t1_, _ = simulate(R, T_A, a, b, "D", "margin")
        r2, h2, t2_, _ = A_vol.simulate(R, T_A, a, b, "D")
        ok = np.allclose(r1.values, r2.values, atol=1e-14) and np.allclose(h1.values, h2.values) and abs(t1_ - t2_) < 1e-12
        o.append(f"  D1.0(σ* {sig_star_A:.1%}) {nm}: 새 엔진 누적 {(1 + r1).prod():.6f} vs A_vol.simulate {(1 + r2).prod():.6f}  {'통과' if ok else '실패'}")
        assert ok, "A 엔진과 불일치"
        r3, _, _, _, _ = simulate(R, one, a, b, "M", "etf")
        direct = (1 + R.re.loc[a:b]).prod() * (1 - COST)
        o.append(f"  B&H 재현 {nm}: {(1 + r3).prod():.6f} vs {direct:.6f}  {'통과' if abs((1 + r3).prod() / direct - 1) < 1e-9 else '실패'}")
    # 2x ETF 모형: 매일 재조정 ETF 1개만 보유(비용 모형 b의 w=2)와 차입 2배(모형 a)의 차이 = 보수 0.9%만 (일간 재조정 효과는 같음)
    two = pd.Series(2.0, index=g.index)
    rA, _, _, _, _ = simulate(R, two, OOS[0], OOS[1], "M", "margin")
    rB, _, _, _, _ = simulate(R, two, OOS[0], OOS[1], "M", "etf")
    o.append(f"  고정 2배 검증: 차입(월말 재조정) 연 {stats(rA, rc)['CAGR']:.2%} vs 2x ETF 100%(일간 재조정, 보수 0.9%) 연 {stats(rB, rc)['CAGR']:.2%}")
    o.append("")

    # --- 규칙 집합
    rules = {}                                     # name -> (target Series, mode, cost model, group)
    rules["S&P 100%"] = (one, "M", "margin", "기준")
    rules[f"D1.0 원본(σ* {sig_star_A:.1%})"] = (T_A, "D", "margin", "비교")
    for cm, cn in (("margin", "차입"), ("etf", "ETF")):
        for L in FIXED:
            rules[f"고정 {L}x [{cn}]"] = (pd.Series(L, index=g.index), "M", cm, "비교")
        for L in LS:
            rules[f"VT L={L} [{cn}]"] = ((SIG_STAR / sig).clip(upper=L), "D", cm, "판정" if L > 1 else "비교")
    n_tested = sum(1 for k, v in rules.items() if v[3] == "판정")
    o.append(f"[시험 수] 판정 대상 규칙 {n_tested}개 (L 3개 × 비용 모형 2개). σ*·밴드·예측 모델은 고정, 격자 없음. 그 외 비교 {len(rules) - n_tested}개")
    o.append("")

    series, helds, trades_all, out = {}, {}, {}, []
    for pn, (a, b) in (("학습", IS), ("검증", OOS)):
        for rn, (tgt, mode, cm, grp) in rules.items():
            ret, held, tr, turn, we = simulate(R, tgt, a, b, mode, cm)
            series[(pn, rn)], helds[(pn, rn)], trades_all[(pn, rn)] = ret, held, tr
            out.append({"period": pn, "rule": rn, "group": grp, **stats(ret, rc, held, tr, turn), "end_w": we})
    RU = pd.DataFrame(out)
    # 검증 하위 구간
    sub = []
    for (pn, rn), ret in series.items():
        if pn != "검증":
            continue
        for sn, (a, b) in {"검증 전반 2000~2012": ("2000-01-01", "2012-12-31"), "검증 후반 2013~2026": ("2013-01-01", OOS[1])}.items():
            sub.append({"period": sn, "rule": rn, "group": rules[rn][3], **stats(ret.loc[a:b], rc, helds[(pn, rn)].loc[a:b])})
    RU = pd.concat([RU, pd.DataFrame(sub)], ignore_index=True)
    RU.to_csv(RES / "t1_rules.csv", index=False, encoding="utf-8-sig")

    o.append("[결과] 연 = CAGR, 노출 = 주식 노출(1.0 = 100%)")
    for pn in RU.period.unique():
        o.append(f"  {pn}")
        for _, x in RU[RU.period == pn].iterrows():
            extra = f"  노출 평균 {x.w_avg:.2f} 최대 {x.w_max:.2f}({x.w_max_date})  >1배 일수 {x.days_over_1:4.0%}" if pd.notna(x.get("w_avg")) else ""
            extra += f"  매매/년 {x.trades_per_yr:5.2f}" if pd.notna(x.get("trades_per_yr")) else ""
            o.append(f"    {x.rule:<24} 연 {x.CAGR:6.2%}  변동성 {x.vol:5.1%}  Sharpe {x.Sharpe:.3f}  MDD {x.MDD:6.1%}{extra}")
    o.append("")

    # --- 판정
    bh_tr = RU[(RU.period == "학습") & (RU.rule == "S&P 100%")].iloc[0]
    bh = RU[(RU.period == "검증") & (RU.rule == "S&P 100%")].iloc[0]
    V = []
    for rn, (tgt, mode, cm, grp) in rules.items():
        if rn == "S&P 100%":
            continue
        x = RU[(RU.period == "검증") & (RU.rule == rn)].iloc[0]
        t = RU[(RU.period == "학습") & (RU.rule == rn)].iloc[0]
        p, q, ps = boot(series[("검증", rn)], series[("검증", "S&P 100%")], rc.reindex(series[("검증", rn)].index))
        c1, c2, c3 = bool(x.CAGR - bh.CAGR >= 0.01), bool(x.MDD >= bh.MDD), bool(p >= 0.90)
        verdict = "채택" if c1 and c2 and c3 else ("보류" if c1 else "기각")
        V.append({"rule": rn, "group": grp, "학습_CAGR": t.CAGR, "학습_CAGR차_%p": (t.CAGR - bh_tr.CAGR) * 100, "학습_MDD": t.MDD, "학습_MDD차_%p": (t.MDD - bh_tr.MDD) * 100, "학습_Sharpe": t.Sharpe,
                  "검증_CAGR": x.CAGR, "S&P_CAGR": bh.CAGR, "CAGR차_%p": (x.CAGR - bh.CAGR) * 100,
                  "검증_MDD": x.MDD, "S&P_MDD": bh.MDD, "MDD차_%p": (x.MDD - bh.MDD) * 100, "검증_Sharpe": x.Sharpe, "S&P_Sharpe": bh.Sharpe,
                  "부트_P(CAGR차>0)": p, "CAGR차_5%": q[0], "CAGR차_50%": q[1], "CAGR차_95%": q[2], "부트_P(Sharpe차>0)": ps,
                  "기준1_CAGR+1%p": c1, "기준2_MDD": c2, "기준3_부트90": c3, "판정": verdict if grp == "판정" else f"(참고) {verdict}"})
    V = pd.DataFrame(V)
    # 학습 구간에서 판정 대표 선택(비용 모형별): 학습 MDD가 S&P보다 나쁘지 않은 것 중 학습 CAGR 최대, 없으면 학습 Sharpe 최대
    reps = {}
    for cn in ("차입", "ETF"):
        c = V[(V.group == "판정") & V.rule.str.endswith(f"[{cn}]")]
        ok = c[c["학습_MDD차_%p"] >= 0]
        reps[cn] = (ok.sort_values("학습_CAGR").iloc[-1].rule, "학습 MDD≤S&P 중 CAGR 최대") if len(ok) else (c.sort_values("학습_Sharpe").iloc[-1].rule, "학습 MDD 모두 S&P보다 나빠 Sharpe 최대")
    V["역할"] = V.rule.map(lambda r: "판정 대표(학습 선택)" if r in [v[0] for v in reps.values()] else ("판정(격자)" if V.set_index("rule").loc[r, "group"] == "판정" else "참고"))
    V.to_csv(RES / "t1_verdict.csv", index=False, encoding="utf-8-sig")
    o.append("[판정] 검증 구간. 기준: ①CAGR ≥ S&P +1.0%p ②MDD가 S&P보다 나쁘지 않음 ③블록 부트(63일, 1,000회) P(CAGR차>0) ≥ 0.90. 채택=①②③, 보류=①만, 기각=그 외")
    o.append(f"  S&P 100% 검증: 연 {bh.CAGR:.2%}  MDD {bh.MDD:.1%}  Sharpe {bh.Sharpe:.3f}")
    for _, x in V.iterrows():
        o.append(f"  {x.rule:<24} [{x['역할']}] 학습 CAGR차 {x['학습_CAGR차_%p']:+.2f}%p MDD차 {x['학습_MDD차_%p']:+.1f}%p | 검증 CAGR {x['검증_CAGR']:.2%} ({x['CAGR차_%p']:+.2f}%p) {'O' if x['기준1_CAGR+1%p'] else 'X'}"
                 f" | MDD {x['검증_MDD']:.1%} ({x['MDD차_%p']:+.1f}%p) {'O' if x['기준2_MDD'] else 'X'}"
                 f" | 부트 P {x['부트_P(CAGR차>0)']:.3f} (CAGR차 5~95% {x['CAGR차_5%']:+.2%}~{x['CAGR차_95%']:+.2%}; Sharpe P {x['부트_P(Sharpe차>0)']:.3f}) {'O' if x['기준3_부트90'] else 'X'} → {x['판정']}")
    for cn, (rn, why) in reps.items():
        fin = V[V.rule == rn].iloc[0]
        o.append(f"  ▶ 비용 모형 {cn} 판정 대표 {rn} ({why}) = {fin['판정']}")
    o.append("")

    # --- 위기 구간
    cr = []
    for cn, (a, b, pn) in CRISES.items():
        row = {"crisis": cn, "period": pn}
        for rn in rules:
            row[rn] = (1 + series[(pn, rn)].loc[a:b]).prod() - 1
        cr.append(row)
    CR = pd.DataFrame(cr)
    CR.to_csv(RES / "t1_crises.csv", index=False, encoding="utf-8-sig")
    o.append("[위기 구간 손실] (1987은 학습 구간 실행분)")
    for _, x in CR.iterrows():
        o.append(f"  {x.crisis}: " + ", ".join(f"{rn} {x[rn]:+.1%}" for rn in rules if rn != "S&P 100%" or True))
    # 1987-10-19 하루
    d = pd.Timestamp("1987-10-19")
    o.append("  1987-10-19 하루: " + ", ".join(f"{rn} {series[('학습', rn)].loc[d]:+.1%}" for rn in rules))
    o.append("")

    # --- 최대 레버리지 사용 시점
    ml = []
    for pn in ("학습", "검증"):
        for rn, (tgt, mode, cm, grp) in rules.items():
            if not rn.startswith("VT") and not rn.startswith("고정"):
                continue
            h = helds[(pn, rn)]
            L = float(rn.split("L=")[1].split(" ")[0]) if rn.startswith("VT") else float(rn.split("x")[0].split()[-1])
            cap = h >= L - 0.05
            yrs = h[cap].groupby(h[cap].index.year).size().sort_values(ascending=False)
            top = ", ".join(f"{y}({c}일)" for y, c in yrs.head(5).items())
            ml.append({"period": pn, "rule": rn, "L": L, "w_max": h.max(), "w_max_date": h.idxmax().date(), "cap_days_ratio": cap.mean(),
                       "cap_days": int(cap.sum()), "top_years_at_cap": top,
                       "first_cap_date": h[cap].index[0].date() if cap.any() else None, "last_cap_date": h[cap].index[-1].date() if cap.any() else None})
    ML = pd.DataFrame(ml)
    ML.to_csv(RES / "t1_maxlev.csv", index=False, encoding="utf-8-sig")
    o.append("[최대 레버리지 사용] 상한 근접 = 노출 ≥ L−0.05")
    for _, x in ML[ML.period == "검증"].iterrows():
        o.append(f"  검증 {x.rule:<24} 최대 노출 {x.w_max:.2f} ({x.w_max_date})  상한 근접 {x.cap_days_ratio:4.0%} ({x.cap_days}일)  많은 연도: {x.top_years_at_cap}")
    o.append("")

    # --- 연간 매매 횟수
    ty = {}
    for rn in rules:
        s = pd.concat([trades_all[("학습", rn)], trades_all[("검증", rn)]])
        ty[rn] = s.groupby(s.index.year).sum().astype(int)
    TY = pd.DataFrame(ty)
    TY.index.name = "year"
    TY.to_csv(RES / "t1_trades_by_year.csv", encoding="utf-8-sig")
    o.append("[연간 매매 횟수] 검증 구간 평균/최대 (연도별 전체는 t1_trades_by_year.csv)")
    for rn in rules:
        v = TY.loc[2000:, rn]
        o.append(f"  {rn:<24} 평균 {v.mean():5.2f}  최대 {v.max():3d} ({v.idxmax()})  0회 연도 {(v == 0).sum()}개")
    o.append("")

    # --- SSO 실제 vs 2x ETF 모형
    sso = yahoo_daily("SSO", True).loc[:OOS[1]]
    s0 = sso.index[0]
    common = sso.index.intersection(R.index)
    rs = sso.reindex(common).pct_change().dropna()
    ri = R.loc[common]
    model = (ETF_LEV * ri.re - (ETF_LEV - 1) * (ri.rc + SPREAD / 252) - FEE / 252).reindex(rs.index)
    model0 = (ETF_LEV * ri.re - (ETF_LEV - 1) * ri.rc).reindex(rs.index)        # 보수·가산 없는 순수 2배
    yrs = len(rs) / 252
    cg = lambda s: (1 + s).prod() ** (1 / yrs) - 1
    beta = np.polyfit(ri.re.reindex(rs.index).values, rs.values, 1)[0]
    te = (rs - model).std() * np.sqrt(252)
    yearly = pd.DataFrame({"SSO": (1 + rs).groupby(rs.index.year).prod() - 1, "model": (1 + model).groupby(model.index.year).prod() - 1})
    yearly["diff_%p"] = (yearly.SSO - yearly.model) * 100
    SC = pd.DataFrame([{"start": rs.index[0].date(), "end": rs.index[-1].date(), "years": yrs, "SSO_CAGR": cg(rs), "model_CAGR": cg(model), "pure2x_CAGR": cg(model0),
                        "SSO_minus_model_%p/yr": (cg(rs) - cg(model)) * 100, "SSO_minus_pure2x_%p/yr": (cg(rs) - cg(model0)) * 100,
                        "daily_corr": rs.corr(model), "beta_to_SP": beta, "tracking_err_ann": te,
                        "SSO_vol": rs.std() * np.sqrt(252), "model_vol": model.std() * np.sqrt(252),
                        "SSO_MDD": ((1 + rs).cumprod() / (1 + rs).cumprod().cummax() - 1).min(), "model_MDD": ((1 + model).cumprod() / (1 + model).cumprod().cummax() - 1).min()}])
    SC.to_csv(RES / "t1_sso_check.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(RES / "t1_sso_yearly.csv", encoding="utf-8-sig")
    x = SC.iloc[0]
    o.append(f"[2x ETF 실제(SSO) vs 모형] {x.start}~{x.end} ({x.years:.1f}년, Yahoo 수정종가)")
    o.append(f"  SSO 연 {x.SSO_CAGR:.2%} | 모형(2·re − (TB3MS+0.5%) − 0.9%) 연 {x.model_CAGR:.2%} | 순수 2배(비용 0) 연 {x.pure2x_CAGR:.2%}")
    o.append(f"  SSO − 모형 = {x['SSO_minus_model_%p/yr']:+.2f}%p/년, SSO − 순수2배 = {x['SSO_minus_pure2x_%p/yr']:+.2f}%p/년 | 일간 상관 {x.daily_corr:.4f}, S&P 베타 {x.beta_to_SP:.3f}, 추적오차 {x.tracking_err_ann:.2%}")
    o.append(f"  MDD: SSO {x.SSO_MDD:.1%} vs 모형 {x.model_MDD:.1%} | 연도별 차이 최대 {yearly['diff_%p'].abs().max():.2f}%p ({yearly['diff_%p'].abs().idxmax()}년)")
    o.append("")

    # --- 사후 참고(판정 외): 각 VT 규칙의 검증 평균 노출을 고정 비중(월말 재조정, 차입 모형)으로 들었을 때
    ph = []
    for rn in rules:
        if not rn.startswith("VT") or not rn.endswith("[차입]"):
            continue
        x = RU[(RU.period == "검증") & (RU.rule == rn)].iloc[0]
        fx = pd.Series(x.w_avg, index=g.index)
        ret, held, tr, turn, _ = simulate(R, fx, OOS[0], OOS[1], "M", "margin")
        p_, q_, ps_ = boot(series[("검증", rn)], ret, rc.reindex(ret.index))
        ph.append({"rule": rn, "VT_CAGR": x.CAGR, "VT_MDD": x.MDD, "VT_Sharpe": x.Sharpe, "w_avg": x.w_avg,
                   "고정_CAGR": stats(ret, rc)["CAGR"], "고정_MDD": stats(ret, rc)["MDD"], "고정_Sharpe": stats(ret, rc)["Sharpe"],
                   "부트_P(VT CAGR>고정)": p_, "부트_P(VT Sharpe>고정)": ps_})
    PH = pd.DataFrame(ph)
    PH.to_csv(RES / "t1_posthoc_fixed.csv", index=False, encoding="utf-8-sig")
    o.append("[사후 참고, 판정 외] 검증 구간: VT 규칙 vs 같은 평균 노출의 고정 비중(월말 재조정, 차입 모형) — 변동성 타이밍 자체의 기여")
    for _, x in PH.iterrows():
        o.append(f"  {x.rule:<24} 평균 노출 {x.w_avg:.2f}: VT 연 {x.VT_CAGR:.2%} MDD {x.VT_MDD:.1%} Sharpe {x.VT_Sharpe:.3f} | 고정 연 {x['고정_CAGR']:.2%} MDD {x['고정_MDD']:.1%} Sharpe {x['고정_Sharpe']:.3f} | P(VT CAGR>고정) {x['부트_P(VT CAGR>고정)']:.3f}, P(Sharpe) {x['부트_P(VT Sharpe>고정)']:.3f}")
    o.append("")

    # --- 현재
    f = sig.iloc[-1]
    o.append(f"[현재] {g.index[-1].date()} 종가 {g.iloc[-1]:,.2f}: V3 예측 {f:.1%} → 목표 노출 σ*/σ̂ = {SIG_STAR / f:.2f} (L=1.25: {min(1.25, SIG_STAR / f):.2f}, L=1.5: {min(1.5, SIG_STAR / f):.2f}, L=2.0: {min(2.0, SIG_STAR / f):.2f})")
    for rn in rules:
        if rn.startswith("VT"):
            o.append(f"  {rn:<24} 검증 종료 보유 노출 {RU[(RU.period == '검증') & (RU.rule == rn)].iloc[0].end_w:.2f}")
    o.append("")

    # --- 일간 노출 저장
    W = pd.DataFrame({rn: pd.concat([helds[("학습", rn)], helds[("검증", rn)]]) for rn in rules if rn.startswith(("VT", "D1.0"))})
    W.insert(0, "V3", sig.reindex(W.index))
    W.insert(0, "close", g.reindex(W.index))
    W.index.name = "date"
    W.round(4).to_csv(RES / "t1_exposure.csv", encoding="utf-8-sig")
    txt = "\n".join(o)
    (RES / "t1_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
