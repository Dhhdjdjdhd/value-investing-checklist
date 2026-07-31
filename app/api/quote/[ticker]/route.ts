import { NextResponse } from 'next/server';

// 실시간 시세 프록시.
// 브라우저에서 야후를 직접 부르면 CORS에 막히므로 서버가 대신 호출한다.
// 보고서 HTML(정적 파일)은 같은 오리진의 이 경로를 부르면 된다.
//
// 한국 종목(000000.KS/.KQ)은 네이버 금융을 먼저 쓴다 — 야후의 KRX 시세는 수 분
// 지연되지만 네이버는 실시간(delayTime 0)이다. 비공식 API라 실패하면 야후로 폴백.

export const dynamic = 'force-dynamic';

// 네이버 상승/하락 코드 → 부호 (1 상한, 2 상승, 3 보합, 4 하한, 5 하락)
const NAVER_SIGN: Record<string, number> = { '1': 1, '2': 1, '3': 0, '4': -1, '5': -1 };

async function fetchNaver(code: string) {
  const res = await fetch(`https://m.stock.naver.com/api/stock/${code}/basic`, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
    next: { revalidate: 10 }, // 실시간 소스라 캐시를 짧게 — 화면 갭 최소화
  });
  if (!res.ok) throw new Error(`naver ${res.status}`);

  const d = await res.json();
  const num = (s: unknown) => Number(String(s ?? '').replace(/,/g, ''));
  const price = num(d.closePrice);
  if (!price) throw new Error('naver no price');

  const sign = NAVER_SIGN[d.compareToPreviousPrice?.code] ?? 0;
  const change = sign * num(d.compareToPreviousClosePrice);
  const prev = price - change;

  return {
    name: String(d.stockName ?? code),
    price,
    prevClose: prev,
    change,
    changePct: prev ? (change / prev) * 100 : 0,
    marketState: d.marketStatus === 'OPEN' ? ('REGULAR' as const) : ('CLOSED' as const),
    // 체결 시각이 있으면 그걸 기준 시각으로 보여준다 (없으면 서버 시각)
    asOf: new Date(d.localTradedAt ?? Date.now()).toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
    }),
  };
}

export async function GET(
  _req: Request,
  { params }: { params: { ticker: string } },
) {
  // 경로로 들어온 값을 그대로 외부 URL에 붙이지 않는다(티커 형식만 허용)
  // 한국 종목(360750.KS)도 쓰므로 숫자를 허용한다
  const ticker = params.ticker.toUpperCase();
  if (!/^[A-Z0-9.\-]{1,10}$/.test(ticker)) {
    return NextResponse.json({ error: 'invalid ticker' }, { status: 400 });
  }

  // 한국 종목이면 네이버 우선 — 실패 시 아래 야후 경로로 폴백
  const kr = ticker.match(/^(\d{6})\.(KS|KQ)$/);
  if (kr) {
    try {
      const q = await fetchNaver(kr[1]);
      return NextResponse.json({
        ticker,
        ...q,
        currency: 'KRW',
        source: 'naver',
        regularStart: null,
        regularEnd: null,
      });
    } catch {
      // 네이버 실패 — 야후로 폴백
    }
  }

  try {
    const res = await fetch(
      `https://query1.finance.yahoo.com/v8/finance/chart/${ticker}?interval=1d&range=1d`,
      {
        // UA가 없으면 야후가 차단한다
        headers: { 'User-Agent': 'Mozilla/5.0' },
        next: { revalidate: 60 }, // 60초 캐시 — 무료 플랜에서 과도한 호출 방지
      },
    );

    if (!res.ok) {
      return NextResponse.json(
        { error: `upstream ${res.status}` },
        { status: 502 },
      );
    }

    const meta = (await res.json())?.chart?.result?.[0]?.meta;
    if (!meta?.regularMarketPrice) {
      return NextResponse.json({ error: 'no data' }, { status: 502 });
    }

    const price = Number(meta.regularMarketPrice);
    const prev = Number(meta.chartPreviousClose ?? meta.previousClose ?? price);

    // 장 상태 판정.
    // 야후 chart API에는 marketState 필드가 없어서 currentTradingPeriod로 직접 계산한다.
    // (전부 epoch 초 단위)
    const nowSec = Math.floor(Date.now() / 1000);
    const tp = meta.currentTradingPeriod ?? {};
    const inRange = (p: { start?: number; end?: number } | undefined) =>
      !!p?.start && !!p?.end && nowSec >= p.start && nowSec < p.end;

    let marketState: 'REGULAR' | 'PRE' | 'POST' | 'CLOSED' = 'CLOSED';
    if (inRange(tp.regular)) marketState = 'REGULAR';
    else if (inRange(tp.pre)) marketState = 'PRE';
    else if (inRange(tp.post)) marketState = 'POST';

    return NextResponse.json({
      ticker,
      name: meta.longName ?? meta.shortName ?? ticker,
      price,
      prevClose: prev,
      change: price - prev,
      changePct: prev ? ((price - prev) / prev) * 100 : 0,
      currency: meta.currency ?? 'USD',
      source: 'yahoo',
      marketState, // 클라이언트는 REGULAR일 때만 짧은 주기로 갱신한다
      regularStart: tp.regular?.start ?? null,
      regularEnd: tp.regular?.end ?? null,
      // toISOString()은 UTC라 KST와 어긋난다 — 화면에 그대로 쓸 수 있게 KST로 만들어 보낸다
      asOf: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }),
    });
  } catch {
    return NextResponse.json({ error: 'fetch failed' }, { status: 502 });
  }
}
