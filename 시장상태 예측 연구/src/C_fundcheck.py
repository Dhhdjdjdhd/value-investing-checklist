"""추가 점검: 엔진의 펀드·신탁 제외 조건(이름에 TRUST·ETF·FUND)이 작동하지 않은 것이 체크리스트 v2 결과에 영향을 줬나.

배경: backtest.load 는 패널의 name 열로 이름 조건을 거는데, 그 열이 전부 비어 있어 SIC 6221 조건만 작동했다.
방법: 엔진(체크리스트 검증/src)을 불러오기만 하고, 메모리에서 유니버스 열만 빼고 다시 돌린다. 엔진·패널 파일은 건드리지 않는다.
실행: py -I src/C_fundcheck.py -> results/C_fundcheck.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
CK = HERE.parent / "체크리스트 검증"
sys.path.insert(0, str(CK / "src"))
from backtest import perf  # noqa: E402
from optimize import IS, OOS, Runner, ew_universe  # noqa: E402

FINAL = {"use_price": None, "rank": "qv", "slots": 20, "rebalance": 3, "swap_gap": None, "buffer": 1.5}  # final.py 와 같음
NAME_RE = r"\bTRUST\b|\bETF\b|\bFUND\b"
# 진짜 펀드·상품 신탁으로 볼 근거(이름): 운용사 상표, 기초자산, ETF/FUND
REAL_RE = r"\bETF\b|\bFUND\b|ISHARES|SPDR|GRAYSCALE|PROSHARES|INVESCO DB|WISDOMTREE|BITCOIN|ETHEREUM|\bGOLD\b|\bSILVER\b|COMMODIT|ROYALTY"
PERIODS = (("학습 2011.04~2018.12", IS), ("검증 2019.01~2026.10", OOS), ("전체", (IS[0], None)))


def classify():
    c = pd.read_csv(CK / "data" / "sec" / "companies.csv").drop_duplicates("cik").set_index("cik")
    nm = c["name"].fillna("").astype(str).str.upper()
    sic = pd.to_numeric(c.sic, errors="coerce")
    c["sic6221"] = sic.eq(6221)
    c["name_hit"] = nm.str.contains(NAME_RE)
    c["real_fund"] = c.sic6221 | (c.name_hit & (nm.str.contains(REAL_RE) | sic.eq(6199) | sic.eq(6189)))
    c["kind"] = np.where(c.real_fund, "펀드·상품 신탁", np.where(c.name_hit, "일반 기업(이름만 TRUST 등)", ""))
    return c


def holdings(log, months):
    """매매 기록을 다시 재생해 월별 보유 종목 집합을 만든다 (m 월말 판정 후 다음 달 보유)."""
    by_m = dict(tuple(log.groupby("m")))
    hold, out = set(), {}
    for m in months:
        for r in by_m.get(m, pd.DataFrame()).itertuples():
            if r.act == "buy":
                hold.add(r.cik)
            else:
                hold.discard(r.cik)
        out[m] = set(hold)
    return out


def split(r):
    rows = {}
    for tag, (a, b) in PERIODS:
        rr = r[(r.index >= pd.Period(a, "M")) & ((r.index <= pd.Period(b, "M")) if b else True)]
        rows[tag] = perf(rr)
    return rows


def fmt(p):
    return f"CAGR {p['CAGR']:6.2%}  변동성 {p['vol']:6.2%}  Sharpe {p['Sharpe']:5.3f}  MDD {p['MDD']:7.2%}  ({p['months']}개월)"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    L = ["추가 점검: 펀드·신탁 제외 조건 미작동이 체크리스트 v2 결과에 준 영향 (작업자 3, 2026-11-22)", "=" * 78, ""]
    c = classify()
    R = Runner("first")
    uni = [x for x in R.mc.columns]
    in_uni = c.reindex(uni)
    leak = in_uni[in_uni.name_hit.fillna(False)]
    L.append("1. 유니버스 점검")
    ann_name_empty = R.ann["name"].isna().all()
    L.append(f"   패널 name 열이 전부 비어 있음: {ann_name_empty}  → 엔진의 이름 조건은 한 종목도 걸러내지 못했다(SIC 6221 조건만 작동).")
    L.append(f"   엔진 유니버스(월말 시총이 있는 종목) {len(uni):,}개 중 SIC 6221: {int(in_uni.sic6221.fillna(False).sum())}개(정상 제외됨)")
    L.append(f"   이름 조건(TRUST·ETF·FUND)에 걸리는데 유니버스에 남아 있던 종목: {len(leak)}개")
    L.append(f"     그중 펀드·상품 신탁: {int(leak.real_fund.sum())}개 / 일반 기업(이름만): {int((~leak.real_fund).sum())}개")
    last_mc = R.mc.iloc[-1]
    max_mc = R.mc.max()
    L.append("")
    L.append("   남아 있던 종목 목록 (분류 / 티커 / 이름 / SIC / 역대 최대 월말 시총 십억 달러)")
    for cik, r in leak.sort_values(["real_fund", "name"], ascending=[False, True]).iterrows():
        L.append(f"     [{r.kind}] {str(r.tickers).split(';')[0]:<6} {r['name'][:44]:<44} SIC {r.sic} {r.sicDescription if isinstance(r.sicDescription, str) else ''} | {max_mc.get(cik, np.nan) / 1e9:,.1f}")
    L.append("")

    # 2. v2 원본 실행과 보유 내역
    r0, log0, _ = R.run("v2 원본", S=FINAL, group="fundcheck")
    months = [m for m in R.mc.index if m >= pd.Period(IS[0], "M")]
    H = holdings(log0, months)
    ever = set().union(*H.values())
    flagged_held = [x for x in ever if x in leak.index]
    L.append("2. (a) v2 포트폴리오에 들어간 적이 있는가 — 2011.04 ~ 2026.10, 보유 종목 연인원 "
             f"{sum(len(v) for v in H.values()):,}종목·월, 한 번이라도 보유한 종목 {len(ever)}개")
    if not flagged_held:
        L.append("   없음. 이름 조건에 걸리는 종목은 v2 포트폴리오에 한 달도 들어가지 않았다.")
    else:
        for x in flagged_held:
            ms = [m for m in months if x in H[m]]
            r = leak.loc[x]
            L.append(f"   [{r.kind}] {str(r.tickers).split(';')[0]} {r['name']} (SIC {r.sic}): {len(ms)}개월 ≈ {len(ms) / 3:.1f}분기 보유, "
                     f"비중 5%(1/20), {ms[0]} ~ {ms[-1]}")
    # 왜 안 들어갔나: 관문 통과 여부
    rows, st = R.state({**__import__("checklist").DEFAULT}, {**__import__("valuation").VDEFAULT})
    s = st[st.cik.isin(leak.index) & (st.m >= pd.Period(IS[0], "M"))]
    mcl = R.mc.stack().rename("mcap").reset_index()
    mcl.columns = ["m", "cik", "mcap"]
    s = s.merge(mcl, on=["m", "cik"], how="left")
    passed = s[s.grade.isin(["S", "A", "G"]) & ~s.sector_excl.fillna(False).astype(bool) & (s.mcap >= 10e9)]
    L.append(f"   참고: 이 {len(leak)}개 종목이 v2 관문 전체(등급 통과·제외 섹터 아님·시총 ≥ $100억)를 통과한 종목·월 수: {len(passed)}")
    if len(passed):
        for cik, g in passed.groupby("cik"):
            r = leak.loc[cik]
            L.append(f"     [{r.kind}] {str(r.tickers).split(';')[0]} {r['name']}: {len(g)}개월 통과 ({g.m.min()} ~ {g.m.max()}), 보유 여부 {'보유함' if cik in ever else '순위 밖이라 보유 안 함'}")
    sx = s.drop_duplicates("cik", keep="last")
    L.append(f"   탈락 이유(최근 상태 기준): 제외 섹터(SIC) {int(sx.sector_excl.fillna(False).astype(bool).sum())}개, 등급 X {int((sx.grade == 'X').sum())}개, "
             f"연도 행 자체가 있는 종목 {sx.cik.nunique()}개 / {len(leak)}개")
    L.append("")

    # 3. 필터를 제대로 적용한 판
    L.append("3. (b) 필터를 적용해 다시 돌린 결과")
    base = split(r0)
    ew0 = split(ew_universe(R.mc, R.tri))
    variants = {"이름 조건 전부 제외(엔진이 의도한 규칙)": set(leak.index),
                "펀드·상품 신탁만 제외(일반 기업은 남김)": set(leak.index[leak.real_fund])}
    res = {"원본(엔진 그대로)": (base, ew0, 0.0)}
    mc0, tri0, dd0 = R.mc, R.tri, R.dd
    for nm, drop in variants.items():
        keep = [x for x in mc0.columns if x not in drop]
        R.mc, R.tri, R.dd = mc0[keep], tri0[keep], dd0[keep]
        R.cache = {}
        r1, log1, _ = R.run(nm, S=FINAL, group="fundcheck")
        same = bool(np.allclose(r0.values, r1.reindex(r0.index).values, atol=1e-12))
        res[nm] = (split(r1), split(ew_universe(R.mc, R.tri)), float(np.abs(r0 - r1.reindex(r0.index)).max()), same, len(drop))
    R.mc, R.tri, R.dd = mc0, tri0, dd0
    for nm, v in res.items():
        L.append(f"   <{nm}>" + (f" — 제외 {v[4]}개, 원본과 월 수익 최대 차이 {v[2]:.2e} ({'완전히 같음' if v[3] else '다름'})" if len(v) > 3 else ""))
        for tag, _ in PERIODS:
            L.append(f"     v2        {tag:<22} {fmt(v[0][tag])}")
        for tag, _ in PERIODS:
            L.append(f"     EW 대형주 {tag:<22} {fmt(v[1][tag])}")
    L.append("")
    b = base["전체"]
    L.append(f"   원본 재현 확인: 전체 구간 CAGR {b['CAGR']:.1%}, Sharpe {b['Sharpe']:.2f}, MDD {b['MDD']:.0%} (최종보고서 15.0% / 1.07 / −22%)")
    L.append("")
    txt = "\n".join(L)
    (HERE / "results" / "C_fundcheck.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
