'use client';

import { useEffect, useState } from 'react';
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

// 기술주 ETF 20년 보유 비교 (360750·133690·381170) — 시뮬레이터 포함 고정 탭
const TECH20 = { ticker: 'TECH20', name: '기술주 20년', desc: '360750·133690·381170' };

// 진입대기 감시판 — 품질 등급별 목표가 목록 (2026-10-21 품질 우주 1회차)
const WATCH = { ticker: 'WATCH', name: '진입대기 16', desc: '등급별 목표가 감시판' };

// 종목 탭 = 진입대기 14종목 + 완주 분석 2종목(MSFT·GOOGL) 보고서(public/reports/<티커>.html). 등급 순(S → A → 일반)
// 종전에는 02.종목분석 md 목록으로 만들었으나, 시뮬레이터 재시작(2026-10-21)으로 보고서를 이 14개로 교체했다
const WATCHLIST = [
  { ticker: 'MA', name: '마스터카드', grade: 'S' },
  { ticker: 'COST', name: '코스트코', grade: 'S' },
  { ticker: 'ADP', name: 'ADP', grade: 'S' },
  { ticker: 'V', name: '비자', grade: 'A' },
  { ticker: 'AAPL', name: '애플', grade: 'A' },
  { ticker: 'RACE', name: '페라리', grade: 'A' },
  { ticker: 'PG', name: 'P&G', grade: 'A' },
  { ticker: 'KO', name: '코카콜라', grade: 'A' },
  { ticker: 'ISRG', name: '인튜이티브 서지컬', grade: 'A' },
  { ticker: 'MSFT', name: '마이크로소프트', grade: 'A' },
  { ticker: 'META', name: '메타', grade: '일반' },
  { ticker: 'GOOGL', name: '알파벳', grade: '일반' },
  { ticker: 'ASML', name: 'ASML', grade: '일반' },
  { ticker: 'CTAS', name: '신타스', grade: '일반' },
  { ticker: 'MCO', name: '무디스', grade: '일반' },
  { ticker: 'CDNS', name: '케이던스', grade: '일반' },
];

// 데스크톱 사이드바 숨김 상태 저장 키 — 새로고침 후에도 유지
const SIDEBAR_KEY = 'vic-sidebar-hidden';

export default function ReportTabs({ stocks }: { stocks: StockMeta[] }) {
  const [active, setActive] = useState(MONITOR.ticker);
  // 모바일 햄버거 메뉴 열림 여부 — 데스크톱에서는 버튼이 숨겨져 항상 false
  const [menuOpen, setMenuOpen] = useState(false);
  // 데스크톱 사이드바 숨김 여부 — 모바일에서는 CSS가 별도 제어하므로 영향 없음
  const [collapsed, setCollapsed] = useState(false);

  // 저장된 숨김 상태 복원 (SSR 불일치 방지를 위해 마운트 후 읽는다)
  useEffect(() => {
    try {
      if (localStorage.getItem(SIDEBAR_KEY) === '1') setCollapsed(true);
    } catch {}
  }, []);

  const toggleSidebar = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0');
      } catch {}
      return next;
    });
  };

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

      {/* vic-expand-btn: 데스크톱에서 사이드바를 숨겼을 때만 노출되는 펼침 버튼 (모바일은 globals.css가 감춤) */}
      {collapsed && (
        <button
          onClick={toggleSidebar}
          aria-label="메뉴 보이기"
          title="메뉴 보이기"
          className="vic-expand-btn fixed left-3 top-3 z-30 flex h-9 w-9 items-center justify-center rounded-full bg-navy text-[15px] text-white shadow-soft opacity-60 transition-opacity hover:opacity-100"
        >
          ☰
        </button>
      )}

      {/* vic-sidebar: 모바일(html.vic-mobile)에서는 globals.css가 숨기고, vic-open일 때 오버레이로 띄운다.
          데스크톱에서는 collapsed일 때 hidden (모바일 vic-open 규칙이 더 구체적이라 모바일 메뉴는 영향 없음) */}
      <aside
        className={`vic-sidebar ${menuOpen ? 'vic-open' : ''} ${collapsed ? 'hidden' : 'flex'} w-48 shrink-0 flex-col border-r border-line bg-white`}
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

          <button
            onClick={() => select(TECH20.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === TECH20.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{TECH20.name}</span>
            <span
              className={`block text-[11px] ${
                active === TECH20.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {TECH20.desc}
            </span>
          </button>

          <div className="my-2 border-t border-line" />

          <button
            onClick={() => select(WATCH.ticker)}
            className={`mb-0.5 block w-full rounded px-3 py-2.5 text-left transition-colors ${
              active === WATCH.ticker
                ? 'bg-navy text-white'
                : 'text-ink-2 hover:bg-paper-2 hover:text-navy'
            }`}
          >
            <span className="block text-[14px] font-bold">{WATCH.name}</span>
            <span
              className={`block text-[11px] ${
                active === WATCH.ticker ? 'text-white/70' : 'text-muted'
              }`}
            >
              {WATCH.desc}
            </span>
          </button>

          {WATCHLIST.map((s) => {
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
                  {s.ticker} · 등급 {s.grade}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="space-y-2 border-t border-line p-3">
          {/* 지금 보는 탭이 분석 종목일 때만 노출 — 화면의 HTML 보고서는 시각 자료이고,
              판정의 원본은 02.종목분석/*.md 체크리스트다. 원본으로 가는 유일한 통로. */}
          {stocks.some((s) => s.ticker === active) && (
            <Link
              href={`/stocks/${active}`}
              className="block text-[12px] font-bold text-navy hover:underline"
            >
              체크리스트 원문 →
            </Link>
          )}
          <div className="flex items-center justify-between">
            <Link
              href="/"
              className="text-[12px] text-muted hover:text-navy hover:underline"
            >
              ← 홈
            </Link>
            {/* vic-collapse-btn: 데스크톱 전용 숨기기 버튼 (모바일은 globals.css가 감춤) */}
            <button
              onClick={toggleSidebar}
              title="메뉴 숨기기"
              className="vic-collapse-btn text-[12px] text-muted hover:text-navy hover:underline"
            >
              메뉴 숨기기 ◀
            </button>
          </div>
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
