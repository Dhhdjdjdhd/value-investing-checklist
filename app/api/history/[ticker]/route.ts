import { NextResponse } from 'next/server';

// 가격 히스토리 프록시 — S&P500 모니터링 차트용.
// quote 라우트와 같은 이유(CORS·UA 차단)로 서버가 야후를 대신 호출한다.

export const dynamic = 'force-dynamic';

// range별 적정 간격 — 포인트 수를 수백 개 이하로 유지한다
const INTERVAL: Record<string, string> = {
  '1mo': '1d',
  '3mo': '1d',
  '6mo': '1d',
  '1y': '1d',
  '3y': '1wk',
  max: '1wk',
};

export async function GET(
  req: Request,
  { params }: { params: { ticker: string } },
) {
  // 한국 종목(360750.KS)의 숫자, 지수(^GSPC)·환율(KRW=X) 심볼까지 허용한다
  const ticker = params.ticker.toUpperCase();
  if (!/^[A-Z0-9.\-^=]{1,12}$/.test(ticker)) {
    return NextResponse.json({ error: 'invalid ticker' }, { status: 400 });
  }

  const range = new URL(req.url).searchParams.get('range') ?? '1y';
  const interval = INTERVAL[range];
  if (!interval) {
    return NextResponse.json({ error: 'invalid range' }, { status: 400 });
  }

  try {
    const res = await fetch(
      `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=${interval}&range=${range}`,
      {
        headers: { 'User-Agent': 'Mozilla/5.0' },
        next: { revalidate: 300 }, // 종가 기반 차트라 5분 캐시면 충분
      },
    );

    if (!res.ok) {
      return NextResponse.json(
        { error: `upstream ${res.status}` },
        { status: 502 },
      );
    }

    const result = (await res.json())?.chart?.result?.[0];
    const ts: number[] = result?.timestamp ?? [];
    const closes: (number | null)[] =
      result?.indicators?.quote?.[0]?.close ?? [];
    if (!ts.length || !closes.length) {
      return NextResponse.json({ error: 'no data' }, { status: 502 });
    }

    // 휴장일 등 null 포인트는 걸러낸다
    const t: number[] = [];
    const c: number[] = [];
    for (let i = 0; i < ts.length; i++) {
      if (closes[i] != null) {
        t.push(ts[i]);
        c.push(Number(closes[i]));
      }
    }

    return NextResponse.json({
      ticker,
      currency: result?.meta?.currency ?? 'KRW',
      t,
      c,
    });
  } catch {
    return NextResponse.json({ error: 'fetch failed' }, { status: 502 });
  }
}
