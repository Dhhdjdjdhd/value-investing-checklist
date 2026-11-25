"""한국(코스피) 패널 생성 — 미국 build_panel.py와 같은 형식으로 data/kr/panel/에 저장해 backtest.py를 그대로 쓴다.

- 회사 키 cik = DART 고유번호(정수), ticker = 종목코드
- 주가: 현재 상장(Yahoo .KS 있음) = Yahoo close(분할 반영)·adj_close(배당 포함)
        상장폐지 등(Yahoo 없음) = 네이버 수정주가(배당 미반영 → 수익률이 약간 낮게 잡힘, 보수적)
- 주식수(오늘 기준) sh_adj = 결산일 주식수 × 결산일 이후 Yahoo 분할 비율의 곱.
  Yahoo 분할 이력이 없는 회사는 미국과 같은 점프 휴리스틱(연도 간 2·3·4·5·10…배 변화)으로 맞춘다.
- 시가총액(t) = close(t) × sh_adj(avail ≤ t 인 최신 연도행)
실행: py src/kr_build_panel.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checklist import row_features  # noqa: E402
from fundamentals import shares_today_basis  # noqa: E402
from kr_fundamentals import KR, build  # noqa: E402

OUT = KR / "panel"
PR = KR / "prices"
START = pd.Timestamp("2015-01-01")

# 미국 SECTOR_EXCL_SIC를 KSIC(induty_code 앞자리)로 옮김
EXCL_PREFIX = ("05", "06", "07", "08",  # 광업
               "192",  # 석유정제
               "201",  # 기초화학
               "24",  # 1차금속(철강·비철)
               "171",  # 펄프·종이
               "50", "51",  # 해운·항공
               "411",  # 건물(주택)건설
               "681",  # 부동산 임대(리츠)
               "64", "65", "66")  # 금융·보험 (단 일반 지주회사 64992는 아래에서 살림)


def excluded(code, name):
    c = str(code or "")
    if c.startswith("64992"):
        return "금융지주" in str(name)
    return c.startswith(EXCL_PREFIX)


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def _naver(code):
    n = PR / "naver" / f"{code}.csv"
    if not n.exists():
        return None
    df = pd.read_csv(n, parse_dates=["date"]).set_index("date").sort_index()
    df = df[df.close > 0]
    df["adj_close"] = df["close"]
    return df


def load_px(code):
    """Yahoo는 네이버와 2016년 이후 모든 해(연 중앙값)·최근 값이 2% 안에서 맞을 때만 쓴다.
    어긋나면(Yahoo 오류 — 예: DH오토넥스 5,020배 — 이거나 감자·유상증자 조정 방식 차이) 네이버를 쓴다."""
    nv = _naver(code)
    y = PR / "yahoo" / f"{code}.csv"
    if y.exists():
        df = pd.read_csv(y, parse_dates=["date"]).set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["close", "adj_close"])
        df = df[(df.close > 0) & (df.adj_close > 0)]
        if len(df) > 260 and nv is not None:
            j = pd.concat([df.close, nv.close], axis=1, keys=["y", "n"]).dropna()
            q = (j.y / j.n)[j.index >= "2016-01-01"]
            yr = q.groupby(q.index.year).median()
            if len(q) and yr.between(0.98, 1.02).all() and abs(q.iloc[-1] - 1) < 0.02:
                return df, "yahoo"
    if nv is not None:
        return nv, "naver"
    return None, None


def fix_share_units(ann, px):
    """주식수 1000배 오류 보정 (2026-11-19). fix_units는 회사 중앙값과 비교해서, 틀린 해가 다수면(조선내화 3년 중 2년)
    오히려 맞는 해를 틀린 쪽으로 바꾼다. 그래서 두 근거가 모두 맞을 때만 고친다:
    ① 주식수 ÷ EPS 역산 주식수 ≈ 1000배(300~3000)  ② 그 주식수로 낸 결산일 PBR > 100 (반대 방향은 1/1000, PBR < 0.01).
    EPS 쪽이 틀린 회사(대한제당 등)는 PBR이 정상이라 건드리지 않는다."""
    n = 0
    for i, r in ann.iterrows():
        df = px.get(r.ticker, (None, None))[0]
        if df is None or not (r.sh_implied > 0) or not (r.equity > 0) or not (r.sh_adj > 0):
            continue
        k = df.index.searchsorted(r.fye, side="right") - 1
        if k < 0 or (r.fye - df.index[k]).days > 10:
            continue
        q, pbr = r.sh_adj / r.sh_implied, df.close.iloc[k] * r.sh_adj / r.equity
        if 300 < q < 3000 and pbr > 100:
            ann.at[i, "sh_adj"] = r.sh_adj / 1000
            n += 1
        elif 1 / 3000 < q < 1 / 300 and pbr < 0.01:
            ann.at[i, "sh_adj"] = r.sh_adj * 1000
            n += 1
    log(f"주식수 1000배 보정 {n}행")


def flags(ann, mc, tri):
    """②금액 단위 오류 ③감자 등으로 시총이 틀렸을 의심 — 회사 단위 표시. kr_backtest에서 제외 실험에 쓴다."""
    a = ann[ann.cy >= 2016].sort_values(["cik", "cy"])
    g = a.groupby("cik")
    ra = a.assets / g.assets.shift(1)
    won = a[(ra > 50) | (ra < 0.02) | ((a.assets < 1e9) & (a.mcap_fy > 1e11))]
    pbr = a.mcap_fy / a.equity.where(a.equity > 0)
    ratio = a[(a.mcap_fy / a.rev > 100) | (pbr > 50) | (pbr < 0.05)]
    # 주가 변화로 설명되지 않는 월 시총 3배 이상 급변 = 주식수 단계 변화(감자·수정주가 불일치)
    jm = (np.log(mc / mc.shift(1)) - np.log(tri / tri.shift(1))).abs() > np.log(3)
    jump = jm.loc[jm.index >= pd.Period("2017-01", "M")].any()
    out = []
    for why, s in (("금액단위", set(won.cik)), ("시총비율", set(ratio.cik)), ("주식수급변", set(jump[jump].index))):
        out += [{"cik": c, "why": why} for c in s]
    f = pd.DataFrame(out).groupby("cik").why.agg("+".join).reset_index()
    f["name"] = f.cik.map(ann.drop_duplicates("cik").set_index("cik").name)
    return f


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    comp = pd.read_csv(KR / "companies.csv", dtype=str)
    ann = build()
    ann = ann.merge(comp[["corp_code", "stock_code", "name", "induty_code"]], on="corp_code", how="left")
    ann["cik"] = ann.corp_code.astype(int)
    ann["ticker"] = ann.stock_code
    ann["sic"] = ann.induty_code
    ann["end"] = ann.fye
    ann["sector_excl"] = [excluded(c, n) for c, n in zip(ann.induty_code, ann.name)]
    ann["rev"] = ann["rev"].fillna(ann["op"].where(ann["op"] > 0))  # 매출 계정 없는 지주사 등: 추세 판정용 대체
    log(f"annual rows {len(ann)} / 회사 {ann.cik.nunique()}")

    sp = pd.read_csv(PR / "yahoo" / "splits.csv", dtype={"code": str}, parse_dates=["date"])
    sp["ticker"], sp["ratio"] = sp.code, sp.numerator / sp.denominator
    sp = sp[sp.ratio > 0]
    px = {t: load_px(t) for t in ann.ticker.dropna().unique()}
    ann["sh_filed"] = ann["fye"]  # 주식수 기준일 = 결산일(분할이 결산 후 일어났으면 보정)
    ann["dil_sh"] = ann["sh"]
    # Yahoo 분할 이력은 Yahoo 가격을 쓰는 회사에만 적용, 나머지는 주식수 점프 휴리스틱
    tick = {c: t for c, t in zip(ann.cik, ann.ticker) if px.get(t, (None, None))[1] == "yahoo"}
    ann["sh_adj"] = shares_today_basis(ann, sp, tick)
    fix_share_units(ann, px)
    ann["eps_c"] = ann["ni"] / ann["sh_adj"]
    ann["opm"] = ann["op"] / ann["rev"]
    ann["roe"] = (ann["ni"] / ann["equity"]).where(ann["equity"] > 0)

    m_mcap, m_tri, m_dd, fy_mcap, src = {}, {}, {}, {}, {}
    for j, (cik, a) in enumerate(ann.groupby("cik")):
        df, s = px.get(a.ticker.iloc[0], (None, None))
        if df is None or len(df) < 120:
            continue
        df = df[df.index >= START - pd.Timedelta(days=400)]
        sh = pd.Series(a.sh_adj.values, index=a.avail.values).dropna().sort_index()
        sh = sh[~sh.index.duplicated(keep="last")]
        if sh.empty or df.empty:
            continue
        shd = sh.reindex(df.index, method="ffill")
        mc = df.close * shd
        me = df.index.to_series().groupby(df.index.to_period("M")).max()
        me = me[me >= START]
        m_mcap[cik] = pd.Series(mc.loc[me.values].values, index=me.index)
        m_tri[cik] = pd.Series(df.adj_close.loc[me.values].values, index=me.index)
        hi = df.close.rolling(252, min_periods=200).max()
        m_dd[cik] = pd.Series((df.close / hi - 1).loc[me.values].values, index=me.index)
        k = df.index.searchsorted(a.end.values, side="right") - 1
        for idx, kk, end, s_ in zip(a.index, k, a.end, a.sh_adj):
            if kk >= 0 and (end - df.index[kk]).days < 10:
                fy_mcap[idx] = df.close.iloc[kk] * s_
        src[cik] = s
        if j % 200 == 0:
            log(f"[{j}] {a.name.iloc[0]}")
    ann["mcap_fy"] = pd.Series(fy_mcap)
    ann["per_fy"] = (ann.mcap_fy / ann.ni).where(ann.ni > 0)
    ann["px_src"] = ann.cik.map(src)
    log("features...")
    feats = [row_features(g) for _, g in ann.groupby("cik")]
    ann = ann.join(pd.concat(feats))
    ann["per_hist"] = [list(g.per_fy.values[max(0, i - 9):i + 1]) for _, g in ann.groupby("cik", sort=True)
                       for i in range(len(g))]
    ann.to_parquet(OUT / "annual_first.parquet")
    pd.DataFrame(m_mcap).to_parquet(OUT / "monthly_mcap_first.parquet")
    pd.DataFrame(m_tri).to_parquet(OUT / "monthly_tri_first.parquet")
    pd.DataFrame(m_dd).to_parquet(OUT / "monthly_dd_first.parquet")
    fl = flags(ann, pd.DataFrame(m_mcap), pd.DataFrame(m_tri))
    fl.to_csv(OUT / "flags.csv", index=False, encoding="utf-8-sig")
    log(f"이상치 표시 {len(fl)}개사 → panel/flags.csv")
    log(f"done rows {len(ann)} priced {len(m_mcap)} (yahoo {sum(v == 'yahoo' for v in src.values())})")


if __name__ == "__main__":
    sys.exit(main())
