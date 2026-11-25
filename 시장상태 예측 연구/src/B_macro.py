"""파트 B. 경기침체 신호와 조건부 확률표 (00_연구설계서 §B, 부록_B.md).

실행: py -I src/B_macro.py
산출: results/B_models.csv, B_rules.csv, B_verdict.csv, B_table.csv, B_calibration.csv,
      B_calibration_score.csv, B_current.csv, B_summary.txt
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
DATA, RES = ROOT / "data", ROOT / "results"
RES.mkdir(exist_ok=True)
GSPC = ROOT.parent / "차트분석 4차 연구" / "data" / "GSPC.json"
sys.path.insert(0, str(ROOT.parent / "대안전략 연구" / "src"))

SEED = 20261122
COST = 0.001
LAM = 0.94
LABEL_LAG = 36          # 결정월 d 의 Y 는 d+36개월 뒤부터 추정에 사용 (12개월 창 + 24개월 판정 지연)
MIN_N = 120
TRAIN_END, VALID_START = "1999-12", "2000-01"
RULES = ["R1>0.5", "R2", "R3>0.5", "R1|R2"]
OUT = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


# ---------------------------------------------------------------- 자료
def load_fred(cut=None):
    d = {}
    for k in ["GS10", "TB3MS", "SAHMREALTIME", "UNRATE", "BAA", "AAA", "USREC"]:
        s = pd.read_csv(DATA / f"fred_{k}.csv", index_col=0, parse_dates=True).iloc[:, 0]
        s = pd.to_numeric(s, errors="coerce").dropna()
        s.index = s.index.to_period("M")
        d[k] = s
    f = pd.DataFrame(d)
    if cut is not None:
        f = f.loc[:pd.Period(cut, "M")]
    return f


def load_gspc(cut=None):
    r = json.load(open(GSPC))["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"],
                  index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    s = s.dropna().groupby(level=0).last()
    return s if cut is None else s.loc[:cut]


def sahm_from_unrate(u):
    ma3 = u.rolling(3).mean()
    return ma3 - ma3.shift(1).rolling(12).min()


def build_macro(f, last_dec):
    """결정월 d 기준 표. x 는 d−1월 값(발표 지연 1개월)."""
    idx = pd.period_range("1949-01", last_dec, freq="M")
    f = f.reindex(pd.period_range(f.index[0], max(f.index[-1], idx[-1]), freq="M"))
    spread = f.GS10 - f.TB3MS
    cs = f.BAA - f.AAA
    sahm_rev = sahm_from_unrate(f.UNRATE)
    sahm = f.SAHMREALTIME.combine_first(sahm_rev)
    m = pd.DataFrame(index=idx)
    m["spread"] = spread.shift(1).reindex(idx)
    m["dcs6"] = (cs - cs.shift(6)).shift(1).reindex(idx)
    m["sahm"] = sahm.shift(1).reindex(idx)
    m["sahm_revised"] = f.SAHMREALTIME.shift(1).reindex(idx).isna()
    u = f.USREC
    y = u[::-1].rolling(12, min_periods=12).max()[::-1].shift(-1)   # d+1..d+12 중 침체
    m["Y"] = y.reindex(idx)
    m["usrec"] = u.reindex(idx)
    return m, (sahm_rev, f.SAHMREALTIME)


# ---------------------------------------------------------------- probit
def probit_fit(X, y, it=100):
    X = np.column_stack([np.ones(len(X)), np.asarray(X, float)])
    y = np.asarray(y, float)
    b = np.zeros(X.shape[1])
    b[0] = norm.ppf(np.clip(y.mean(), 1e-4, 1 - 1e-4))
    for _ in range(it):
        z = np.clip(X @ b, -8, 8)
        p, q = norm.cdf(z), norm.pdf(z)
        p = np.clip(p, 1e-10, 1 - 1e-10)
        lam = np.where(y == 1, q / p, -q / (1 - p))
        g = X.T @ lam
        H = -(X * (lam * (lam + z))[:, None]).T @ X
        step = np.linalg.solve(H - 1e-9 * np.eye(len(b)), g)
        b = b - step
        if np.abs(step).max() < 1e-9:
            break
    return b


def probit_pred(b, X):
    X = np.column_stack([np.ones(len(X)), np.asarray(X, float)])
    return norm.cdf(X @ b)


def expanding_probs(m):
    """매년 12월 말 확장 창 재추정 -> 다음 해 결정월의 확률. 반환: p1, p2, p3, 계수 기록."""
    p = pd.DataFrame(index=m.index, columns=["p1", "p2", "p3"], dtype=float)
    coefs = []
    for yr in range(m.index[0].year + 1, m.index[-1].year + 1):
        T = pd.Period(f"{yr - 1}-12", "M")
        tr = m.loc[:T - LABEL_LAG]
        use = m.index[m.index.year == yr]
        t1 = tr.dropna(subset=["spread", "Y"])
        if len(t1) >= MIN_N and t1.Y.nunique() == 2:
            b = probit_fit(t1[["spread"]], t1.Y)
            ok = m.loc[use, "spread"].notna()
            p.loc[use[ok], "p1"] = probit_pred(b, m.loc[use[ok], ["spread"]])
            coefs.append({"est": str(T), "model": "R1", "n": len(t1), "a": b[0], "b_spread": b[1]})
        t3 = tr.dropna(subset=["spread", "dcs6", "Y"])
        if len(t3) >= MIN_N and t3.Y.nunique() == 2:
            b = probit_fit(t3[["spread", "dcs6"]], t3.Y)
            ok = m.loc[use, ["spread", "dcs6"]].notna().all(axis=1)
            p.loc[use[ok], "p3"] = probit_pred(b, m.loc[use[ok], ["spread", "dcs6"]])
            coefs.append({"est": str(T), "model": "R3", "n": len(t3), "a": b[0], "b_spread": b[1], "c_dcs6": b[2]})
        t2 = tr.dropna(subset=["sahm", "Y"])
        if len(t2) >= MIN_N:
            on = t2.sahm >= 0.5
            pon = t2.Y[on].mean() if on.any() else t2.Y.mean()
            poff = t2.Y[~on].mean() if (~on).any() else t2.Y.mean()
            ok = m.loc[use, "sahm"].notna()
            p.loc[use[ok], "p2"] = np.where(m.loc[use[ok], "sahm"] >= 0.5, pon, poff)
            coefs.append({"est": str(T), "model": "R2", "n": len(t2), "p_on": pon, "p_off": poff, "n_on": int(on.sum())})
    return p, pd.DataFrame(coefs)


def auc(score, y):
    d = pd.DataFrame({"s": score, "y": y}).dropna()
    r = d.s.rank()
    n1, n0 = (d.y == 1).sum(), (d.y == 0).sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    return (r[d.y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def reliability(pred, obs, years, spec, event, nb=10):
    d = pd.DataFrame({"p": pred, "o": obs, "yr": years}).dropna()
    if d.p.nunique() <= nb:
        d["bin"] = d.p.rank(method="dense").astype(int)
    else:
        d["bin"] = pd.qcut(d.p, nb, labels=False, duplicates="drop") + 1
    g = d.groupby("bin").agg(pred_mean=("p", "mean"), obs_freq=("o", "mean"), n=("o", "size"), n_years=("yr", "nunique"))
    g.insert(0, "event", event)
    g.insert(0, "spec", spec)
    return g.reset_index()


# ---------------------------------------------------------------- 월간 수익과 전략
def monthly_returns(g, f):
    import valuation
    sh = valuation.shiller()
    pm = g.groupby(g.index.to_period("M")).last()
    D = sh.D.copy()
    D.index = pd.PeriodIndex(D.index, freq="M")
    Psh = sh.P.copy()
    Psh.index = D.index
    lastd = D.dropna().index[-1]
    dy = (D / Psh).loc[lastd]
    div = (D / 12).reindex(pm.index)
    div[pm.index > lastd] = (pm * dy / 12)[pm.index > lastd]
    rs = (pm + div) / pm.shift(1) - 1
    rc = (f.TB3MS / 1200).reindex(pm.index).ffill()
    # Shiller 월평균 기준 총수익 (점검용)
    sh_tr = ((Psh + D / 12) / Psh.shift(1) - 1)
    return pd.DataFrame({"rs": rs, "rc": rc, "px": pm}).dropna(subset=["rs"]), sh_tr, str(lastd), dy


def sim(w, R):
    """w: 그 달 주식 비중(이미 한 달 밀린 것)."""
    w = w.reindex(R.index).astype(float)
    turn = w.diff().abs().fillna(0)
    return w * R.rs + (1 - w) * R.rc - COST * turn


def stats(r, rc):
    ex = r - rc
    eq = (1 + r).cumprod()
    n = len(r)
    return {"CAGR": eq.iloc[-1] ** (12 / n) - 1, "vol": r.std() * np.sqrt(12),
            "Sharpe": ex.mean() / ex.std() * np.sqrt(12),
            "MDD": (eq / eq.cummax().clip(lower=1) - 1).min()}


def boot_sharpe(r, b, rc, n_boot=1000, block=12):
    rng = np.random.default_rng(SEED)
    a, c = (r - rc).values, (b - rc).values
    n = len(a)
    nb = int(np.ceil(n / block))
    hit = 0
    diffs = []
    for _ in range(n_boot):
        st = rng.integers(0, n, nb)
        ix = ((st[:, None] + np.arange(block)[None, :]) % n).ravel()[:n]
        x, y = a[ix], c[ix]
        dlt = x.mean() / x.std(ddof=1) - y.mean() / y.std(ddof=1)
        diffs.append(dlt * np.sqrt(12))
        hit += dlt > 0
    return hit / n_boot, np.percentile(diffs, [5, 50, 95])


def monthly_signals(m, p):
    s = pd.DataFrame(index=m.index)
    s["R1>0.5"] = p.p1 > 0.5
    s["R2"] = m.sahm >= 0.5
    s["R3>0.5"] = p.p3 > 0.5
    s["R1|R2"] = s["R1>0.5"] | s["R2"]
    return s


# ---------------------------------------------------------------- 일간 상태와 조건부 표
def ewma_vol(g):
    r = np.log(g).diff().values
    v = np.full(len(r), np.nan)
    v[21] = np.nanmean(r[1:22] ** 2)
    for i in range(22, len(r)):
        v[i] = LAM * v[i - 1] + (1 - LAM) * r[i] ** 2
    v[:60] = np.nan
    return pd.Series(np.sqrt(252 * v), index=g.index)


def daily_states(g, p1_dec, vol_cuts=None):
    """p1_dec: 결정월 d 의 R1 확률 -> d+1월의 모든 날에 적용."""
    st = pd.DataFrame(index=g.index)
    st["px"] = g
    st["v2"] = ewma_vol(g)
    if vol_cuts is None:
        vol_cuts = st.v2.loc[:"1999-12-31"].quantile([1 / 3, 2 / 3]).values
    st["vol"] = np.where(st.v2.isna(), None, np.where(st.v2 <= vol_cuts[0], "1낮음", np.where(st.v2 <= vol_cuts[1], "2중간", "3높음")))
    st["ddv"] = g / g.cummax() - 1
    st["dd"] = np.select([st.ddv > -0.05, st.ddv > -0.10, st.ddv > -0.20], ["1: 0~-5", "2: -5~-10", "3: -10~-20"], "4: -20이하")
    sma = g.rolling(200).mean()
    st["ma"] = np.where(sma.isna(), None, np.where(g > sma, "위", "아래"))
    mon = g.index.to_period("M")
    papp = p1_dec.shift(1)                      # m월에 적용되는 확률 = m−1월 말 결정
    st["p1"] = papp.reindex(mon).values
    st["r1"] = np.where(st.p1.isna(), None, np.where(st.p1 > 0.3, "높음", "낮음"))
    return st, vol_cuts


def outcomes(st):
    a = st.px.values
    n = len(a)
    o = pd.DataFrame(index=st.index)
    for k, h in {"r1m": 21, "r3m": 63, "r12m": 252}.items():
        r = np.full(n, np.nan)
        r[: n - 1 - h] = a[1 + h:] / a[1: n - h] - 1
        o[k] = r
    fmin = pd.Series(a[::-1]).rolling(252, min_periods=252).min().values[::-1]      # t..t+251 최소
    fmin_next = np.r_[fmin[1:], np.nan]                                              # t+1..t+252
    o["add10"] = np.where(np.isnan(fmin_next), np.nan, (fmin_next / a <= 0.90).astype(float))
    dd = st.ddv.values
    dmin = pd.Series(dd[::-1]).rolling(252, min_periods=252).min().values[::-1]
    dmin_next = np.r_[dmin[1:], np.nan]
    o["hit20"] = np.where(np.isnan(dmin_next), np.nan, (dmin_next <= -0.20).astype(float))
    o["neg12"] = np.where(np.isnan(o.r12m), np.nan, (o.r12m < 0).astype(float))
    full = ~np.isnan(o.r12m.values)
    end_date = pd.Series(st.index).shift(-253).values                               # 결과 창 끝 날짜
    o["window_end"] = end_date
    o["full"] = full
    return o


def cl_se(x, yr):
    d = pd.DataFrame({"x": x, "g": yr}).dropna()
    G = d.g.nunique()
    if G < 2:
        return np.nan
    e = (d.x - d.x.mean()).groupby(d.g).sum()
    return np.sqrt((e ** 2).sum() / len(d) ** 2 * G / (G - 1))


def cell_stats(d):
    yr = d.index.year
    run = (pd.Series(d["_pos"].values).diff() != 1).sum()
    r = {"n_days": len(d), "n_runs": int(run), "n_years": int(pd.Index(yr).nunique())}
    for k in ["r1m", "r3m", "r12m"]:
        q = d[k].quantile([0.1, 0.5, 0.9]).values
        r.update({f"{k}_q10": q[0], f"{k}_q50": q[1], f"{k}_q90": q[2]})
    for k in ["add10", "hit20", "neg12"]:
        r[f"p_{k}"] = d[k].mean()
        r[f"se_{k}"] = cl_se(d[k].values, yr)
    r["flag"] = "참고" if r["n_years"] < 5 else ""
    return pd.Series(r)


SPECS = {"vol": ["vol"], "dd": ["dd"], "ma": ["ma"], "r1": ["r1"],
         "T3": ["vol", "dd", "ma"], "T4": ["vol", "dd", "ma", "r1"]}
FALLBACK = {"T4": ["T4", "T3", "dd"], "T3": ["T3", "dd"], "vol": ["vol"], "dd": ["dd"], "ma": ["ma"], "r1": ["r1"]}
EVENTS = ["add10", "hit20", "neg12"]


def make_tables(X):
    """X: 상태+결과, 결과 창이 온전한 날만. sample 열 포함."""
    rows = []
    for sname, keys in SPECS.items():
        base = X.dropna(subset=keys)
        if "r1" in keys:
            base = base[base.index >= "1967-01-01"]
        for smp in ["학습", "검증", "전체"]:
            d = base if smp == "전체" else base[base["sample"] == smp]
            if d.empty:
                continue
            t = d.groupby(keys).apply(cell_stats).reset_index()
            for k in ["vol", "dd", "ma", "r1"]:
                if k not in t:
                    t[k] = "-"
            t.insert(0, "sample", smp)
            t.insert(0, "table", sname)
            rows.append(t)
    T = pd.concat(rows, ignore_index=True)
    front = ["table", "sample", "vol", "dd", "ma", "r1", "flag", "n_days", "n_runs", "n_years"]
    return T[front + [c for c in T.columns if c not in front]]


def predict_from_table(X, sname, ev):
    """학습 표로 검증 구간 예측. 반환: (예측, 기준 확률, 관측, 내려간 비율)."""
    r1_based = sname in ("T4", "r1")
    tr = X[X["sample"] == "학습"]
    va = X[X["sample"] == "검증"]
    if r1_based:
        tr = tr[tr.index >= "1967-01-01"].dropna(subset=["r1"])
        va = va.dropna(subset=["r1"])
    base = tr[ev].mean()
    pred = pd.Series(np.nan, index=va.index)
    level = pd.Series("기준", index=va.index)
    for fb in FALLBACK[sname]:
        keys = SPECS[fb]
        g = tr.dropna(subset=keys).groupby(keys)
        cell = pd.DataFrame({"p": g[ev].mean(), "ny": g.apply(lambda d: d.index.year.nunique())})
        cell = cell[cell.ny >= 5]
        j = va[keys].merge(cell, left_on=keys, right_index=True, how="left")["p"]
        j.index = va.index
        fill = pred.isna() & j.notna()
        pred[fill] = j[fill]
        level[fill] = fb
    pred = pred.fillna(base)
    return pred, base, va[ev], level


def boot_brier(e_model, e_base, n_boot=1000, block=250):
    rng = np.random.default_rng(SEED)
    d = (e_model - e_base)
    n = len(d)
    nb = int(np.ceil(n / block))
    st = rng.integers(0, n, (n_boot, nb))
    cs = np.concatenate([[0], np.cumsum(np.r_[d, d])])
    tot = (cs[st + block] - cs[st]).sum(axis=1)
    return (tot < 0).mean()


# ---------------------------------------------------------------- 전체 계산 (자르기 점검에 재사용)
def compute(cut=None):
    f = load_fred(cut)
    g = load_gspc(cut)
    last_dec = str(g.index[-1].to_period("M"))
    m, sahm_pair = build_macro(f, last_dec)
    p, coefs = expanding_probs(m)
    sig = monthly_signals(m, p)
    return dict(f=f, g=g, m=m, p=p, coefs=coefs, sig=sig, sahm_pair=sahm_pair)


def main():
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.float_format", lambda x: f"{x:.4f}")
    C = compute()
    f, g, m, p, coefs, sig = C["f"], C["g"], C["m"], C["p"], C["coefs"], C["sig"]
    say("=== 파트 B. 경기침체 신호와 조건부 확률표 ===")
    say(f"자료: GSPC {g.index[0].date()} ~ {g.index[-1].date()}, FRED ~ {f.index[-1]}")

    # ---------- 엔진 검증 0: probit 모의 자료
    rng = np.random.default_rng(1)
    Xs = rng.normal(size=(20000, 2))
    ys = (0.3 - 0.8 * Xs[:, 0] + 0.5 * Xs[:, 1] + rng.normal(size=20000) > 0).astype(float)
    bs = probit_fit(Xs, ys)
    say(f"\n[검증] probit 모의 자료 계수(참값 0.3, -0.8, 0.5): {np.round(bs, 3)}")
    rev, rt = C["sahm_pair"]
    ov = pd.concat([rev, rt], axis=1).dropna()
    say(f"[점검] UNRATE로 계산한 삼 규칙 vs SAHMREALTIME ({ov.index[0]}~): 상관 {ov.corr().iloc[0, 1]:.3f}, "
        f"평균 절대차 {(ov.iloc[:, 0] - ov.iloc[:, 1]).abs().mean():.3f}")

    # ---------- B2 모델 평가
    say("\n--- B2. 침체 확률 모델 ---")
    first = p.dropna(subset=["p1"]).index[0]
    say(f"첫 확률: R1 {first}, R3 {p.p3.dropna().index[0]}, R2 {p.p2.dropna().index[0]}")
    say("마지막 추정 계수:")
    say(coefs.groupby("model").tail(1).to_string(index=False))
    base_rate = m.loc["1950-01":TRAIN_END, "Y"].mean()
    va = m.loc[VALID_START:].dropna(subset=["Y"])
    tr = m.loc[str(first):TRAIN_END]
    say(f"기준 확률(1950-01~1999-12 Y 빈도) = {base_rate:.4f}; 검증 결정월 {va.index[0]}~{va.index[-1]} ({len(va)}개월), 검증 Y 빈도 {va.Y.mean():.4f}")
    rows, cal = [], []
    for name, pc, sc in [("R1 금리차 probit", "p1", "spread"), ("R2 삼 규칙", "p2", "sahm"), ("R3 금리차+신용Δ6 probit", "p3", None)]:
        for smp, d in [("학습(1967~1999)", tr), ("검증(2000~)", va)]:
            pp = p.loc[d.index, pc]
            ok = pp.notna()
            y = d.Y[ok]
            bs_m = ((pp[ok] - y) ** 2).mean()
            bs_b = ((base_rate - y) ** 2).mean()
            score = pp[ok] if sc is None else (-d.loc[ok, sc] if sc == "spread" else d.loc[ok, sc])
            row = {"model": name, "sample": smp, "n": int(ok.sum()), "Y_freq": y.mean(), "Brier": bs_m, "Brier_base": bs_b,
                   "skill": 1 - bs_m / bs_b, "AUC": auc(score, y), "p_mean": pp[ok].mean(), "p_max": pp[ok].max(),
                   "months_p>0.5": int((pp[ok] > 0.5).sum()), "months_p>0.3": int((pp[ok] > 0.3).sum())}
            if smp.startswith("검증"):
                e1, e0 = ((pp[ok] - y) ** 2).values, ((base_rate - y) ** 2).values
                rng = np.random.default_rng(SEED)
                n, blk = len(e1), 12
                hits = 0
                for _ in range(1000):
                    st_ = rng.integers(0, n, int(np.ceil(n / blk)))
                    ix = ((st_[:, None] + np.arange(blk)[None, :]) % n).ravel()[:n]
                    hits += e1[ix].mean() < e0[ix].mean()
                row["boot_P(Brier<base)"] = hits / 1000
                row["판정"] = "예측력 있음" if bs_m < bs_b else "예측력 없음"
                cal.append(reliability(pp[ok].values, y.values, y.index.year, name.split()[0], "침체12개월"))
            rows.append(row)
    models = pd.DataFrame(rows)
    models.to_csv(RES / "B_models.csv", index=False, encoding="utf-8-sig")
    say(models.to_string(index=False))
    # 신호별 적중 (검증)
    say("\n검증 구간 침체 시작(USREC 0→1)과 신호 선행:")
    u = m.usrec
    starts = u.index[(u == 1) & (u.shift(1) == 0) & (u.index >= pd.Period("1967-01", "M"))]
    for s0 in starts:
        w = sig.loc[s0 - 24:s0 + 6]
        line = []
        for r in RULES[:3]:
            on = w.index[w[r].values]
            line.append(f"{r}: {('첫 켜짐 ' + str(on[0]) + f' ({(on[0] - s0).n:+d}개월)') if len(on) else '안 켜짐'}")
        say(f"  침체 시작 {s0} | " + " | ".join(line))

    # ---------- B3 전략
    say("\n--- B3. 침체 신호 전략 ---")
    R, sh_tr, lastd, dy = monthly_returns(g, f)
    say(f"월간 총수익: {R.index[0]} ~ {R.index[-1]}; Shiller 배당 ~{lastd}, 이후 배당수익률 {dy:.4%} 고정")
    W = {}
    for r in RULES:
        W[r] = (1 - 0.5 * sig[r].astype(float)).shift(1).reindex(R.index).fillna(1.0)
    sma = g.rolling(200).mean()
    above = (g > sma).groupby(g.index.to_period("M")).last()
    W["TF200"] = above.astype(float).shift(1).reindex(R.index).fillna(1.0)
    W["B&H"] = pd.Series(1.0, index=R.index)
    rets = pd.DataFrame({k: sim(w, R) for k, w in W.items()})
    # 검증: B&H 재현
    bh_direct = (1 + R.rs).prod()
    bh_engine = (1 + rets["B&H"]).prod()
    say(f"[검증] B&H 재현: 엔진 누적 {bh_engine:.6f} vs 직접 누적 {bh_direct:.6f} (차이 {abs(bh_engine / bh_direct - 1):.2e})")
    cmp_ = pd.concat([R.rs, sh_tr], axis=1).loc["1950-02":lastd].dropna()
    cg = lambda x: (1 + x).prod() ** (12 / len(x)) - 1
    say(f"[검증] 총수익 연복리 1950-02~{lastd}: GSPC 월말+Shiller 배당 {cg(cmp_.iloc[:, 0]):.4%} vs Shiller 월평균 기준 {cg(cmp_.iloc[:, 1]):.4%}; "
        f"가격만 {(R.px.loc[lastd] / g.loc[:'1950-01-31'].iloc[-1]) ** (12 / len(cmp_)) - 1:.4%}")

    periods = {"학습(1967-01~1999-12)": ("1967-01", TRAIN_END), "검증(2000-01~2026-11)": (VALID_START, str(R.index[-1])),
               "참고: R2만 1950~1999": ("1950-02", TRAIN_END)}
    rr = []
    for pn, (a, b) in periods.items():
        for k in RULES + ["TF200", "B&H"]:
            x = rets.loc[a:b, k]
            s_ = stats(x, R.rc.loc[a:b])
            wv = W[k].loc[a:b]
            s_.update({"period": pn, "rule": k, "avg_w": wv.mean(), "months_on": int((wv < 1).sum()),
                       "switches": int((wv.diff().abs() > 0).sum())})
            rr.append(s_)
    rules = pd.DataFrame(rr)[["period", "rule", "CAGR", "vol", "Sharpe", "MDD", "avg_w", "months_on", "switches"]]
    # 학습 순위
    trn = rules[(rules.period.str.startswith("학습")) & rules.rule.isin(RULES)].copy()
    trn["order"] = trn.rule.map({r: i for i, r in enumerate(RULES)})
    elig = trn[trn.months_on > 0].sort_values(["Sharpe", "MDD", "order"], ascending=[False, False, True])
    excluded = trn[trn.months_on == 0].rule.tolist()
    best = elig.rule.iloc[0]
    rules["train_rank"] = rules.rule.map({r: i + 1 for i, r in enumerate(elig.rule)})
    say(f"시험한 규칙 수: {len(RULES)}. 학습 구간에 한 번도 안 켜져 순위에서 뺀 규칙: {excluded if excluded else '없음'}")
    say(f"학습 1위: {best}")

    a, b = periods["검증(2000-01~2026-11)"]
    rcv = R.rc.loc[a:b]
    bh_s = stats(rets.loc[a:b, "B&H"], rcv)
    verd = []
    for k in RULES:
        x = rets.loc[a:b, k]
        s_ = stats(x, rcv)
        wbar = W[k].loc[a:b].mean()
        fx = wbar * R.rs.loc[a:b] + (1 - wbar) * rcv
        fs = stats(fx, rcv)
        pb, qs = boot_sharpe(x, rets.loc[a:b, "B&H"], rcv)
        c1 = (s_["Sharpe"] > bh_s["Sharpe"]) and (s_["Sharpe"] > fs["Sharpe"])
        c2 = (s_["MDD"] - bh_s["MDD"]) >= 0.05
        c3 = pb >= 0.90
        v = "채택" if (c1 and c2 and c3) else ("보류" if (c1 and c2) else "탈락")
        verd.append({"rule": k, "학습1위": k == best, "Sharpe": s_["Sharpe"], "Sharpe_BH": bh_s["Sharpe"], "Sharpe_고정비중": fs["Sharpe"],
                     "고정비중_w": wbar, "CAGR": s_["CAGR"], "CAGR_BH": bh_s["CAGR"], "CAGR_고정비중": fs["CAGR"],
                     "MDD": s_["MDD"], "MDD_BH": bh_s["MDD"], "MDD_고정비중": fs["MDD"], "MDD개선_pp": (s_["MDD"] - bh_s["MDD"]) * 100,
                     "boot_P(ΔSharpe>0)": pb, "ΔSharpe_q05": qs[0], "ΔSharpe_q95": qs[2],
                     "기준1": c1, "기준2": c2, "기준3": c3, "판정(참고)": v})
    verdict = pd.DataFrame(verd)
    verdict["공식판정"] = np.where(verdict["학습1위"], verdict["판정(참고)"], "(판정 대상 아님)")
    rules.to_csv(RES / "B_rules.csv", index=False, encoding="utf-8-sig")
    verdict.to_csv(RES / "B_verdict.csv", index=False, encoding="utf-8-sig")
    say(rules.to_string(index=False))
    say("\n검증 구간 판정표:")
    say(verdict.T.to_string())
    final = verdict[verdict["학습1위"]].iloc[0]
    say(f"\n>>> B3 공식 판정: 학습 1위 규칙 [{best}] = {final['공식판정']}")
    # 신호 켜진 구간
    say("\n신호 켜진 구간(결정월 기준, 1967~):")
    for r in RULES[:3]:
        s_ = sig[r].loc["1967-01":]
        grp = (s_ != s_.shift()).cumsum()
        segs = [f"{x.index[0]}~{x.index[-1]}" for _, x in s_.groupby(grp) if x.iloc[0]]
        say(f"  {r}: {', '.join(segs) if segs else '없음'}")

    # ---------- B4 조건부 표
    say("\n--- B4. 조건부 확률표 (S&P 가격 기준) ---")
    st, cuts = daily_states(g, p.p1)
    say(f"V2 국면 경계(~1999-12-31 일간 V2의 1/3, 2/3 분위): {cuts[0]:.4f}, {cuts[1]:.4f}")
    o = outcomes(st)
    X = pd.concat([st, o], axis=1)
    X["_pos"] = np.arange(len(X))
    we = pd.to_datetime(X.window_end)
    X["sample"] = np.where(X.full & (we <= pd.Timestamp("1999-12-31")), "학습",
                           np.where(X.full & (X.index >= "2000-01-03"), "검증", None))
    Xf = X[X.full & X.vol.notna() & X.ma.notna()].copy()
    say(f"표본 일수: 학습 {int((Xf['sample'] == '학습').sum())}, 검증 {int((Xf['sample'] == '검증').sum())}, 전체 {len(Xf)} "
        f"({Xf.index[0].date()} ~ {Xf.index[-1].date()})")
    T = make_tables(Xf)
    T.to_csv(RES / "B_table.csv", index=False, encoding="utf-8-sig")
    show = ["vol", "dd", "ma", "r1", "flag", "n_days", "n_runs", "n_years", "r1m_q50", "r3m_q50", "r12m_q10", "r12m_q50", "r12m_q90", "p_add10", "se_add10", "p_hit20", "se_hit20", "p_neg12"]
    for tn in ["vol", "dd", "ma", "r1"]:
        say(f"\n[{tn}] 전체 표본")
        say(T[(T.table == tn) & (T["sample"] == "전체")][show].to_string(index=False))
    say("\n[T3] 전체 표본")
    say(T[(T.table == "T3") & (T["sample"] == "전체")][show].to_string(index=False))
    say("\n[T4] 전체 표본 (1967~)")
    say(T[(T.table == "T4") & (T["sample"] == "전체")][show].to_string(index=False))

    # 보정 검증
    say("\n보정 검증: 학습 표 -> 검증 구간 예측")
    sc = []
    for sname in SPECS:
        for ev in EVENTS:
            pred, base, obs, level = predict_from_table(Xf, sname, ev)
            e1, e0 = ((pred - obs) ** 2).values, ((base - obs) ** 2).values
            sc.append({"spec": sname, "event": ev, "주판정": sname == "T4" and ev in ("add10", "hit20"), "n_days": len(obs),
                       "obs_freq_valid": obs.mean(), "base_train": base, "pred_mean": pred.mean(),
                       "Brier": e1.mean(), "Brier_base": e0.mean(), "skill": 1 - e1.mean() / e0.mean(),
                       "boot_P(Brier<base)": boot_brier(e1, e0), "AUC": auc(pred, obs),
                       "share_fallback": (level != sname).mean(),
                       "판정": "예측력 있음" if e1.mean() < e0.mean() else "예측력 없음"})
            cal.append(reliability(pred.values, obs.values, obs.index.year, sname, ev))
    score = pd.DataFrame(sc)
    score.to_csv(RES / "B_calibration_score.csv", index=False, encoding="utf-8-sig")
    calib = pd.concat(cal, ignore_index=True)
    calib.to_csv(RES / "B_calibration.csv", index=False, encoding="utf-8-sig")
    say(f"시험한 (표 × 사건) 수: {len(score)} (주 판정 2개)")
    say(score.to_string(index=False))
    say("\n신뢰도 구간 (T4, T3, dd):")
    say(calib[calib.spec.isin(["T4", "T3", "dd"])].to_string(index=False))
    say("\n신뢰도 구간 (침체 모델):")
    say(calib[calib.event == "침체12개월"].to_string(index=False))

    # ---------- 현재 상태 판독
    say("\n--- 현재 상태 판독표 (2026-11-20) ---")
    t = st.index[-1]
    cur = st.iloc[-1]
    d_now = m.index[-1]
    sma_now = g.rolling(200).mean().iloc[-1]
    say(f"기준일 {t.date()} 종가 {cur.px:.2f}, 사상 최고 {g.max():.2f}({g.idxmax().date()}), 낙폭 {cur.ddv:.2%} -> 구간 [{cur.dd}]")
    say(f"V2(EWMA 0.94) {cur.v2:.2%} -> 국면 [{cur.vol}] (경계 {cuts[0]:.2%}, {cuts[1]:.2%}); VIX 35.9는 참고(상태 변수 아님)")
    say(f"200일선 {sma_now:.2f} -> [{cur.ma}] ({cur.px / sma_now - 1:+.2%})")
    say(f"R1 확률: 11월 적용분(9월 지표) {cur.p1:.3f} -> [{cur.r1}]; 최신({d_now} 결정, 10월 지표: 금리차 {m.spread.iloc[-1]:.2f}%p) {p.p1.iloc[-1]:.3f}")
    say(f"R3 확률 최신 {p.p3.iloc[-1]:.3f} (신용 스프레드 6개월 변화 {m.dcs6.iloc[-1]:+.2f}%p); 삼 규칙 최신 {m.sahm.iloc[-1]:.2f} (발동 기준 0.5), R2 확률 {p.p2.iloc[-1]:.3f}")
    say(f"침체 신호 규칙 상태(12월 적용): " + ", ".join(f"{r}={'켜짐' if sig[r].iloc[-1] else '꺼짐'}" for r in RULES))
    key = {"vol": cur.vol, "dd": cur.dd, "ma": cur.ma, "r1": cur.r1}
    cr = []
    for sname in ["T4", "T3", "dd", "vol", "ma", "r1"]:
        for smp in ["전체", "학습", "검증"]:
            q = T[(T.table == sname) & (T["sample"] == smp)]
            for k in SPECS[sname]:
                q = q[q[k] == key[k]]
            if len(q):
                cr.append(q.iloc[0])
            else:
                cr.append(pd.Series({"table": sname, "sample": smp, **{k: key[k] for k in SPECS[sname]}, "flag": "해당 칸 없음", "n_days": 0}))
    # 무조건 기준
    for smp, d in [("전체", Xf), ("학습", Xf[Xf["sample"] == "학습"]), ("검증", Xf[Xf["sample"] == "검증"])]:
        s_ = cell_stats(d)
        s_["table"], s_["sample"] = "무조건", smp
        cr.append(s_)
    current = pd.DataFrame(cr)
    front = ["table", "sample", "vol", "dd", "ma", "r1", "flag", "n_days", "n_runs", "n_years"]
    current = current[front + [c for c in current.columns if c not in front]]
    current.to_csv(RES / "B_current.csv", index=False, encoding="utf-8-sig")
    cshow = ["table", "sample", "flag", "n_days", "n_runs", "n_years", "r1m_q10", "r1m_q50", "r1m_q90", "r3m_q10", "r3m_q50", "r3m_q90",
             "r12m_q10", "r12m_q50", "r12m_q90", "p_add10", "se_add10", "p_hit20", "se_hit20", "p_neg12"]
    say(f"현재 칸: 변동성 {cur.vol} / 낙폭 {cur.dd} / 200일선 {cur.ma} / R1 {cur.r1}")
    say(current[cshow].to_string(index=False))
    # 현재 칸에 해당했던 과거 구간
    cellmask = (st.vol == cur.vol) & (st.dd == cur.dd) & (st.ma == cur.ma)
    yrs = sorted(set(st.index[cellmask].year))
    say(f"T3 현재 칸에 있었던 연도: {yrs}")

    # ---------- 엔진 검증: 룩어헤드
    say("\n--- 엔진 검증: 룩어헤드(2010-12-31에서 자르고 재계산) ---")
    C2 = compute("2010-12-31")
    ix = C2["m"].index
    chk = {}
    for col in ["p1", "p2", "p3"]:
        a_, b_ = C2["p"][col], p.loc[ix, col]
        chk[col] = bool(((a_ - b_).abs().fillna(0) < 1e-12).all() and (a_.isna() == b_.isna()).all())
    chk["signals"] = bool((C2["sig"] == sig.loc[ix]).all().all())
    chk["x(spread,dcs6,sahm)"] = bool(((C2["m"][["spread", "dcs6", "sahm"]] - m.loc[ix, ["spread", "dcs6", "sahm"]]).abs().fillna(0) < 1e-12).all().all())
    st2, _ = daily_states(C2["g"], C2["p"].p1, cuts)
    cols = ["vol", "dd", "ma", "r1"]
    same = (st2[cols].fillna("NA") == st.loc[st2.index, cols].fillna("NA")).all().all()
    chk["daily_states"] = bool(same and np.allclose(st2.v2.dropna(), st.loc[st2.index, "v2"].dropna()))
    say("자른 계산과 전체 계산 일치 여부: " + ", ".join(f"{k}={v}" for k, v in chk.items()))
    say(f"룩어헤드 점검: {'통과' if all(chk.values()) else '실패'}")

    (RES / "B_summary.txt").write_text("\n".join(OUT), encoding="utf-8")


if __name__ == "__main__":
    main()
