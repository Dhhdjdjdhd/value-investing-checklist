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
      <body className="h-full overflow-hidden">{children}</body>
    </html>
  );
}
