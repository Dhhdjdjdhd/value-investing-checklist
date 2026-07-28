import type { Verdict } from '@/lib/content';

// 판정 3색은 tailwind.config.ts의 pass/warn/fail 토큰과 고정 대응한다.
const STYLE: Record<Verdict, string> = {
  매수: 'bg-pass/10 text-pass border-pass/30',
  관망: 'bg-warn/10 text-warn border-warn/30',
  패스: 'bg-fail/10 text-fail border-fail/30',
};

export default function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-[13px] font-bold ${STYLE[verdict]}`}
    >
      {verdict}
    </span>
  );
}
