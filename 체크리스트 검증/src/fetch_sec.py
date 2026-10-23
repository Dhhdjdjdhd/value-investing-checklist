"""SEC XBRL frames + submissions 수집기 (작업지시 W1, 작성: value-investing-checklist-f9).

사용법 (작업 폴더 '체크리스트 검증' 기준):
    py src/fetch_sec.py frames      # frames 원본 json 수집 (이미 받은 것·404 기록된 것은 건너뜀)
    py src/fetch_sec.py facts       # 원본 json -> data/sec/facts_long.parquet
    py src/fetch_sec.py companies   # 대형 CIK 의 submissions -> data/sec/companies.csv (이어받기)
    py src/fetch_sec.py cf          # 대형 CIK 의 companyfacts -> data/sec/cf_long.parquet (최초 공시값, 이어받기)
    py src/fetch_sec.py all         # 위 네 단계 순서대로
    py src/fetch_sec.py cf_refresh 2027Q1   # 분기 재점검: 상장 중인 회사 companyfacts 다시 받기 (이어받기)

- User-Agent 에 이메일을 넣지 않음. 요청 간격 0.25초(초당 4회 이하).
- 여유 메모리 1GB 미만이면 단계 사이·요청 사이에서 멈춤(다시 실행하면 이어서 진행).
- --max-minutes N: N분이 지나면 회사 사이에서 깔끔하게 종료(종료코드 3, 다시 실행하면 이어서).
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SEC_DIR = ROOT / "data" / "sec"
FRAMES_DIR = SEC_DIR / "frames"
MISSING_JSON = SEC_DIR / "frames_missing.json"
FACTS = SEC_DIR / "facts_long.parquet"
COMPANIES = SEC_DIR / "companies.csv"
COMPANIES_FAIL = SEC_DIR / "companies_failed.json"

HEADERS = {"User-Agent": "value-investing-checklist research"}
SEC_INTERVAL = 0.25
MAX_RETRIES = 5
MIN_FREE_MB = int(os.environ.get("MIN_FREE_MB", 1024))  # 스트리밍 단계는 환경변수로 낮춰 실행 가능
YEARS = range(2005, 2026)

DURATION = {
    "USD": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "OperatingIncomeLoss", "NetIncomeLoss", "IncomeTaxExpenseBenefit",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
            "ShareBasedCompensation", "PaymentsForRepurchaseOfCommonStock", "PaymentsOfDividends"],
    "USD-per-shares": ["EarningsPerShareDiluted"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
INSTANT = {
    "USD": ["StockholdersEquity", "LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtCurrent", "DebtCurrent",
            "CommercialPaper", "ShortTermBorrowings", "CashAndCashEquivalentsAtCarryingValue", "Assets",
            "AccountsReceivableNetCurrent"],
}
REVENUE_CONCEPTS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
US_EXCHANGES = {"NYSE", "Nasdaq", "CBOE", "NYSE American", "NYSE MKT", "NYSE Arca", "BATS"}

_last_request = 0.0


def free_mb():
    """Windows 여유 물리 메모리(MB). 다른 OS 에서는 None."""
    if sys.platform != "win32":
        return None
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2**20


class LowMemory(Exception):
    pass


DEADLINE = None  # --max-minutes 로 정한 종료 시각(time.time 기준). 회사·티커 사이에서만 확인


def set_deadline(argv):
    global DEADLINE
    if "--max-minutes" in argv:
        DEADLINE = time.time() + 60 * float(argv[argv.index("--max-minutes") + 1])


def time_up():
    return DEADLINE is not None and time.time() >= DEADLINE


def check_memory():
    fm = free_mb()
    if fm is not None and fm < MIN_FREE_MB:
        raise LowMemory(f"여유 메모리 {fm:,.0f}MB < {MIN_FREE_MB}MB")


def log(msg):
    print(msg, flush=True)


def sec_get(url: str) -> bytes | None:
    """SEC GET. 404 -> None, 429/5xx -> 지수 백오프 재시도."""
    global _last_request
    for attempt in range(MAX_RETRIES + 1):
        wait = SEC_INTERVAL - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if not (e.code == 429 or 500 <= e.code < 600) or attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** (attempt + 1) + random.uniform(0, 1))
        except urllib.error.URLError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def frame_jobs():
    """(taxonomy, concept, unit, period)"""
    for unit, concepts in DURATION.items():
        for c in concepts:
            for y in YEARS:
                yield "us-gaap", c, unit, f"CY{y}"
    for unit, concepts in INSTANT.items():
        for c in concepts:
            for y in YEARS:
                yield "us-gaap", c, unit, f"CY{y}Q4I"
    # 시가총액용 표지 주식수: 기준일이 연중에 흩어져 있어 분기 4개 모두
    for y in YEARS:
        for q in range(1, 5):
            yield "dei", "EntityCommonStockSharesOutstanding", "shares", f"CY{y}Q{q}I"


def fetch_frames():
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    missing = json.loads(MISSING_JSON.read_text(encoding="utf-8")) if MISSING_JSON.exists() else {}
    jobs = list(frame_jobs())
    for i, (tax, c, unit, per) in enumerate(jobs, 1):
        key = f"{c}_{per}"
        out = FRAMES_DIR / f"{key}.json"
        if out.exists() or key in missing:
            continue
        check_memory()
        body = sec_get(f"https://data.sec.gov/api/xbrl/frames/{tax}/{c}/{unit}/{per}.json")
        if body is None:
            missing[key] = "404"
            MISSING_JSON.write_text(json.dumps(missing, indent=1), encoding="utf-8")
            log(f"[{i}/{len(jobs)}] {key}: 404")
            continue
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(out)  # 중간에 끊겨도 깨진 json 이 남지 않게
        log(f"[{i}/{len(jobs)}] {key}: {len(body) / 1e6:.1f}MB")
    log(f"frames: {len(jobs) - len(missing)} 받음 / 404 {len(missing)}")


def build_facts():
    unit_of = {c: u for d in (DURATION, INSTANT) for u, cs in d.items() for c in cs}
    unit_of["EntityCommonStockSharesOutstanding"] = "shares"
    frames = []
    for p in sorted(FRAMES_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        df = pd.DataFrame(d["data"])
        if df.empty:
            continue
        if "start" not in df:
            df["start"] = None
        df["concept"] = d["tag"]
        df["period"] = d["ccp"]
        df["unit"] = unit_of.get(d["tag"], d["uom"])
        if "loc" not in df:
            df["loc"] = None
        frames.append(df[["cik", "entityName", "loc", "concept", "unit", "period", "start", "end", "val", "accn"]])
    facts = pd.concat(frames, ignore_index=True)
    facts["cik"] = facts["cik"].astype("int64")
    for col in ("start", "end"):
        facts[col] = pd.to_datetime(facts[col])
    # accn = 제출자ID-YY-일련번호. YY 가 제출 연도(이 값을 낸 공시가 나온 해, 재작성 여부 판단용)
    yy = facts["accn"].str.split("-").str[1].astype(int)
    facts["filed_year"] = (yy + 2000).where(yy < 90, yy + 1900).astype("int16")
    facts.to_parquet(FACTS, index=False)
    log(f"facts_long: {len(facts):,}행, CIK {facts.cik.nunique():,}개 -> {FACTS}")
    return facts


def large_ciks(facts):
    rev = facts[facts.concept.isin(REVENUE_CONCEPTS) & (facts.val >= 1e9)].cik
    ni = facts[(facts.concept == "NetIncomeLoss") & (facts.val >= 1e8)].cik
    return sorted(set(rev) | set(ni))


def fetch_companies():
    facts = pd.read_parquet(FACTS, columns=["cik", "concept", "val"])
    ciks = large_ciks(facts)
    del facts
    done = set(pd.read_csv(COMPANIES).cik) if COMPANIES.exists() else set()
    failed = json.loads(COMPANIES_FAIL.read_text(encoding="utf-8")) if COMPANIES_FAIL.exists() else {}
    todo = [c for c in ciks if c not in done]
    log(f"companies: 대상 {len(ciks):,}개, 남은 {len(todo):,}개")
    for i, cik in enumerate(todo, 1):
        check_memory()
        if time_up():
            COMPANIES_FAIL.write_text(json.dumps(failed, indent=1), encoding="utf-8")
            log(f"TIME: --max-minutes 도달, {i - 1}/{len(todo)}에서 종료 (다시 실행하면 이어서)")
            return False
        try:
            body = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            if body is None:
                failed[str(cik)] = "404"
                continue
            d = json.loads(body)
        except Exception as e:  # noqa: BLE001 - 실패는 기록 후 계속
            failed[str(cik)] = f"{type(e).__name__}: {e}"
            continue
        finally:
            if i % 50 == 0 or i == len(todo):
                COMPANIES_FAIL.write_text(json.dumps(failed, indent=1), encoding="utf-8")
        tickers = d.get("tickers") or []
        exchanges = [x or "" for x in (d.get("exchanges") or [])]
        row = {
            "cik": cik, "name": d.get("name"), "tickers": ";".join(tickers), "exchanges": ";".join(exchanges),
            "sic": d.get("sic"), "sicDescription": d.get("sicDescription"), "fiscalYearEnd": d.get("fiscalYearEnd"),
            "entityType": d.get("entityType"), "stateOfIncorporation": d.get("stateOfIncorporation"),
            "delisted_guess": len(tickers) == 0,
        }
        pd.DataFrame([row]).to_csv(COMPANIES, mode="a", header=not COMPANIES.exists(), index=False, encoding="utf-8")
        if i % 100 == 0:
            log(f"[{i}/{len(todo)}] {d.get('name')}  (free {free_mb() or 0:,.0f}MB)")
    log(f"companies: 완료, 실패 {len(failed)}개")
    return True


CF_PARTS = SEC_DIR / "cf_parts"
CF_DONE = SEC_DIR / "cf_done.txt"
CF_LONG = SEC_DIR / "cf_long.parquet"
CF_FAIL = SEC_DIR / "cf_failed.json"
ANNUAL_FORMS = {"10-K", "10-K405", "10-KT", "20-F", "40-F"}
QUARTER_FORMS = {"10-Q"}
CF_COLS = ["cik", "concept", "unit", "start", "end", "val", "filed", "form", "fy", "fp", "accn"]
CF_FLUSH_EVERY = 100  # 회사 100개마다 parquet 조각으로 내보내 메모리에 쌓지 않음


def _base_form(form):
    return form[:-2] if form.endswith("/A") else form


# companyfacts 에만 추가로 받는 개념(frames 에는 없음). 표본 점검에서 Visa 자본총계·희석주식수, KO 장기부채 누락 보완
# W2: 순이익 대체(MA·BKNG·BSX), 영업이익 근사용 이자비용·영업비용(ADP·ZTS·BURL), 매출 대체 태그(CPRT 등)
CF_EXTRA_DURATION = {
    "USD": ["GrossProfit", "CostsAndExpenses", "PaymentsToAcquireProductiveAssets",
            "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic",
            "NetIncomeLossAvailableToCommonStockholdersDiluted", "InterestExpense", "OperatingExpenses",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"],
    "shares": ["WeightedAverageNumberOfShareOutstandingBasicAndDiluted"],
}
CF_EXTRA_INSTANT = {
    "USD": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "LongTermDebtAndFinanceLeaseObligations", "DebtLongtermAndShorttermCombinedAmount",
            "OtherLongTermDebtNoncurrent", "LongtermDebtNoncurrentExcludingCurrentMaturities"],
}


# frames 단위 표기 -> companyfacts 단위 표기 (frames 는 "USD-per-shares", companyfacts 는 "USD/shares")
CF_UNIT = {"USD-per-shares": "USD/shares"}


def cf_rows(cik, d):
    """companyfacts json -> 남길 사실 목록.
    duration: 연간 공시(10-K 계열, /A 포함) 중 fp=FY.
    instant(재무상태표·표지 주식수): 위 + 10-Q(/A 포함)."""
    want = {"us-gaap": {c: (u, False) for src in (DURATION, CF_EXTRA_DURATION) for u, cs in src.items() for c in cs}
                       | {c: (u, True) for src in (INSTANT, CF_EXTRA_INSTANT) for u, cs in src.items() for c in cs},
            "dei": {"EntityCommonStockSharesOutstanding": ("shares", True)}}
    rows = []
    for tax, concepts in want.items():
        facts = (d.get("facts") or {}).get(tax) or {}
        for c, (unit, instant) in concepts.items():
            unit = CF_UNIT.get(unit, unit)
            for fact in ((facts.get(c) or {}).get("units") or {}).get(unit, []):
                base = _base_form(fact.get("form", ""))
                if base in ANNUAL_FORMS and fact.get("fp") == "FY":
                    pass
                elif instant and base in QUARTER_FORMS:
                    pass
                else:
                    continue
                rows.append((cik, c, unit, fact.get("start"), fact["end"], fact["val"], fact["filed"],
                             fact["form"], fact.get("fy"), fact.get("fp"), fact["accn"]))
    return rows


def _flush_cf(buf, done_now, part_no):
    if buf:
        df = pd.DataFrame(buf, columns=CF_COLS)
        CF_PARTS.mkdir(parents=True, exist_ok=True)
        df.to_parquet(CF_PARTS / f"part_{part_no:05d}.parquet", index=False)
    # 조각을 쓴 다음에 완료 표시: 중간에 끊기면 그 조각의 회사만 다시 받음
    with CF_DONE.open("a", encoding="utf-8") as fh:
        fh.writelines(f"{c}\n" for c in done_now)


def fetch_companyfacts():
    facts = pd.read_parquet(FACTS, columns=["cik", "concept", "val"])
    ciks = large_ciks(facts)
    del facts
    done = set(int(x) for x in CF_DONE.read_text(encoding="utf-8").split()) if CF_DONE.exists() else set()
    failed = json.loads(CF_FAIL.read_text(encoding="utf-8")) if CF_FAIL.exists() else {}
    todo = [c for c in ciks if c not in done]
    part_no = len(list(CF_PARTS.glob("part_*.parquet"))) if CF_PARTS.exists() else 0
    log(f"companyfacts: 대상 {len(ciks):,}개, 남은 {len(todo):,}개")
    buf, done_now, t0, mb = [], [], time.time(), 0.0
    finished = True
    try:
        for i, cik in enumerate(todo, 1):
            check_memory()
            if time_up():
                log(f"TIME: --max-minutes 도달, {i - 1}/{len(todo)}에서 종료 (다시 실행하면 이어서)")
                finished = False
                break
            try:
                body = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
                if body is None:
                    failed[str(cik)] = "404"
                else:
                    mb += len(body) / 1e6
                    buf.extend(cf_rows(cik, json.loads(body)))
                    del body  # 원본은 메모리에서 바로 버림
                    failed.pop(str(cik), None)
            except Exception as e:  # noqa: BLE001 - 실패는 기록 후 계속
                failed[str(cik)] = f"{type(e).__name__}: {e}"[:200]
            done_now.append(cik)
            if len(done_now) >= CF_FLUSH_EVERY or i == len(todo):
                _flush_cf(buf, done_now, part_no)
                part_no += 1
                buf, done_now = [], []
                CF_FAIL.write_text(json.dumps(failed, indent=1), encoding="utf-8")
                log(f"[{i}/{len(todo)}] {time.time() - t0:.0f}s, 받은 {mb:,.0f}MB, 실패 {len(failed)}, free {free_mb() or 0:,.0f}MB")
    finally:
        if done_now:  # 메모리 부족 등으로 멈출 때도 받은 만큼은 저장
            _flush_cf(buf, done_now, part_no)
            CF_FAIL.write_text(json.dumps(failed, indent=1), encoding="utf-8")
    # 실패한 회사는 완료 목록에서 빼서 다음 실행 때 다시 시도
    if failed:
        keep = [c for c in CF_DONE.read_text(encoding="utf-8").split() if c not in failed or failed[c] == "404"]
        CF_DONE.write_text("".join(f"{c}\n" for c in keep), encoding="utf-8")
    if finished:
        combine_cf()
    return finished


def combine_cf(compact=False):
    parts = sorted(CF_PARTS.glob("part_*.parquet"))
    cf = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    for col in ("start", "end", "filed"):
        cf[col] = pd.to_datetime(cf[col])
    cf["cik"] = cf["cik"].astype("int64")
    cf["fy"] = pd.to_numeric(cf["fy"], errors="coerce").round().astype("Int32")  # 조각마다 float/int 섞임, 범위 밖 값 있음
    cf = cf.drop_duplicates()  # 형 변환 뒤에: 새로 고침 조각(문자열 날짜)과 기존 조각이 같은 값으로 겹친다
    cf.to_parquet(CF_LONG, index=False)
    log(f"cf_long: {len(cf):,}행, CIK {cf.cik.nunique():,}개 -> {CF_LONG}")
    if compact:  # 조각을 하나로 합쳐 분기마다 조각이 늘지 않게
        tmp = CF_PARTS / "part_00000.parquet.tmp"
        cf.to_parquet(tmp, index=False)
        for p in parts:
            p.unlink()
        tmp.replace(CF_PARTS / "part_00000.parquet")


def refresh_companyfacts(tag):
    """분기 재점검용: 티커가 있는(상장 중인) 회사의 companyfacts를 다시 받아 새 공시를 더한다.
    companyfacts는 과거 공시를 모두 담고 있어 기존 조각과 합치면 최초 공시값은 그대로, 새 값만 늘어난다.
    진행 목록 cf_refresh_{tag}.txt로 이어받기."""
    comp = pd.read_csv(COMPANIES)
    ciks = sorted(set(comp[~comp.delisted_guess.astype(bool)].cik.astype(int)))
    done_path = SEC_DIR / f"cf_refresh_{tag}.txt"
    done = set(int(x) for x in done_path.read_text(encoding="utf-8").split()) if done_path.exists() else set()
    todo = [c for c in ciks if c not in done]
    part_no = max([int(p.stem.split("_")[1]) for p in CF_PARTS.glob("part_*.parquet")], default=-1) + 1
    log(f"companyfacts 새로 고침({tag}): 대상 {len(ciks):,}개, 남은 {len(todo):,}개")
    buf, done_now, t0, fails = [], [], time.time(), 0

    def flush():
        nonlocal part_no, buf, done_now
        if buf:
            CF_PARTS.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(buf, columns=CF_COLS).to_parquet(CF_PARTS / f"part_{part_no:05d}.parquet", index=False)
            part_no += 1
        with done_path.open("a", encoding="utf-8") as fh:
            fh.writelines(f"{c}\n" for c in done_now)
        buf, done_now = [], []

    try:
        for i, cik in enumerate(todo, 1):
            check_memory()
            if time_up():
                log(f"TIME: --max-minutes 도달, {i - 1}/{len(todo)}에서 종료 (다시 실행하면 이어서)")
                return False
            try:
                body = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
                if body is not None:
                    buf.extend(cf_rows(cik, json.loads(body)))
                    del body
            except Exception as e:  # noqa: BLE001 - 실패한 회사는 기존 값으로 둔다
                fails += 1
                log(f"  {cik}: {type(e).__name__}: {e}"[:200])
            done_now.append(cik)
            if len(done_now) >= CF_FLUSH_EVERY:
                flush()
                log(f"[{i}/{len(todo)}] {time.time() - t0:.0f}s, 실패 {fails}, free {free_mb() or 0:,.0f}MB")
    finally:
        flush()
    combine_cf(compact=True)
    return True


REPORT = ROOT / "01_데이터.md"
PRICES_DIR = ROOT / "data" / "prices"


def _md_table(df, floatfmt="{:,.0f}"):
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df.itertuples(index=False):
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def frames_vs_first(facts, cf, ciks):
    """frames 값과 companyfacts 최초 공시값(가장 이른 filed) 비교. 연간 duration 은 기간 길이 330~400일만."""
    f = facts[facts.cik.isin(ciks)].copy()
    c = cf[cf.cik.isin(ciks)].copy()
    dur = c.start.notna()
    days = (c.end - c.start).dt.days
    c = c[~dur | days.between(330, 400)]
    c = c.sort_values("filed")
    key = ["cik", "concept", "end"]
    f["start_k"] = f.start.fillna(pd.Timestamp(0))
    c["start_k"] = c.start.fillna(pd.Timestamp(0))
    first = c.groupby(key + ["start_k"]).agg(first_val=("val", "first"), first_filed=("filed", "first"),
                                             last_val=("val", "last"), n_filings=("val", "size")).reset_index()
    m = f.merge(first, on=key + ["start_k"], how="left")
    rows = []
    for con, g in m.groupby("concept"):
        g = g[g.first_val.notna()]
        if g.empty:
            continue
        base = g.first_val.abs().where(g.first_val != 0)
        diff = (g.val - g.first_val).abs() / base
        rows.append({"concept": con, "비교 행": len(g), "|차이|>5%": f"{(diff > 0.05).mean():.1%}",
                     "|차이|>1%": f"{(diff > 0.01).mean():.1%}",
                     "최초≠최신 공시": f"{(g.first_val != g.last_val).mean():.1%}",
                     "여러 번 공시": f"{(g.n_filings > 1).mean():.1%}"})
    match = m.first_val.notna().mean()
    return pd.DataFrame(rows), match


def write_report():
    facts = pd.read_parquet(FACTS)
    comp = pd.read_csv(COMPANIES)
    missing = json.loads(MISSING_JSON.read_text(encoding="utf-8")) if MISSING_JSON.exists() else {}
    n_frames = len(list(FRAMES_DIR.glob("*.json")))
    big = set(large_ciks(facts))
    L = [f"# 01. 데이터", "",
         f"- 작성: {time.strftime('%Y-%m-%d %H:%M')} / 작성자: value-investing-checklist-f9 (`src/fetch_sec.py report`)",
         "- 출처: SEC XBRL frames·submissions·companyfacts(data.sec.gov), Yahoo Finance chart v8", ""]

    # 수집 개수
    cf = pd.read_parquet(CF_LONG) if CF_LONG.exists() else None
    man = pd.read_csv(PRICES_DIR / "manifest.csv") if (PRICES_DIR / "manifest.csv").exists() else None
    splits = pd.read_csv(PRICES_DIR / "splits.csv") if (PRICES_DIR / "splits.csv").exists() else None
    cf_fail = json.loads(CF_FAIL.read_text(encoding="utf-8")) if CF_FAIL.exists() else {}
    comp_fail = json.loads(COMPANIES_FAIL.read_text(encoding="utf-8")) if COMPANIES_FAIL.exists() else {}
    L += ["## 수집 개수", "", "| 항목 | 값 |", "|---|---:|",
          f"| frames 요청 / 받음 / 404 | {n_frames + len(missing)} / {n_frames} / {len(missing)} |",
          f"| facts_long 행 / CIK | {len(facts):,} / {facts.cik.nunique():,} |",
          f"| 대형 CIK (어느 해든 매출 ≥ $1B 또는 순이익 ≥ $100M) | {len(big):,} |",
          f"| companies.csv 회사 / 실패 | {len(comp):,} / {len(comp_fail)} |",
          f"| 티커 있음 / 없음(상장폐지 추정) | {(~comp.delisted_guess).sum():,} / {comp.delisted_guess.sum():,} |"]
    if cf is not None:
        L.append(f"| cf_long 행 / CIK / 실패 | {len(cf):,} / {cf.cik.nunique():,} / {len(cf_fail)} |")
    if man is not None:
        ok = (man.status == "ok").sum()
        L.append(f"| 주가 대상 티커 / 성공 / 실패 | {len(man):,} / {ok:,} ({ok / len(man):.1%}) / {len(man) - ok:,} |")
    if splits is not None:
        L.append(f"| 분할 이벤트 / 티커 | {len(splits):,} / {splits.ticker.nunique():,} |")
    L += ["", "404 frames 는 대부분 XBRL 의무화(2009~2011) 전 연도이거나 폐지·신설 태그 "
          "(SalesRevenueNet 2020~, RevenueFromContractWithCustomer… ~2013): "
          + ", ".join(sorted(missing)[:0]) + f"전체 목록은 `data/sec/frames_missing.json`.", ""]

    # 연도별 CIK 수
    d = facts[facts.period.str.fullmatch(r"CY\d{4}")]
    yr = d.period.str[2:].astype(int)
    rev = d.concept.isin(REVENUE_CONCEPTS)
    tab = pd.DataFrame({
        "연도": sorted(yr.unique()),
    })
    tab["CIK(아무 값)"] = tab["연도"].map(d.groupby(yr).cik.nunique())
    tab["순이익 있음"] = tab["연도"].map(d[d.concept == "NetIncomeLoss"].groupby(yr).cik.nunique())
    tab["매출 있음"] = tab["연도"].map(d[rev].groupby(yr[rev]).cik.nunique())
    lg = d[(rev & (d.val >= 1e9)) | ((d.concept == "NetIncomeLoss") & (d.val >= 1e8))]
    tab["그해 대형"] = tab["연도"].map(lg.groupby(lg.period.str[2:].astype(int)).cik.nunique())
    L += ["## 연도별 CIK 수 (연간 frames, CY 기준)", "", _md_table(tab.fillna(0).astype(int)), ""]

    # 시점 문제
    nd = facts[facts.concept != "EntityCommonStockSharesOutstanding"]
    lag = nd.filed_year - nd.end.dt.year
    L += ["## frames 값의 공시 시점", "",
          "frames 는 각 기간에 그 값을 보고한 **가장 최근 공시**의 값을 준다(다음 해 10-K 의 비교연도 값 등).",
          "", "| 공시연도 − 기말연도 | 비율 |", "|---:|---:|"]
    for k, v in lag.clip(upper=4).value_counts(normalize=True).sort_index().items():
        L.append(f"| {'4 이상' if k == 4 else int(k)} | {v:.1%} |")
    if cf is not None:
        tbl, match = frames_vs_first(facts, cf, big)
        L += ["", f"### frames vs 최초 공시값 (대형 CIK, companyfacts 와 매칭된 {match:.1%})", "",
              "최초 공시값 = 같은 (cik, concept, start, end) 중 가장 이른 filed. duration 은 기간 330~400일만 비교.",
              "", _md_table(tbl), ""]

    # 상장폐지 추정 대형 CIK
    rv = facts[facts.concept.isin(REVENUE_CONCEPTS)].groupby("cik").val.max()
    last = facts.groupby("cik").end.max()
    dl = comp[comp.delisted_guess].copy()
    dl["최대 매출($B)"] = dl.cik.map(rv) / 1e9
    dl["마지막 기말"] = dl.cik.map(last).dt.strftime("%Y-%m")
    dl = dl.sort_values("최대 매출($B)", ascending=False)
    top = dl.head(30)[["cik", "name", "최대 매출($B)", "마지막 기말", "sicDescription"]].copy()
    top["최대 매출($B)"] = top["최대 매출($B)"].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "")
    L += ["## 티커 없는(상장폐지 추정) 대형 CIK", "",
          f"{len(dl):,}개 (대형 CIK 의 {len(dl) / len(comp):.1%}). 합병·인수·파산·비상장 전환·외국 모회사 자회사 등이 섞여 있음. "
          "이 회사들은 주가가 없어 백테스트에서 빠지므로 생존편향의 크기로 볼 수 있다.", "",
          "최대 매출 상위 30개:", "", _md_table(top.astype(str)), ""]

    # 주가 이상치
    if man is not None:
        L += ["## 주가 수집", ""]
        fail = man[man.status != "ok"]
        if len(fail):
            L += [f"실패 {len(fail)}개 (앞 40개):", "", _md_table(fail.head(40)[["cik", "ticker", "yahoo", "error"]].astype(str)), ""]
        L += price_anomalies(man[man.status == "ok"].yahoo.tolist(), splits)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"report -> {REPORT}")


def price_anomalies(tickers, splits):
    """하루 ±50% 넘는 adj_close 변동, OHLC 오류, 짧은 이력."""
    big, ohlc, short = [], 0, 0
    for t in tickers:
        p = PRICES_DIR / f"{t}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if len(df) < 252:
            short += 1
        r = df.adj_close / df.adj_close.shift() - 1
        for i in r[r.abs() > 0.5].index:
            big.append((t, df.date[i], r[i], df.close[i] / df.close[i - 1] - 1))
        ohlc += int(((df.high < df.low) | (df.close > df.high * 1.0001) | (df.close < df.low * 0.9999)).sum())
    L = [f"- 이력 1년 미만 티커: {short}개", f"- OHLC 논리오류 행: {ohlc:,}건 (전체 합계)",
         f"- 하루 adj_close ±50% 초과 변동: {len(big):,}건, 티커 {len({b[0] for b in big}):,}개"]
    if big:
        b = pd.DataFrame(big, columns=["ticker", "date", "adj 변동", "close 변동"])
        b["분할일"] = [bool(splits is not None and ((splits.ticker == t) & (splits.date == d)).any())
                     for t, d in zip(b.ticker, b.date)]
        b = b.reindex(b["adj 변동"].abs().sort_values(ascending=False).index).head(30)
        b["adj 변동"] = b["adj 변동"].map("{:+.0%}".format)
        b["close 변동"] = b["close 변동"].map("{:+.0%}".format)
        L += ["", "변동이 큰 30건 (분할일과 겹치면 Yahoo 분할 보정 누락 의심):", "", _md_table(b.astype(str))]
    return L + [""]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    set_deadline(sys.argv)
    try:
        if step in ("frames", "all"):
            fetch_frames()
        if step in ("facts", "all"):
            check_memory()
            build_facts()
        if step in ("companies", "all") and not fetch_companies():
            return 3  # 시간 제한으로 중단: 다시 실행
        if step in ("cf", "all") and not fetch_companyfacts():
            return 3
        if step == "cf_refresh" and not refresh_companyfacts(sys.argv[2]):
            return 3
        if step == "report":
            write_report()
    except LowMemory as e:
        log(f"STOP: {e}. 다시 실행하면 이어서 진행")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
