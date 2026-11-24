'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';

// 메인 랜딩 — 좌우 스와이프로 두 장을 넘겨 본다(타이머 없음).
//   1장: 투자 원칙 문구(Just Keep Buying) + 보고서 진입 버튼
//   2장: 시장이 크게 흔들릴 때 읽을 문장(2026-11-24 정리)
// 데스크톱에서는 아래 점을 눌러 넘긴다.

const STEADY_LINES: { head: string; body: string }[] = [
  { head: '이 돈은 20년 뒤에 쓴다.', body: '생활비는 직장에서 나오고, 이 계좌에서 꺼낼 일은 없다.' },
  { head: '나는 계속 사는 사람이다.', body: '사업 잉여금이 생기면 더 넣는다. 지금 하락은 내게 할인이다.' },
  {
    head: '이 하락은 미리 알고 있던 일이다.',
    body: '−10%는 거의 매년, −20%는 몇 년에 한 번, −35%는 10년에 한 번쯤 온다.',
  },
  { head: '원화 말고 퍼센트로 본다.', body: '"−8,000만"이 아니라 "−20%, 몇 년에 한 번 오는 일"이다.' },
  {
    head: "내 계획에 '팔기'는 없다.",
    body: '가격이 떨어졌다는 건 팔 이유가 아니다. 미국 경제 전체가 망한다는 증거가 있을 때만 다시 생각한다.',
  },
  {
    head: '나는 AI 혁명을 믿는다.',
    body: '20년 개발하면서 직접 본 것이다. 그 열매는 몇 달이 아니라 몇 년, 십수 년에 걸쳐 온다.',
  },
  {
    head: '나는 이미 한 번 겪어 봤다.',
    body: '400~500만이면 엄청 아플 줄 알았는데, 막상 6~700만에도 괜찮았다(2026-11). 생각보다 나는 단단하다.',
  },
  {
    head: '일본은 34년, 미국은 길어야 십수 년이었다.',
    body: '그래서 한 나라가 아닌 미국 전체 지수를 골랐고, 시간은 내 편이다.',
  },
  {
    head: "많이 힘들면 '팔기' 대신 '섞기'.",
    body: '80/20(453850)으로 변동성을 줄이는 길이 이미 계획에 있다.',
  },
];

function PrinciplesSlide() {
  return (
    <div className="flex flex-col items-center">
      <h1 className="text-4xl font-bold text-navy">Just Keep Buying</h1>

      <ul className="mt-9 space-y-3 text-[17px] leading-relaxed text-ink-2">
        <li>🌱 일찍 시작하라</li>
        <li>🎯 타이밍을 맞추려 하지 마라</li>
        <li>🐢 서두르지 마라, 천천히 가라</li>
        <li>🌳 오랫동안 유지하라</li>
      </ul>

      <Link
        href="/dashboard"
        className="mt-11 rounded-card bg-navy px-7 py-3 text-[15px] font-bold text-white shadow-soft transition-colors hover:bg-navy-2"
      >
        보고서 보러가기 →
      </Link>
    </div>
  );
}

function SteadySlide() {
  return (
    <div className="flex w-full max-w-xl flex-col items-center">
      <h2 className="text-2xl font-bold text-navy">흔들릴 때 읽을 것</h2>
      <ol className="mt-6 space-y-3 text-left">
        {STEADY_LINES.map((l, i) => (
          <li key={i} className="flex gap-3 text-[15px] leading-snug">
            <span className="w-5 shrink-0 text-right font-bold text-navy-soft">{i + 1}.</span>
            <span>
              <b className="text-ink">{l.head}</b> <span className="text-ink-2">{l.body}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

const SLIDES = [PrinciplesSlide, SteadySlide];

export default function HomePage() {
  const trackRef = useRef<HTMLDivElement>(null);
  const [idx, setIdx] = useState(0);

  // 가로 스크롤 위치로 현재 장을 계산 (손가락으로 넘겨도, 점을 눌러도 동일하게 갱신)
  const onScroll = () => {
    const el = trackRef.current;
    if (!el) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== idx) setIdx(i);
  };

  const go = (i: number) => {
    const el = trackRef.current;
    if (!el) return;
    el.scrollTo({ left: i * el.clientWidth, behavior: 'smooth' });
  };

  return (
    <main className="flex h-full flex-col">
      {/* 좌우로 스와이프하면 장이 넘어간다 — CSS scroll-snap(브라우저 기본 터치 스크롤) 사용 */}
      <div
        ref={trackRef}
        onScroll={onScroll}
        className="flex flex-1 snap-x snap-mandatory overflow-x-auto overflow-y-hidden overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {SLIDES.map((Slide, i) => (
          <section
            key={i}
            aria-hidden={i !== idx}
            className="flex h-full w-full shrink-0 snap-center snap-always flex-col items-center overflow-y-auto px-6 py-10 text-center"
          >
            <div className="my-auto flex w-full flex-col items-center">
              <Slide />
            </div>
          </section>
        ))}
      </div>

      <div className="flex justify-center gap-2 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-2">
        {SLIDES.map((_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => go(i)}
            aria-label={`${i + 1}번째 화면 보기`}
            className={`h-2.5 rounded-full transition-all ${
              i === idx ? 'w-6 bg-navy' : 'w-2.5 bg-navy-soft/40 hover:bg-navy-soft'
            }`}
          />
        ))}
      </div>
    </main>
  );
}
