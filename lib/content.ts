import fs from 'node:fs';
import path from 'node:path';
import matter from 'gray-matter';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeStringify from 'rehype-stringify';

// 분석 문서는 DB가 아니라 마크다운 파일이 원본이다.
// 이유: 문서가 곧 상품이고, git 히스토리가 곧 개정 이력이 된다. DB는 로그인·결제가 필요해지면 그때.
//
// 원본은 02.종목분석/ 하나뿐이다 (2026-08-16 통합).
// 종전에는 content/stocks/에 사본을 두고 손으로 맞췄는데, MSFT의 2026-08-14 점검 로그가
// 사본에 반영되지 않아 사이트가 낡은 결론을 보여주는 일이 실제로 발생했다. 사본은 삭제.

const STOCKS_DIR = path.join(process.cwd(), '02.종목분석');

// 이 폴더에는 스크리닝·후보목록 등 종목 문서가 아닌 파일도 함께 있다.
// frontmatter에 ticker가 있는 파일만 종목 분석으로 취급한다 (파일명 규칙에 의존하지 않는다).
//
// 문서는 통째로 공개한다 — 매매 실행 기록(6단계)·청산 기록(8단계)·수정 이력까지.
// 판단의 근거와 그 판단이 틀렸을 때의 수정 과정이 함께 보이는 것이 이 문서의 가치다.

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
  // 원본은 윈도우에서 작성돼 CRLF다. 줄바꿈을 먼저 통일해 둔다 —
  // 자바스크립트 정규식의 `.`은 \r에 매칭되지 않아, CRLF 상태로는 아래 섹션 판별이 조용히 실패한다.
  const raw = fs.readFileSync(filePath, 'utf-8').replace(/\r\n/g, '\n');
  const { data, content } = matter(raw);

  // ticker가 없으면 종목 분석 문서가 아니다 (스크리닝 메모 등).
  if (!data.ticker) return null;

  const meta: StockMeta = {
    ticker: String(data.ticker),
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

/** 폴더 안의 종목 문서만 골라 파싱한다 (파일명이 한글·날짜라 티커로 직접 찾을 수 없다) */
function readAllDocs() {
  if (!fs.existsSync(STOCKS_DIR)) return [];

  return fs
    .readdirSync(STOCKS_DIR)
    .filter((f) => f.endsWith('.md'))
    .map(parseFile)
    .filter((d): d is NonNullable<typeof d> => d !== null);
}

/** 목록용 — 본문은 파싱하지 않는다(최신 분석일 우선 정렬) */
export function getAllStocks(): StockMeta[] {
  return readAllDocs()
    .map((d) => d.meta)
    .sort((a, b) => b.date.localeCompare(a.date));
}

/** 상세용 — 본문을 HTML로 변환해서 함께 반환 */
export async function getStock(ticker: string): Promise<StockDoc | null> {
  const doc = readAllDocs().find((d) => d.meta.ticker === ticker);
  if (!doc) return null;

  const { meta } = doc;

  // 원본 문서 첫 줄의 H1은 페이지 헤더와 중복되므로 뺀다.
  const content = doc.content.replace(/^\s*#\s+.*\n/, '');

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
