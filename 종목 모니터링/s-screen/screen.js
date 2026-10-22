// S급 1단계 기계적 스크린 — SEC XBRL companyfacts 기반
// 규칙 원본: 02.진입과_청산_원칙.md §1 (2026-10-22 확정)
//  ① ROIC(현금 미차감) 20%↑ 10년  ④ 희석 EPS 10년 감소 없음(코로나 1년만 예외)  ⑤ 경기순환 숫자 기준
//  + 3단계 ⚠️ 사전 점검: 장기부채÷순이익 4배↑, FCF−SBC 3년 평균 80% 미만, 희석주식수 증가
// 해자·단계별 ⚠️는 자동 판정 불가 → 2단계(사람)에서
const fs = require('fs');
const UA = { 'User-Agent': 'valueInvestingChecklist research bot' }; // 개인정보 넣지 않음
const uni = JSON.parse(fs.readFileSync('universe.json', 'utf8'));
const CACHE = 'cache';
if (!fs.existsSync(CACHE)) fs.mkdirSync(CACHE);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function get(url, file) {
  if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, 'utf8'));
  for (let i = 0; i < 3; i++) {
    const r = await fetch(url, { headers: UA });
    if (r.status === 404) return null;
    if (r.ok) { const j = await r.json(); fs.writeFileSync(file, JSON.stringify(j)); return j; }
    await sleep(2000 * (i + 1));
  }
  return null;
}

const days = (a, b) => (new Date(b) - new Date(a)) / 864e5;

// 연간(flow) 값: 10-K 계열, 기간 350~380일, 기간말별 최신 제출값(분할·재작성 반영)
function flow(f, tags, unit = 'USD') {
  const out = {};
  for (const tag of tags) {
    const u = f[tag]?.units?.[unit];
    if (!u) continue;
    const best = {};
    for (const x of u) {
      if (!/^(10-K|20-F)/.test(x.form) || !x.start) continue;
      const d = days(x.start, x.end);
      if (d < 350 || d > 380) continue;
      if (!best[x.end] || x.filed > best[x.end].filed) best[x.end] = x;
    }
    for (const e in best) if (out[e] === undefined) out[e] = best[e].val; // 앞 태그 우선
  }
  return out;
}
// 시점(instant) 값
function inst(f, tags, unit = 'USD') {
  const out = {};
  for (const tag of tags) {
    const u = f[tag]?.units?.[unit];
    if (!u) continue;
    const best = {};
    for (const x of u) {
      if (!/^(10-K|20-F)/.test(x.form) || x.start) continue;
      if (!best[x.end] || x.filed > best[x.end].filed) best[x.end] = x;
    }
    for (const e in best) if (out[e] === undefined) out[e] = best[e].val;
  }
  return out;
}
// 같은 회계연도말을 ±10일 오차로 찾기 (52/53주 회계연도 대응)
function near(obj, end) {
  if (obj[end] !== undefined) return obj[end];
  for (const k in obj) if (Math.abs(days(k, end)) <= 10) return obj[k];
  return undefined;
}
function pairs(f, tags, unit) {
  const byAcc = {};
  for (const tag of tags) {
    const u = f[tag]?.units?.[unit];
    if (!u) continue;
    for (const x of u) {
      if (!/^(10-K|20-F)/.test(x.form) || !x.start) continue;
      const d = days(x.start, x.end);
      if (d < 350 || d > 380) continue;
      (byAcc[x.accn] ||= { filed: x.filed, v: {} }).v[x.end] ??= x.val;
    }
    if (Object.keys(byAcc).length) break; // 첫 태그만
  }
  // a→b 비율: 둘 다 담은 보고서 중 가장 최근 것
  return (a, b) => {
    let best = null;
    for (const k in byAcc) {
      const g = byAcc[k], va = near(g.v, a), vb = near(g.v, b);
      if (va === undefined || vb === undefined) continue;
      if (!best || g.filed > best.filed) best = { filed: g.filed, va, vb };
    }
    return best;
  };
}
const covid = (end) => end >= '2020-03-31' && end <= '2021-06-30';

function analyze(t, cf) {
  const f = cf?.facts?.['us-gaap'];
  if (!f) return { t, cls: '데이터없음', why: 'us-gaap 없음(IFRS·20-F 등)' };
  const NI = flow(f, ['NetIncomeLoss', 'ProfitLoss']);
  const OP = flow(f, ['OperatingIncomeLoss']);
  const PT = flow(f, ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments', 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic']);
  const TX = flow(f, ['IncomeTaxExpenseBenefit']);
  const INT = flow(f, ['InterestExpense', 'InterestExpenseNonoperating', 'InterestExpenseDebt']);
  const EPS = flow(f, ['EarningsPerShareDiluted', 'EarningsPerShareBasicAndDiluted'], 'USD/shares');
  const CFO = flow(f, ['NetCashProvidedByUsedInOperatingActivities', 'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations']);
  const CAPEX = flow(f, ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets']);
  const SBC = flow(f, ['ShareBasedCompensation', 'AllocatedShareBasedCompensationExpense']);
  const SH = flow(f, ['WeightedAverageNumberOfDilutedSharesOutstanding'], 'shares');
  const EQ = inst(f, ['StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'StockholdersEquity']);
  const LTD = inst(f, ['LongTermDebt', 'LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities', 'DebtLongtermAndShorttermCombinedAmount']);
  const LTDN = inst(f, ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations']);
  const LTDC = inst(f, ['LongTermDebtCurrent', 'LongTermDebtAndCapitalLeaseObligationsCurrent']);
  const CP = inst(f, ['CommercialPaper']);
  const STB = inst(f, ['ShortTermBorrowings']);

  // 최근 11개 회계연도말 (EPS 전년비 10개용)
  const ends = Object.keys(NI).filter((e) => e >= '2014-06-01').sort();
  const fy = [];
  for (const e of ends) if (!fy.length || days(fy[fy.length - 1], e) > 300) fy.push(e);
  const last = fy.slice(-11);
  if (last.length < 6 || last[last.length - 1] < '2025-01-01') return { t, cls: '데이터부족', why: `연간 ${last.length}개, 최신 ${last[last.length - 1] || '-'}` };

  const notes = [];
  let debtTagMissing = false;
  const debtAt = (e) => {
    let d = near(LTD, e);
    if (d === undefined) {
      const a = near(LTDN, e), b = near(LTDC, e);
      if (a === undefined && b === undefined) { debtTagMissing = true; d = 0; } else d = (a || 0) + (b || 0);
    }
    return d + (near(CP, e) || 0) + (near(STB, e) || 0);
  };

  // ① ROIC 10년
  const roic = [];
  for (const e of last.slice(-10)) {
    let op = near(OP, e);
    const pt = near(PT, e), tx = near(TX, e);
    if (op === undefined && pt !== undefined) { op = pt + (near(INT, e) || 0); if (!notes.includes('영업이익=세전+이자(대체)')) notes.push('영업이익=세전+이자(대체)'); }
    const eq = near(EQ, e);
    if (op === undefined || eq === undefined) { roic.push({ e, v: null }); continue; }
    let rate = pt > 0 && tx !== undefined ? tx / pt : 0.21;
    rate = Math.min(Math.max(rate, 0), 0.5);
    const ic = eq + debtAt(e);
    roic.push({ e, v: ic > 0 ? (op * (1 - rate)) / ic : NaN });
  }
  if (debtTagMissing) notes.push('부채 태그 일부 없음(0 처리 — ROIC 과대 가능)');
  const rv = roic.map((x) => x.v);
  const roicMin = Math.min(...rv.filter((v) => v !== null && !isNaN(v)));
  const roicNeg = rv.some((v) => isNaN(v));
  const roicGap = rv.filter((v) => v === null).length;

  // ④ EPS 10년
  const eps = last.map((e) => ({ e, v: near(EPS, e) }));
  const dec = [];
  const ep = pairs(f, ['EarningsPerShareDiluted', 'EarningsPerShareBasicAndDiluted'], 'USD/shares');
  for (let i = 1; i < eps.length; i++) {
    const p = ep(eps[i - 1].e, eps[i].e);
    const a = p ? p.va : eps[i - 1].v, b = p ? p.vb : eps[i].v;
    if (a === undefined || b === undefined) continue;
    if (b < a) dec.push({ e: eps[i].e, pct: a > 0 ? (b / a - 1) * 100 : -999, cov: covid(eps[i].e) });
  }
  const covDec = dec.filter((d) => d.cov);
  const nonCov = dec.filter((d) => !d.cov).concat(covDec.slice(1)); // 코로나 예외는 1년만
  const epsGap = eps.filter((x) => x.v === undefined).length;

  // ⑤ 경기순환: FY2007~2010 고점 대비 저점, 10년 내 −20% 감익(코로나 제외)
  const OPX = { ...OP };
  for (const e in PT) if (OPX[e] === undefined) OPX[e] = PT[e] + (INT[e] || 0);
  const opAll = Object.keys(OPX).sort();
  const gfc = opAll.filter((e) => e >= '2007-01-01' && e <= '2011-06-30').map((e) => ({ e, v: OPX[e] }));
  let gfcDrop = null;
  if (gfc.length >= 2) {
    let peak = -Infinity, drop = 0;
    for (const x of gfc) { if (x.v > peak) peak = x.v; else if (peak > 0) drop = Math.min(drop, x.v / peak - 1); }
    gfcDrop = drop * 100;
  }
  const opL = last.map((e) => near(OPX, e));
  const opDrops = [];
  for (let i = 1; i < last.length; i++) if (opL[i - 1] > 0 && opL[i] !== undefined && opL[i] / opL[i - 1] - 1 <= -0.2 && !covid(last[i])) opDrops.push(`${last[i].slice(0, 4)} ${((opL[i] / opL[i - 1] - 1) * 100).toFixed(0)}%`);

  // 3단계 ⚠️ 사전 점검
  const le = last[last.length - 1];
  const ni = NI[le];
  const debtNI = ni > 0 ? debtAt(le) / ni : Infinity;
  const l3 = last.slice(-3);
  let fs3 = 0, ni3 = 0, fcfOk = true;
  for (const e of l3) { const c = near(CFO, e), k = near(CAPEX, e), s = near(SBC, e), n = near(NI, e); if (c === undefined || n === undefined) { fcfOk = false; continue; } fs3 += c - (k || 0) - (s || 0); ni3 += n; }
  const fcfR = fcfOk && ni3 > 0 ? fs3 / ni3 : null;
  const shp = pairs(f, ['WeightedAverageNumberOfDilutedSharesOutstanding'], 'shares');
  let shR = 1, shOk = true;
  for (let i = 1; i < last.length; i++) { const p = shp(last[i - 1], last[i]); if (!p || !p.va) { shOk = false; break; } shR *= p.vb / p.va; }
  const shUp = shOk ? shR - 1 : null;
  const warn = [];
  if (debtNI >= 4) warn.push(`부채÷순이익 ${debtNI.toFixed(1)}배`);
  if (fcfR !== null && fcfR < 0.8) warn.push(`FCF−SBC ${(fcfR * 100).toFixed(0)}%`);
  if (shUp !== null && shUp > 0.05) warn.push(`희석주식 +${(shUp * 100).toFixed(0)}%`);

  // 판정
  const fails = [], reviews = [];
  if (last.length < 11) reviews.push(`연간 데이터 ${last.length}개(10년 미만)`);
  if (roicMin < 0.2) (roicMin >= 0.18 ? reviews : fails).push(`ROIC 최저 ${(roicMin * 100).toFixed(1)}%`);
  if (roicNeg) reviews.push('투하자본 음수(ROIC 산식 불능)');
  if (roicGap) reviews.push(`ROIC 결측 ${roicGap}년`);
  for (const d of nonCov) (d.pct > -1 ? reviews : fails).push(`EPS ${d.e.slice(0, 7)} ${d.pct.toFixed(1)}%`);
  if (epsGap) reviews.push(`EPS 결측 ${epsGap}년`);
  const soft = [];
  if (gfcDrop !== null && gfcDrop <= -30) soft.push(`FY07~10 영업이익 ${gfcDrop.toFixed(0)}%`);
  else if (gfcDrop !== null && gfcDrop <= -25) reviews.push(`FY07~10 영업이익 ${gfcDrop.toFixed(0)}%(경계)`);
  if (gfcDrop === null) reviews.push('FY07~10 데이터 없음');
  if (opDrops.length) soft.push(`영업이익 −20%↓ ${opDrops.join(', ')}`);
  if (warn.length >= 2) fails.push(`3단계 ⚠️ ${warn.length}개(조건부)`);

  const cls = fails.length ? '탈락' : soft.length || reviews.length ? '확인필요' : '통과';
  reviews.push(...soft.map((x) => x + '(일회성 미제거 — 원문 확인)'));
  return {
    t, cls, fy: `${last[0].slice(0, 7)}~${le.slice(0, 7)}`, roicMin: +(roicMin * 100).toFixed(1),
    roic: rv.map((v) => (v === null ? null : isNaN(v) ? 'neg' : +(v * 100).toFixed(1))),
    eps: eps.map((x) => x.v), covidDec: covDec.map((d) => `${d.e.slice(0, 7)} ${d.pct.toFixed(1)}%`),
    gfcDrop: gfcDrop === null ? null : +gfcDrop.toFixed(1), debtNI: +debtNI.toFixed(2), fcfSbc: fcfR === null ? null : +(fcfR * 100).toFixed(0),
    warn, fails, reviews, notes,
  };
}

(async () => {
  const res = [];
  let i = 0;
  for (const { t, cik } of uni) {
    const c = String(cik).padStart(10, '0');
    const file = `${CACHE}/${c}.json`;
    const had = fs.existsSync(file);
    let cf = null;
    try { cf = await get(`https://data.sec.gov/api/xbrl/companyfacts/CIK${c}.json`, file); } catch (e) { cf = null; }
    let r;
    try { r = cf ? analyze(t, cf) : { t, cls: '데이터없음', why: 'companyfacts 없음' }; } catch (e) { r = { t, cls: '오류', why: String(e).slice(0, 120) }; }
    res.push(r);
    if (!had) await sleep(150); // SEC 초당 10회 제한 준수
    if (++i % 50 === 0) console.log(i, '/', uni.length);
  }
  fs.writeFileSync('result.json', JSON.stringify(res, null, 1));
  const cnt = {};
  res.forEach((r) => (cnt[r.cls] = (cnt[r.cls] || 0) + 1));
  console.log('완료', cnt);
})();
