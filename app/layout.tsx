import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '가치투자 체크리스트 — 5단계로 검증한 종목 분석',
  description:
    '사업의 질·경영진·재무·밸류에이션·최종 거부권까지 5단계 체크리스트로 검증한 종목 분석 기록.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 보고서를 화면 가득 띄우기 위해 페이지 자체는 스크롤하지 않는다(스크롤은 iframe 안에서).
  return (
    <html lang="ko" className="h-full">
      <head>
        {/* 실제 모바일 기기 감지 → <html>.vic-mobile (body 렌더 전 실행, momcare 방식).
            모바일에서는 사이드바를 숨겨 S&P500 모니터링 화면만 노출한다. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){var ua=navigator.userAgent||'';var m=(navigator.userAgentData&&navigator.userAgentData.mobile===true)||/iPhone|iPod|Android.*Mobile|Windows Phone|BlackBerry|IEMobile|Opera Mini/i.test(ua);if(m)document.documentElement.classList.add('vic-mobile');})();`,
          }}
        />
      </head>
      <body className="h-full overflow-hidden">{children}</body>
    </html>
  );
}
