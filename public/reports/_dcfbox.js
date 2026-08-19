/*
 * 밸류에이션 표 아래에 "이 숫자가 어떻게 나왔는가"를 접이식으로 붙인다.
 *
 * 각 보고서 HTML에서 이렇게 부른다 (원하는 위치의 <script>에서 호출 — 그 자리에 삽입된다):
 *   <script src="/reports/_dcfbox.js"></script>
 *   <script>vicDcfBox({ eps0:10.9, g1:.13, g2:.09, r:.095, per:18.6, perSrc:'역산' });</script>
 *
 * 내용은 02.종목분석/*.md 의 같은 섹션과 동일한 계산을 한다.
 * 숫자를 여기에 적어두지 않고 매번 계산하는 이유: md의 표와 값이 어긋나면 바로 드러나게 하기 위함.
 */
function vicDcfBox(cfg) {
  var me = document.currentScript;
  if (!me) return;

  var money = function (v) {
    return v < 100 ? '$' + v.toFixed(2) : '$' + Math.round(v).toLocaleString();
  };

  // 2단계 DCF — 1~5년은 g1, 6~10년은 g2로 EPS를 키우고 각 해를 현재가치로 할인해 더한다
  var eps = cfg.eps0,
    pv = 0,
    row = {};
  for (var n = 1; n <= 10; n++) {
    eps *= 1 + (n <= 5 ? cfg.g1 : cfg.g2);
    var disc = Math.pow(1 + cfg.r, n);
    pv += eps / disc;
    if (n === 1 || n === 5 || n === 10) row[n] = [eps, disc, eps / disc];
  }
  var d10 = Math.pow(1 + cfg.r, 10);
  var tv = eps * cfg.per; // 10년 뒤 시점의 주식 가치
  var tvpv = tv / d10; // 그 현재가치
  var total = pv + tvpv;
  var share = Math.round((tvpv / total) * 100);
  var srcNote =
    cfg.perSrc === '역산' ? '역산으로 채운 값' : '표에 기재된 값';

  injectStyle();

  var d = document.createElement('details');
  d.className = 'vic-dcf';
  d.innerHTML =
    '<summary>▸ 이 표의 숫자는 어떻게 나왔는가 — 산식과 계산 과정</summary>' +
    '<div class="vic-dcf-body">' +
    '<p><b>2단계 DCF</b> — 앞으로 벌어들일 이익을 지금 가치로 바꿔 더한 값이 내재가치다. ' +
    '미래의 돈은 지금 돈보다 가치가 낮으므로(지금 받으면 굴릴 수 있다) <b>깎아서(할인해서)</b> 더한다.</p>' +
    '<p class="vic-dcf-f">현재가치 = 미래 금액 ÷ (1 + 할인율)<sup>연차</sup><br>' +
    '내재가치 = [1~10년 EPS의 현재가치 합] + [10년 뒤 주식가치의 현재가치]</p>' +
    '<p><b>기본 시나리오 실제 계산</b> — 기준 EPS ' +
    money(cfg.eps0) +
    ' · 성장 +' +
    Math.round(cfg.g1 * 100) +
    '%(1~5년) / +' +
    Math.round(cfg.g2 * 100) +
    '%(6~10년) · 할인율 ' +
    (cfg.r * 100).toFixed(1) +
    '% · 종료 PER ' +
    cfg.per +
    '배(' +
    srcNote +
    ')</p>' +
    '<div class="table-scroll"><table><tr><th>연차</th><th>그해 EPS</th><th>÷ 할인계수</th><th>= 현재가치</th></tr>' +
    tr('1년차', money(row[1][0]), '÷ ' + row[1][1].toFixed(3), money(row[1][2])) +
    tr('5년차', money(row[5][0]), '÷ ' + row[5][1].toFixed(3), money(row[5][2])) +
    tr('10년차', money(row[10][0]), '÷ ' + row[10][1].toFixed(3), money(row[10][2])) +
    tr('…', '(2~4, 6~9년차 생략)', '', '') +
    tr('<b>1~10년 합계</b>', '', '', '<b>' + money(pv) + '</b>') +
    tr(
      '<b>터미널</b> (10년차 EPS ' + money(row[10][0]) + ' × ' + cfg.per + '배 = ' + money(tv) + ')',
      '',
      '÷ ' + d10.toFixed(3),
      '<b>' + money(tvpv) + '</b>',
    ) +
    tr('<b>내재가치</b>', '', '', '<b>' + money(total) + '</b>') +
    '</table></div>' +
    '<p class="vic-dcf-key"><b>터미널이 내재가치의 ' +
    share +
    '%를 차지한다.</b> 앞 10년을 아무리 정교하게 계산해도, 실제로 값을 좌우하는 것은 ' +
    '<b>"10년 뒤에도 이 회사가 건재한가"</b>라는 가정이다. 그래서 <b>1단계(사업의 질)에서 ❌면 그 시점에서 분석을 중단</b>한다 — ' +
    '그 질문에 답할 수 없으면 내재가치의 ' +
    share +
    '%가 근거를 잃는다. <b>4단계는 1단계 위에 서 있다.</b></p>' +
    '<p class="vic-dcf-term"><b>EPS</b> 주당순이익, 1주가 1년에 벌어다 주는 돈 · ' +
    '<b>PER</b> 주가÷EPS, 1년 이익의 몇 배 가격인가 · ' +
    '<b>할인율</b> 미래 이익을 깎는 비율(높을수록 보수적) · ' +
    '<b>종료 PER</b> 10년 뒤 이 주식이 받을 것으로 보는 PER</p>' +
    '</div>';

  me.parentNode.insertBefore(d, me);

  function tr(a, b, c, e) {
    return '<tr><td>' + a + '</td><td>' + b + '</td><td>' + c + '</td><td>' + e + '</td></tr>';
  }

  function injectStyle() {
    if (document.getElementById('vicDcfStyle')) return;
    var s = document.createElement('style');
    s.id = 'vicDcfStyle';
    s.textContent = [
      '.vic-dcf{margin-top:16px;border:1px solid var(--border);border-radius:10px;',
      'background:var(--surface-1);font-size:13.5px}',
      '.vic-dcf>summary{cursor:pointer;padding:11px 16px;font-size:13px;font-weight:600;',
      'color:var(--series-1);list-style:none}',
      '.vic-dcf>summary::-webkit-details-marker{display:none}',
      '.vic-dcf[open]>summary{border-bottom:1px solid var(--border)}',
      '.vic-dcf-body{padding:14px 16px 18px;color:var(--text-secondary);line-height:1.7}',
      '.vic-dcf-body p{margin-bottom:10px}',
      '.vic-dcf-body b{color:var(--text-primary)}',
      '.vic-dcf-f{padding:10px 14px;border-left:3px solid var(--gridline);',
      'background:var(--page);font-variant-numeric:tabular-nums}',
      '.vic-dcf-body table{margin:6px 0 12px}',
      '.vic-dcf-body td:first-child{color:var(--text-secondary)}',
      // 핵심 문단은 배경을 줘서 접었다 폈을 때 눈에 먼저 들어오게 한다
      '.vic-dcf-key{padding:11px 14px;border-radius:8px;background:var(--page);',
      'border-left:3px solid var(--status-warning)}',
      '.vic-dcf-term{margin-top:10px;font-size:12px;color:var(--text-muted)}',
      '.vic-dcf-term b{color:var(--text-secondary)}',
    ].join('');
    document.head.appendChild(s);
  }
}
