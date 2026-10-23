"""체크리스트 백테스트 엔진 독립 검증 (작업지시 W2, 작성: value-investing-checklist-f9).

실행 (작업 폴더 '체크리스트 검증' 기준):  py -m pytest tests -q
src/ 코드는 읽기만 하고 수정하지 않는다. 합성 데이터만 쓰므로 data/ 없이 돈다.
알려진 버그는 xfail(strict=True)로 남긴다 -> 고치면 XPASS 로 실패하니 그때 xfail 을 지운다.
2026-10-23 매니저 수정본(B1~B10·B14 반영) 기준으로 갱신. 1차 xfail 5개(B1·B3·B4·B5·B6 재현)는 모두 통과로 전환.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from backtest import monthly_state, simulate  # noqa: E402
from checklist import DEFAULT, grade, row_features  # noqa: E402
from fundamentals import build_annual_cf, fix_units, shares_today_basis  # noqa: E402
from valuation import VDEFAULT, dcf, intrinsic, per_median  # noqa: E402


# ---------------------------------------------------------------- 합성 companyfacts
def _fact(concept, end, val, filed, cik=1, dur=True, form="10-K"):
    end = pd.Timestamp(end)
    return {"cik": cik, "concept": concept, "unit": "USD", "start": end - pd.Timedelta(days=364) if dur else pd.NaT,
            "end": end, "val": float(val), "filed": pd.Timestamp(filed), "form": form, "fy": end.year, "fp": "FY",
            "accn": f"a{filed}"}


def _cf(rows):
    return pd.DataFrame(rows)


def _year_facts(end, filed, ni=10.0, rev=100.0, sh=100.0, cik=1):
    return [_fact("Revenues", end, rev, filed, cik), _fact("NetIncomeLoss", end, ni, filed, cik),
            _fact("OperatingIncomeLoss", end, ni * 1.3, filed, cik),
            _fact("WeightedAverageNumberOfDilutedSharesOutstanding", end, sh, filed, cik),
            _fact("StockholdersEquity", end, 50.0, filed, cik, dur=False)]


# ---------------------------------------------------------------- 1. 시점
def test_avail_is_first_10k_filing():
    rows = _year_facts("2016-12-31", "2017-02-15")
    # 다음 해 10-K 의 비교연도 값, 10-K/A 재공시는 avail 을 바꾸면 안 된다
    rows += [_fact("NetIncomeLoss", "2016-12-31", 11.0, "2018-02-15"), _fact("Revenues", "2016-12-31", 101, "2018-02-15"),
             _fact("NetIncomeLoss", "2016-12-31", 12.0, "2017-05-01", form="10-K/A")]
    a = build_annual_cf(_cf(rows), "first")
    assert len(a) == 1
    assert a.avail.iloc[0] == pd.Timestamp("2017-02-15")
    assert a.ni.iloc[0] == 10.0 and a.rev.iloc[0] == 100.0


def test_last_mode_takes_restated_value_but_same_avail():
    rows = _year_facts("2016-12-31", "2017-02-15")
    rows += [_fact("NetIncomeLoss", "2016-12-31", 11.0, "2018-02-15")]
    a = build_annual_cf(_cf(rows), "last")
    assert a.ni.iloc[0] == 11.0
    assert a.avail.iloc[0] == pd.Timestamp("2017-02-15")


def test_first_mode_value_known_at_avail_when_tag_changes():  # B6
    # FY2016 매출을 2017 10-K 는 SalesRevenueNet 로, 2019 10-K(비교연도)는 ASC 606 새 태그로 다시 보고
    rows = _year_facts("2016-12-31", "2017-02-15")
    rows = [r for r in rows if r["concept"] != "Revenues"]
    rows += [_fact("SalesRevenueNet", "2016-12-31", 100.0, "2017-02-15"),
             _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "2016-12-31", 130.0, "2019-02-15")]
    a = build_annual_cf(_cf(rows), "first")
    assert a.avail.iloc[0] == pd.Timestamp("2017-02-15")
    assert a.rev.iloc[0] == 100.0  # 2017-02-15 에 알 수 있던 값


def test_first_mode_drops_values_first_filed_after_avail():  # B6
    rows = _year_facts("2016-12-31", "2017-02-15")
    rows += [_fact("ShareBasedCompensation", "2016-12-31", 3.0, "2019-02-15")]  # 2년 뒤 10-K 에서 처음 태깅
    a = build_annual_cf(_cf(rows), "first")
    assert np.isnan(a.sbc.iloc[0])


def test_52_53_week_fiscal_years_kept():  # B7
    rows = (_year_facts("2011-01-01", "2011-03-01") + _year_facts("2011-12-31", "2012-02-28", ni=11)
            + _year_facts("2012-12-29", "2013-02-27", ni=12))
    a = build_annual_cf(_cf(rows), "first")
    assert list(a.cy) == [2010, 2011, 2012]
    assert list(a.ni) == [10, 11, 12]


def test_net_income_and_operating_income_fallbacks():  # B3
    rows = [_fact("Revenues", "2016-12-31", 100, "2017-02-15"), _fact("ProfitLoss", "2016-12-31", 9, "2017-02-15"),
            _fact("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                  "2016-12-31", 12, "2017-02-15"),
            _fact("InterestExpense", "2016-12-31", 2, "2017-02-15")]
    a = build_annual_cf(_cf(rows), "first")
    assert a.ni.iloc[0] == 9  # NetIncomeLoss 없으면 ProfitLoss
    assert a.op.iloc[0] == 14  # OperatingIncomeLoss 없으면 세전이익 + 이자비용
    rows += [_fact("NetIncomeLoss", "2016-12-31", 8, "2017-02-15")]
    assert build_annual_cf(_cf(rows), "first").ni.iloc[0] == 8  # 우선순위


def test_eps_implied_shares_when_diluted_shares_missing():  # B2 수집 수정 후 경로
    rows = [r for r in _year_facts("2016-12-31", "2017-02-15", ni=10)
            if r["concept"] != "WeightedAverageNumberOfDilutedSharesOutstanding"]
    rows += [{**_fact("EarningsPerShareDiluted", "2016-12-31", 0.5, "2017-02-15"), "unit": "USD/shares"}]
    a = build_annual_cf(_cf(rows), "first")
    assert a.dil_sh.iloc[0] == pytest.approx(20)


def _split_cf(last_restated=True):
    """FY2018·2019 희석주식수 100(원공시). 2020-08 4:1 분할 뒤 FY2020·21 10-K 는 비교연도를 400 으로 재작성."""
    rows = []
    for y, sh in ((2018, 100), (2019, 100), (2020, 400), (2021, 400)):
        rows += _year_facts(f"{y}-12-31", f"{y + 1}-02-15", ni=10 + y - 2018, sh=sh)
    if last_restated:
        for y, filed in ((2018, "2021-02-15"), (2019, "2021-02-15"), (2019, "2022-02-15")):
            rows.append(_fact("WeightedAverageNumberOfDilutedSharesOutstanding", f"{y}-12-31", 400, filed))
    return _cf(rows), pd.DataFrame({"ticker": ["XX"], "date": [pd.Timestamp("2020-08-31")], "ratio": [4.0]}), {1: "XX"}


def test_monthly_state_uses_only_available_rows():
    rows = pd.DataFrame({"cik": [1, 1], "cy": [2016, 2017], "avail": pd.to_datetime(["2017-03-01", "2018-03-01"]),
                         "grade": ["A", "S"]})
    months = pd.period_range("2017-02", "2020-06", freq="M")
    st = monthly_state(rows, months).set_index("m")
    assert pd.Period("2017-02", "M") not in st.index
    assert st.loc[pd.Period("2017-03", "M"), "cy"] == 2016
    assert st.loc[pd.Period("2018-02", "M"), "cy"] == 2016
    assert st.loc[pd.Period("2018-03", "M"), "cy"] == 2017
    assert (st.t >= st.avail).all()
    # 2년(730일) 넘게 갱신 없으면 버림: 2018-03-01 -> 2020-01-31 은 701일, 2020-02-29 는 730일
    assert st.index.max() == pd.Period("2020-01", "M")


# ---------------------------------------------------------------- 4. 분할 보정 (B4: splits.csv 기반)
def _sh_frame(sh, avail, cik=1):
    return pd.DataFrame({"cik": cik, "dil_sh": np.asarray(sh, float), "avail": pd.to_datetime(avail)})


AV4 = ["2012-02-15", "2013-02-15", "2014-02-15", "2015-02-15"]


def test_shares_today_basis_with_splits_csv_7for1():
    # AAPL 2014-06-09 7:1 처럼 휴리스틱 비율 목록에 없던 분할도 splits.csv 로 보정
    sp = pd.DataFrame({"ticker": ["AA"], "date": [pd.Timestamp("2014-06-09")], "ratio": [7.0]})
    sh = shares_today_basis(_sh_frame([900, 930, 950, 6200], AV4), sp, {1: "AA"})
    np.testing.assert_allclose(sh, [6300, 6510, 6650, 6200])


def test_shares_today_basis_with_ticker_keeps_stock_merger():
    # 분할 이력 없는 회사의 주식 발행 인수(1.5배)는 그대로 -> 희석이 dilution 에 남음
    sh = shares_today_basis(_sh_frame([100, 100, 150, 150], AV4), pd.DataFrame(columns=["ticker", "date", "ratio"]),
                            {1: "AA"})
    np.testing.assert_allclose(sh, [100, 100, 150, 150])


def test_shares_heuristic_without_ticker():
    # 티커 없는(상장폐지) 회사: 점프 휴리스틱. 15:1 은 잡고 1.5배 인수는 그대로
    sh = shares_today_basis(_sh_frame([60, 58, 870, 860], AV4), None, None)
    np.testing.assert_allclose(sh, [900, 870, 870, 860])
    sh2 = shares_today_basis(_sh_frame([100, 100, 150, 150], AV4), None, None)
    np.testing.assert_allclose(sh2, [100, 100, 150, 150])


def test_fix_units_thousands():
    # NVDA FY2008~11 처럼 희석주식수를 천 주 단위로 보고한 해
    np.testing.assert_allclose(fix_units([0.6, 0.55, 616, 625, 594]), [600, 550, 616, 625, 594])


def test_first_mode_shares_today_basis_end_to_end():
    cf, sp, tk = _split_cf()
    a = build_annual_cf(cf, "first", sp, tk)
    np.testing.assert_allclose(a.sh_adj, 400)  # 원공시 100 × 4
    np.testing.assert_allclose(a.eps_c, a.ni / 400)


def test_last_mode_shares_not_double_split():  # N1 회귀 테스트 (매니저 수정: 분할 기준일 = 값의 공시일 sh_filed)
    cf, sp, tk = _split_cf()
    a = build_annual_cf(cf, "last", sp, tk)
    np.testing.assert_allclose(a.sh_adj, 400)  # 현재 FY2018·19 는 1,600


# ---------------------------------------------------------------- 판정
def _hist(cy, eps, op=None):
    n = len(cy)
    return pd.DataFrame({"cy": cy, "roic": 0.25, "eps_c": np.asarray(eps, float), "ni": np.asarray(eps, float) * 100,
                         "rev": np.arange(n) + 100.0, "op": np.asarray(op if op is not None else eps, float) * 150,
                         "fcf_sbc": np.asarray(eps, float) * 100, "sh_adj": 100.0})


def test_covid_single_drop_is_allowed():
    cy = list(range(2015, 2025))
    eps = [1, 1.1, 1.2, 1.3, 1.4, 1.0, 1.5, 1.6, 1.7, 1.8]  # 2020 만 감소
    f = row_features(_hist(cy, eps)).iloc[-1]
    assert f.eps_consistent and f.eps_drops == 1
    eps2 = [1, 1.1, 1.2, 1.3, 1.2, 1.4, 1.5, 1.6, 1.7, 1.8]  # 2019 감소
    assert not row_features(_hist(cy, eps2)).iloc[-1].eps_consistent


def test_cyclical_numeric_rule():
    cy = list(range(2012, 2022))
    op = [1, 1.1, 1.2, 0.9, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]  # 2015 −25%
    assert row_features(_hist(cy, op, op)).iloc[-1].cyclical
    op2 = [1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.0, 1.8]  # 2020 −41% 는 제외
    assert not row_features(_hist(cy, op2, op2)).iloc[-1].cyclical


def test_grade_roic_mode_warn():
    # ROIC 미달: 기본(fail)은 X, roic_mode='warn' 이면 경고 1개 -> A
    cy = list(range(2012, 2022))
    h = _hist(cy, [1 + 0.1 * i for i in range(10)])
    h["roic"] = 0.12
    feat = row_features(h, DEFAULT)
    feat["ltd_ni"] = 1.0
    assert grade(feat, DEFAULT)[0].iloc[-1] == "X"
    g, warn = grade(feat, {**DEFAULT, "roic_mode": "warn"})
    assert g.iloc[-1] == "A" and warn.iloc[-1] == 1


def test_grade_respects_use_cyclical_param():  # B5
    cy = list(range(2012, 2022))
    op = [1, 1.1, 1.2, 0.9, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]
    h = _hist(cy, op, op)
    feat = row_features(h, DEFAULT)
    feat["ltd_ni"] = 1.0
    g_on, _ = grade(feat, DEFAULT)
    g_off, _ = grade(feat, {**DEFAULT, "use_cyclical": False})  # optimize.py "경기순환 숫자판정 끔"과 같은 호출
    assert g_on.iloc[-1] == "G"
    assert g_off.iloc[-1] != "G"


# ---------------------------------------------------------------- 내재가치
def test_dcf_matches_meta_hand_calc():
    # 02.종목분석/메타_META_분석_20261022.md 기본 시나리오: EPS 26.20, 11%/7%, 9%, PER 14.7 -> $658.64
    assert dcf(26.20, 0.11, 0.07, 0.09, 14.7) == pytest.approx(658.64, abs=0.05)


def test_per_median_drops_outliers():
    assert per_median(np.array([20, 22, 24, 100, np.nan])) == 22
    assert np.isnan(per_median(np.array([20, 22])))


def test_intrinsic_scenario_order():
    c, b, o = intrinsic(10.0, 8.0, 0.12, np.array([25, 26, 27, 28.0]), VDEFAULT)
    assert c < b < o


# ---------------------------------------------------------------- 5. simulate
def _market(n_stocks=5, months=("2011-01", "2011-12"), price=None):
    m = pd.period_range(*months, freq="M")
    ciks = list(range(1, n_stocks + 1))
    mc = pd.DataFrame(20e9, index=m, columns=ciks)
    tri = pd.DataFrame(100.0, index=m, columns=ciks) if price is None else price
    dd = pd.DataFrame(-0.1, index=m, columns=ciks)
    rows = []
    for mm in m:
        for c in ciks:  # 시총 20B, 기본 IV 40B+c -> 모두 목표가 아래, 여유는 cik 클수록 큼
            rows.append({"m": mm, "cik": c, "grade": "A", "iv": 40e9 + c * 1e9, "iv_opt": 60e9, "sector_excl": False,
                         "roic_med5": 0.2, "fcf_sbc": 1e9, "ni": 1e9})
    return mc, tri, dd, pd.DataFrame(rows)


def _sim(mc, tri, dd, st, **S):
    return simulate(None, mc, tri, dd, S={"start": "2011-01", **S}, rows=st, state=st)


def test_simulate_slots_and_cost():
    mc, tri, dd, st = _market()
    r, log, nh = _sim(mc, tri, dd, st, slots=3, cost=0.001, swap_gap=None)
    assert nh.max() == 3
    assert set(log[log.act == "buy"].cik) == {3, 4, 5}  # 여유 큰 순
    assert r.iloc[0] == pytest.approx(-3 * (1 / 3) * 0.001)  # 가격 불변, 매수 3건 비용
    assert (r.iloc[1:] == 0).all()


def test_simulate_delisting_frees_slot():
    m = pd.period_range("2011-01", "2011-12", freq="M")
    tri = pd.DataFrame(100.0, index=m, columns=[1, 2, 3, 4, 5])
    tri.loc[pd.Period("2011-06", "M"):, 5] = np.nan  # 5번이 5월 말을 끝으로 상장폐지
    mc, _, dd, st = _market(price=tri)
    mc.loc[pd.Period("2011-06", "M"):, 5] = np.nan
    r, log, nh = _sim(mc, tri, dd, st, slots=3, cost=0.0, swap_gap=None)
    d = log[log.act == "delisted"]
    assert list(d.cik) == [5] and d.m.iloc[0] == pd.Period("2011-06", "M")
    assert nh.max() <= 3
    assert 2 in set(log[(log.act == "buy") & (log.m == pd.Period("2011-06", "M"))].cik)  # 다음 달 빈 슬롯 채움


def test_simulate_monthly_return_is_equal_weight_of_holdings():
    m = pd.period_range("2011-01", "2011-03", freq="M")
    tri = pd.DataFrame(100.0, index=m, columns=[1, 2, 3, 4, 5])
    tri.loc[pd.Period("2011-02", "M"), 5] = 110.0  # +10%
    mc, _, dd, st = _market(price=tri, months=("2011-01", "2011-03"))
    r, log, nh = _sim(mc, tri, dd, st, slots=2, cost=0.0, swap_gap=None)
    assert r.loc[pd.Period("2011-02", "M")] == pytest.approx(0.05)  # 슬롯 1/2 × 10%


def test_simulate_rebalance_trades_only_on_schedule():
    mc, tri, dd, st = _market()
    r, log, nh = _sim(mc, tri, dd, st, slots=2, cost=0.001, swap_gap=None, use_price=None, rebalance=3)
    assert set(log.m.astype(str)) <= {"2011-01", "2011-04", "2011-07", "2011-10"}
    assert nh.max() == 2


def test_simulate_sell_on_fail_grade():
    mc, tri, dd, st = _market()
    st.loc[(st.cik == 5) & (st.m >= pd.Period("2011-04", "M")), "grade"] = "X"
    r, log, nh = _sim(mc, tri, dd, st, slots=3, cost=0.0, swap_gap=None)
    s = log[log.act == "sell_fail"]
    assert list(s.cik) == [5] and s.m.iloc[0] == pd.Period("2011-04", "M")
    assert 2 in set(log[(log.act == "buy") & (log.m == pd.Period("2011-04", "M"))].cik)
