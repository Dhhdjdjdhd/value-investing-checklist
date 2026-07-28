// 헬스체크 — 두 가지 용도로 쓴다.
// ① Render가 배포 성공 여부를 판단 (render.yaml의 healthCheckPath)
// ② 외부 모니터링(UptimeRobot 등)이 주기적으로 호출해 무료 플랜 슬립을 방지
//
// 정적 생성되면 항상 같은 응답이 캐시되어 ②가 무의미해지므로 강제로 동적 처리한다.
export const dynamic = 'force-dynamic';

export function GET() {
  // toISOString()은 UTC라 KST와 9시간 어긋난다 — 로그를 눈으로 확인할 때 헷갈리므로 KST로 찍는다
  const now = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });

  return Response.json({
    status: 'ok',
    time: now,
    uptime: Math.floor(process.uptime()), // 초 — 값이 계속 작으면 재시작을 반복 중이라는 뜻
  });
}
