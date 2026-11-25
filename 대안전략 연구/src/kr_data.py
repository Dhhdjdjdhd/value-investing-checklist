"""I. 국내주식 여러 전략용 데이터 — Yahoo 월말 종가·수정주가·월별 배당 합계 (2000-01~).

우주: 현재 코스피 대형·중형주 약 110개(아래 목록, 결과 보기 전에 고정). 지금 상장된 종목만이라 생존편향이 있다
→ 비교 기준을 '같은 우주 동일비중'으로 둬서 전략 간 비교는 공정하게 하고, 코스피 대비 수치는 참고로만 본다.
실행: py src/kr_data.py -> data/kr_y/{code}.csv (month, close, adj, div)
"""
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "kr_y"
OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (compatible; research-script)"

UNIVERSE = """
005930 삼성전자|005935 삼성전자우|000660 SK하이닉스|005380 현대차|000270 기아|005490 POSCO홀딩스|051910 LG화학
006400 삼성SDI|012330 현대모비스|055550 신한지주|105560 KB금융|086790 하나금융지주|316140 우리금융지주|017670 SK텔레콤
030200 KT|015760 한국전력|033780 KT&G|066570 LG전자|003550 LG|034730 SK|009150 삼성전기|011170 롯데케미칼
010950 S-Oil|000810 삼성화재|032830 삼성생명|034220 LG디스플레이|011200 HMM|010140 삼성중공업|042660 한화오션
047040 대우건설|000720 현대건설|004020 현대제철|036460 한국가스공사|010130 고려아연|009540 HD한국조선해양
028260 삼성물산|035420 NAVER|035720 카카오|068270 셀트리온|207940 삼성바이오로직스|096770 SK이노베이션
018260 삼성에스디에스|323410 카카오뱅크|024110 기업은행|138040 메리츠금융지주|005830 DB손해보험|001450 현대해상
088350 한화생명|006800 미래에셋증권|016360 삼성증권|039490 키움증권|071050 한국금융지주|000100 유한양행
128940 한미약품|000120 CJ대한통운|097950 CJ제일제당|001040 CJ|271560 오리온|004370 농심|007310 오뚜기
139480 이마트|023530 롯데쇼핑|004170 신세계|069960 현대백화점|282330 BGF리테일|051900 LG생활건강
090430 아모레퍼시픽|002790 아모레퍼시픽홀딩스|021240 코웨이|035250 강원랜드|008770 호텔신라|003490 대한항공
020560 아시아나항공|180640 한진칼|086280 현대글로비스|011070 LG이노텍|034020 두산에너빌리티|000150 두산
042670 HD현대인프라코어|267250 HD현대|329180 HD현대중공업|010620 HD현대미포|012450 한화에어로스페이스
000880 한화|009830 한화솔루션|047810 한국항공우주|064350 현대로템|079550 LIG넥스원|011780 금호석유
010060 OCI홀딩스|011790 SKC|006260 LS|010120 LS ELECTRIC|001120 LX인터내셔널|047050 포스코인터내셔널
003670 포스코퓨처엠|005940 NH투자증권|029780 삼성카드|078930 GS|006360 GS건설|028050 삼성E&A|000210 DL
375500 DL이앤씨|036570 엔씨소프트|251270 넷마블|259960 크래프톤|352820 하이브|030000 제일기획
017800 현대엘리베이터|002380 KCC|004990 롯데지주|005300 롯데칠성|001680 대상|007070 GS리테일|004800 효성
298050 HS효성첨단소재|120110 코오롱인더|161390 한국타이어앤테크놀로지|073240 금호타이어|204320 HL만도
018880 한온시스템|005850 에스엘|011210 현대위아|002320 한진|000080 하이트진로|192820 코스맥스
"""
CODES = dict(x.strip().split(" ", 1) for x in UNIVERSE.replace("\n", "|").split("|") if x.strip())


def fetch(code):
    p = OUT / f"{code}.csv"
    if p.exists():
        return pd.read_csv(p, index_col=0)
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.KS?period1=946684800&period2=9999999999"
         f"&interval=1d&events=div")
    for k in range(3):
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read())
            break
        except Exception as e:  # noqa: BLE001
            if k == 2:
                raise
            time.sleep(3 * (k + 1))
    r = r["chart"]["result"][0]
    ts = pd.to_datetime(r["timestamp"], unit="s")
    q = r["indicators"]
    d = pd.DataFrame({"close": q["quote"][0]["close"], "adj": q["adjclose"][0]["adjclose"]}, index=ts).dropna()
    m = d.groupby(d.index.strftime("%Y-%m")).last()
    divs = (r.get("events") or {}).get("dividends") or {}
    dv = pd.Series({pd.to_datetime(int(v["date"]), unit="s").strftime("%Y-%m"): v["amount"] for v in divs.values()},
                   dtype=float)
    dv = dv.groupby(level=0).sum()
    m["div"] = dv.reindex(m.index).fillna(0.0)
    m.index.name = "month"
    m.to_csv(p)
    return m


def load_all():
    out = {}
    for code in CODES:
        p = OUT / f"{code}.csv"
        if p.exists():
            out[code] = pd.read_csv(p, index_col=0)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ok = bad = 0
    for code, name in CODES.items():
        try:
            m = fetch(code)
            ok += 1
            print(code, name, m.index[0], len(m), f"배당월 {int((m['div'] > 0).sum())}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print("실패", code, name, e)
        time.sleep(0.4)
    print("완료", ok, "실패", bad)
