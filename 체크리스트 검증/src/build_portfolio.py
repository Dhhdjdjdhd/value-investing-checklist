"""v2 선정 20을 동일비중으로 일괄 진입한 가상 장부 → public/reports/PORTFOLIO.html 데이터 블록.

체결가 = 선정 기준일(screen_now.csv price_date) 종가, 환율 = Yahoo KRW=X 최신값.
수량 = round(자본 × 5% ÷ 원화 주가), 남는 돈은 현금. 실행: py src/build_portfolio.py [자본(원)]
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

from build_watch import KO, GRADE, VETO

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT.parent / "public" / "reports" / "PORTFOLIO.html"
N, W = 20, 0.05

# 업종 묶음(도넛 색) · 세부 업종(근거 모달)
SECTOR = {
    "DPZ": ("소비재", "외식 프랜차이즈"), "BKNG": ("소비재", "온라인 여행"), "DECK": ("소비재", "신발(HOKA·UGG)"),
    "LULU": ("소비재", "스포츠 의류"), "DDS": ("소비재", "백화점"), "ULTA": ("소비재", "화장품 소매"),
    "TSCO": ("소비재", "농촌 생활용품 소매"), "TPR": ("소비재", "패션 잡화(코치)"), "AZO": ("소비재", "자동차부품 소매"),
    "HD": ("소비재", "주택개선 소매"),
    "MCK": ("헬스케어 유통", "의약품 도매"), "CAH": ("헬스케어 유통", "의약품 도매"), "COR": ("헬스케어 유통", "의약품 도매"),
    "OTIS": ("산업재", "엘리베이터 설치·유지보수"), "LII": ("산업재", "냉난방 공조"),
    "ADP": ("업무 서비스", "급여·인사 아웃소싱"), "PAYX": ("업무 서비스", "중소기업 급여·인사"), "IT": ("업무 서비스", "IT 리서치·자문"),
    "CHKP": ("기술", "보안 소프트웨어"), "QCOM": ("기술", "모바일 반도체·라이선스"),
}


def quote(t):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]["meta"]["regularMarketPrice"]


def main(capital):
    s = pd.read_csv(ROOT / "results" / "screen_now.csv")
    s = s[~s.ticker.isin(VETO)].head(N).reset_index(drop=True)
    fx = quote("KRW=X")
    holdings, spent = [], 0
    for i, r in s.iterrows():
        px = float(r.price)
        krw = round(px * fx)
        n = max(1, round(capital * W / krw))
        spent += n * krw
        grp, ind = SECTOR[r.ticker]
        grade = GRADE[r.grade]
        holdings.append({
            "rank": i + 1, "name": KO.get(r.ticker, r.ticker), "code": r.ticker,
            "sector": grp, "industry": ind, "grade": grade, "entryDate": "2026-10-23",
            "shares": n, "avgPrice": krw,
            "roic": round(r.roic_med5 * 100, 1), "fcfYield": round(r.fcf_yield * 100, 1),
            "intrinsicValue": round(float(r.iv_ps), 1),
            "entryReason": (
                f"체크리스트 v2 선정 {i + 1}위 · 등급 {grade}. ROIC 5년 중앙값 {r.roic_med5 * 100:.1f}%, "
                f"FCF 수익률 {r.fcf_yield * 100:.1f}%, PER {r.pe:.1f}. "
                f"체결가 = {r.price_date} 종가 ${px:.2f} × 환율 {fx:.2f}원 → 주당 {krw:,}원, {n}주 "
                f"(목표 비중 5% = {capital * W:,.0f}원에 가장 가까운 정수 주). "
                f"내재가치(DCF 기본값) ${r.iv_ps:.1f}는 참고용 — v2는 목표가를 기다리지 않는다. "
                f"점검: 분기마다 순위 재계산, 30위 밖이거나 관문 탈락이면 교체, 10% 넘으면 5%로 되돌림."
            ),
        })
    cash = int(capital - spent)
    if cash < 0:
        raise SystemExit(f"자본 초과 {cash:,}원 — 자본을 늘리세요")
    data = json.dumps({"cash": cash, "holdings": holdings}, ensure_ascii=False, indent=2)
    text = HTML.read_text(encoding="utf-8")
    new, k = re.subn(r"// <DATA>\n.*?\n// </DATA>", lambda _: f"// <DATA>\nvar DEFAULT_DATA = {data};\n// </DATA>",
                     text, flags=re.S)
    assert k == 1, "데이터 블록 표시를 찾지 못함"
    HTML.write_text(new, encoding="utf-8")
    w = [h["shares"] * h["avgPrice"] / capital * 100 for h in holdings]
    print(f"환율 {fx:.2f} · 매입 {spent:,}원 · 현금 {cash:,}원 · 비중 {min(w):.2f}~{max(w):.2f}%")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1e8)
