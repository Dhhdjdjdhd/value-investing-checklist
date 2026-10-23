"""results/screen_now.csv -> public/reports/WATCH.html (개정 체크리스트 v2 선정 20 + 유지 구간 21~30).

기존 WATCH.html의 <head>(스타일)는 그대로 쓰고 본문·데이터·컬럼만 교체한다.
1·2단계 정성 거부권: 00 원칙 §6 '능력범위 밖 목록'에 있는 종목은 제외(VETO).
실행: py src/build_watch.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT.parent / "public" / "reports" / "WATCH.html"
REPORTS = WATCH.parent
VETO = {"ADBE": "능력범위 밖 목록 — 소프트웨어의 AI 대체 속도 (00 §6)"}
KO = {"DPZ": "도미노피자", "BKNG": "부킹홀딩스", "MCK": "맥케슨", "DECK": "데커스", "OTIS": "오티스", "LULU": "룰루레몬",
      "CAH": "카디널헬스", "DDS": "딜라즈", "LII": "레녹스", "ADP": "ADP", "PAYX": "페이첵스", "ADBE": "어도비",
      "IT": "가트너", "ULTA": "울타뷰티", "COR": "센코라", "TSCO": "트랙터서플라이", "TPR": "태피스트리", "AZO": "오토존",
      "CHKP": "체크포인트", "HD": "홈디포", "MEDP": "메드페이스", "QCOM": "퀄컴", "ACN": "액센츄어", "PCAR": "팩카",
      "CMG": "치폴레", "CF": "CF인더스트리스", "WSM": "윌리엄스소노마", "ZTS": "조에티스", "FICO": "페어아이작",
      "MA": "마스터카드", "AAPL": "애플", "COST": "코스트코", "GGG": "그라코", "UI": "유비쿼티"}
GRADE = {"S": "S", "A": "A", "G": "일반"}


def main():
    s = pd.read_csv(ROOT / "results" / "screen_now.csv")
    s = s[~s.ticker.isin(VETO)].head(30).reset_index(drop=True)
    s["v2rank"] = range(1, len(s) + 1)
    rows = []
    for r in s.itertuples():
        rows.append({"rk": r.v2rank, "t": r.ticker, "ko": KO.get(r.ticker, r.ticker), "g": GRADE[r.grade],
                     "roic": round(r.roic_med5, 3), "fy": round(r.fcf_yield, 4), "pe": round(r.pe, 1),
                     "price": round(r.price, 2), "iv": round(r.iv_ps, 2) if pd.notna(r.iv_ps) else None,
                     "nr": 0 if (REPORTS / f"{r.ticker}.html").exists() else 1, "keep": int(r.v2rank > 20)})
    asof = str(s.price_date.iloc[0])
    html = WATCH.read_text(encoding="utf-8")
    head = html[:html.index("<body>")]
    head = head.replace(head[head.index("<title>"):head.index("</title>") + 8],
                        "<title>체크리스트 v2 선정 20 — 품질 관문 + 품질·가치 순위</title>")
    veto_txt = " · ".join(f"{k}({v})" for k, v in VETO.items())
    body = BODY.replace("__ROWS__", json.dumps(rows, ensure_ascii=False)).replace("__ASOF__", asof).replace("__VETO__", veto_txt)
    WATCH.write_text(head + body, encoding="utf-8")
    print(f"WATCH.html: {len(rows)} rows (선정 20 + 유지 구간 {len(rows) - 20}), 가격 {asof}")


BODY = r"""<body>
<div class="wrap" style="max-width:1080px">
<header>
  <div class="kicker">가치투자 체크리스트 v2 · 2026-10-23 백테스트 검증 후 개정 · 정량 선정 20 + 유지 구간 10</div>
  <h1>선정 20 <span style="color:var(--text-muted);font-weight:600">품질 관문 + 품질·가치 순위</span></h1>
  <div class="sub">v2 규칙: ① 3단계 정량 관문 통과(ROIC 5년 중앙값 ≥15%, 순이익 흑자, EPS·매출 5년 증가, 장기부채÷순이익 ≤6) + 경기순환·금융 제외 + 시총 ≥$10B → ② 순위 = ROIC 백분위 + (FCF−SBC)÷시총 백분위 → ③ 상위 20 동일비중, 분기마다 점검, 보유 종목은 30위 안이면 유지. 기본 정렬: 순위. 헤더를 누르면 정렬, 끌어서 놓으면 컬럼 이동.</div>
</header>
<div class="notice">📌 <b>정량 선정 목록이다 — 1·2단계(해자·경영진) 정성 거부권은 별도.</b> 목록 종목도 매수 전 템플릿 1·2단계와 "일시적 vs 구조적" 판별은 그대로 거친다. 정성 거부: __VETO__ → 다음 순위로 대체. <span id="asof" class="muted">현재가 불러오는 중… (표의 값은 __ASOF__ 종가)</span></div>
<section class="card">
  <div class="table-scroll"><table id="t">
    <thead><tr></tr></thead>
    <tbody></tbody>
  </table></div>
  <p class="muted" style="margin-top:10px">흐린 행(21~30위) = 유지 구간: 새로 사지는 않지만 이미 보유 중이면 팔지 않는다. ROIC = 5년 중앙값(02 §1 산식: NOPAT ÷ (자본+차입금), 현금 미차감). FCF수익률 = (영업현금흐름 − 설비투자 − 주식보상비) ÷ 시가총액. PER·FCF수익률은 현재가에 맞춰 다시 계산된다. 엔진 IV = 템플릿 4단계 기본 시나리오의 기계적 근사, 현재가/IV = 현재가가 IV보다 몇 % 높은가(초록 = IV 이하). 참고용이며 v2에서는 진입 조건이 아니다. <button id="wt-reset" class="wt-reset">정렬·컬럼 순서 초기화</button></p>
</section>
<section class="card">
  <h2>왜 바꿨나 <span class="w">2011.04~2026.10 백테스트 · 미국 상장사 · 시점 정확한 SEC 공시값 · 편도 비용 0.1%</span></h2>
  <table>
    <thead><tr><th>전략</th><th>CAGR</th><th>변동성</th><th>Sharpe</th><th>최대낙폭</th></tr></thead>
    <tbody>
      <tr><td><b>체크리스트 v2</b> (이 목록의 규칙)</td><td>15.0%</td><td>14.1%</td><td><b>1.07</b></td><td>−22%</td></tr>
      <tr><td>현행 체크리스트 (목표가 대기·10종목)</td><td>14.1%</td><td>18.5%</td><td>0.81</td><td>−24%</td></tr>
      <tr><td>S&amp;P500 (SPY)</td><td>13.8%</td><td>14.1%</td><td>0.99</td><td>−24%</td></tr>
      <tr><td>대형주 동일비중</td><td>12.3%</td><td>14.8%</td><td>0.86</td><td>−24%</td></tr>
    </tbody>
  </table>
  <p class="muted" style="margin-top:10px">v2는 현행보다 위험이 확실히 낮고(변동성 −4.4%p), S&amp;P500과는 통계적으로 구분되지 않는다(Sharpe 우위 확률 70%). 주가가 없는 상장폐지 대형사(186개)가 빠져 있어 결과는 체크리스트 쪽에 다소 유리하다. 상세: 체크리스트 검증/99_최종보고서.md</p>
</section>
<div class="disclaimer">원본: 체크리스트 검증/results/screen_now.csv (SEC companyfacts 최초 공시값 + Yahoo 주가, __ASOF__). 등급은 엔진의 정량 판정(1·2단계 정성 ⚠️ 미반영 — 사람 판정보다 후하다). 보고서 링크가 있는 종목만 이름을 누르면 열린다. 투자 권유가 아니다.</div>
</div>
<script>
var ROWS = __ROWS__;
function m(v) { return v == null ? '<span class="muted">—</span>' : (v >= 100 ? '$' + Math.round(v).toLocaleString() : '$' + v.toFixed(1)); }
function pct(v, d) { return (v >= 0 ? '+' : '') + (v * 100).toFixed(d == null ? 1 : d) + '%'; }
ROWS.forEach(function (r) { r.p0 = r.price; r.pe0 = r.pe; r.fy0 = r.fy; });
var GRADE = { S: 0, A: 1, '일반': 2 };
var COLS = [
  { k: 'rk', h: '순위', asc: true, v: function (r) { return r.rk; }, td: function (r) { return '<td><b>' + r.rk + '</b></td>'; } },
  { k: 'name', h: '종목', asc: true, v: function (r) { return r.ko; }, td: function (r) { return '<td>' + (r.nr ? r.ko : '<a href="/reports/' + r.t + '.html">' + r.ko + '</a>') + ' <span class="muted">' + r.t + '</span>' + (r.keep ? ' <span class="tag warn" style="font-size:11px">유지 구간</span>' : '') + '</td>'; } },
  { k: 'g', h: '등급', asc: true, align: 'center', v: function (r) { return GRADE[r.g]; }, td: function (r) { return '<td class="g g' + r.g + '">' + r.g + '</td>'; } },
  { k: 'roic', h: 'ROIC 5년', v: function (r) { return r.roic; }, td: function (r) { return '<td>' + (r.roic * 100).toFixed(0) + '%</td>'; } },
  { k: 'fy', h: 'FCF수익률', v: function (r) { return r.fy; }, td: function (r) { return '<td>' + (r.fy * 100).toFixed(1) + '%</td>'; } },
  { k: 'pe', h: 'PER', v: function (r) { return r.pe; }, td: function (r) { return '<td>' + r.pe.toFixed(1) + '</td>'; } },
  { k: 'price', h: '현재가', v: function (r) { return r.price; }, td: function (r) { return '<td><b>$' + r.price.toFixed(2) + '</b></td>'; } },
  { k: 'iv', h: '엔진 IV(참고)', v: function (r) { return r.iv || 0; }, td: function (r) { return '<td>' + m(r.iv) + '</td>'; } },
  { k: 'mos', h: '현재가/IV', v: function (r) { return r.mos == null ? 99 : r.mos; }, td: function (r) { return '<td class="' + (r.mos <= 0 ? 'up' : 'warn-txt') + '">' + (r.mos == null ? '—' : pct(r.mos)) + '</td>'; } }
];
var BY = {};
COLS.forEach(function (c) { BY[c.k] = c; });
var STATE_KEY = 'vic-watch-v2';
var DEFAULT = { order: COLS.map(function (c) { return c.k; }), k: 'rk', dir: 1 };
var st = JSON.parse(JSON.stringify(DEFAULT));
try {
  var saved = JSON.parse(localStorage.getItem(STATE_KEY));
  if (saved && saved.order && saved.order.length === COLS.length && saved.order.every(function (k) { return BY[k]; })) st = saved;
} catch (e) {}
function save() { try { localStorage.setItem(STATE_KEY, JSON.stringify(st)); } catch (e) {} }
function render() {
  ROWS.forEach(function (r) {
    r.pe = r.pe0 * r.price / r.p0; r.fy = r.fy0 * r.p0 / r.price;
    r.mos = r.iv ? r.price / r.iv - 1 : null; // +면 IV보다 비쌈
  });
  var col = BY[st.k];
  if (col && col.v) {
    ROWS.sort(function (a, b) {
      var x = col.v(a), y = col.v(b);
      var d = typeof x === 'string' ? x.localeCompare(y, 'ko') : x - y;
      return d * st.dir || a.rk - b.rk;
    });
  }
  document.querySelector('#t thead tr').innerHTML = st.order.map(function (k) {
    var c = BY[k], on = st.k === k;
    return '<th draggable="true" data-k="' + k + '" class="wt-th' + (c.v ? ' wt-sortable' : '') + (on ? ' wt-on' : '') + '"' +
      (c.align ? ' style="text-align:' + c.align + '"' : '') + (c.v ? ' title="클릭: 정렬 · 끌기: 컬럼 이동"' : ' title="끌기: 컬럼 이동"') + '>' +
      c.h + (on ? (st.dir > 0 ? ' ▲' : ' ▼') : '') + '</th>';
  }).join('');
  document.querySelector('#t tbody').innerHTML = ROWS.map(function (r) {
    return '<tr' + (r.keep ? ' style="opacity:.6"' : '') + '>' + st.order.map(function (k) { return BY[k].td(r); }).join('') + '</tr>';
  }).join('');
}
var thead = document.querySelector('#t thead'), dragK = null;
thead.addEventListener('click', function (e) {
  var th = e.target.closest('th'); if (!th) return;
  var c = BY[th.dataset.k]; if (!c.v) return;
  if (st.k === c.k) st.dir = -st.dir; else { st.k = c.k; st.dir = c.asc ? 1 : -1; }
  save(); render();
});
thead.addEventListener('dragstart', function (e) {
  var th = e.target.closest('th'); if (!th) return;
  dragK = th.dataset.k; th.classList.add('wt-drag');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragK);
});
thead.addEventListener('dragover', function (e) {
  var th = e.target.closest('th'); if (!th || !dragK) return;
  e.preventDefault();
  thead.querySelectorAll('.wt-over, .wt-over-r').forEach(function (x) { x.classList.remove('wt-over', 'wt-over-r'); });
  if (th.dataset.k !== dragK) th.classList.add(st.order.indexOf(dragK) < st.order.indexOf(th.dataset.k) ? 'wt-over-r' : 'wt-over');
});
thead.addEventListener('drop', function (e) {
  var th = e.target.closest('th'); if (!th || !dragK) return;
  e.preventDefault();
  var to = th.dataset.k;
  if (to !== dragK) {
    var right = st.order.indexOf(dragK) < st.order.indexOf(to);
    st.order.splice(st.order.indexOf(dragK), 1);
    st.order.splice(st.order.indexOf(to) + (right ? 1 : 0), 0, dragK);
    save();
  }
  dragK = null; render();
});
thead.addEventListener('dragend', function () {
  dragK = null;
  thead.querySelectorAll('.wt-drag, .wt-over, .wt-over-r').forEach(function (x) { x.classList.remove('wt-drag', 'wt-over', 'wt-over-r'); });
});
document.getElementById('wt-reset').addEventListener('click', function () {
  st = JSON.parse(JSON.stringify(DEFAULT));
  try { localStorage.removeItem(STATE_KEY); } catch (e) {}
  render();
});
render();
Promise.all(ROWS.map(function (r) {
  return fetch('/api/quote/' + r.t).then(function (x) { return x.ok ? x.json() : null; }).then(function (q) { if (q && q.price) r.price = q.price; }).catch(function () {});
})).then(function () {
  render();
  document.getElementById('asof').textContent = '현재가: ' + new Date().toLocaleString('ko-KR') + ' 기준 실시간';
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
