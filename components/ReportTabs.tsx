'use client';

import { useState } from 'react';
import Link from 'next/link';
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

// 매매 계좌 실시간 대시보드 — 분석 보고서가 아닌 고정 탭
const PORTFOLIO = { ticker: 'PORTFOLIO', name: '포트폴리오', desc: '보유·손익 실시간' };

export default function ReportTabs({ stocks }: { stocks: StockMeta[] }) {
  const [active, setActive] = useState(MONITOR.ticker);
  // 모바일 햄버거 메뉴 열림 여부 — 데스크톱에서는 버튼이 숨겨져 항상 false
  const [menuOpen, setMenuOpen] = useState(false);

  // 탭 선택 공통 — 모바일 메뉴가 열려 있었다면 닫는다
  const select = (ticker: string) => {
    setActive(ticker);
    setMenuOpen(false);
  };

  // LTP 계열 잠금 탭 공통 — 한 번 인증하면 세션 동안 모두 열린다
  const openLocked = (ticker: string) => {
    if (sessionStorage.getItem(RETIRE_KEY) === '1') {
      select(ticker);
      return;
    }
    const input = window.prompt('비밀번호를 입력하세요');
    if (input === RETIRE_PW) {
      sessionStorage.setItem(RETIRE_KEY, '1');
      select(ticker);
    } else if (input !== null) {
      alert('비밀번호가 틀렸습니다');
    }
  };

  return (
    <div className="flex h-full">
      {/* vic-menu-btn: 사이드바가 숨겨지는 모바일에서만 노출되는 햄버거 버튼 (globals.css에서 제어) */}
      <button
        onClick={() => setMenuOpen(true)}
        aria-label="메뉴 열기"
        className="vic-menu-btn hidden fixed left-3 top-3 z-50 h-10 w-10 items-center justify-center rounded-full bg-navy text-[16px] text-white shadow-soft"
      >
        ☰
      </button>

      {/* vic-backdrop: 모바일 메뉴가 열렸을 때 바깥 터치로 닫는 딤 영역 */}
      {menuOpen && (
        <div
          onClick={() => setMenuOpen(false)}
          className="vic-backdrop hidden fixed inset-0 z-40 bg-black/35"
        />
      )}

      {/* vic-sidebar: 모바일(html.vic-mobile)에서는 globals.css가 숨기고, vic-open일 때 오버레이로 띄운다 */}
      <aside
        className={`vic-sidebar ${menuOpen ? 'vic-open' : ''} flex w-48 shrink-0 flex-col border-r border-line bg-white`}
      >
        <nav className="flex-1 overflow-y-auto p-2">
          <button
            onClick={() => select(MONITOR.ticker)}
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

          <button
            onClick={() => select(PORTFOLIO.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === PORTFOLIO.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{PORTFOLIO.name}</span>
            <span
              className={`block text-[11px] ${
                active === PORTFOLIO.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {PORTFOLIO.desc}
            </span>
          </button>

          <div className="my-2 border-t border-line" />

          {stocks.map((s) => {
            const on = s.ticker === active;
            return (
              <button
                key={s.ticker}
                onClick={() => select(s.ticker)}
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
          <Link
            href="/"
            className="text-[12px] text-muted hover:text-navy hover:underline"
          >
            ← 홈
          </Link>
        </div>
      </aside>

      {/* key를 주어 탭 전환 시 iframe이 새로 마운트되도록 한다(스크롤 위치 초기화) */}
      <iframe
        key={active}
        src={`/reports/${active}.html`}
        title={`${active} 분석 보고서`}
        className="h-full flex-1 border-0"
      />

      {/* vic-home-fab: 사이드바가 숨겨지는 모바일에서만 노출되는 홈 버튼 (globals.css에서 제어) */}
      <Link
        href="/"
        aria-label="홈으로"
        className="vic-home-fab hidden fixed bottom-5 right-5 z-50 h-12 w-12 items-center justify-center rounded-full bg-navy text-[18px] text-white shadow-soft"
      >
        ←
      </Link>
    </div>
  );
}
