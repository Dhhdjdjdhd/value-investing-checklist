"""SEC companyfacts(cf_long) -> 회사×회계연도 재무 패널 + 체크리스트용 기초 지표.

시점 원칙(mode='first'): 회계연도 행의 avail = 그 해 매출·순이익을 처음 공시한 날.
  각 항목은 avail + 30일 이내에 공시된 값 중에서만 고른다(나중 재작성 값 차단).
mode='last': 가장 나중 공시값(재작성 반영) — 비교용.
주식수는 '오늘 분할 기준'으로 환산한다: 희석주식수 × (그 행 avail 이후 분할 비율의 곱).
  -> 시가총액 = Yahoo close(분할 반영) × 오늘 기준 주식수, EPS 추세 = 순이익 ÷ 오늘 기준 주식수.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WINDOW = pd.Timedelta(days=30)

REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"]
NI = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
      "NetIncomeLossAvailableToCommonStockholdersDiluted"]
PRETAX = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]
# 이름 -> 우선순위 concept 목록
DUR = {"rev": REV, "ni": NI, "pretax": PRETAX,
       "op": ["OperatingIncomeLoss"], "tax": ["IncomeTaxExpenseBenefit"], "intexp": ["InterestExpense"],
       "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
       "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
       "sbc": ["ShareBasedCompensation"], "buyback": ["PaymentsForRepurchaseOfCommonStock"],
       "div": ["PaymentsOfDividends"],
       "dil_sh": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"],
       "eps": ["EarningsPerShareDiluted"]}
INST = {"equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "ltd": ["LongTermDebt"],
        "ltd_nc": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndFinanceLeaseObligations",
                   "LongtermDebtNoncurrentExcludingCurrentMaturities", "OtherLongTermDebtNoncurrent"],
        "ltd_cur": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
        "debt_all": ["DebtLongtermAndShorttermCombinedAmount"],
        "debt_cur": ["DebtCurrent"], "cp": ["CommercialPaper"], "stb": ["ShortTermBorrowings"],
        "cash": ["CashAndCashEquivalentsAtCarryingValue"], "assets": ["Assets"], "ar": ["AccountsReceivableNetCurrent"]}


def fiscal_year(end):
    """52/53주 회계연도(1월 초 마감)를 앞 해로: (기말 − 20일)의 연도."""
    return (end - pd.Timedelta(days=20)).dt.year


def build_annual_cf(cf=None, mode="first", splits=None, tickers=None):
    if cf is None:
        cf = pd.read_parquet(DATA / "sec" / "cf_long.parquet")
    cf = cf[cf.form.str.match(r"^(10-K|10-K405|10-KT|20-F|40-F)$", na=False)].copy()
    cf["end"] = pd.to_datetime(cf["end"])
    cf["start"] = pd.to_datetime(cf["start"], errors="coerce")
    cf["filed"] = pd.to_datetime(cf["filed"])
    dur = cf[cf.start.notna()]
    dur = dur[((dur.end - dur.start).dt.days).between(330, 400)].copy()
    ins = cf[cf.start.isna()].copy()
    dur["fyr"] = fiscal_year(dur.end)
    ins["fyr"] = fiscal_year(ins.end)

    # 행 키와 avail: 매출·순이익을 처음 공시한 (cik, 회계연도)
    base = dur[dur.concept.isin(REV + NI)]
    key = base.sort_values("filed").groupby(["cik", "fyr"]).agg(end=("end", "max"), avail=("filed", "min"))

    def pick(df, names):
        sub = df[df.concept.isin(names)].merge(key[["avail"]], left_on=["cik", "fyr"], right_index=True)
        if mode == "first":
            sub = sub[sub.filed <= sub.avail + WINDOW]
        sub["pri"] = sub.concept.map({n: i for i, n in enumerate(names)})
        sub = sub.sort_values(["pri", "filed", "end"], ascending=[True, mode == "first", False])
        return sub.drop_duplicates(["cik", "fyr"]).set_index(["cik", "fyr"])[["val", "filed"]]

    out = key.copy()
    for nm, cs in DUR.items():
        p = pick(dur, cs)
        out[nm] = p.val
        if nm in ("dil_sh", "eps"):  # 분할 보정 기준일: 이 값을 공시한 날 (last 모드는 재작성 공시일)
            out[nm + "_filed"] = p.filed
    for nm, cs in INST.items():
        out[nm] = pick(ins, cs).val
    out = out.reset_index().rename(columns={"fyr": "cy"})
    nm = cf.drop_duplicates("cik").set_index("cik")
    out["name"] = out.cik.map(nm["entityName"]) if "entityName" in nm.columns else np.nan
    out = out.sort_values(["cik", "cy"]).reset_index(drop=True)
    return add_metrics(out, splits, tickers)


def add_metrics(a, splits=None, tickers=None):
    # 순이익 대체 후 영업이익 대체: 세전이익 + 이자비용
    a["op"] = a["op"].fillna(a["pretax"] + a["intexp"].fillna(0))
    has_lt = a["ltd"].notna() | a["ltd_nc"].notna() | a["ltd_cur"].notna()
    debt = a["ltd"].fillna(a["ltd_nc"].fillna(0) + a["ltd_cur"].fillna(0))
    short = a["stb"].fillna(a["cp"]).fillna(0)
    short = short.where(a["ltd"].notna() | a["ltd_cur"].notna(), a["debt_cur"].fillna(short))
    debt = (debt + short).where(has_lt | a["stb"].notna() | a["cp"].notna(), a["debt_all"])
    a["debt"] = debt.fillna(0)
    a["debt_known"] = has_lt | a["debt_all"].notna()
    a["ltdebt"] = a["ltd"].fillna(a["ltd_nc"]).fillna(a["debt_all"])
    # 유효세율: 일회성 세금(2017 세제개편 등)으로 5~40% 밖이면 법정세율 근사로 대체
    raw_tr = (a["tax"] / a["pretax"]).where(a["pretax"] > 0)
    stat = np.where(a["cy"] >= 2018, 0.21, 0.35)
    tr = raw_tr.where(raw_tr.between(0.05, 0.40), stat)
    a["nopat"] = a["op"] * (1 - tr)
    a["ic"] = a["equity"] + a["debt"]  # 02 §1: 현금 미차감, 기말, 리스 제외
    a["roic"] = (a["nopat"] / a["ic"]).where(a["ic"] > 0)
    a["roe"] = (a["ni"] / a["equity"]).where(a["equity"] > 0)
    a["fcf"] = a["cfo"] - a["capex"].fillna(0)
    a["fcf_sbc"] = a["fcf"] - a["sbc"].fillna(0)
    a["opm"] = a["op"] / a["rev"]
    a["ltd_ni"] = (a["ltdebt"].fillna(0) / a["ni"]).where(a["ni"] > 0)
    a["capex_ni"] = (a["capex"] / a["ni"]).where(a["ni"] > 0)
    # 희석주식수 미공시(Visa처럼 클래스 차원으로만 보고) -> 순이익 ÷ 희석 EPS로 역산
    implied = (a["ni"] / a["eps"]).where((a["eps"].abs() > 0.01) & (a["ni"].abs() > 0))
    use_imp = a["dil_sh"].isna() & implied.notna()
    a["dil_sh"] = a["dil_sh"].fillna(implied)
    a["sh_filed"] = a["dil_sh_filed"].where(~use_imp, a["eps_filed"]).fillna(a["avail"])
    a["sh_adj"] = shares_today_basis(a, splits, tickers)
    a["eps_c"] = a["ni"] / a["sh_adj"]
    # 주식수를 전혀 알 수 없는 회사(Visa·ERIE: 클래스 차원으로만 보고): EPS 추세 대신 순이익 추세. 시총은 계산 불가
    no_sh = a.groupby("cik")["sh_adj"].transform(lambda s: s.isna().all())
    a.loc[no_sh, "eps_c"] = a.loc[no_sh, "ni"] / 1e9
    return a


def shares_today_basis(a, splits=None, tickers=None):
    """희석주식수를 오늘 분할 기준으로. 티커·분할 이력이 있으면 splits.csv로, 없으면 점프 휴리스틱."""
    out = pd.Series(np.nan, index=a.index)
    sp_by_tk = dict(tuple(splits.groupby("ticker"))) if splits is not None and len(splits) else {}
    for cik, g in a.groupby("cik"):
        sh = g["dil_sh"].astype(float)
        if sh.isna().all():
            continue
        tk = tickers.get(cik) if tickers is not None else None
        if tk is not None:
            sh = sh.to_numpy(copy=True)
            sp = sp_by_tk.get(tk)
            if sp is not None:  # 분할 보정을 먼저 하고(공시 시점 기준 -> 오늘 기준) 빈 연도는 그 뒤에 채움
                for d, r in zip(sp.date, sp.ratio):
                    basis = g["sh_filed"] if "sh_filed" in g else g["avail"]
                    sh[(basis < d).to_numpy()] *= r  # 그 값을 공시한 뒤에 일어난 분할만
            out[g.index] = fix_units(pd.Series(sh).ffill().bfill().to_numpy())
            continue
        sh = sh.ffill().bfill().to_numpy(copy=True)
        for i in range(len(sh) - 1, 0, -1):
            p, c = sh[i - 1], sh[i]
            if p <= 0:
                continue
            q = c / p
            for r in (2, 3, 4, 5, 10, 15, 20):
                hit = [qq for qq in (r, 1 / r) if abs(q / qq - 1) < 0.08]
                if hit:
                    sh[:i] *= hit[0]
                    break
        out[g.index] = fix_units(sh)
    return out


def fix_units(sh):
    """단위 오류(천 주 단위로 보고, NVDA FY2008~11·CPRT FY2014 등): 이웃 연도와 300배 이상 차이 나면 1000배 보정."""
    sh = np.asarray(sh, dtype=float).copy()
    ok = np.isfinite(sh) & (sh > 0)
    if ok.sum() < 3:
        return sh
    med = np.median(sh[ok])  # 여러 해 연속 오류도 잡도록 전체 중앙값과 비교
    q = med / np.where(ok, sh, 1)
    bad = ok & ((q > 300) | (q < 1 / 300))  # 천 단위·백만 단위 오류 양방향
    sh[bad] *= 1000.0 ** np.round(np.log(q[bad]) / np.log(1000))
    return sh


SECTOR_EXCL_SIC = [
    (1000, 1499),   # 광업·석유가스 채굴
    (2900, 2999),   # 석유정제
    (2800, 2829),   # 화학(기초)
    (3310, 3399),   # 철강·비철
    (2600, 2631),   # 제지
    (4400, 4499),   # 해운
    (4510, 4529),   # 항공
    (1520, 1531),   # 주택건설
    (6798, 6798),   # 리츠
    (6200, 6299),   # 증권·자산운용
    (6000, 6199),   # 은행 (D/E·ROIC 체계가 다름 — 04 '선택'을 제외로)
    (6300, 6411),   # 보험
]
# 메모리 반도체는 SIC로 구분 불가(3674에 NVDA·TXN 등 섞임) -> 숫자 기준 경기순환 판정에 맡김


def excluded_sector(sic):
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return False
    return any(lo <= s <= hi for lo, hi in SECTOR_EXCL_SIC)
