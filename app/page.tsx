import Link from 'next/link';

// 메인 랜딩 — 투자 원칙 문구(Just Keep Buying)를 먼저 보여주고,
// 보고서 탭 화면(/dashboard)으로 진입하는 구조.
export default function HomePage() {
  return (
    <main className="flex h-full flex-col items-center justify-center px-6 text-center">
      <h1 className="text-4xl font-bold text-navy">Just Keep Buying</h1>

      <ul className="mt-9 space-y-3 text-[17px] leading-relaxed text-ink-2">
        <li>🌱 일찍 시작하라</li>
        <li>🎯 타이밍을 맞추려 하지 마라</li>
        <li>🌳 오랫동안 유지하라</li>
      </ul>

      <Link
        href="/dashboard"
        className="mt-11 rounded-card bg-navy px-7 py-3 text-[15px] font-bold text-white shadow-soft transition-colors hover:bg-navy-2"
      >
        보고서 보러가기 →
      </Link>
    </main>
  );
}
