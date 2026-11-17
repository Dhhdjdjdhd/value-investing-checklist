"""DART 원자료(data/kr/dart) -> 회사×회계연도 재무 패널 (data/kr/annual.parquet).

- 값 출처 우선순위: 그 해 사업보고서 당기 → 다음 해 보고서 전기 → 그다음 해 보고서 전전기.
  2015 사업보고서의 전기·전전기로 2013·2014년도 값을 얻는다.
- avail(투자자가 알 수 있는 날) = 출처 보고서 접수일. 단 그 해 자기 보고서가 결산 후 105일보다 늦게
  접수됐으면(대개 정정공시로 접수번호가 바뀐 경우) 결산 후 105일로 본다 — 정정값을 원 제출 시점에 쓰는 한계가 있다.
- 계정은 표준 ID(ifrs_ → ifrs-full_ 통일)로 찾고, '-표준계정코드 미사용-'은 계정명으로 보완한다.
- 주식수: 주식의 총수 현황(2016~)의 (발행 − 자기주식), 보통주+우선주 합계. 없으면 지배순이익 ÷ 기본 EPS.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fundamentals import fix_units  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KR = ROOT / "data" / "kr"
DART = KR / "dart"
YEARS = range(2013, 2026)
LATE = pd.Timedelta(days=105)

IS_ = ("IS", "CIS")
# 이름 -> (재무제표 구분, 표준 ID 목록, 계정명 정규식)
ITEMS = {
    "rev": (IS_, ["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익|매출|수익|매출액\(영업수익\))$"),
    "op": (IS_, ["dart_OperatingIncomeLoss"], r"^영업(이익|손익|이익\(손실\)|손실)$"),
    "pretax": (IS_, ["ifrs-full_ProfitLossBeforeTax"], r"^법인세(비용)?차감전"),
    "tax": (IS_, ["ifrs-full_IncomeTaxExpenseContinuingOperations"], r"^법인세(비용|비용\(수익\))$"),
    "ni_all": (IS_, ["ifrs-full_ProfitLoss"], r"^(당기순이익|당기순이익\(손실\)|당기순손익)$"),
    "ni_p": (IS_, ["ifrs-full_ProfitLossAttributableToOwnersOfParent"], r"^(지배기업.*(순이익|순손익)|.*지배기업.*소유주.*당기순)"),
    "eps": (IS_, ["ifrs-full_BasicEarningsLossPerShare"], r"^(기본주당|기본 주당|보통주 기본주당)"),
    "equity_all": (("BS",), ["ifrs-full_Equity"], r"^자본총계$"),
    "equity_p": (("BS",), ["ifrs-full_EquityAttributableToOwnersOfParent"], r"^지배기업.*소유주.*지분$"),
    "assets": (("BS",), ["ifrs-full_Assets"], r"^자산총계$"),
    "liab": (("BS",), ["ifrs-full_Liabilities"], r"^부채총계$"),
    "cash": (("BS",), ["ifrs-full_CashAndCashEquivalents"], r"^현금및현금성자산$"),
    "cfo": (("CF",), ["ifrs-full_CashFlowsFromUsedInOperatingActivities"], r"^영업활동.*현금"),
    "capex": (("CF",), ["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"], r"^유형자산의?\s?취득"),
    "div": (("CF",), ["ifrs-full_DividendsPaidClassifiedAsFinancingActivities"], r"^배당금의?\s?지급"),
}
DEBT_IDS = {
    "ifrs-full_ShorttermBorrowings", "dart_ShortTermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "dart_CurrentPortionOfBonds", "dart_CurrentPortionOfConvertibleBonds", "dart_CurrentPortionOfExchangeableBond",
    "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "dart_LongTermBorrowingsGross", "dart_BondsIssued", "dart_ConvertibleBonds", "dart_ExchangeableBonds",
    "dart_BondsWithWarrant", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived", "ifrs-full_LongtermBorrowings", "ifrs-full_BondsIssued",
    "ifrs-full_NoncurrentPortionOfNoncurrentBorrowings", "ifrs-full_Borrowings",
}
DEBT_NM = re.compile(r"(차입금|사채)")
DEBT_NOT = re.compile(r"(할인|할증|전환권|조정|이자|리스|충당|파생|상환|대여|미지급|선급|보증|기타)")
CURRENT = re.compile(r"(유동|단기)")


def num(s):
    if s is None:
        return np.nan
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def norm_id(i):
    return "ifrs-full_" + i[5:] if i.startswith("ifrs_") else i


def extract(rows, col):
    """보고서 한 개의 rows에서 col(thstrm/frmtrm/bfefrmtrm)_amount 기준 항목 dict."""
    out = {}
    for k, (sj, ids, rx) in ITEMS.items():
        cand = [r for r in rows if r["sj_div"] in sj]
        v = np.nan
        for want in ids:  # 표준 ID 우선, 손익계산서(IS) 먼저
            hit = [r for r in cand if norm_id(r["account_id"]) == want]
            hit.sort(key=lambda r: sj.index(r["sj_div"]))
            for r in hit:
                v = num(r.get(col + "_amount"))
                if np.isfinite(v):
                    break
            if np.isfinite(v):
                break
        if not np.isfinite(v):
            for r in sorted(cand, key=lambda r: sj.index(r["sj_div"])):
                if re.search(rx, r["account_nm"].strip()):
                    v = num(r.get(col + "_amount"))
                    if np.isfinite(v):
                        break
        out[k] = v
    debt = ltd = 0.0
    seen = False
    for r in rows:
        if r["sj_div"] != "BS":
            continue
        i, nm = norm_id(r["account_id"]), r["account_nm"].strip()
        ok = i in DEBT_IDS or (i.startswith("-표준") and DEBT_NM.search(nm) and not DEBT_NOT.search(nm))
        if not ok:
            continue
        v = num(r.get(col + "_amount"))
        if not np.isfinite(v):
            continue
        seen = True
        debt += abs(v)
        if not (CURRENT.search(nm) or "Current" in i or "Shortterm" in i or "ShortTerm" in i):
            ltd += abs(v)
    out["debt"] = debt if seen else np.nan
    out["ltdebt"] = ltd if seen else np.nan
    if np.isfinite(out["capex"]):
        out["capex"] = abs(out["capex"])
    if np.isfinite(out["div"]):
        out["div"] = abs(out["div"])
    return out


def shares_from(path):
    """(발행 − 자기주식) 보통주+우선주. 반환: (보통주, 합계)"""
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return np.nan, np.nan
    com = tot = np.nan
    pref = 0.0
    for r in j.get("list", []):
        se = re.sub(r"\s+", "", r.get("se", ""))
        iss, tre = num(r.get("istc_totqy")), num(r.get("tesstk_co"))
        if not np.isfinite(iss):
            continue
        out = iss - (tre if np.isfinite(tre) else 0)
        if se == "합계":
            tot = out
        elif "보통" in se and not np.isfinite(com):
            com = out
        elif "우선" in se or "우선수" in se:
            pref += out
    if np.isfinite(com):
        tot2 = com + pref
        tot = tot2 if not np.isfinite(tot) or tot2 <= tot * 1.001 else tot
    return com, tot


def fy_end(year, acc_mt):
    m = int(acc_mt) if str(acc_mt).isdigit() and 1 <= int(acc_mt) <= 12 else 12
    return pd.Timestamp(year=year, month=m, day=1) + pd.offsets.MonthEnd(0)


def build(codes=None):
    comp = pd.read_csv(KR / "companies.csv", dtype=str).set_index("corp_code")
    dirs = [d for d in DART.iterdir() if d.is_dir() and (codes is None or d.name in codes)]
    recs = []
    for d in dirs:
        cc = d.name
        acc = comp.at[cc, "acc_mt"] if cc in comp.index else "12"
        reps = {}
        for y in range(2015, 2026):
            p = d / f"{y}_fin.json"
            if p.exists():
                j = json.loads(p.read_text(encoding="utf-8"))
                if j.get("status") == "000" and j.get("list"):
                    reps[y] = j
        for y in YEARS:
            src = None
            for ry, col in ((y, "thstrm"), (y + 1, "frmtrm"), (y + 2, "bfefrmtrm")):
                if ry in reps:
                    v = extract(reps[ry]["list"], col)
                    if np.isfinite(v["rev"]) or np.isfinite(v["ni_all"]):
                        src = (ry, col, v)
                        break
            if src is None:
                continue
            ry, col, v = src
            rep = reps[ry]
            rdate = pd.Timestamp(rep["list"][0]["rcept_no"][:8])
            fye = fy_end(y, acc)
            avail = min(rdate, fy_end(ry, acc) + LATE) if ry == y else rdate
            com, tot = shares_from(d / f"{y}_sh.json")
            recs.append({"corp_code": cc, "cy": y, "fye": fye, "avail": avail, "src_year": ry, "src_col": col,
                         "fs_div": rep.get("fs_div"), "sh_com": com, "sh_tot": tot, **v})
    a = pd.DataFrame(recs).sort_values(["corp_code", "cy"]).reset_index(drop=True)
    return add_metrics(a)


def add_metrics(a):
    a["ni"] = a["ni_p"].fillna(a["ni_all"])
    a["equity"] = a["equity_p"].fillna(a["equity_all"])
    # 주식수: 공시값 없으면 지배순이익 ÷ 기본 EPS로 역산(2013~2015 포함)
    # EPS가 작으면 원 단위 반올림 오차가 커서(포스코퓨처엠 2025: EPS 51원 → 8배 과대) |EPS| ≥ 100원일 때만 역산
    implied = (a["ni"] / a["eps"]).where((a["eps"].abs() >= 100) & (a["ni"].abs() > 0))
    a["sh_implied"] = implied
    a["sh"] = a["sh_tot"].fillna(implied)
    a["sh"] = a.groupby("corp_code")["sh"].transform(lambda s: s.ffill().bfill())
    # 단위 오류(덕성 2024: 주식수를 100만 배로 기재): 회사 중앙값과 300배 넘게 다르면 1000의 거듭제곱으로 보정
    a["sh"] = a.groupby("corp_code")["sh"].transform(lambda s: pd.Series(fix_units(s.to_numpy()), index=s.index))
    a["op"] = a["op"].fillna(a["pretax"])
    raw_tr = (a["tax"] / a["pretax"]).where(a["pretax"] > 0)
    stat = np.where(a["cy"] >= 2018, 0.264, 0.242)  # 법인세 최고세율(지방세 포함) 근사
    tr = raw_tr.where(raw_tr.between(0.05, 0.40), stat)
    a["debt"] = a["debt"].fillna(0)
    a["nopat"] = a["op"] * (1 - tr)
    a["ic"] = a["equity"] + a["debt"]  # 미국과 같은 산식: 현금 미차감, 기말, 리스 제외
    a["roic"] = (a["nopat"] / a["ic"]).where(a["ic"] > 0)
    a["fcf"] = a["cfo"] - a["capex"].fillna(0)
    a["fcf_sbc"] = a["fcf"]  # 한국은 주식보상비용이 작고 표준 계정이 없어 0으로 둔다
    a["ltd_ni"] = (a["ltdebt"].fillna(0) / a["ni"]).where(a["ni"] > 0)
    return a


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    codes = None
    if "--pilot" in sys.argv:
        codes = set((KR / "pilot_codes.txt").read_text().strip().split(","))
    a = build(codes)
    a.to_parquet(KR / ("annual_pilot.parquet" if codes else "annual.parquet"))
    print(len(a), "행,", a.corp_code.nunique(), "개사")
