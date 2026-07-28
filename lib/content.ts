import fs from 'node:fs';
import path from 'node:path';
import matter from 'gray-matter';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeStringify from 'rehype-stringify';

// 분석 문서는 DB가 아니라 content/ 폴더의 마크다운 파일이 원본이다.
// 이유: 문서가 곧 상품이고, git 히스토리가 곧 개정 이력이 된다. DB는 로그인·결제가 필요해지면 그때.

const STOCKS_DIR = path.join(process.cwd(), 'content', 'stocks');

/** 최종 판단 — 체크리스트 결론 섹션의 "매수 / 관망 / 패스"와 1:1 대응 */
export type Verdict = '매수' | '관망' | '패스';

export interface StockMeta {
  ticker: string; // 파일명이자 URL 경로 (예: GOOGL)
  name: string; // 한글 종목명
  date: string; // 분석일 (YYYY-MM-DD)
  verdict: Verdict;
  price: number; // 분석 시점 주가
  intrinsicValue: number; // 기본 시나리오 내재가치
  targetPrice: number; // 목표 매수가 (기본 −20%)
  summary: string; // 한 줄 근거 요약
}

export interface StockDoc extends StockMeta {
  html: string; // 렌더된 본문
}

/** 안전마진 = (내재가치 − 주가) ÷ 내재가치. 템플릿 4단계와 동일한 공식. */
export function marginOfSafety(meta: StockMeta): number {
  return ((meta.intrinsicValue - meta.price) / meta.intrinsicValue) * 100;
}

function parseFile(fileName: string) {
  const filePath = path.join(STOCKS_DIR, fileName);
  const raw = fs.readFileSync(filePath, 'utf-8');
  const { data, content } = matter(raw);

  const meta: StockMeta = {
    ticker: path.basename(fileName, '.md'),
    name: String(data.name ?? ''),
    date: String(data.date ?? ''),
    verdict: (data.verdict ?? '관망') as Verdict,
    price: Number(data.price ?? 0),
    intrinsicValue: Number(data.intrinsicValue ?? 0),
    targetPrice: Number(data.targetPrice ?? 0),
    summary: String(data.summary ?? ''),
  };

  return { meta, content };
}

/** 목록용 — 본문은 파싱하지 않는다(최신 분석일 우선 정렬) */
export function getAllStocks(): StockMeta[] {
  if (!fs.existsSync(STOCKS_DIR)) return [];

  return fs
    .readdirSync(STOCKS_DIR)
    .filter((f) => f.endsWith('.md'))
    .map((f) => parseFile(f).meta)
    .sort((a, b) => b.date.localeCompare(a.date));
}

/** 상세용 — 본문을 HTML로 변환해서 함께 반환 */
export async function getStock(ticker: string): Promise<StockDoc | null> {
  const filePath = path.join(STOCKS_DIR, `${ticker}.md`);
  if (!fs.existsSync(filePath)) return null;

  const { meta, content } = parseFile(`${ticker}.md`);

  // 분석 문서는 표와 체크박스가 핵심이라 GFM 필수.
  // rehypeRaw: 문서 안에 직접 쓴 HTML(각주·강조 블록)을 살리기 위함.
  const file = await unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeRaw)
    .use(rehypeStringify)
    .process(content);

  // 표는 열이 많아 모바일에서 넘친다. 각 표만 가로 스크롤되도록 감싼다
  // (본문 전체를 스크롤시키면 읽기가 나빠진다).
  const html = String(file).replace(
    /<table>([\s\S]*?)<\/table>/g,
    '<div class="vic-table-wrap"><table>$1</table></div>',
  );

  return { ...meta, html };
}
