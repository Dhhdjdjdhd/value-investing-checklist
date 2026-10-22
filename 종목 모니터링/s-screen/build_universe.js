// 스크린 대상 유니버스 생성 — S&P 500(위키백과) + 품질우주 표 티커 → SEC CIK 매핑 → universe.json
// 실행: node build_universe.js  (그다음 node screen.js)
const fs = require('fs');
const UA = { 'User-Agent': 'valueInvestingChecklist research bot' }; // 개인정보 넣지 않음
const QU = '../../02.종목분석/품질우주_20261021.md';

(async () => {
  const tk = await (await fetch('https://www.sec.gov/files/company_tickers.json', { headers: UA })).json();
  const html = await (await fetch('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', { headers: { 'User-Agent': 'Mozilla/5.0' } })).text();

  // 위키백과 constituents 표의 첫 열(티커)
  const tb = html.slice(html.indexOf('id="constituents"'));
  const sp = [];
  for (const r of tb.slice(0, tb.indexOf('</table>')).split('<tr').slice(2)) {
    const m = r.match(/<td[^>]*>\s*<a[^>]*>([A-Z.]+)<\/a>/);
    if (m) sp.push(m[1].replace('.', '-'));
  }
  // 품질우주 문서 표의 첫 열 티커
  const qu = [...fs.readFileSync(QU, 'utf8').matchAll(/^\| \**([A-Z]{1,5})\** \|/gm)].map((m) => m[1]);

  const cik = {};
  for (const k in tk) cik[tk[k].ticker] = tk[k].cik_str;
  const all = [...new Set([...sp, ...qu])];
  const ok = all.filter((t) => cik[t]).map((t) => ({ t, cik: cik[t] }));
  fs.writeFileSync('universe.json', JSON.stringify(ok));
  console.log(`S&P500 ${sp.length} · 품질우주 ${qu.length} → ${ok.length}종목 (CIK 미매핑: ${all.filter((t) => !cik[t]).join(',') || '없음'})`);
})();
