"""파트 C — 종목별 조건부 확률: 큰 하락(고점 대비 −30%, −50%) 뒤 회복.

설계: ../00_연구설계서.md §C, 실행 세부: ../부록_C.md (결과를 보기 전에 고정)
실행: py -I src/C_stock.py surv     # C1 생존편향 측정 -> results/C_survivorship.txt
      py -I src/C_stock.py events   # 사건 추출 -> results/C_events.csv
      py -I src/C_stock.py check    # 엔진 검증 -> results/C_engine_check.txt
      py -I src/C_stock.py analyze  # 표·판정·참고 사례·요약
      py -I src/C_stock.py all
기존 엔진(체크리스트 검증/src)은 불러오기만 한다.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
CK = ROOT / "체크리스트 검증"
sys.path.insert(0, str(CK / "src"))
from checklist import DEFAULT, grade, row_features  # noqa: E402
from prices import load_price  # noqa: E402

RES = HERE / "results"
DATA = HERE / "data"
RES.mkdir(exist_ok=True)
DATA_END = np.datetime64("2026-10-22")
EV_START = np.datetime64("2006-01-01")
MIN_MCAP = 1e9
THS = (-0.30, -0.50)
H = {1: 365, 3: 1096, 5: 1826}
PERIODS = {"학습": (2006, 2015), "검증": (2016, 2021), "최근": (2022, 2026)}
SEED = 20261122
NBOOT = 2000
FEAT_COLS = ["n_years", "roic_last", "roic_med5", "roic_min10", "eps5_up", "rev5_up", "eps_cagr", "rev_cagr",
             "eps_cagr5", "eps_consistent", "eps_drops", "cyc_0710", "cyc_10y", "cyclical", "fcf_ratio",
             "dilution", "ni_last"]


# ---------------------------------------------------------------- 자료
def load_ann():
    ann = pd.read_parquet(CK / "data" / "panel" / "annual_first.parquet")
    g, _ = grade(ann, DEFAULT)
    ann["grade"] = g.values
    ann["end"] = pd.to_datetime(ann["end"])
    ann["avail"] = pd.to_datetime(ann["avail"])
    return ann


def fund_ciks(ann):
    """엔진 backtest.load 와 같은 취지: 상품·코인 신탁, 펀드 제외.
    패널의 name 열은 비어 있어서(엔진에서는 이름 조건이 실제로 작동하지 않음) companies.csv 의 이름을 쓴다."""
    comp = pd.read_csv(CK / "data" / "sec" / "companies.csv").drop_duplicates("cik").set_index("cik")
    nm = comp["name"].fillna("").astype(str).str.upper()
    bad = (comp.sic.astype(str).isin(["6221", "6221.0"])) | nm.str.contains(r"\bTRUST\b|\bETF\b|\bFUND\b")
    return set(comp.index[bad])


def load_manifest():
    m = pd.read_csv(CK / "data" / "prices" / "manifest.csv")
    return m[m.status.eq("ok")].drop_duplicates("cik")


def load_gspc():
    j = json.load(open(ROOT / "차트분석 4차 연구" / "data" / "GSPC.json", encoding="utf-8"))
    r = j["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")]
    return s, s / s.cummax() - 1


def load_spy():
    s = pd.read_csv(ROOT / "차트 아록리즘 분석" / "data" / "raw" / "SPY.csv", parse_dates=["date"]).set_index("date").adj_close
    return s.sort_index()


# ---------------------------------------------------------------- 사건
def find_events(close, th):
    """하락 구간(고점 -> 회복)마다 th 를 처음 넘은 날의 위치. 반환: (사건 위치, 고점값)."""
    runmax = np.maximum.accumulate(close)
    dd = close / runmax - 1
    ep = np.cumsum(close >= runmax)  # 고점(같거나 새 고점)마다 새 구간
    hit = np.flatnonzero(dd <= th)
    if len(hit) == 0:
        return hit, runmax
    first = hit[np.r_[True, ep[hit][1:] != ep[hit][:-1]]]
    return first, runmax


def ret_to(dates, adj, i, target):
    """i 에서 target(날짜) 이하 마지막 거래일까지 adj 수익. 가격이 먼저 끝나면 마지막 가격으로 청산."""
    j = np.searchsorted(dates, target, side="right") - 1
    return adj[j] / adj[i] - 1


def asof(s, d):
    k = s.index.searchsorted(pd.Timestamp(d), side="right") - 1
    return s.iloc[k] if k >= 0 else np.nan


def event_outcomes(dates, close, adj, i, peak, spy, data_end=DATA_END):
    t = dates[i]
    o = {}
    after = close[i + 1:]
    rec_idx = np.flatnonzero(after >= peak)
    o["days_to_rec"] = int((dates[i + 1 + rec_idx[0]] - t).astype(int)) if len(rec_idx) else np.nan
    for k, days in H.items():
        tgt = t + np.timedelta64(days, "D")
        if tgt > data_end:
            o[f"rec{k}"] = np.nan
            continue
        o[f"rec{k}"] = float(o["days_to_rec"] <= days) if np.isfinite(o["days_to_rec"]) else 0.0
    for nm, days in (("12", 365), ("36", 1096)):
        tgt = t + np.timedelta64(days, "D")
        if tgt > data_end:
            o[f"ret{nm}"] = o[f"ex{nm}"] = np.nan
        else:
            o[f"ret{nm}"] = ret_to(dates, adj, i, tgt)
            o[f"ex{nm}"] = o[f"ret{nm}"] - (asof(spy, tgt) / asof(spy, t) - 1)
    for nm, days in (("1y", 365), ("3y", 1096)):
        tgt = t + np.timedelta64(days, "D")
        if tgt > data_end:
            o[f"more30_{nm}"] = np.nan
        else:
            j = np.searchsorted(dates, tgt, side="right") - 1
            o[f"more30_{nm}"] = float((close[i + 1:j + 1] <= 0.7 * close[i]).any())
    return o


def firm_events(cik, tk, a, spy, gdd, cutoff=None, with_outcomes=True):
    """한 기업의 사건 목록. a = 그 기업의 연도 행(grade 포함). cutoff 가 있으면 그 날까지의 정보만으로 다시 계산."""
    df = load_price(tk)
    if df is None or len(df) < 2:
        return [], "주가 없음"
    if cutoff is not None:
        df = df[df.index <= cutoff]
        a = a[a.avail <= cutoff].drop(columns=FEAT_COLS + ["grade"])
        if len(a):
            a = a.join(row_features(a.sort_values("cy")))
            a["grade"] = grade(a, DEFAULT)[0].values
        if len(df) < 2:
            return [], "주가 없음"
    dates = df.index.values.astype("datetime64[D]")
    close = df.close.values.astype(float)
    adj = df.adj_close.values.astype(float)
    a = a.sort_values(["avail", "cy"])
    sh = a.dropna(subset=["sh_adj"])
    if sh.empty:
        return [], "주식수 없음"
    sh_av = sh.avail.values.astype("datetime64[D]")
    sh_v = sh.sh_adj.values
    av = a.avail.values.astype("datetime64[D]") if len(a) else np.array([], dtype="datetime64[D]")
    delisted = bool(dates[-1] < DATA_END - np.timedelta64(30, "D")) and cutoff is None
    out = []
    for th in THS:
        idx, runmax = find_events(close, th)
        for i in idx:
            t = dates[i]
            if t < EV_START:
                continue
            k = np.searchsorted(sh_av, t, side="left") - 1  # avail < t
            backfill = k < 0
            mcap = close[i] * (sh_v[0] if backfill else sh_v[k])
            if not (mcap >= MIN_MCAP):
                continue
            r = {"cik": cik, "ticker": tk, "th": int(round(-th * 100)), "date": str(t), "year": int(str(t)[:4]),
                 "close": close[i], "peak": runmax[i], "dd": close[i] / runmax[i] - 1, "mcap": mcap,
                 "mcap_backfill": int(backfill), "delisted": int(delisted)}
            kk = np.searchsorted(av, t, side="left") - 1
            row = a.iloc[kk] if kk >= 0 else None
            if row is not None and (t - av[kk]).astype(int) >= 730:
                row = None
            if row is None:
                r.update(Q="불가", q_reason="연도행 없음", grade=None, cyc_num=None, fy=np.nan, avail=None)
            else:
                r.update(grade=row.grade, cyc_num=bool(row.cyclical), fy=int(row.cy), avail=str(row.avail.date()))
                if row.n_years < DEFAULT["min_years"]:
                    r.update(Q="불가", q_reason="이력 5년 미만")
                else:
                    r.update(Q="실패" if row.grade == "X" else "통과", q_reason="")
            r["sp_dd"] = float(asof(gdd, t))
            r["M"] = "시장형" if r["sp_dd"] <= -0.15 else "개별형"
            if with_outcomes:
                r.update(event_outcomes(dates, close, adj, i, runmax[i], spy))
            out.append(r)
    return out, "ok"


def build_events():
    ann = load_ann()
    funds = fund_ciks(ann)
    man = load_manifest()
    spy = load_spy()
    _, gdd = load_gspc()
    ann_g = dict(tuple(ann.groupby("cik")))
    sector = ann.drop_duplicates("cik").set_index("cik").sector_excl.fillna(False).astype(bool)
    rows, status = [], {}
    for n, (cik, tk) in enumerate(zip(man.cik, man.yahoo)):
        if cik in funds:
            status[cik] = "펀드·신탁 제외"
            continue
        if cik not in ann_g:
            status[cik] = "연도 패널 없음"
            continue
        ev, st = firm_events(cik, tk, ann_g[cik], spy, gdd)
        status[cik] = st
        for r in ev:
            r["S"] = "순환·제외섹터" if sector.get(cik, False) else "그 외"
        rows += ev
        if n % 400 == 0:
            print(n, tk, len(rows), flush=True)
    ev = pd.DataFrame(rows)
    ev["period"] = pd.cut(ev.year, [2005, 2015, 2021, 2026], labels=["학습", "검증", "최근"]).astype(str)
    ev.to_csv(RES / "C_events.csv", index=False, encoding="utf-8-sig")
    st = pd.Series(status).value_counts()
    st.to_csv(RES / "C_universe_status.csv", header=["기업 수"], encoding="utf-8-sig")
    print(st.to_string())
    print("events", len(ev), ev.groupby(["th", "period"]).size().to_dict())
    return ev


# ---------------------------------------------------------------- C1 생존편향
def alive_firms(ann, lo, hi, funds):
    """기말이 [lo, hi]년 안이고 매출 ≥ $1B 인 연도 행이 있는 기업 -> 그 구간 마지막 행."""
    a = ann[(ann.end.dt.year >= lo) & (ann.end.dt.year <= hi) & (ann.rev >= 1e9) & ~ann.cik.isin(funds)]
    return a.sort_values("cy").drop_duplicates("cik", keep="last").set_index("cik")


def survivorship():
    ann = load_ann()
    funds = fund_ciks(ann)
    comp = pd.read_csv(CK / "data" / "sec" / "companies.csv")
    man = pd.read_csv(CK / "data" / "prices" / "manifest.csv")
    priced = set(man[man.status.eq("ok")].cik)
    L = []
    L.append("C1. 상장폐지 종목 포함 여부 측정 (작업자 3, 2026-11-22)")
    L.append("=" * 60)
    has_tk = comp.tickers.fillna("").str.len() > 0
    L.append(f"SEC 대형 기업(companies.csv): {len(comp):,}개")
    L.append(f"  티커 있음 {has_tk.sum():,} / 티커 없음(상장폐지·합병 추정) {(~has_tk).sum():,} ({(~has_tk).mean():.1%})")
    L.append(f"  주가 파일 있음 {comp.cik.isin(priced).sum():,} / 주가 없음 {(~comp.cik.isin(priced)).sum():,} "
             f"({(~comp.cik.isin(priced)).mean():.1%})")
    end = pd.to_datetime(man.end)
    L.append(f"주가 파일 {len(man):,}개의 마지막 거래일: 최소 {end.min().date()}, 최대 {end.max().date()}")
    L.append(f"  2026년 이전에 끝나는 종목: {(end < '2026-01-01').sum()}개 / 자료 끝 30일 전에 끝나는 종목: "
             f"{(end < pd.Timestamp('2026-09-22')).sum()}개")
    L.append("  => 주가 자료에는 상장폐지 종목이 한 개도 없다. 사건 표는 '2026년 10월까지 살아남은 회사'만의 기록이다.")
    L.append("")
    L.append("구간별 '살아 있던 큰 회사'(기말이 구간 안, 매출 ≥ $1B 인 연도 행 보유, 펀드 제외) 중 주가 없는 비율")
    rows = []
    for nm, (lo, hi) in PERIODS.items():
        al = alive_firms(ann, lo, hi, funds)
        p = al.index.isin(priced)
        rows.append((nm, lo, hi, len(al), int(p.sum()), int((~p).sum()), (~p).mean()))
        L.append(f"  {nm} {lo}~{hi}: 전체 {len(al):,} / 주가 있음 {p.sum():,} / 주가 없음 {(~p).sum():,} ({(~p).mean():.1%})")
    L.append("")
    un = ann[~ann.cik.isin(priced) & ~ann.cik.isin(funds)]
    last = un.groupby("cik").end.max().dt.year
    L.append(f"주가 없는 기업 {last.size:,}개의 마지막 회계연도 분포(= 사라진 시기 근사)")
    bins = pd.cut(last, [1990, 2009, 2012, 2015, 2018, 2021, 2024, 2027],
                  labels=["~2009", "2010~12", "2013~15", "2016~18", "2019~21", "2022~24", "2025~"])
    for k, v in bins.value_counts().sort_index().items():
        L.append(f"  {k}: {v:,}")
    L.append("  (2025~ 는 상장폐지가 아니라 미국 거래소 티커가 없는 현존 회사일 수 있다: 외국 상장사·비상장 공시사)")
    L.append("")
    L.append("구간 마지막 연도 행 기준, 주가 없는 기업의 품질 관문(Q)과 섹터(S) 구성 — 하한 보정에 쓰는 수")
    for nm, (lo, hi) in PERIODS.items():
        al = alive_firms(ann, lo, hi, funds)
        u = al[~al.index.isin(priced)]
        q = np.where(u.n_years < 5, "불가", np.where(u.grade == "X", "실패", "통과"))
        vc = pd.Series(q).value_counts().to_dict()
        L.append(f"  {nm}: Q 통과 {vc.get('통과', 0)} / 실패 {vc.get('실패', 0)} / 불가 {vc.get('불가', 0)} ; "
                 f"순환·제외섹터 {int(u.sector_excl.fillna(False).sum())} / 그 외 {int((~u.sector_excl.fillna(False).astype(bool)).sum())}")
    L.append("")
    sh = {r[0]: r[6] for r in rows}
    L.append(f"결론: 생존편향이 크다. 상장폐지 종목 주가는 0개이고, 구간별 큰 회사 중 주가 없는 비율이 "
             f"학습 {sh['학습']:.0%}, 검증 {sh['검증']:.0%}, 최근 {sh['최근']:.0%} 다.")
    L.append("      회복 확률은 낙관적으로 치우친다. C6 하한 보정(주가 없는 기업 = 전부 회복 실패)을 반드시 함께 낸다.")
    L.append("주의: '주가 없음'에는 상장폐지·피인수 외에 미국 거래소 티커가 없는 공시사(비상장 채권 발행사, 외국 상장사,")
    L.append("      자회사)도 섞여 있다. 처음부터 상장 주식이 없던 회사도 있으므로 하한은 실제보다 더 비관적이다.")
    txt = "\n".join(L)
    (RES / "C_survivorship.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


# ---------------------------------------------------------------- 통계
def boot_diff(d, col, a, b, cluster):
    """두 집단(a, b: bool 배열) 평균 차이의 군집 부트스트랩 90% 구간."""
    d = d.assign(_a=a, _b=b)
    d = d[d[col].notna() & (d._a | d._b)]
    if d._a.sum() == 0 or d._b.sum() == 0:
        return np.nan, np.nan, np.nan
    codes, uniq = pd.factorize(d[cluster])
    F = len(uniq)
    y = d[col].values.astype(float)
    na = np.bincount(codes, weights=d._a.values.astype(float), minlength=F)
    nb = np.bincount(codes, weights=d._b.values.astype(float), minlength=F)
    ka = np.bincount(codes, weights=y * d._a.values, minlength=F)
    kb = np.bincount(codes, weights=y * d._b.values, minlength=F)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, F, size=(NBOOT, F))
    with np.errstate(invalid="ignore", divide="ignore"):
        diff = ka[idx].sum(1) / na[idx].sum(1) - kb[idx].sum(1) / nb[idx].sum(1)
    point = ka.sum() / na.sum() - kb.sum() / nb.sum()
    lo, hi = np.nanpercentile(diff, [5, 95])
    return point, lo, hi


def grp_stats(d):
    r = {"사건 수": len(d), "기업 수": d.cik.nunique(), "연도 수": d.year.nunique()}
    for k in (1, 3, 5):
        r[f"회복{k}년"] = d[f"rec{k}"].mean()
        r[f"회복{k}년_n"] = int(d[f"rec{k}"].notna().sum())
    for c, nm in (("ret12", "12개월 수익"), ("ret36", "36개월 수익"), ("ex12", "12개월 초과"), ("ex36", "36개월 초과")):
        r[f"{nm} 평균"] = d[c].mean()
        r[f"{nm} 중앙"] = d[c].median()
    r["36개월 손실 확률"] = (d.ret36.dropna() < 0).mean() if d.ret36.notna().any() else np.nan
    r["36개월 지수 하회 확률"] = (d.ex36.dropna() < 0).mean() if d.ex36.notna().any() else np.nan
    r["추가 −30% (1년)"] = d.more30_1y.mean()
    r["추가 −30% (3년)"] = d.more30_3y.mean()
    rec = d.days_to_rec.dropna()
    r["회복 일수 중앙(회복한 사건)"] = rec.median() if len(rec) else np.nan
    return r


def groups(d):
    q, m, s = d.Q, d.M, d.S
    cyc = d.cyc_num.map({True: True, False: False, "True": True, "False": False})
    return {
        "전체": np.ones(len(d), bool),
        "Q 통과": (q == "통과").values, "Q 실패": (q == "실패").values, "Q 판정 불가": (q == "불가").values,
        "M 시장형": (m == "시장형").values, "M 개별형": (m == "개별형").values,
        "S 그 외(비순환)": (s == "그 외").values, "S 순환·제외섹터": (s != "그 외").values,
        "참고: 숫자 기준 비순환": (cyc == False).values, "참고: 숫자 기준 순환": (cyc == True).values,  # noqa: E712
        "참고: v2 관문 전체 통과(Q 통과·비순환섹터)": ((q == "통과") & (s == "그 외")).values,
        "Q 통과 × 시장형": ((q == "통과") & (m == "시장형")).values,
        "Q 통과 × 개별형": ((q == "통과") & (m == "개별형")).values,
        "Q 실패 × 시장형": ((q == "실패") & (m == "시장형")).values,
        "Q 실패 × 개별형": ((q == "실패") & (m == "개별형")).values,
    }


VARS = {"Q": ("Q 통과", "Q 실패"), "M": ("M 시장형", "M 개별형"), "S": ("S 그 외(비순환)", "S 순환·제외섹터")}


def phantoms(ann, funds, priced, ev):
    """하한 보정용 가상 사건 수: 구간 × (전체, Q, S)."""
    out = {}
    for nm, (lo, hi) in PERIODS.items():
        al = alive_firms(ann, lo, hi, funds)
        isp = al.index.isin(priced)
        u = al[~isp]
        q = np.where(u.n_years < 5, "불가", np.where(u.grade == "X", "실패", "통과"))
        se = u.sector_excl.fillna(False).astype(bool).values
        cnt = {"전체": len(u), "Q 통과": int((q == "통과").sum()), "Q 실패": int((q == "실패").sum()),
               "S 그 외(비순환)": int((~se).sum()), "S 순환·제외섹터": int(se.sum())}
        inc = {}
        for th in (30, 50):
            e = ev[(ev.th == th) & (ev.period == nm)]
            inc[th] = float(np.isin(al.index[isp], e.cik.unique()).mean())
        out[nm] = {"cnt": cnt, "inc": inc, "alive_priced": int(isp.sum())}
    return out


def analyze():
    ev = pd.read_csv(RES / "C_events.csv")
    ann = load_ann()
    funds = fund_ciks(ann)
    priced = set(load_manifest().cik)
    ph = phantoms(ann, funds, priced, ev)

    # ---- 조건표
    rows = []
    for th in (30, 50):
        for per in PERIODS:
            d = ev[(ev.th == th) & (ev.period == per)]
            for gname, mask in groups(d).items():
                rows.append({"문턱": f"−{th}%", "구간": per, "조건": gname, **grp_stats(d[mask])})
    tab = pd.DataFrame(rows)
    tab.loc[tab["연도 수"] < 5, "비고"] = "참고(연도 5개 미만)"
    tab.to_csv(RES / "C_table.csv", index=False, encoding="utf-8-sig", float_format="%.4f")

    # ---- 판정
    vrows = []
    for th in (30, 50):
        for var, (ga, gb) in VARS.items():
            rec = {"문턱": f"−{th}%", "변수": var, "비교": f"{ga} − {gb}"}
            ok_n, ok_diff, ok_ci, signs = True, True, True, []
            for per in ("학습", "검증"):
                d = ev[(ev.th == th) & (ev.period == per)]
                g = groups(d)
                a, b = g[ga], g[gb]
                da, db = d[a & d.rec3.notna().values], d[b & d.rec3.notna().values]
                pt, lo, hi = boot_diff(d, "rec3", a, b, "cik")
                _, ylo, yhi = boot_diff(d, "rec3", a, b, "year")
                rec.update({f"{per} A 회복3년": da.rec3.mean(), f"{per} B 회복3년": db.rec3.mean(), f"{per} 차이": pt,
                            f"{per} 기업군집 90% 하한": lo, f"{per} 기업군집 90% 상한": hi,
                            f"{per} 연도군집 90% 하한(참고)": ylo, f"{per} 연도군집 90% 상한(참고)": yhi,
                            f"{per} A 사건/기업": f"{len(da)}/{da.cik.nunique()}", f"{per} B 사건/기업": f"{len(db)}/{db.cik.nunique()}"})
                if min(len(da), len(db)) < 30 or min(da.cik.nunique(), db.cik.nunique()) < 20:
                    ok_n = False
                ok_diff &= bool(abs(pt) >= 0.10) if np.isfinite(pt) else False
                ok_ci &= bool(lo > 0 or hi < 0) if np.isfinite(lo) else False
                signs.append(np.sign(pt))
                # 하한 보정
                c, inc = ph[per]["cnt"], ph[per]["inc"][th]
                if var == "M":
                    na_, nb_ = len(da), len(db)
                    pa = c["전체"] * na_ / max(na_ + nb_, 1)
                    pb = c["전체"] * nb_ / max(na_ + nb_, 1)
                else:
                    pa, pb = c[ga], c[gb]
                for tag, w in (("극단 하한", 1.0), ("사건율 보정 하한", inc)):
                    la = da.rec3.sum() / (len(da) + pa * w) if len(da) + pa * w > 0 else np.nan
                    lb = db.rec3.sum() / (len(db) + pb * w) if len(db) + pb * w > 0 else np.nan
                    rec.update({f"{per} {tag} A": la, f"{per} {tag} B": lb, f"{per} {tag} 차이": la - lb})
                # backfill 제외 민감도
                d2 = d[d.mcap_backfill == 0]
                g2 = groups(d2)
                rec[f"{per} 차이(주식수 backfill 제외)"] = boot_diff(d2, "rec3", g2[ga], g2[gb], "cik")[0]
            same = len(set(signs)) == 1
            if not ok_n:
                v = "판정 불가(표본 부족)"
            elif ok_diff and ok_ci and same:
                v = "유용"
            else:
                v = "유용하지 않음"
            why = []
            if not same:
                why.append("학습·검증 방향 다름")
            if not ok_diff:
                why.append("차이 10%p 미만인 구간 있음")
            if not ok_ci:
                why.append("90% 구간이 0을 포함하는 구간 있음")
            rec["판정"] = v
            rec["사유"] = "; ".join(why) if v != "유용" else "기준 모두 충족"
            rec["대표 판정"] = "예" if th == 30 else "보조"
            vrows.append(rec)
    ver = pd.DataFrame(vrows)
    ver.to_csv(RES / "C_verdict.csv", index=False, encoding="utf-8-sig", float_format="%.4f")

    # ---- 전체 회복 확률의 하한
    lb_rows = []
    for th in (30, 50):
        for per in ("학습", "검증"):
            d = ev[(ev.th == th) & (ev.period == per)]
            for k in (1, 3, 5):
                x = d[f"rec{k}"].dropna()
                n_ph, inc = ph[per]["cnt"]["전체"], ph[per]["inc"][th]
                lb_rows.append({"문턱": f"−{th}%", "구간": per, "기간": f"{k}년", "관측 회복 확률": x.mean(), "관측 사건": len(x),
                                "주가 없는 기업": n_ph, "주가 있는 기업의 사건 발생 비율": inc,
                                "사건율 보정 하한": x.sum() / (len(x) + n_ph * inc), "극단 하한": x.sum() / (len(x) + n_ph)})
    lb = pd.DataFrame(lb_rows)
    lb.to_csv(RES / "C_lowerbound.csv", index=False, encoding="utf-8-sig", float_format="%.4f")

    post = posthoc(ev)
    ref, now = reference_cases(ev, ann, tab)
    write_summary(ev, tab, ver, lb, ph, ref, now, post)


def posthoc(ev):
    """[사후] 결과를 본 뒤 추가한 민감도. 판정에는 쓰지 않는다.
    M2: S&P 가 '최근 252거래일 고점' 대비 −15% 이하일 때만 시장형 (사전 정의는 1950년 이후 최고가 대비라서
    2006년·2010~2012년처럼 지수가 예전 고점을 오래 밑돈 기간도 시장형이 된다)."""
    s, _ = load_gspc()
    dd252 = s / s.rolling(252, min_periods=200).max() - 1
    k = dd252.index.searchsorted(pd.to_datetime(ev.date), side="right") - 1
    ev = ev.assign(M2=np.where(dd252.values[k] <= -0.15, "시장형", "개별형"))
    rows = []
    for th in (30, 50):
        for per in ("학습", "검증"):
            d = ev[(ev.th == th) & (ev.period == per)]
            a, b = (d.M2 == "시장형").values, (d.M2 == "개별형").values
            pt, lo, hi = boot_diff(d, "rec3", a, b, "cik")
            _, ylo, yhi = boot_diff(d, "rec3", a, b, "year")
            rows.append({"문턱": f"−{th}%", "구간": per, "시장형 사건": int(a.sum()), "개별형 사건": int(b.sum()),
                         "시장형 연도 수": d[a].year.nunique(),
                         "시장형 회복3년": d[a].rec3.mean(), "개별형 회복3년": d[b].rec3.mean(), "차이": pt,
                         "기업군집 90% 하한": lo, "기업군집 90% 상한": hi, "연도군집 90% 하한": ylo, "연도군집 90% 상한": yhi,
                         "시장형 36개월 초과 중앙": d[a].ex36.median(), "개별형 36개월 초과 중앙": d[b].ex36.median(),
                         "시장형 지수 하회 확률": (d[a].ex36.dropna() < 0).mean(), "개별형 지수 하회 확률": (d[b].ex36.dropna() < 0).mean()})
    post = pd.DataFrame(rows)
    post.to_csv(RES / "C_posthoc.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
    # 연도별 분포(사전 정의 M)
    e = ev[ev.th == 30]
    yr = e.groupby(["year", "M"]).agg(사건=("rec3", "size"), 회복3년=("rec3", "mean"), 초과36중앙=("ex36", "median")).unstack()
    yr.columns = [f"{b} {a}" for a, b in yr.columns]
    yr.to_csv(RES / "C_by_year.csv", encoding="utf-8-sig", float_format="%.3f")
    return post


# ---------------------------------------------------------------- 참고 사례
def case_events(dates, close, name):
    rows = []
    for th in THS:
        idx, runmax = find_events(close, th)
        for i in idx:
            after = close[i + 1:]
            rj = np.flatnonzero(after >= runmax[i])
            j_end = i + 1 + rj[0] if len(rj) else len(close) - 1
            seg = close[i:j_end + 1]
            pk_i = int(np.flatnonzero(close[:i + 1] == runmax[i])[-1])
            rows.append({"종목": name, "문턱": f"−{int(round(-th * 100))}%", "고점일": str(dates[pk_i]), "고점": runmax[i],
                         "사건일": str(dates[i]), "사건일 종가": close[i],
                         "이후 최저(고점 대비)": seg.min() / runmax[i] - 1,
                         "회복일": str(dates[j_end]) if len(rj) else "",
                         "사건일→회복 일수": int((dates[j_end] - dates[i]).astype(int)) if len(rj) else np.nan,
                         "고점→회복 일수": int((dates[j_end] - dates[pk_i]).astype(int)) if len(rj) else np.nan,
                         "상태": "회복" if len(rj) else "미회복(자료 끝 기준)"})
    return rows


def reference_cases(ev, ann, tab):
    rows, now = [], {}
    for nm, label in (("samsung", "삼성전자(005930.KS, 원화 종가)"), ("NVDA", "NVDA")):
        p = DATA / f"C_px_{nm}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
        dates, close = df.index.values.astype("datetime64[D]"), df.close.values.astype(float)
        rows += case_events(dates, close, label)
        rm = np.maximum.accumulate(close)
        pk_d = str(dates[int(np.flatnonzero(close == rm[-1])[-1])])
        now[label] = (f"자료 {dates[0]} ~ {dates[-1]}. 기준일 종가 {close[-1]:,.2f}, 직전 고점 {rm[-1]:,.2f} ({pk_d}), "
                      f"현재 낙폭 {close[-1] / rm[-1] - 1:.1%}")
    ref = pd.DataFrame(rows)
    ref.to_csv(RES / "C_reference.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
    # NVDA 현재 조건
    a = ann[ann.ticker == "NVDA"].sort_values("cy")
    if len(a):
        r = a.iloc[-1]
        _, gdd = load_gspc()
        q = "실패" if r.grade == "X" else "통과"
        m = "시장형" if gdd.iloc[-1] <= -0.15 else "개별형"
        T = tab.set_index(["문턱", "구간", "조건"])
        cell = f"Q {q} × {m}"
        c1, c2 = T.loc[("−30%", "학습", cell)], T.loc[("−30%", "검증", cell)]
        now["NVDA 조건"] = (f"최근 연도 행 FY{int(r.cy)} 등급 {r.grade} → Q {q}, 섹터 {'순환·제외' if bool(r.sector_excl) else '그 외'}"
                           f"(숫자 기준 순환 판정은 {'해당' if bool(r.cyclical) else '비해당'}), "
                           f"S&P 낙폭 {gdd.iloc[-1]:.1%}({gdd.index[-1].date()}) → {m}. "
                           f"해당 칸 '{cell}' (−30% 사건): 3년 회복 학습 {c1['회복3년']:.0%}(n={int(c1['사건 수'])}) · 검증 {c2['회복3년']:.0%}(n={int(c2['사건 수'])}), "
                           f"36개월 S&P 대비 초과 중앙 검증 {c2['36개월 초과 중앙']:+.0%}, 추가 −30%(3년) 검증 {c2['추가 −30% (3년)']:.0%}. "
                           f"생존편향이 있는 숫자이고 한 종목의 예측이 아니다")
    p = DATA / "C_px_ANT.csv"
    if p.exists():
        n = len(pd.read_csv(p))
        now["ANT"] = f"거래 {n}일뿐(상장 직후). 고점·사건을 정의할 수 없어 생략"
    return ref, now


# ---------------------------------------------------------------- 엔진 검증
def engine_check():
    L = ["엔진 검증 (파트 C, 작업자 3)", "=" * 60]
    ev = pd.read_csv(RES / "C_events.csv")
    ann = load_ann()
    spy = load_spy()
    g, gdd = load_gspc()
    man = load_manifest()
    ann_g = dict(tuple(ann.groupby("cik")))
    # 1) 룩어헤드: 2015-12-31 에서 자르고 다시 계산
    cut = pd.Timestamp("2015-12-31")
    rng = np.random.default_rng(SEED)
    ciks = [c for c in ev.cik.unique()]
    pick = rng.choice(ciks, size=min(300, len(ciks)), replace=False)
    tk = dict(zip(man.cik, man.yahoo))
    re_rows = []
    for c in pick:
        r, _ = firm_events(c, tk[c], ann_g[c], spy, gdd, cutoff=cut, with_outcomes=False)
        re_rows += r
    re = pd.DataFrame(re_rows)
    full = ev[ev.cik.isin(pick) & (ev.date <= "2015-12-31")]
    key = ["cik", "th", "date"]
    f_nb = full[full.mcap_backfill == 0]
    m = f_nb.merge(re, on=key, how="outer", suffixes=("", "_cut"), indicator=True)
    both = m[m._merge == "both"]
    L.append("1) 룩어헤드 점검 — 2015-12-31 에서 주가·연도 행을 자르고 사건·시총·Q 를 다시 계산 (기업 %d개 표본)" % len(pick))
    L.append(f"   전체 자료 기준 2015년 이전 사건: {len(full)}개 (그중 주식수 backfill {int(full.mcap_backfill.sum())}개 = 사전에 밝힌 예외)")
    only_full = m[m._merge == "left_only"]
    only_cut = m[(m._merge == "right_only")]
    only_cut_nb = only_cut[only_cut.mcap_backfill_cut == 0]
    L.append(f"   backfill 아닌 사건 {len(f_nb)}개: 자른 자료에서도 같은 날 사건 {len(both)}개 / 전체에만 있음 {len(only_full)}개 / "
             f"자른 쪽에만 있음(backfill 아님) {len(only_cut_nb)}개")
    if len(both):
        L.append(f"   고점 일치 {np.isclose(both.peak, both.peak_cut).mean():.1%} / 시총 일치 "
                 f"{np.isclose(both.mcap, both.mcap_cut, rtol=1e-9).mean():.1%} / Q 일치 {(both.Q == both.Q_cut).mean():.1%} "
                 f"/ 등급 일치 {(both.grade.fillna('-') == both.grade_cut.fillna('-')).mean():.1%} / M 일치 {(both.M == both.M_cut).mean():.1%}")
        bad = both[both.Q != both.Q_cut]
        if len(bad):
            L.append("   Q 불일치 사례: " + "; ".join(f"{r.ticker} {r.date} {r.Q}->{r.Q_cut}" for r in bad.head(10).itertuples()))
    if len(only_full):
        L.append("   전체에만 있는 사례: " + "; ".join(f"{r.ticker} {r.date}" for r in only_full.head(10).itertuples()))
    # 2) B&H 재현
    L.append("")
    L.append("2) B&H 재현")
    tri = pd.read_parquet(CK / "data" / "panel" / "monthly_tri_first.parquet")
    tri.columns = tri.columns.astype(int)
    diffs = []
    for c in pick[:150]:
        if c not in tri.columns:
            continue
        df = load_price(tk[c])
        dates = df.index.values.astype("datetime64[D]")
        adj = df.adj_close.values
        s = tri[c].dropna()
        if len(s) < 40:
            continue
        for k in rng.choice(len(s) - 36, size=3, replace=False):
            m0, m1 = s.index[k], s.index[k + 36]
            i = np.searchsorted(dates, np.datetime64(m0.to_timestamp(how="end").date()), side="right") - 1
            mine = ret_to(dates, adj, i, np.datetime64(m1.to_timestamp(how="end").date()))
            diffs.append(mine - (s.iloc[k + 36] / s.iloc[k] - 1))
    diffs = np.array(diffs)
    L.append(f"   종목 36개월 보유 수익: 내 함수(일봉) vs 엔진 패널 monthly_tri — {len(diffs)}건, 최대 절대 차이 {np.abs(diffs).max():.2e}")
    i0, i1 = spy.index.searchsorted(pd.Timestamp("2006-01-03")), len(spy) - 1
    yrs = (spy.index[i1] - spy.index[i0]).days / 365.25
    L.append(f"   SPY B&H {spy.index[i0].date()} ~ {spy.index[i1].date()}: 총수익 {spy.iloc[i1] / spy.iloc[i0] - 1:+.1%}, "
             f"연 {(spy.iloc[i1] / spy.iloc[i0]) ** (1 / yrs) - 1:.2%} (배당 포함, 알려진 값 약 연 10~11%)")
    L.append(f"   S&P 낙폭: 2009-03-09 {gdd.loc['2009-03-09']:.1%} (알려진 값 −56.8%), 2020-03-23 {gdd.loc['2020-03-23']:.1%} (−33.9%), "
             f"2022-10-12 {gdd.loc['2022-10-12']:.1%} (−25.4%)")
    # 3) 사건 정의 자체 점검
    L.append("")
    L.append("3) 사건 정의 점검")
    c = np.array([100, 80, 69, 60, 49, 75, 100, 110, 76, 50, 120.0])
    L.append(f"   합성 가격 {c.tolist()} -> −30% 사건 위치 {find_events(c, -0.30)[0].tolist()} (기대 [2, 8]), "
             f"−50% 사건 위치 {find_events(c, -0.50)[0].tolist()} (기대 [4, 9])")
    e30 = ev[ev.th == 30]
    L.append(f"   사건일 낙폭: −30% 사건 최대 {e30.dd.max():.3f} (≤ −0.30 이어야 함), 시총 최소 {ev.mcap.min() / 1e9:.2f}십억 달러")
    L.append(f"   한 기업·한 문턱에서 같은 고점을 두 번 쓴 사건: {int(ev.duplicated(['cik', 'th', 'peak']).sum())}개 (0 이어야 함)")
    L.append(f"   회복 순서 모순(rec1=1 인데 rec3=0): {int(((ev.rec1 == 1) & (ev.rec3 == 0)).sum())}개")
    txt = "\n".join(L)
    (RES / "C_engine_check.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


# ---------------------------------------------------------------- 요약
def pct(x, d=0):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.{d}f}%"


def pp(x):
    return "—" if not np.isfinite(x) else f"{x * 100:+.1f}%p"


def write_summary(ev, tab, ver, lb, ph, ref, now, post):
    L = ["파트 C 요약 — 종목별 큰 하락 뒤 회복 확률 (작업자 3, 2026-11-22)", "=" * 70, ""]
    interp = HERE / "src" / "C_interp.txt"  # 결과를 본 뒤 사람이 쓴 해석(숫자는 아래 표가 원본)
    if interp.exists():
        L += interp.read_text(encoding="utf-8").strip().splitlines() + [""]
    T = tab.set_index(["문턱", "구간", "조건"])
    L.append("[판정] (대표 = −30% 사건, 3년 안 직전 고점 회복 확률의 집단 간 차이)")
    for d in ver.to_dict("records"):
        L.append(f"  {d['문턱']} {d['변수']} ({d['비교']}): {d['판정']} [{d['대표 판정']}] — {d['사유']}")
        for per in ("학습", "검증"):
            L.append(f"      {per}: {pct(d[f'{per} A 회복3년'])} vs {pct(d[f'{per} B 회복3년'])}, 차이 {pp(d[f'{per} 차이'])} "
                     f"(기업군집 90% {pp(d[f'{per} 기업군집 90% 하한'])} ~ {pp(d[f'{per} 기업군집 90% 상한'])}; "
                     f"연도군집 참고 {pp(d[f'{per} 연도군집 90% 하한(참고)'])} ~ {pp(d[f'{per} 연도군집 90% 상한(참고)'])}) "
                     f"사건/기업 A {d[f'{per} A 사건/기업']}, B {d[f'{per} B 사건/기업']} | "
                     f"사건율 보정 하한 차이 {pp(d[f'{per} 사건율 보정 하한 차이'])}, 극단 하한 차이 {pp(d[f'{per} 극단 하한 차이'])}")
    L.append("")
    L.append("[기본 확률] 시총 ≥ $10억, 살아남은 회사 기준(낙관적) → 괄호는 생존편향 하한(사건율 보정 / 극단)")
    for th in ("−30%", "−50%"):
        for per in ("학습", "검증"):
            r = T.loc[(th, per, "전체")]
            b = lb[(lb.문턱 == th) & (lb.구간 == per)].set_index("기간")
            L.append(f"  {th} {per}: 사건 {int(r['사건 수'])}개 / 기업 {int(r['기업 수'])}개 | 회복 1년 {pct(r['회복1년'])} "
                     f"({pct(b.loc['1년', '사건율 보정 하한'])}/{pct(b.loc['1년', '극단 하한'])}), "
                     f"3년 {pct(r['회복3년'])} ({pct(b.loc['3년', '사건율 보정 하한'])}/{pct(b.loc['3년', '극단 하한'])}), "
                     f"5년 {pct(r['회복5년'])} ({pct(b.loc['5년', '사건율 보정 하한'])}/{pct(b.loc['5년', '극단 하한'])})")
            L.append(f"      36개월 수익 중앙 {pct(r['36개월 수익 중앙'])} · 평균 {pct(r['36개월 수익 평균'])}, S&P 대비 초과 중앙 {pct(r['36개월 초과 중앙'])} · "
                     f"평균 {pct(r['36개월 초과 평균'])}, 지수 하회 확률 {pct(r['36개월 지수 하회 확률'])}, 추가 −30% 확률 1년 {pct(r['추가 −30% (1년)'])} · 3년 {pct(r['추가 −30% (3년)'])}")
        r = T.loc[(th, "최근", "전체")]
        L.append(f"  {th} 최근(2022~, 참고): 사건 {int(r['사건 수'])}개 | 회복 1년 {pct(r['회복1년'])} (n={int(r['회복1년_n'])}), 12개월 수익 중앙 {pct(r['12개월 수익 중앙'])}, "
                 f"초과 중앙 {pct(r['12개월 초과 중앙'])}, 추가 −30% 1년 {pct(r['추가 −30% (1년)'])}")
    L.append("")
    L.append("[조건별 표 — −30% 사건] 회복 3년 / 36개월 초과수익 중앙 / 추가 −30%(3년) / 사건 수")
    for per in ("학습", "검증"):
        L.append(f"  <{per}>")
        for g in ["Q 통과", "Q 실패", "Q 판정 불가", "M 시장형", "M 개별형", "S 그 외(비순환)", "S 순환·제외섹터",
                  "Q 통과 × 시장형", "Q 통과 × 개별형", "Q 실패 × 시장형", "Q 실패 × 개별형"]:
            r = T.loc[("−30%", per, g)]
            note = " ※참고(연도 5개 미만)" if r["연도 수"] < 5 else ""
            L.append(f"    {g:<16} {pct(r['회복3년']):>5} / {pct(r['36개월 초과 중앙']):>6} / {pct(r['추가 −30% (3년)']):>5} / {int(r['사건 수']):>5}{note}")
    L.append("")
    L.append("[생존편향] 주가 자료에 상장폐지 종목 0개. 구간별 '주가 없는 큰 회사' 수와 주가 있는 회사의 사건 발생 비율")
    for per in ("학습", "검증"):
        L.append(f"  {per}: 주가 없는 기업 {ph[per]['cnt']['전체']}개 (주가 있는 기업 {ph[per]['alive_priced']}개), 사건 발생 비율 −30% {pct(ph[per]['inc'][30])}, −50% {pct(ph[per]['inc'][50])}")
    L.append("")
    L.append("[사후 민감도 — 판정에 쓰지 않음] M2: S&P 가 최근 252거래일 고점 대비 −15% 이하일 때만 시장형")
    for d in post.to_dict("records"):
        L.append(f"  {d['문턱']} {d['구간']}: 시장형 {pct(d['시장형 회복3년'])} (n={d['시장형 사건']}, 연도 {d['시장형 연도 수']}개) vs 개별형 {pct(d['개별형 회복3년'])} "
                 f"(n={d['개별형 사건']}), 차이 {pp(d['차이'])} (기업군집 90% {pp(d['기업군집 90% 하한'])} ~ {pp(d['기업군집 90% 상한'])}; "
                 f"연도군집 {pp(d['연도군집 90% 하한'])} ~ {pp(d['연도군집 90% 상한'])}) | 36개월 초과 중앙 {pct(d['시장형 36개월 초과 중앙'])} vs {pct(d['개별형 36개월 초과 중앙'])}")
    L.append("")
    L.append("[참고 사례 — 판정 외]")
    for k, v in now.items():
        L.append(f"  {k}: {v}")
    if len(ref):
        for nm, g in ref.groupby("종목"):
            for th, gg in g.groupby("문턱"):
                rec = gg[gg["상태"] == "회복"]
                L.append(f"  {nm} {th}: 사건 {len(gg)}번, 회복 {len(rec)}번, 사건일→회복 일수 중앙 "
                         f"{rec['사건일→회복 일수'].median() if len(rec) else float('nan'):.0f}일 (최소 {rec['사건일→회복 일수'].min() if len(rec) else float('nan'):.0f}, "
                         f"최대 {rec['사건일→회복 일수'].max() if len(rec) else float('nan'):.0f})")
    L.append("")
    L.append("파일: C_events.csv(사건 원자료), C_table.csv(조건표), C_verdict.csv(판정), C_lowerbound.csv(하한), "
             "C_survivorship.txt, C_engine_check.txt, C_reference.csv(삼성전자·NVDA 사건 목록), C_by_year.csv, "
             "C_posthoc.csv(사후 민감도), C_universe_status.csv")
    txt = "\n".join(L)
    (RES / "C_summary.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("surv", "all"):
        survivorship()
    if cmd in ("events", "all"):
        build_events()
    if cmd in ("check", "all"):
        engine_check()
    if cmd in ("analyze", "all"):
        analyze()
