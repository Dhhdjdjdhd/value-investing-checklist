'use client';

import { useState } from 'react';
import type { StockMeta } from '@/lib/content';

// 분석 보고서 HTML은 <style>·<script>를 자체 포함한 완결 문서다.
// body만 뽑아 넣으면 스타일이 깨지므로 iframe으로 통째로 띄운다.

// 분석 보고서가 아닌 고정 탭 — 적립식 ETF 모니터링 화면
const MONITOR = { ticker: 'SNP500', name: 'S&P500', desc: '360750 · 모니터링' };

// 비밀번호로 잠긴 고정 탭 — LTP(Long-Term Plan). 티커처럼 보이게 위장 (RETIRE.html 자체에도 동일 게이트가 있어 직접 URL 접근도 막는다)
const RETIRE = { ticker: 'RETIRE', name: 'LTP', desc: '🔒 Long-term · 리서치' };
const RETIRE_PW = '880115';
const RETIRE_KEY = 'vic-retire-ok';

// LTP 파생안 — 배당+나스닥 50:50 은퇴 플랜 (LTP와 같은 비밀번호·세션 키 공유)
const DIVNDQ = { ticker: 'DIVNDQ', name: 'LTP-2', desc: '🔒 배당+나스닥 50:50' };

export default function ReportTabs({ stocks }: { stocks: StockMeta[] }) {
  const [active, setActive] = useState(MONITOR.ticker);

  // LTP 계열 잠금 탭 공통 — 한 번 인증하면 세션 동안 모두 열린다
  const openLocked = (ticker: string) => {
    if (sessionStorage.getItem(RETIRE_KEY) === '1') {
      setActive(ticker);
      return;
    }
    const input = window.prompt('비밀번호를 입력하세요');
    if (input === RETIRE_PW) {
      sessionStorage.setItem(RETIRE_KEY, '1');
      setActive(ticker);
    } else if (input !== null) {
      alert('비밀번호가 틀렸습니다');
    }
  };

  return (
    <div className="flex h-full">
      {/* vic-sidebar: 모바일(html.vic-mobile)에서는 globals.css가 숨긴다 */}
      <aside className="vic-sidebar flex w-48 shrink-0 flex-col border-r border-line bg-white">
        <nav className="flex-1 overflow-y-auto p-2">
          <button
            onClick={() => setActive(MONITOR.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === MONITOR.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{MONITOR.name}</span>
            <span
              className={`block text-[11px] ${
                active === MONITOR.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {MONITOR.desc}
            </span>
          </button>

          <button
            onClick={() => openLocked(RETIRE.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === RETIRE.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{RETIRE.name}</span>
            <span
              className={`block text-[11px] ${
                active === RETIRE.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {RETIRE.desc}
            </span>
          </button>

          <button
            onClick={() => openLocked(DIVNDQ.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === DIVNDQ.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{DIVNDQ.name}</span>
            <span
              className={`block text-[11px] ${
                active === DIVNDQ.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {DIVNDQ.desc}
            </span>
          </button>

          <div className="my-2 border-t border-line" />

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
