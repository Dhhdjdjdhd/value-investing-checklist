import { NextResponse } from 'next/server';

// 헬스체크 — 외부 모니터링(UptimeRobot)이 주기적으로 호출해 무료 플랜 슬립을 막는다.
// 정적 생성되면 항상 같은 응답이 캐시되어 의미가 없으므로 강제로 동적 처리한다.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET() {
  // toISOString()은 UTC라 KST와 9시간 어긋난다 — 로그를 눈으로 볼 때 헷갈리므로 KST로 찍는다
  const now = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });

  return NextResponse.json({
    status: 'ok',
    time: now,
    uptime: Math.floor(process.uptime()), // 초 — 계속 작은 값이면 재시작 반복 중이라는 뜻
  });
}
