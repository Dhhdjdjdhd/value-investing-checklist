"""한국(코스피) 백테스트용 OpenDART 수집기.

사용법 (작업 폴더 '체크리스트 검증' 기준):
    py src/kr_fetch_dart.py corps              # 종목코드 있는 전 회사의 기업개황 -> data/kr/companies.csv
    py src/kr_fetch_dart.py fin                # 대상 회사 × 2015~2025 사업보고서 전체 재무제표(CFS, 없으면 OFS)
    py src/kr_fetch_dart.py shares             # 대상 회사 × 2016~2025 주식의 총수 현황
    --limit 30   : 앞에서 N개 회사만 (시범)
    --only 00126380,00790501 : 지정 회사만

- 이어받기: 이미 받은 파일은 건너뛴다. '데이타 없음'(013)도 빈 파일로 남겨 다시 부르지 않는다.
- 일일 한도 초과(020) 등 진행 불가 상태면 저장 후 종료(종료코드 3). 다음 날 같은 명령으로 이어서 받는다.
- 원자료는 응답 JSON 그대로 data/kr/dart/{corp_code}/ 에 저장한다(항목 매핑은 kr_fundamentals.py에서).
- 대상 회사: 현재 코스피(Y) + 상장폐지(E) 중 data/kr/delisted_targets.csv 에 있는 회사.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
KR = ROOT / "data" / "kr"
DART = KR / "dart"
COMPANIES = KR / "companies.csv"
DELISTED = KR / "delisted_targets.csv"
API = "https://opendart.fss.or.kr/api/"
FIN_YEARS = range(2015, 2026)
SH_YEARS = range(2016, 2026)
GAP = 0.15  # 호출 간격(초)


class Stop(Exception):
    pass


def api_key():
    for line in (ROOT.parent / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DART_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DART_API_KEY가 .env.local에 없습니다")


KEY = None


def call(path, **params):
    params["crtfc_key"] = KEY
    url = API + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # 네트워크 오류는 잠깐 쉬고 재시도
            if attempt == 3:
                raise Stop(f"네트워크 오류 {e}")
            time.sleep(3 * (attempt + 1))
    time.sleep(GAP)
    st = j.get("status")
    if st in ("000", "013"):
        return j
    # 020 한도 초과, 010/011/012 키 문제, 800 점검, 900 기타 -> 중단
    raise Stop(f"DART {st} {j.get('message')}")


def save(p: Path, j):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def listed_codes():
    root = ET.parse(KR / "CORPCODE.xml").getroot()
    rows = [{c.tag: (c.text or "").strip() for c in e} for e in root]
    return [r for r in rows if r.get("stock_code")]


def cmd_corps(args):
    done = pd.read_csv(COMPANIES, dtype=str) if COMPANIES.exists() else pd.DataFrame()
    have = set(done.corp_code) if len(done) else set()
    todo = [r for r in listed_codes() if r["corp_code"] not in have]
    todo = select(todo, args)
    out = []
    try:
        for i, r in enumerate(todo):
            j = call("company.json", corp_code=r["corp_code"])
            out.append({"corp_code": r["corp_code"], "stock_code": r["stock_code"], "name": j.get("stock_name") or r["corp_name"],
                        "corp_cls": j.get("corp_cls", ""), "induty_code": j.get("induty_code", ""),
                        "acc_mt": j.get("acc_mt", ""), "est_dt": j.get("est_dt", "")})
            if i % 200 == 0:
                print(f"corps {i}/{len(todo)}", flush=True)
    except Stop as e:
        print("중단:", e)
        flush_companies(done, out)
        sys.exit(3)
    flush_companies(done, out)


def flush_companies(done, out):
    df = pd.concat([done, pd.DataFrame(out)], ignore_index=True)
    df.to_csv(COMPANIES, index=False, encoding="utf-8-sig")
    print("companies.csv", len(df), "행 / 코스피", (df.corp_cls == "Y").sum())


def targets():
    c = pd.read_csv(COMPANIES, dtype=str)
    t = c[c.corp_cls == "Y"]
    if DELISTED.exists():
        d = pd.read_csv(DELISTED, dtype=str)
        t = pd.concat([t, c[c.corp_code.isin(d.corp_code)]])
    return t.drop_duplicates("corp_code").to_dict("records")


def select(rows, args):
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["corp_code"] in keep]
    if args.limit:
        rows = rows[: args.limit]
    return rows


def cmd_fin(args):
    rows = select(targets(), args)
    n = 0
    try:
        for i, r in enumerate(rows):
            cc = r["corp_code"]
            for y in FIN_YEARS:
                p = DART / cc / f"{y}_fin.json"
                if p.exists():
                    continue
                j = call("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=y, reprt_code="11011", fs_div="CFS")
                j["fs_div"] = "CFS"
                if j["status"] == "013":
                    j = call("fnlttSinglAcntAll.json", corp_code=cc, bsns_year=y, reprt_code="11011", fs_div="OFS")
                    j["fs_div"] = "OFS"
                    n += 1
                save(p, j)
                n += 1
            if i % 50 == 0:
                print(f"fin 회사 {i}/{len(rows)} 호출 {n}", flush=True)
    except Stop as e:
        print("중단:", e, "/ 이번 호출", n)
        sys.exit(3)
    print("fin 완료 / 이번 호출", n)


def cmd_shares(args):
    rows = select(targets(), args)
    n = 0
    try:
        for i, r in enumerate(rows):
            cc = r["corp_code"]
            for y in SH_YEARS:
                p = DART / cc / f"{y}_sh.json"
                if p.exists():
                    continue
                save(p, call("stockTotqySttus.json", corp_code=cc, bsns_year=y, reprt_code="11011"))
                n += 1
            if i % 50 == 0:
                print(f"shares 회사 {i}/{len(rows)} 호출 {n}", flush=True)
    except Stop as e:
        print("중단:", e, "/ 이번 호출", n)
        sys.exit(3)
    print("shares 완료 / 이번 호출", n)


def main():
    global KEY
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["corps", "fin", "shares"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    args = ap.parse_args()
    KEY = api_key()
    {"corps": cmd_corps, "fin": cmd_fin, "shares": cmd_shares}[args.cmd](args)


if __name__ == "__main__":
    main()
