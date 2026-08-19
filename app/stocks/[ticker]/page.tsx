import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getAllStocks, getStock, marginOfSafety } from '@/lib/content';
import VerdictBadge from '@/components/VerdictBadge';

// 빌드 시점에 전 종목을 미리 HTML로 만들어 둔다.
// 검색 노출이 사업 유입 경로이므로 정적 생성이 기본값이다.
export function generateStaticParams() {
  return getAllStocks().map((s) => ({ ticker: s.ticker }));
}

export async function generateMetadata({
  params,
}: {
  params: { ticker: string };
}): Promise<Metadata> {
  const doc = await getStock(params.ticker);
  if (!doc) return { title: '분석을 찾을 수 없습니다' };

  return {
    title: `${doc.name} (${doc.ticker}) 분석 — ${doc.verdict}`,
    description: doc.summary,
  };
}

export default async function StockPage({
  params,
}: {
  params: { ticker: string };
}) {
  const doc = await getStock(params.ticker);
  if (!doc) notFound();

  const mos = marginOfSafety(doc);

  // layout이 body에 overflow-hidden을 걸어 두었으므로(보고서를 화면 가득 띄우기 위함),
  // 긴 문서인 이 페이지는 자체 스크롤 영역을 만들어야 한다. 없으면 아래가 잘려서 안 보인다.
  return (
    <article className="mx-auto h-full max-w-4xl overflow-y-auto px-5 py-8">
      <Link
        href="/dashboard"
        className="text-[13px] text-muted hover:text-navy"
      >
        ← 보고서 화면으로
      </Link>

      {/* 요약 카드 — 본문을 다 읽지 않아도 결론과 근거 숫자가 먼저 보이게 한다 */}
      <header className="mb-8 mt-3 rounded-card border border-line bg-white p-6 shadow-soft">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-navy">
            {doc.name}
            <span className="ml-2 text-base font-normal text-muted">
              {doc.ticker}
            </span>
          </h1>
          <VerdictBadge verdict={doc.verdict} />
        </div>

        {doc.summary && (
          <p className="mb-5 text-[15px] leading-relaxed text-ink-2">
            {doc.summary}
          </p>
        )}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-4 text-[14px] sm:grid-cols-4">
          <div>
            <dt className="mb-0.5 text-[12px] text-muted">분석 시점 주가</dt>
            <dd className="font-bold tabular-nums text-ink">
              ${doc.price.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="mb-0.5 text-[12px] text-muted">내재가치 (기본)</dt>
            <dd className="font-bold tabular-nums text-ink">
              ${doc.intrinsicValue.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="mb-0.5 text-[12px] text-muted">목표 매수가</dt>
            <dd className="font-bold tabular-nums text-ink">
              ${doc.targetPrice.toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="mb-0.5 text-[12px] text-muted">안전마진</dt>
            <dd
              className={`font-bold tabular-nums ${
                mos >= 20 ? 'text-pass' : 'text-warn'
              }`}
            >
              {mos.toFixed(1)}%
            </dd>
          </div>
        </dl>

        <p className="mt-4 border-t border-line pt-3 text-[12px] text-muted">
          분석일 {doc.date} · 위 숫자는 분석 시점 기준이며 현재가와 다릅니다.
        </p>
      </header>

      <div
        className="vic-doc"
        dangerouslySetInnerHTML={{ __html: doc.html }}
      />
    </article>
  );
}
