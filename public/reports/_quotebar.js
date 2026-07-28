/*
 * 트리거/내재가치 바에 실시간 현재가를 얹는 공통 스크립트.
 *
 * 각 보고서 HTML에서 이렇게 부른다:
 *   <script src="/reports/_quotebar.js"></script>
 *   <script>vicQuoteBar({ ticker:'CPRT', lo:20, hi:55, target:30.8, cost:28.20,
 *                         chart:'https://kr.investing.com/equities/copart-inc-chart' });</script>
 *
 * 전제: 바가 #vicRangeWrap(.range-wrap) / #vicTrack(.range-track) 으로 표시돼 있을 것.
 * 좌표계는 기존 마커와 동일하게 left% = (가격-lo)/(hi-lo)*100 을 쓴다.
 *
 * 갱신 규칙 — 미국 정규장일 때만 짧은 주기로 돈다.
 * 장이 닫혀 있으면 값이 변하지 않으므로 개장 여부만 가끔 확인한다.
 */
function vicQuoteBar(cfg) {
  var TICK_OPEN = 60 * 1000; // 정규장: 60초
  var TICK_IDLE = 5 * 60 * 1000; // 그 외: 5분마다 개장 여부만 확인
  var LABEL = {
    REGULAR: '정규장',
    PRE: '프리마켓',
    POST: '애프터마켓',
    CLOSED: '장마감',
  };

  var wrap = document.getElementById('vicRangeWrap');
  var track = document.getElementById('vicTrack');
  if (!wrap || !track) return;

  injectStyle();

  // 상세 표시줄은 바 아래에 따로 둔다.
  // 바 안에 넣으면 기존 마커(현재 주가·평단)와 겹친다.
  var line = document.createElement('div');
  line.className = 'vic-nowline';
  line.innerHTML = '<span class="vic-dim">현재가 불러오는 중…</span>';
  wrap.appendChild(line);

  var dot = document.createElement('div');
  dot.className = 'vic-dot';
  track.appendChild(dot);

  wrap.addEventListener('click', function () {
    window.open(
      cfg.chart,
      'vicChart_' + cfg.ticker,
      'width=1280,height=860,scrollbars=yes,resizable=yes',
    );
  });

  var timer;
  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(tick, ms);
  }

  function tick() {
    // 다른 탭을 보고 있으면 호출하지 않는다(돌아오면 즉시 갱신)
    if (document.hidden) {
      schedule(TICK_IDLE);
      return;
    }
    fetch('/api/quote/' + cfg.ticker)
      .then(function (r) {
        return r.ok ? r.json() : Promise.reject(r.status);
      })
      .then(function (q) {
        schedule(render(q) ? TICK_OPEN : TICK_IDLE);
      })
      .catch(function () {
        line.innerHTML =
          '<span class="vic-dim">현재가를 불러오지 못했습니다 — 바를 클릭하면 차트가 열립니다</span>';
        dot.style.display = 'none';
        schedule(TICK_IDLE);
      });
  }

  function render(q) {
    var up = q.change >= 0;
    var color = up ? 'var(--status-critical)' : 'var(--series-1)';
    var cls = up ? 'vic-up' : 'vic-down';
    var sgn = up ? '+' : '';
    var open = q.marketState === 'REGULAR';

    // 바 밖으로 나가면 양끝에 붙인다
    var pct = Math.max(
      0,
      Math.min(100, ((q.price - cfg.lo) / (cfg.hi - cfg.lo)) * 100),
    );
    dot.style.display = '';
    dot.style.left = pct + '%';
    dot.style.background = color;
    dot.style.animationPlayState = open ? 'running' : 'paused';

    var html =
      '<span class="vic-badge' +
      (open ? ' vic-open' : '') +
      '">' +
      (LABEL[q.marketState] || '장마감') +
      '</span>' +
      '<b class="vic-price ' +
      cls +
      '">$' +
      q.price.toFixed(2) +
      '</b>' +
      '<span class="' +
      cls +
      '">' +
      sgn +
      q.change.toFixed(2) +
      ' (' +
      sgn +
      q.changePct.toFixed(2) +
      '%)</span>';

    // 매수한 종목이면 평단 대비 손익을, 아니면 목표 매수가까지 거리를 보여준다
    if (cfg.cost) {
      var pl = ((q.price - cfg.cost) / cfg.cost) * 100;
      html +=
        '<span class="vic-dim">평단 $' +
        cfg.cost.toFixed(2) +
        ' 대비 <b class="' +
        (pl >= 0 ? 'vic-up' : 'vic-down') +
        '">' +
        (pl >= 0 ? '+' : '') +
        pl.toFixed(1) +
        '%</b></span>';
    }
    if (cfg.target) {
      var gap = ((q.price - cfg.target) / cfg.target) * 100;
      html +=
        '<span class="vic-dim">목표 매수가 $' +
        cfg.target +
        ' ' +
        (q.price <= cfg.target
          ? '<b class="vic-reach">이하 ✔</b>'
          : '까지 ' + gap.toFixed(1) + '% 남음') +
        '</span>';
    }
    html +=
      '<span class="vic-dim vic-asof">' +
      q.asOf +
      (open ? ' · 60초마다 갱신' : ' 기준') +
      '</span>' +
      '<span class="vic-cta">차트 ↗</span>';

    line.innerHTML = html;
    return open;
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) tick(); // 탭으로 돌아오면 바로 최신값
  });

  tick();

  function injectStyle() {
    if (document.getElementById('vicQuoteBarStyle')) return;
    var s = document.createElement('style');
    s.id = 'vicQuoteBarStyle';
    s.textContent = [
      '.vic-clickable{cursor:pointer;border-radius:8px;transition:background .15s}',
      '.vic-clickable:hover{background:rgba(42,120,214,.07)}',
      // 현재가 점 — 펄스로 눈에 띄게. 값이 바뀌면 부드럽게 미끄러진다
      '.vic-dot{position:absolute;top:4px;width:14px;height:14px;margin-left:-7px;margin-top:-7px;',
      'border-radius:50%;border:3px solid var(--surface-1);z-index:4;',
      'animation:vicPulse 2s infinite;transition:left .5s ease,background .3s}',
      '@keyframes vicPulse{0%{box-shadow:0 0 0 0 rgba(208,59,59,.55)}',
      '70%{box-shadow:0 0 0 12px rgba(208,59,59,0)}100%{box-shadow:0 0 0 0 rgba(208,59,59,0)}}',
      // 상세 한 줄 — 바 아래에 두어 기존 마커와 겹치지 않게 한다
      '.vic-nowline{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;',
      'margin-top:14px;padding-top:10px;border-top:1px dashed var(--gridline);font-size:13px}',
      '.vic-nowline .vic-price{font-size:19px;font-variant-numeric:tabular-nums}',
      '.vic-nowline b{font-variant-numeric:tabular-nums}',
      '.vic-dim{color:var(--text-secondary)}',
      '.vic-asof{opacity:.75;font-size:12px}',
      '.vic-cta{margin-left:auto;font-weight:600;color:var(--series-1);white-space:nowrap}',
      '.vic-badge{padding:1px 7px;border-radius:10px;font-size:11px;font-weight:700;',
      'background:var(--gridline);color:var(--text-secondary)}',
      '.vic-badge.vic-open{background:var(--status-good);color:#fff}',
      '.vic-up{color:var(--status-critical)}', // 상승 = 빨강 (국내 관행)
      '.vic-down{color:var(--series-1)}', // 하락 = 파랑
      '.vic-reach{color:var(--status-good)}',
    ].join('');
    document.head.appendChild(s);
  }
}
