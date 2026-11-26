"""T7 자료 조립: 1971-01~2026-10 월간 수익률(달러 기준 주 결과) + 1990-01~ 원화 보조.

달러(results/t7_assets_usd.csv)
  sp   : S&P500 총수익. 1990-01~ 는 `대안전략 연구/src/alloc.py` build().ru 그대로(^GSPC+2.8% → 1993-03부터 SPY 조정종가).
         1971-01~1989-12 는 Yahoo ^GSPC 월말 종가 + Shiller 배당(D/12)으로 앞으로 이어 붙임.
  b30  : 30년 국채 합성(alloc.bond_ret, 매달 새 30년물). 금리: 1989-01~ ^TYX 월말(alloc과 동일),
         1977-02~1988-12 FRED GS30(월평균), 1970-12~1977-01 FRED GS20 + (GS30−GS20 평균 스프레드, 1977-02~1978-01).
  gold : LBMA 오후 고시 월평균(datahub.io core/gold-prices ← Bundesbank). FRED GOLDAMGBD228NLBM 은 삭제(404, 2026-11-26 확인).
  gold_gcf : 참고용, Yahoo GC=F 월말(2000-08~, 대안전략 연구 캐시) — 월평균 vs 월말 차이 점검에만 사용.
원화(results/t7_assets_krw.csv, 1990-01~): eq 환노출 S&P, b30h 30년 국채 환헤지(캐리 포함), gold 금×원/달러 — alloc.build() 재사용.
실행: py src/t7_data.py
"""
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
ALT = ROOT.parent / "대안전략 연구"
sys.path.insert(0, str(ALT / "src"))
from alloc import bond_ret, build, yahoo  # noqa: E402  (대안전략 연구 합성 시계열 재사용)

START, END = "1971-01", "2026-10"


def fred(sid):
    s = pd.read_csv(RES / f"t7_raw_fred_{sid}.csv", index_col=0, parse_dates=True).iloc[:, 0]
    s.index = s.index.strftime("%Y-%m")
    return pd.to_numeric(s, errors="coerce")


def shiller():
    d = pd.read_excel(ALT / "data/shiller/ie_data.xls", sheet_name="Data", header=7)
    d = d[pd.to_numeric(d.Date, errors="coerce").notna()].copy()
    d["m"] = d.Date.astype(float).map(lambda x: f"{int(x)}-{round((x - int(x)) * 100):02d}")
    d = d.set_index("m")
    for c in ["P", "D", "Rate GS10"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def main():
    D = build()  # 1990-01~ (alloc): ru 달러 주식, un 원화 주식, bh 30년 환헤지, carry, fx, tyx
    log = []

    # --- S&P 총수익(달러) ---
    gs = pd.read_csv(RES / "t7_raw_yahoo_GSPC_m.csv", index_col=0).iloc[:, 0]   # 월말 종가, 1970-01~
    sh = shiller()
    div_m = (sh.D / 12).reindex(gs.index)                                          # 월 배당(지수 단위)
    sp_early = (gs + div_m) / gs.shift(1) - 1
    sp = pd.concat([sp_early.loc["1971-01":"1989-12"], D.ru.loc["1990-01":END]])
    log.append(f"S&P: 1971-01~1989-12 Yahoo ^GSPC 월말 + Shiller D/12 / 1990-01~ alloc.build().ru. "
               f"1971~89 배당수익률 평균 {(div_m.loc['1971-01':'1989-12'] / gs.shift(1).loc['1971-01':'1989-12']).mean() * 12:.2%}/년")

    # --- 30년 국채 금리 이어 붙이기 ---
    gs30, gs20 = fred("GS30"), fred("GS20")
    spread = (gs30 - gs20).loc["1977-02":"1978-01"].mean()
    y = pd.Series(dtype=float)
    y = pd.concat([(gs20 + spread).loc["1970-12":"1977-01"], gs30.loc["1977-02":"1988-12"], yahoo("^TYX").loc["1989-01":END]]) / 100
    assert y.index.is_monotonic_increasing and not y.index.duplicated().any()
    y = y.ffill()
    b30 = bond_ret(y, 30).loc["1971-01":END]
    chk = (b30.loc["1990-01":] - (D.bh - D.carry).loc["1990-01":END]).abs().max()
    log.append(f"30년 국채 금리: 1970-12~1977-01 GS20+{spread:.3f}%p(1977-02~1978-01 평균 스프레드) / 1977-02~1988-12 GS30 / 1989-01~ ^TYX. "
               f"1990~ alloc(bh−carry)와 최대 차 {chk:.2e} (동일 확인)")

    # --- 금 ---
    g = pd.read_csv(RES / "t7_raw_gold_datahub_monthly.csv", index_col=0).iloc[:, 0]
    gold = g.pct_change().loc["1971-01":END]
    gcf = yahoo("GC=F").pct_change()  # 캐시(대안전략 연구/data/y_GC=F_c.csv) 사용, 네트워크 호출 없음
    log.append(f"금: datahub 월평균 {g.index[0]}~{g.index[-1]}, 1971-01 ${g.loc['1971-01']:.0f} → 2026-10 ${g.loc['2026-10']:.0f}. "
               f"GC=F(월말)와 월수익 상관 {pd.concat([gold, gcf], axis=1).dropna().corr().iloc[0, 1]:.3f} (2000-09~)")

    A = pd.DataFrame({"sp": sp, "b30": b30, "gold": gold}).loc[START:END]
    A["gold_gcf"] = gcf.reindex(A.index)
    assert A[["sp", "b30", "gold"]].notna().all().all(), A[A[["sp", "b30", "gold"]].isna().any(axis=1)]
    A.to_csv(RES / "t7_assets_usd.csv", encoding="utf-8-sig")

    # --- 원화 보조 (1990-01~) ---
    dfx = D.fx.pct_change()
    K = pd.DataFrame({"eq": D.un, "b30h": D.bh, "gold": (1 + gold.reindex(D.index)) * (1 + dfx) - 1}).loc["1990-01":END]
    K.to_csv(RES / "t7_assets_krw.csv", encoding="utf-8-sig")

    # --- 출처 기록 ---
    today = datetime.date.today().isoformat()
    src = [
        f"# T7 데이터 출처 (받은 날짜 {today})",
        "- 금: datahub.io core/gold-prices monthly.csv (원자료 Deutsche Bundesbank, LBMA 오후 고시 월평균, USD/oz) — results/t7_raw_gold_datahub_monthly.csv",
        "  * FRED GOLDAMGBD228NLBM 은 2026-11-26 요청 시 404(삭제됨). 설계서가 허용한 '동등한 공개 월별 자료'로 대체.",
        "  * 월평균이라 월말 고시보다 변동성이 조금 작게 나온다. 2000-09~ GC=F 월말과 비교표(t7_gold_source_check.csv)로 영향 크기를 적었다.",
        "- 30년 국채 금리: FRED GS30(1977-02~), GS20(1953-04~) — results/t7_raw_fred_GS30.csv, t7_raw_fred_GS20.csv (월평균, %)",
        "  * 1989-01~ 는 대안전략 연구 캐시 ^TYX 월말(data/y_TYX_c.csv) — alloc.build() 그대로.",
        "- S&P500: Yahoo ^GSPC 일간 → 월말 종가(1970-01~) — results/t7_raw_yahoo_GSPC_m.csv; 배당은 대안전략 연구/data/shiller/ie_data.xls (Robert Shiller, D열, 연율 배당).",
        "  * 1990-01~ 는 alloc.build().ru (^GSPC+2.8%/년 → 1993-03부터 SPY 조정종가) 그대로.",
        "- 원/달러·CD91: 대안전략 연구/data/ecos_krw.csv (ECOS, alloc.build() 재사용). 원화 보조 결과는 1990-01~.",
        "",
        "# 조립 로그",
        *[f"- {x}" for x in log],
        f"- 달러 자산 표: {A.index[0]}~{A.index[-1]} {len(A)}개월 / 원화 보조: {K.index[0]}~{K.index[-1]} {len(K)}개월",
    ]
    (RES / "t7_sources.txt").write_text("\n".join(src), encoding="utf-8")
    print("\n".join(src))


if __name__ == "__main__":
    main()
