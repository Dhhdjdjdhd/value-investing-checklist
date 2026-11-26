# 미국 대형주 시점별 데이터 만들기 (2026-11-26) — pick_us.py 용
#  - 후보: 2010~2026 사이 미국 시총 상위권에 든 적 있는 '미국 공시(10-K)' 기업을 넉넉히 나열(사후 작성 목록 → 누락 가능, 한계로 명시)
#  - SEC companyfacts → 체크리스트 검증 fetch_sec.cf_rows(같은 항목) → fundamentals.build_annual_cf(mode='first', 최초 공시값)
#  - SEC submissions → SIC(업종 제외용), Yahoo → 일별 close(분할 반영)·adjclose(배당 포함)·분할 이력
#  - 출력: 물타기 백테스트/data_us/{annual.parquet, close.parquet, adj.parquet, meta.csv}
import sys, json, time, urllib.request
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent / '체크리스트 검증' / 'src'))
import fetch_sec, fundamentals  # noqa: E402

OUT = HERE / 'data_us'; OUT.mkdir(exist_ok=True)
# www.sec.gov 티커 목록이 403(이메일 없는 User-Agent) → CIK 직접 지정, submissions의 이름·티커로 검증
# 합병·재상장으로 CIK가 바뀐 회사는 [새 CIK, 옛 CIK...]를 한 회사로 합침(옛 공시의 최초값 보존)
CIKS = dict(AAPL=320193, MSFT=789019, GOOGL=[1652044, 1288776], AMZN=1018724, META=1326801, NVDA=1045810, TSLA=1318605, **{'BRK-B': 1067983},
            AVGO=[1730168, 1649338, 1441634], LLY=59478, JPM=19617, V=1403161, MA=1141391, UNH=731766, XOM=34088, WMT=104169, JNJ=200406,
            PG=80424, HD=354950, CVX=93410, KO=21344, PEP=77476, MRK=310158, ABBV=1551152, PFE=78003, ORCL=1341439, CSCO=858877, INTC=50863,
            IBM=51143, GE=40545, T=732717, VZ=732712, CMCSA=1166691, DIS=[1744489, 1001039], MCD=63908, BAC=70858, WFC=72971, C=831001,
            GS=886982, MS=895421, AXP=4962, NFLX=1065280, ADBE=796343, CRM=1108524, AMD=2488, QCOM=804328, TXN=97476, COST=909832,
            NKE=320187, PM=1413329, MO=764180, AMGN=318154, GILD=882095, BMY=14272, ABT=1800, TMO=97745, DHR=313616, MDT=[1613103, 64670],
            HON=773840, UPS=1090727, BA=12927, MMM=66740, CAT=18230, UNP=100885, LIN=[1707925, 884905], ACN=1467373, SLB=87347, COP=1163165,
            OXY=797468, EOG=821189, PYPL=1633917, BKNG=1075531, ISRG=1035267, NOW=1373715, PLTR=1321655, MU=723125, LRCX=707549, AMAT=6951,
            KLAC=319201, ADI=6281, CVS=64803, CI=[1739940, 701221], ELV=1156039, LOW=60667, SBUX=829224, MDLZ=1103982, KHC=1637459,
            DOW=1751788, DD=1666700, GM=1467858, F=37996, CHTR=1091667, TMUS=1283699, NEE=753308, DUK=1326160, SO=92122, SPGI=64040,
            BLK=[2012383, 1364742], SCHW=316709, UBER=1543151, ANET=1596532, HPQ=47217, WBA=1618921, LMT=936468, RTX=101829, USB=36104,
            MET=1099219, AIG=5272, EBAY=1065088, APP=1751008, CELG=816284, AGN=1578845, ESRX=1532063, EMC=790070, MON=1110783, TWX=1105705)
TICKERS = list(CIKS)


def yget(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1104537600&period2=1800000000&interval=1d&events=split'
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))['chart']['result'][0]
    except Exception as e:
        return None, None, None, str(e)[:60]
    ix = pd.to_datetime(r['timestamp'], unit='s').normalize()
    cl = pd.Series(r['indicators']['quote'][0]['close'], index=ix)
    adj = pd.Series(r['indicators'].get('adjclose', [{}])[0].get('adjclose', cl.values), index=ix)
    sp = [(pd.to_datetime(v['date'], unit='s').normalize(), v['numerator'] / v['denominator']) for v in (r.get('events', {}).get('splits') or {}).values()]
    g = lambda s: s.dropna().groupby(level=0).last()
    return g(cl), g(adj), sp, None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    rows, meta, closes, adjs, splits = [], [], {}, {}, []
    for t in TICKERS:
        cl_ = CIKS[t] if isinstance(CIKS[t], list) else [CIKS[t]]
        cik = cl_[0]; d = None
        for j, c in enumerate(cl_):
            raw = fetch_sec.sec_get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json')
            sub = json.loads(fetch_sec.sec_get(f'https://data.sec.gov/submissions/CIK{c:010d}.json') or b'{}')
            tks = [x.replace('.', '-') for x in sub.get('tickers', [])]
            print(f'검증 {t} CIK {c}: {sub.get("name")} 티커 {tks}' + ('' if t in tks or j > 0 else '  ← 티커 불일치 확인 필요'), flush=True)
            if raw is None: print('companyfacts 없음', t, c); continue
            dd = json.loads(raw); rows += fetch_sec.cf_rows(cik, dd)  # 옛 CIK 공시도 새 CIK로 합침
            if j == 0: d, s = dd, sub
        if d is None: continue
        cl, adj, sp, err = yget(t)
        if t == 'EMC': cl = None  # 티커 재사용(Dell 계열 다른 증권) → 가격 버림
        if cl is None or len(cl) < 100: print('가격 없음', t, err)
        else:
            closes[t], adjs[t] = cl, adj
            splits += [dict(ticker=t, date=a, ratio=b) for a, b in sp]
        meta.append(dict(ticker=t, cik=cik, name=d.get('entityName'), sic=s.get('sic'), sicDesc=s.get('sicDescription'),
                         price_from=cl.index[0].date() if cl is not None and len(cl) else None, price_to=cl.index[-1].date() if cl is not None and len(cl) else None))
        print('완료', t, cik, s.get('sic'), flush=True)
        time.sleep(0.2)
    cf = pd.DataFrame(rows, columns=fetch_sec.CF_COLS)
    M = pd.DataFrame(meta); SP = pd.DataFrame(splits, columns=['ticker', 'date', 'ratio'])
    a = fundamentals.build_annual_cf(cf, mode='first', splits=SP, tickers=M.set_index('cik').ticker)
    a = a.merge(M[['cik', 'ticker', 'sic']], on='cik', how='left')
    a.to_parquet(OUT / 'annual.parquet', index=False)
    pd.DataFrame(closes).to_parquet(OUT / 'close.parquet'); pd.DataFrame(adjs).to_parquet(OUT / 'adj.parquet')
    M.to_csv(OUT / 'meta.csv', index=False, encoding='utf-8-sig'); SP.to_csv(OUT / 'splits.csv', index=False)
    print('annual', a.shape, '회사', a.cik.nunique())


if __name__ == '__main__':
    main()
