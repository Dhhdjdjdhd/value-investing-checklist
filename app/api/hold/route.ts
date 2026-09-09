import { NextResponse } from 'next/server';
import { getDb } from '@/lib/mongo';

// 계좌별 보유 내역 저장소.
// 데이터가 워낙 작아서(계좌 몇 줄) hold 컬렉션에 문서 하나로 통째로 저장한다.
//   GET /api/hold → { hold: [{name, ticker?, shares, cost}, ...] } — 저장된 값이 없으면 hold: null
//   PUT /api/hold → body { hold: [...] } 저장.
//                   EDIT_TOKEN 환경변수가 설정돼 있으면 x-edit-token 헤더가 일치해야 한다.
//
// ticker는 선택 필드다. 처음엔 모든 계좌가 360750 하나였어서 없이 저장된 문서가 있고,
// 화면(SNP500.html)이 그런 항목을 360750으로 간주한다 — 그래서 여기서도 강제하지 않는다.

export const dynamic = 'force-dynamic';

const DOC_ID = 'snp500';

// quote/history 라우트가 받는 티커 형식과 동일
const TICKER_RE = /^[A-Z0-9.\-^=]{1,12}$/;

export async function GET() {
  try {
    const db = await getDb();
    const doc = await db
      .collection('hold')
      .findOne({ id: DOC_ID }, { projection: { _id: 0 } });
    return NextResponse.json({ hold: doc?.hold ?? null });
  } catch {
    return NextResponse.json({ error: 'db unavailable' }, { status: 503 });
  }
}

export async function PUT(req: Request) {
  const token = process.env.EDIT_TOKEN;
  if (token && req.headers.get('x-edit-token') !== token) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  let hold: unknown;
  try {
    hold = (await req.json())?.hold;
  } catch {
    /* 아래 형식 검사에서 걸러진다 */
  }
  const ok =
    Array.isArray(hold) &&
    hold.length > 0 &&
    hold.length <= 10 &&
    hold.every(
      (h: any) =>
        h &&
        typeof h.name === 'string' &&
        h.name.length > 0 &&
        h.name.length <= 20 &&
        (h.ticker === undefined ||
          (typeof h.ticker === 'string' && TICKER_RE.test(h.ticker))) &&
        Number.isInteger(h.shares) &&
        h.shares >= 0 &&
        typeof h.cost === 'number' &&
        isFinite(h.cost) &&
        h.cost >= 0,
    );
  if (!ok) {
    return NextResponse.json({ error: 'invalid body' }, { status: 400 });
  }

  // 필요한 필드만 추려 저장 (임의 필드 주입 방지)
  const clean = (hold as any[]).map((h) => ({
    name: h.name,
    // 없으면 넣지 않는다 — 화면이 360750으로 간주하므로 굳이 채울 이유가 없다
    ...(h.ticker === undefined ? {} : { ticker: h.ticker }),
    shares: h.shares,
    cost: h.cost,
  }));

  try {
    const db = await getDb();
    await db.collection('hold').updateOne(
      { id: DOC_ID },
      {
        $set: {
          hold: clean,
          // toISOString()은 UTC라 KST와 어긋난다 — 사람이 볼 값이므로 KST 문자열로 저장
          updatedAt: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }),
        },
      },
      { upsert: true },
    );
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: 'db unavailable' }, { status: 503 });
  }
}
