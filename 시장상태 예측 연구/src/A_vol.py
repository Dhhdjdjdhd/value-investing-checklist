"""A. 변동성 예측과 변동성 목표화 (00_연구설계서 §A, 부록_A.md).

실행: py -I src/A_vol.py
산출: results/A_forecast.csv, A_models.csv, A_rules.csv, A_verdict.csv, A_summary.txt, data/A_TB3MS.csv
"""
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
DATA.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT.parent / "차트분석 4차 연구" / "src"))
sys.path.insert(0, str(ROOT.parent / "대안전략 연구" / "src"))
import p5_fear  # noqa: E402  (load)
import alloc  # noqa: E402
import valuation  # noqa: E402

UA = "Mozilla/5.0 (compatible; research-script)"
IS = ("1952-01-01", "1999-12-31")
OOS = ("2000-01-01", "2026-11-20")
H, LAM, COST, SPREAD, SEED = 21, 0.94, 0.001, 0.005, 20261122
LAG = 1  # 1 = t일 종가 신호를 t+1일 종가에 체결(수정판). 0 = 같은 종가 체결(이전판, *_sameclose 파일)
CRISES = {"닷컴 2000-03-24~2002-10-09": ("2000-03-24", "2002-10-09"),
          "금융위기 2007-10-09~2009-03-09": ("2007-10-09", "2009-03-09"),
          "코로나 2020-02-19~2020-03-23": ("2020-02-19", "2020-03-23"),
          "2022 2022-01-03~2022-10-12": ("2022-01-03", "2022-10-12")}


# ---------------------------------------------------------------- 데이터
def tb3ms():
    p = DATA / "A_TB3MS.csv"
    if not p.exists():
        u = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS"
        for k in range(3):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=90).read()
                break
            except Exception:
                time.sleep(3 * (k + 1))
        p.write_bytes(raw)
    d = pd.read_csv(p)
    s = pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").values, index=pd.to_datetime(d.iloc[:, 0]).dt.strftime("%Y-%m"))
    return s.dropna()


def build_returns(g):
    """일간 가격수익, 배당수익, 총수익, 현금수익."""
    mk = pd.Series(g.index.strftime("%Y-%m"), index=g.index)
    gm = g.groupby(mk.values).last()
    prev = gm.shift(1)
    prev.iloc[0] = g.iloc[0]
    nd = g.groupby(mk.values).size().astype(float)
    nd.iloc[-1] = max(nd.iloc[-1], 21.0)  # 마지막 달은 진행 중
    sh = valuation.shiller()
    dm = (sh.D / 12).reindex(gm.index) / prev          # 월 배당 수익 (Shiller)
    spy = alloc.yahoo("SPY", True)
    gap = (spy.pct_change().reindex(gm.index) - gm.pct_change()).loc[:"2026-10"]
    roll = gap.rolling(12).mean().clip(lower=0).reindex(gm.index).ffill()
    dm = dm.where(dm.notna() & (dm.index <= "2023-06"), roll)
    assert dm.notna().all(), "배당 결측"
    div = (dm / nd).reindex(mk.values).values
    tb = tb3ms().reindex(gm.index).ffill()
    assert tb.notna().all(), "TB3MS 결측"
    R = pd.DataFrame({"px": g.pct_change().values, "div": div, "rc": (tb / 100 / 252).reindex(mk.values).values}, index=g.index)
    R["re"] = R.px + R["div"]
    R["month"] = mk.values
    return R, dm, tb


# ---------------------------------------------------------------- GARCH
def _unpack(th, v0):
    w = np.exp(th[0]) * v0
    p = 0.9999 / (1 + np.exp(-th[1]))
    a = p / (1 + np.exp(-th[2]))
    return w, a, p - a


def garch_h(e, w, a, b, h0):
    """h[t] = w + a e[t-1]^2 + b h[t-1], h[0]=h0. 길이 len(e)+1 (마지막은 다음날 예측)."""
    x = w + a * e ** 2
    y, _ = lfilter([1.0], [1.0, -b], x, zi=[b * h0])
    return np.concatenate([[h0], y])


def garch_fit(e, start=None):
    v0 = e.var()

    def nll(th):
        w, a, b = _unpack(th, v0)
        h = garch_h(e, w, a, b, v0)[:-1]
        return 0.5 * np.sum(np.log(h) + e ** 2 / h)

    starts = [start] if start is not None else []
    starts += [np.array([np.log(0.02), 4.0, -2.5]), np.array([np.log(0.05), 3.0, -2.0])]
    best = None
    for s in starts:
        o = minimize(nll, s, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 4000})
        if best is None or o.fun < best.fun:
            best = o
    return best.x, _unpack(best.x, v0)


def garch_selftest():
    rng = np.random.default_rng(1)
    w, a, b = 1e-6, 0.08, 0.90
    n = 12000
    e = np.zeros(n)
    h = w / (1 - a - b)
    for t in range(n):
        e[t] = np.sqrt(h) * rng.standard_normal()
        h = w + a * e[t] ** 2 + b * h
    _, (w2, a2, b2) = garch_fit(e)
    return (w, a, b), (w2, a2, b2)


# ---------------------------------------------------------------- 예측
def forecasts(g, vix):
    """모든 값은 t일 종가까지의 정보만 쓴다. 반환: DataFrame(V1..V4, RVf), GARCH 모수표."""
    r = np.log(g).diff()
    r2 = (r ** 2).values
    n = len(g)
    F = pd.DataFrame(index=g.index)
    F["V1"] = np.sqrt(252 * pd.Series(r2, index=g.index).rolling(H).mean())
    v = np.full(n, np.nan)
    s = r2[1:H + 1].mean()
    v[H] = s
    for t in range(H + 1, n):
        s = LAM * s + (1 - LAM) * r2[t]
        v[t] = s
    F["V2"] = np.sqrt(252 * v)
    # V3: 매년 첫 거래일에 전년 말까지로 재추정
    yrs = g.index.year.values
    v3 = np.full(n, np.nan)
    pars, th = [], None
    rv = r.values
    for Y in range(1952, yrs.max() + 1):
        k = np.searchsorted(yrs, Y)          # Y년 첫 거래일 위치
        k2 = np.searchsorted(yrs, Y + 1)     # Y년 끝 다음 위치
        est = rv[1:k]
        mu = est.mean()
        e = est - mu
        th, (w, a, b) = garch_fit(e, th)
        h0 = e.var()
        eall = rv[1:k2] - mu
        h = garch_h(eall, w, a, b, h0)       # h[j]는 수익 index j+1 의 분산; h[len]은 다음날
        hn = h[1:]                           # hn[j] = eall[j](=수익 index j+1) 다음날 분산
        p = a + b
        vbar = w / (1 - p)
        avg = vbar + (hn - vbar) * (1 - p ** H) / (H * (1 - p))
        v3[k:k2] = avg[k - 1:k2 - 1]
        if np.isnan(v3[k - 1]):              # 첫 해만: 1951년 마지막 날 예측(같은 추정 표본) → 1952 첫날 비중용
            v3[k - 1] = avg[k - 2]
        pars.append({"year": Y, "n_obs": len(e), "mu": mu, "omega": w, "alpha": a, "beta": b,
                     "persist": p, "longrun_vol": np.sqrt(252 * vbar)})
    F["V3"] = np.sqrt(252 * v3)
    F["V4"] = (vix / 100).reindex(g.index)
    F["RVf"] = F["V1"].shift(-H)            # t+1 ~ t+21 실현
    return F, pd.DataFrame(pars)


def evaluate(F, model, a, b, monthly=False):
    last_ok = F.index[F.RVf.notna()]
    d = F.loc[a:b, [model, "RVf"]].dropna()
    # 목표 구간이 같은 구간 안에서 끝나야 한다
    pos = F.index.get_indexer(d.index) + H
    d = d[(pos < len(F.index)) & (F.index[np.minimum(pos, len(F.index) - 1)] <= pd.Timestamp(b))]
    if monthly:
        mk = d.index.strftime("%Y-%m")
        d = d[~pd.Series(mk, index=d.index).duplicated(keep="last").values]
    x, y = np.log(d[model].values), np.log(d.RVf.values)
    ratio = d.RVf.values ** 2 / d[model].values ** 2
    return {"N": len(d), "R2_reg": np.corrcoef(x, y)[0, 1] ** 2,
            "R2_direct": 1 - ((y - x) ** 2).sum() / ((y - y.mean()) ** 2).sum(),
            "QLIKE": np.mean(ratio - np.log(ratio) - 1), "bias_log": (x - y).mean()}


# ---------------------------------------------------------------- 엔진
def simulate(R, tgt, a, b, mode, thr=0.2):
    """tgt: t일 종가 목표 비중(Series). mode 'M'=월말마다, 'D'=|목표-보유|>thr 일 때.
    t일 종가에 매매, t+1일 수익부터 반영. 반환: 일간수익, 보유비중(그날 시작 시점), 회전, 종료 후 보유비중."""
    idx = R.index
    i0, i1 = idx.searchsorted(pd.Timestamp(a)), idx.searchsorted(pd.Timestamp(b), side="right")
    re, rc, mon = R.re.values, R.rc.values, R.month.values
    raw = tgt.reindex(idx)
    tg = raw.shift(LAG).values               # tg[i] = (i−LAG)일 종가 신호, i일 종가에 체결
    w0 = tg[i0 - 1]
    if not np.isfinite(w0):                  # 신호가 막 시작된 첫날만 같은 종가 신호로 진입
        w0 = raw.values[i0 - 1]
    assert np.isfinite(w0), "시작 비중 없음"
    tot = 1.0 - COST * abs(w0)
    E, C = tot * w0, tot * (1 - w0)
    prev_tot = 1.0
    rets, held, turn = np.empty(i1 - i0), np.empty(i1 - i0), abs(w0)
    for j, i in enumerate(range(i0, i1)):
        held[j] = E / (E + C)
        E *= 1 + re[i]
        C *= 1 + (rc[i] if C >= 0 else rc[i] + SPREAD / 252)
        tot = E + C
        cur = E / tot
        t = tg[i]
        k = i - LAG                           # 신호일
        last_day = (k + 1 >= len(idx)) or (mon[k + 1] != mon[k])
        do = np.isfinite(t) and ((mode == "M" and last_day) or (mode == "D" and abs(t - cur) > thr))
        if do and i + 1 < len(idx):
            d = abs(t - cur)
            tot *= 1 - COST * d
            turn += d
            E, C = tot * t, tot * (1 - t)
        rets[j] = tot / prev_tot - 1
        prev_tot = tot
    return pd.Series(rets, index=idx[i0:i1]), pd.Series(held, index=idx[i0:i1]), turn, E / (E + C)


def stats(ret, rc, held=None, turn=None):
    e = (1 + ret).cumprod()
    yrs = len(ret) / 252
    x = ret - rc.reindex(ret.index)
    out = {"CAGR": e.iloc[-1] ** (1 / yrs) - 1, "vol": ret.std() * np.sqrt(252),
           "Sharpe": x.mean() / x.std() * np.sqrt(252), "MDD": (e / np.maximum(e.cummax(), 1.0) - 1).min()}
    if held is not None:
        out["w_avg"] = held.mean()
        out["w_min"] = held.min()
    if turn is not None:
        out["turn_per_yr"] = turn / yrs
    return out


def boot_sharpe_diff(ra, rb, rc, n=1000, block=250):
    """원형 블록 부트스트랩: P(Sharpe_a − Sharpe_b > 0)."""
    rng = np.random.default_rng(SEED)
    xa, xb = (ra - rc).values, (rb - rc).values
    T = len(xa)
    nb = int(np.ceil(T / block))
    diffs = np.empty(n)
    off = np.arange(block)
    for k in range(n):
        st = rng.integers(0, T, nb)
        ii = ((st[:, None] + off[None, :]) % T).ravel()[:T]
        a_, b_ = xa[ii], xb[ii]
        diffs[k] = (a_.mean() / a_.std() - b_.mean() / b_.std()) * np.sqrt(252)
    return (diffs > 0).mean(), np.percentile(diffs, [5, 50, 95])


# ---------------------------------------------------------------- 실행
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    o = []
    g, vix = p5_fear.load("GSPC"), p5_fear.load("VIX")
    g = g.loc[:OOS[1]]
    R, dm, tb = build_returns(g)
    rc = R.rc

    # --- 엔진 검증
    o.append(f"[체결 규칙] t일 종가 신호 → t+{LAG}일 종가 체결 (LAG={LAG})")
    o.append("[엔진 검증]")
    tp, fp = garch_selftest()
    ok_g = abs(fp[1] - tp[1]) < 0.02 and abs(fp[2] - tp[2]) < 0.03
    o.append(f"  GARCH MLE 모의 자료: 참값 α {tp[1]:.3f} β {tp[2]:.3f} ω {tp[0]:.2e} → 추정 α {fp[1]:.3f} β {fp[2]:.3f} ω {fp[0]:.2e}  {'통과' if ok_g else '실패'}")
    F, P = forecasts(g, vix)
    cut = "2010-12-31"
    F2, _ = forecasts(g.loc[:cut], vix.loc[:cut])
    cols = ["V1", "V2", "V3", "V4"]
    A, B = F.loc[:cut, cols], F2[cols]
    same = bool(np.allclose(A.values, B.values, rtol=1e-9, atol=1e-12, equal_nan=True))
    o.append(f"  룩어헤드 점검(2010-12-31 절단 재계산 = 전체 계산, V1~V4 {A.notna().sum().sum():,}개 값): {'통과' if same else '실패'}")
    assert same, "룩어헤드 의심"
    one = pd.Series(1.0, index=g.index)
    for nm, (a, b) in (("학습", IS), ("검증", OOS)):
        ret, _, _, _ = simulate(R, one, a, b, "M")
        direct = (1 + R.re.loc[a:b]).prod() * (1 - COST)
        eng = (1 + ret).prod()
        o.append(f"  B&H 재현 {nm}: 엔진 {eng:.6f} vs 직접 누적×(1−진입비용) {direct:.6f}  {'통과' if abs(eng / direct - 1) < 1e-9 else '실패'}")
        assert abs(eng / direct - 1) < 1e-9
    mret = (1 + R.re).groupby(R.month).prod() - 1
    sh = valuation.shiller()
    shtr = ((sh.P + sh.D / 12) / sh.P.shift(1) - 1)
    spy = alloc.yahoo("SPY", True).pct_change()

    def cagr(s, a, b):
        s = s.loc[a:b].dropna()
        return (1 + s).prod() ** (12 / len(s)) - 1
    o.append(f"  총수익 대조 1952-01~2023-06: 내 일간 총수익 연 {cagr(mret, '1952-01', '2023-06'):.2%} vs Shiller 월간 총수익 연 {cagr(shtr, '1952-01', '2023-06'):.2%}")
    o.append(f"  총수익 대조 1993-03~2026-10: 내 일간 총수익 연 {cagr(mret, '1993-03', '2026-10'):.2%} vs SPY 수정주가 연 {cagr(spy, '1993-03', '2026-10'):.2%}")
    o.append(f"  배당 수익(연): 1952~1999 평균 {dm.loc['1952-01':'1999-12'].mean() * 12:.2%}, 2000~2023-06 {dm.loc['2000-01':'2023-06'].mean() * 12:.2%}, 2023-07~ {dm.loc['2023-07':].mean() * 12:.2%}")
    o.append(f"  T-bill(연): 1952~1999 평균 {tb.loc['1952-01':'1999-12'].mean():.2f}%, 2000~ {tb.loc['2000-01':].mean():.2f}%, 최근값 {tb.iloc[-1]:.2f}% (FRED 마지막 달 {tb3ms().index[-1]})")
    o.append("")

    # --- A1 예측 평가
    rows = []
    for m in cols:
        for pn, (a, b) in (("학습 1952~1999", IS), ("학습 중 1990~1999", ("1990-01-01", "1999-12-31")), ("검증 2000~2026", OOS)):
            if m == "V4" and pn.startswith("학습 1952"):
                continue
            for samp, mo in (("매일", False), ("월말", True)):
                rows.append({"model": m, "period": pn, "sample": samp, **evaluate(F, m, a, b, mo)})
    M = pd.DataFrame(rows)
    M.to_csv(RES / "A_models.csv", index=False, encoding="utf-8-sig")
    tr = M[(M.period == "학습 1952~1999") & (M["sample"] == "매일")].set_index("model")
    best = tr.QLIKE.idxmin()
    o.append("[A1 예측 평가] 목표 = 다음 21거래일 실현 변동성. R²는 log-log 회귀, QLIKE는 낮을수록 좋음")
    for pn in M.period.unique():
        o.append(f"  {pn}")
        for _, x in M[M.period == pn].iterrows():
            o.append(f"    {x.model} {x['sample']}  N {x.N:>6,}  R² {x.R2_reg:.3f}  R²(직접) {x.R2_direct:+.3f}  QLIKE {x.QLIKE:.4f}  log편향 {x.bias_log:+.3f}")
    o.append(f"  → 학습 1위(QLIKE 매일 표본, V1~V3): {best}  (R² 기준 1위: {tr.R2_reg.idxmax()})")
    g_last = P.iloc[-1]
    o.append(f"  GARCH 최근 모수({int(g_last.year)}년 1월 추정, {int(g_last.n_obs):,}일): α {g_last.alpha:.4f} β {g_last.beta:.4f} α+β {g_last.persist:.4f} 장기 변동성 {g_last.longrun_vol:.1%}")
    o.append("")

    # --- A2 전략
    v1 = F.V1.loc["1950-01-01":"1999-12-31"]
    sig_star = v1.mean()
    sig = F[best]
    T = {"1.0": (sig_star / sig).clip(upper=1.0), "1.5": (sig_star / sig).clip(upper=1.5)}
    T2 = {k: (sig_star / F2[best]).clip(upper=float(k)) for k in T}
    assert all(np.allclose(T[k].loc[:cut].values, T2[k].values, equal_nan=True) for k in T), "비중 룩어헤드"
    sma = g.rolling(200).mean()
    tf = (g > sma).astype(float).where(sma.notna())
    rules = {"M1.0": ("1.0", "M"), "D1.0": ("1.0", "D"), "M1.5": ("1.5", "M"), "D1.5": ("1.5", "D")}
    out, series, endw = [], {}, {}
    for pn, (a, b) in (("학습", IS), ("검증", OOS)):
        ret, held, turn, _ = simulate(R, one, a, b, "M")
        series[(pn, "B&H")] = ret
        out.append({"period": pn, "rule": "B&H", **stats(ret, rc, held, turn)})
        ret, held, turn, _ = simulate(R, tf, a, b, "D", 0.5)
        series[(pn, "TF200")] = ret
        out.append({"period": pn, "rule": "TF200", **stats(ret, rc, held, turn)})
        for rn, (L, mode) in rules.items():
            ret, held, turn, we = simulate(R, T[L], a, b, mode)
            series[(pn, rn)] = ret
            endw[(pn, rn)] = we
            s = stats(ret, rc, held, turn)
            out.append({"period": pn, "rule": rn, **s})
            fx = pd.Series(s["w_avg"], index=g.index)
            ret, held, turn, _ = simulate(R, fx, a, b, "M")
            series[(pn, f"고정({rn})")] = ret
            out.append({"period": pn, "rule": f"고정({rn} 평균 {s['w_avg']:.0%})", "match": rn, **stats(ret, rc, held, turn)})
    RU = pd.DataFrame(out)
    # 참고: 검증 하위 구간, 위기 구간
    for (pn, rn), ret in series.items():
        if pn != "검증":
            continue
        for sn, (a, b) in {"검증 전반 2000~2012": ("2000-01-01", "2012-12-31"), "검증 후반 2013~2026": ("2013-01-01", OOS[1])}.items():
            lab = RU[(RU.period == "검증")].iloc[[list(k for k in series if k[0] == "검증").index((pn, rn))]].rule.iloc[0]
            RU = pd.concat([RU, pd.DataFrame([{"period": sn, "rule": lab, **stats(ret.loc[a:b], rc)}])], ignore_index=True)
    RU.to_csv(RES / "A_rules.csv", index=False, encoding="utf-8-sig")

    o.append(f"[A2 변동성 목표화] σ* = {sig_star:.2%} (1950~1999 21일 실현 변동성 평균), 예측 모델 = {best}")
    o.append("  시험 수: 예측 모델 4개, 전략 규칙 4개(판정 대상은 L=1.0 두 개 중 학습 1위 하나)")
    for pn in RU.period.unique():
        o.append(f"  {pn}")
        for _, x in RU[RU.period == pn].iterrows():
            extra = f"  평균비중 {x.w_avg:4.0%}  회전/년 {x.turn_per_yr:5.2f}" if pd.notna(x.get("w_avg")) else ""
            o.append(f"    {x.rule:<22} 연 {x.CAGR:6.2%}  변동성 {x.vol:5.1%}  Sharpe {x.Sharpe:.3f}  MDD {x.MDD:6.1%}{extra}")
    cr = []
    for cn, (a, b) in CRISES.items():
        cr.append("    " + cn + ": " + ", ".join(f"{rn} {(1 + series[('검증', rn)].loc[a:b]).prod() - 1:+.1%}" for rn in ["B&H", "TF200", "M1.0", "D1.0", "M1.5", "D1.5"]))
    o.append("  위기 구간 수익(참고)")
    o += cr
    o.append("")

    # --- 사후 참고(판정 외): V2(EWMA)로 같은 D1.0
    TV2 = (sig_star / F.V2).clip(upper=1.0)
    ph = []
    for pn, (a, b) in (("학습", IS), ("검증", OOS)):
        ret, held, turn, we = simulate(R, TV2, a, b, "D")
        s = stats(ret, rc, held, turn)
        if pn == "검증":
            s["부트_P(Sharpe차>0)"], _ = boot_sharpe_diff(ret, series[("검증", "B&H")], rc.reindex(ret.index))
            s["현재보유"] = we
            for sn, (a2, b2) in {"전반 2000~2012": ("2000-01-01", "2012-12-31"), "후반 2013~2026": ("2013-01-01", OOS[1])}.items():
                s[f"Sharpe_{sn}"] = stats(ret.loc[a2:b2], rc)["Sharpe"]
        ph.append({"period": pn, "rule": "D1.0(V2 EWMA, 사후 참고)", **s})
    PH = pd.DataFrame(ph)
    PH.to_csv(RES / "A_posthoc_V2.csv", index=False, encoding="utf-8-sig")
    o.append("[사후 참고, 판정 외] V2(EWMA)로 같은 D1.0")
    for _, x in PH.iterrows():
        o.append(f"    {x.period} 연 {x.CAGR:6.2%}  변동성 {x.vol:5.1%}  Sharpe {x.Sharpe:.3f}  MDD {x.MDD:6.1%}  평균비중 {x.w_avg:4.0%}  회전/년 {x.turn_per_yr:5.2f}"
                 + (f"  부트 P {x['부트_P(Sharpe차>0)']:.3f}  전반 Sharpe {x['Sharpe_전반 2000~2012']:.3f}  후반 Sharpe {x['Sharpe_후반 2013~2026']:.3f}" if x.period == "검증" else ""))
    o.append("")

    # --- 판정
    L1 = RU[(RU.period == "학습") & RU.rule.isin(["M1.0", "D1.0"])].sort_values(["Sharpe", "MDD"], ascending=False)
    top = L1.iloc[0].rule
    V = []
    vr = RU[RU.period == "검증"]
    bh = vr[vr.rule == "B&H"].iloc[0]
    for rn in rules:
        x = vr[vr.rule == rn].iloc[0]
        fxr = vr[vr.match == rn].iloc[0]
        p, q = boot_sharpe_diff(series[("검증", rn)], series[("검증", "B&H")], rc.reindex(series[("검증", rn)].index))
        pf, qf = boot_sharpe_diff(series[("검증", rn)], series[("검증", f"고정({rn})")], rc.reindex(series[("검증", rn)].index))
        c1 = bool(x.Sharpe > bh.Sharpe and x.Sharpe > fxr.Sharpe)
        c2 = bool(x.MDD - bh.MDD >= 0.05)
        c3 = bool(p >= 0.90)
        verdict = "채택" if c1 and c2 and c3 else ("보류" if c1 and c2 else "탈락")
        role = "판정 대상(학습 1위)" if rn == top else ("참고(L=1.0 학습 2위)" if rn.endswith("1.0") else "참고(L=1.5)")
        tr_ = RU[(RU.period == "학습") & (RU.rule == rn)].iloc[0]
        V.append({"rule": rn, "역할": role, "학습_Sharpe": tr_.Sharpe, "학습_MDD": tr_.MDD,
                  "검증_Sharpe": x.Sharpe, "B&H_Sharpe": bh.Sharpe, "고정비중_Sharpe": fxr.Sharpe,
                  "검증_MDD": x.MDD, "B&H_MDD": bh.MDD, "MDD개선_%p": (x.MDD - bh.MDD) * 100,
                  "검증_CAGR": x.CAGR, "B&H_CAGR": bh.CAGR, "평균비중": x.w_avg,
                  "부트_P(Sharpe차>0)": p, "Sharpe차_5%": q[0], "Sharpe차_50%": q[1], "Sharpe차_95%": q[2],
                  "부트_P(고정비중 대비>0)": pf,
                  "기준1_Sharpe": c1, "기준2_MDD": c2, "기준3_부트": c3, "판정": verdict})
    V = pd.DataFrame(V)
    V.to_csv(RES / "A_verdict.csv", index=False, encoding="utf-8-sig")
    o.append("[판정] 기준: ①검증 Sharpe > B&H 그리고 > 평균 노출 맞춤 고정 비중 ②MDD 5%p 이상 개선 ③부트스트랩 P ≥ 0.90")
    o.append(f"  학습 1위(L=1.0): {top}  (학습 Sharpe " + ", ".join(f"{r.rule} {r.Sharpe:.3f}" for _, r in L1.iterrows()) + ")")
    for _, x in V.iterrows():
        o.append(f"  {x.rule} [{x['역할']}] Sharpe {x['검증_Sharpe']:.3f} (B&H {x['B&H_Sharpe']:.3f}, 고정 {x['고정비중_Sharpe']:.3f}) {'O' if x['기준1_Sharpe'] else 'X'}"
                 f" | MDD {x['검증_MDD']:.1%} (B&H {x['B&H_MDD']:.1%}, 개선 {x['MDD개선_%p']:+.1f}%p) {'O' if x['기준2_MDD'] else 'X'}"
                 f" | 부트 P {x['부트_P(Sharpe차>0)']:.3f} (Sharpe차 5~95% {x['Sharpe차_5%']:+.3f}~{x['Sharpe차_95%']:+.3f}) {'O' if x['기준3_부트'] else 'X'}"
                 f" | 고정 대비 P {x['부트_P(고정비중 대비>0)']:.3f} → {x['판정']}")
    fin = V[V.rule == top].iloc[0]
    o.append(f"  ▶ 파트 A 최종 판정: {top} = {fin['판정']}")
    o.append("")

    # --- 현재
    d = g.index[-1]
    f = F.iloc[-1]
    o.append(f"[현재] {d.date()} 종가 {g.iloc[-1]:,.2f} 기준")
    o.append(f"  예측 변동성(연율, 다음 21거래일): V1 {f.V1:.1%} | V2 {f.V2:.1%} | V3 {f.V3:.1%} | V4(VIX) {f.V4:.1%}")
    o.append(f"  채택 모델 {best} = {f[best]:.1%}, σ* = {sig_star:.1%} → 목표 비중 L=1.0: {T['1.0'].iloc[-1]:.0%}, L=1.5: {T['1.5'].iloc[-1]:.0%}")
    pct = (F[best].loc[:d] < f[best]).mean()
    o.append(f"  현재 {best} 예측은 1952년 이후 분포의 {pct:.0%} 분위 (검증 구간 중앙값 {F[best].loc[OOS[0]:].median():.1%})")
    me = R.index[(R.month != R.month.shift(-1)) & (R.index < d)][-1]
    o.append(f"  월간 규칙(M1.0): 지금 적용 중인 비중은 {me.date()} 종가 신호분(다음 거래일 종가 체결) {T['1.0'].loc[me]:.0%} (당시 예측 {F[best].loc[me]:.1%}). 오늘 다시 계산하면 {T['1.0'].iloc[-1]:.0%}")
    o.append(f"  매일 규칙(D1.0): 현재 보유 비중 {endw[('검증', 'D1.0')]:.0%}, 목표 {T['1.0'].iloc[-1]:.0%} → 차이 {abs(T['1.0'].iloc[-1] - endw[('검증', 'D1.0')]):.0%}p ({'다음 거래일 매매' if abs(T['1.0'].iloc[-1] - endw[('검증', 'D1.0')]) > 0.2 else '유지'})")
    o.append(f"  참고 L=1.5: M1.5 적용 중 {T['1.5'].loc[me]:.0%}, D1.5 보유 {endw[('검증', 'D1.5')]:.0%}")

    o.append("")
    o.append("[한계]")
    o.append("  - 학습 구간은 GARCH 예열 때문에 1952-01부터다(설계서는 1950-01).")
    o.append("  - 체결: t일 종가 신호를 t+1일 종가에 체결한다(수정판, LAG=1). 같은 종가에 체결한 이전판은 *_sameclose 파일에 있다.")
    o.append("  - 배당은 월 배당을 거래일에 고르게 나눈 값이고, 2023-07 이후는 SPY와 지수의 수익 차이로 추정했다.")
    o.append("  - 비용은 편도 0.1%뿐이다. 세금과 환율은 넣지 않았다(달러 기준).")
    o.append("  - 모델 선택 기준(QLIKE)과 R² 기준의 1위가 다르다. R² 1위인 V2로 돌린 D1.0은 사후 참고로만 냈다(판정 외).")
    o.append("  - VIX(V4)는 R²가 가장 높지만 수준이 실현 변동성보다 높게 치우쳐 있고 1990년부터만 있어 전략에 쓰지 않았다.")

    FO = F.loc["1952-01-01":, ["RVf"] + cols].copy()
    FO.insert(0, "close", g)
    FO["w_L1.0"] = T["1.0"]
    FO["w_L1.5"] = T["1.5"]
    FO.index.name = "date"
    FO.round(6).to_csv(RES / "A_forecast.csv", encoding="utf-8-sig")
    P.to_csv(RES / "A_garch_params.csv", index=False, encoding="utf-8-sig")
    txt = "\n".join(o)
    (RES / "A_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
