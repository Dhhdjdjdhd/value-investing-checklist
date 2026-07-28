import type { Config } from 'tailwindcss';

// 가치투자 체크리스트 디자인 토큰
// 네이비(신뢰·절제) · 아이보리(가독) · 골드(강조)
// 판정 3색(pass/warn/fail)은 체크리스트의 ✅/⚠️/❌ 와 1:1 대응 — 임의로 늘리지 말 것
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: '#1B2A41', 2: '#0F1B2D', soft: '#3D5372' }, // 신뢰·절제
        paper: { DEFAULT: '#FBFAF7', 2: '#F2EFE9' }, // 본문 배경 (장문 가독)
        ink: { DEFAULT: '#1F2933', 2: '#4A5561' }, // 본문 텍스트
        muted: '#7B8794',
        line: '#E3E0D9',
        gold: { DEFAULT: '#B8912F', soft: '#D9BE72' }, // 강조 (남용 금지)
        // 판정 3색 — 체크리스트 판정과 고정 대응
        pass: '#2F7A55', // ✅ 통과
        warn: '#B07A19', // ⚠️ 조건부 통과
        fail: '#A8362F', // ❌ 탈락
      },
      fontFamily: {
        sans: ['Pretendard', 'sans-serif'],
        serif: ['"Noto Serif KR"', 'serif'],
      },
      borderRadius: {
        card: '14px',
      },
      boxShadow: {
        soft: '0 12px 32px -18px rgba(27,42,65,.28)',
      },
    },
  },
  plugins: [],
};

export default config;
