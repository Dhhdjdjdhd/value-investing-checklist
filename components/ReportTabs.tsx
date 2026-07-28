'use client';

import { useState } from 'react';
import type { StockMeta } from '@/lib/content';

// 분석 보고서 HTML은 <style>·<script>를 자체 포함한 완결 문서다.
// body만 뽑아 넣으면 스타일이 깨지므로 iframe으로 통째로 띄운다.

export default function ReportTabs({ stocks }: { stocks: StockMeta[] }) {
  const [active, setActive] = useState(stocks[0]?.ticker ?? '');

  if (stocks.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        content/stocks 에 분석 문서가 없습니다.
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <aside className="flex w-48 shrink-0 flex-col border-r border-line bg-white">
        <nav className="flex-1 overflow-y-auto p-2">
          {stocks.map((s) => {
            const on = s.ticker === active;
            return (
              <button
                key={s.ticker}
                onClick={() => setActive(s.ticker)}
                className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
                  on
                    ? 'bg-navy text-white'
                    : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
                }`}
              >
                <span className="block text-[14px] font-bold">{s.name}</span>
                <span
                  className={`block text-[11px] ${
                    on ? 'text-white/70' : 'text-muted'
                  }`}
                >
                  {s.ticker}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          <a
            href={`/reports/${active}.html`}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-muted hover:text-navy hover:underline"
          >
            새 창에서 열기 ↗
          </a>
        </div>
      </aside>

      {/* key를 주어 탭 전환 시 iframe이 새로 마운트되도록 한다(스크롤 위치 초기화) */}
      <iframe
        key={active}
        src={`/reports/${active}.html`}
        title={`${active} 분석 보고서`}
        className="h-full flex-1 border-0"
      />
    </div>
  );
}
