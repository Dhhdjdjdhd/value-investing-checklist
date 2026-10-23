"""폭락 알림 모니터 — 공통 로직.

시세 조회(가치투자 체크리스트 사이트 API) → 사상 최고가 대비 낙폭 계산 → 알림 판정 → Gmail 발송.
monitor.py(작업 스케줄러가 30분마다 실행)와 ui.py(설정 화면)가 함께 쓴다.
"""
import copy
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import logging
import os
import re
import smtplib
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr
from logging.handlers import RotatingFileHandler

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, 'config.json')
STATE_PATH = os.path.join(BASE, 'state.json')
CACHE_PATH = os.path.join(BASE, 'history_cache.json')
LOG_PATH = os.path.join(BASE, 'logs', 'monitor.log')
LOCK_PATH = os.path.join(BASE, 'monitor.lock')

TASK_NAME = 'DrawdownMonitor'
CRED_TARGET = 'DrawdownMonitor:gmail'
FAIL_ALERT_AFTER = 6          # 연속 실패 6회(=3시간)면 이상 알림
EPISODE_MIN_DEPTH = -0.05     # 통계 캐시에는 -5% 이상 낙폭 구간만 남긴다

DEFAULT_CONFIG = {
    'api_base': 'https://value-investing-checklist.onrender.com/api',
    'email': {'sender': '', 'recipient': '', 'send_recovery': True, 'weekly_summary': True},
    'hysteresis_pct': 3,
    'tickers': [
        # 기준선은 일봉 역대 빈도로 정했다: 1단계 ≈1~3년에 1회, 2단계 ≈4~5년, 3단계 ≈10년+, 4단계 ≈20년+.
        # 하루 급락은 최근 10년 기준 연 1~2회 수준. (2026-10-18 분석)
        {'symbol': 'MSFT', 'name': '마이크로소프트', 'enabled': True, 'levels': [15, 25, 35, 50], 'daily_drop_pct': 5},
        {'symbol': 'GOOGL', 'name': '알파벳', 'enabled': True, 'levels': [15, 25, 35, 50], 'daily_drop_pct': 6},
        {'symbol': 'GC=F', 'name': '금 (선물)', 'enabled': True, 'levels': [10, 20, 25, 40], 'daily_drop_pct': 4},
    ],
}

log = logging.getLogger('monitor')


def setup_logging():
    if log.handlers:
        return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    h = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
    log.addHandler(h)
    log.setLevel(logging.INFO)


# ── 파일 ────────────────────────────────────────────────────────────

def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return copy.deepcopy(default)


def save_json(path, data):
    # 임시 파일에 쓴 뒤 교체 — 쓰는 도중 꺼져도 파일이 깨지지 않는다
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        save_json(CONFIG_PATH, cfg)
    return cfg


# ── 앱 비밀번호 (윈도 자격 증명 관리자) ───────────────────────────────

class _FILETIME(ctypes.Structure):
    _fields_ = [('lo', wt.DWORD), ('hi', wt.DWORD)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [('Flags', wt.DWORD), ('Type', wt.DWORD), ('TargetName', wt.LPWSTR), ('Comment', wt.LPWSTR),
                ('LastWritten', _FILETIME), ('CredentialBlobSize', wt.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wt.DWORD),
                ('AttributeCount', wt.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wt.LPWSTR), ('UserName', wt.LPWSTR)]


_adv = ctypes.WinDLL('advapi32', use_last_error=True)
_adv.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wt.DWORD]
_adv.CredWriteW.restype = wt.BOOL
_adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
_adv.CredReadW.restype = wt.BOOL
_adv.CredFree.argtypes = [ctypes.c_void_p]
_CRED_TYPE_GENERIC, _CRED_PERSIST_LOCAL_MACHINE = 1, 2


def save_password(user, password):
    blob = password.encode('utf-16-le')
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    c = _CREDENTIAL(Type=_CRED_TYPE_GENERIC, TargetName=CRED_TARGET, UserName=user,
                    CredentialBlobSize=len(blob), CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)),
                    Persist=_CRED_PERSIST_LOCAL_MACHINE)
    if not _adv.CredWriteW(ctypes.byref(c), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def load_password():
    p = ctypes.POINTER(_CREDENTIAL)()
    if not _adv.CredReadW(CRED_TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode('utf-16-le')
    finally:
        _adv.CredFree(p)


# ── 시세 (사이트 API) ────────────────────────────────────────────────

def _get(cfg, path):
    """사이트 API 호출. Render 무료 플랜은 잠들어 있으면 첫 응답이 30~60초 걸린다."""
    url = cfg['api_base'].rstrip('/') + path
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'drawdown-monitor'})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:   # 잘못된 심볼·range — 다시 해도 같으니 바로 실패
                raise RuntimeError(f'{path} 조회 실패: HTTP {e.code}') from e
            last = e
            time.sleep(5 * (i + 1))
        except Exception as e:  # noqa: BLE001 — 네트워크 오류·서버 슬립은 재시도
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f'{path} 조회 실패: {last}')


def fetch_quote(cfg, symbol):
    q = _get(cfg, '/quote/' + urllib.parse.quote(symbol, safe=''))
    if 'price' not in q:
        raise RuntimeError(f'{symbol} 시세 없음: {q.get("error")}')
    return q


def fetch_market_cap(symbol):
    """시가총액 (값, 통화). 한국 종목은 네이버, 그 외는 나스닥 API(미국 상장 주식·ADR).
    지수·선물·환율(^, =)은 시총이 없으니 None. 사이트 시세 API(야후 chart)는 시총을 주지 않는다."""
    if '^' in symbol or '=' in symbol:
        return None
    hdr = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    kr = re.match(r'^(\d{6})\.(KS|KQ)$', symbol)
    if kr:
        req = urllib.request.Request(f'https://m.stock.naver.com/api/stock/{kr[1]}/integration', headers=hdr)
        with urllib.request.urlopen(req, timeout=30) as r:
            infos = json.load(r)['totalInfos']
        text = next(i['value'] for i in infos if i['code'] == 'marketValue')   # 예: "1,268조 6,425억"
        jo = re.search(r'([\d,]+)조', text)
        eok = re.search(r'([\d,]+)억', text)
        num = lambda m: int(m[1].replace(',', '')) if m else 0  # noqa: E731
        return num(jo) * 10**12 + num(eok) * 10**8, 'KRW'
    req = urllib.request.Request(
        f'https://api.nasdaq.com/api/quote/{urllib.parse.quote(symbol)}/summary?assetclass=stocks', headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r).get('data') or {}
    v = ((data.get('summaryData') or {}).get('MarketCap') or {}).get('value', '')
    v = str(v).replace(',', '').replace('$', '')
    return (float(v), 'USD') if v.replace('.', '').isdigit() else None


def update_market_cap(symbol, st):
    """하루 한 번만 받는다. 실패하면 이전 값을 그대로 둔다 — 시총은 알림 판정에 쓰지 않는 참고 정보."""
    today = dt.date.today().isoformat()
    if (st.get('mcap') or {}).get('date') == today:
        return
    try:
        r = fetch_market_cap(symbol)
    except Exception as e:  # noqa: BLE001
        log.warning('%s 시총 조회 실패: %s', symbol, e)
        return
    st['mcap'] = {'value': r[0], 'currency': r[1], 'date': today} if r else {'value': None, 'date': today}


def cap_text(m):
    """1.81T USD → '$1.81T', 84B → '$84.0B', 한국 → '1,268조'."""
    if not m or not m.get('value'):
        return '-'
    v = m['value']
    if m.get('currency') == 'KRW':
        return f'{v / 1e12:,.1f}조' if v >= 1e12 else f'{v / 1e8:,.0f}억'
    return f'${v / 1e12:.2f}T' if v >= 1e12 else f'${v / 1e9:.1f}B'


def _is_daily(ts):
    """최근 60개 포인트의 간격 중앙값이 4일 이하면 일봉 (주말·연휴 3~4일 간격은 정상)."""
    gaps = [b - a for a, b in zip(ts[-61:], ts[-60:])]
    return bool(gaps) and statistics.median(gaps) <= 4 * 86400


def fetch_history(cfg, symbol):
    """전체 일봉. range=all이 실패하거나 일봉이 아니면 월봉(max) + 3년 주봉 + 최근 1년 일봉으로 대신한다.
    월봉은 월말 종가만 있어 월중 고점을 놓치므로, 최근 구간일수록 촘촘한 데이터로 바꿔 끼워 최고가를 맞춘다."""
    sym = urllib.parse.quote(symbol, safe='')
    try:
        h, resolution = _get(cfg, f'/history/{sym}?range=all'), '일봉'
        if not _is_daily(h['t']):
            # 응답은 성공인데 일봉이 아닌 경우 — 야후가 range=max를 2주~3개월 간격으로 솎아 준 적이 있다(2026-10).
            # 그대로 쓰면 그 사이의 고점을 놓쳐 낙폭이 작게 나오므로 실패와 같이 취급한다
            raise RuntimeError('range=all이 일봉이 아님')
    except RuntimeError as e:
        log.warning('%s %s — 월봉 + 3년 주봉 + 최근 1년 일봉으로 대신 계산', symbol, e)
        # 거친 데이터일수록 앞쪽에만 쓴다: 전체(월봉) → 최근 3년(주봉) → 최근 1년(일봉)
        m, w, d = (_get(cfg, f'/history/{sym}?range={r}') for r in ('max', '3y', '1y'))
        old = [(t, c) for t, c in zip(m['t'], m['c']) if t < w['t'][0]]
        mid = [(t, c) for t, c in zip(w['t'], w['c']) if t < d['t'][0]]
        h = {'t': [t for t, _ in old + mid] + d['t'], 'c': [c for _, c in old + mid] + d['c']}
        resolution = '월봉(3년 주봉·1년 일봉)'
    rows = [[dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), c] for t, c in zip(h['t'], h['c'])]
    return rows, resolution


def analyze(rows):
    """사상 최고가와 낙폭 구간 목록. 구간 = 고점 → (최저점) → 그 고점을 다시 넘은 날."""
    eps, cur = [], None
    peak, peak_d = rows[0][1], rows[0][0]
    for d, p in rows:
        if p >= peak:
            if cur:
                cur['recovery'] = d
                eps.append(cur)
                cur = None
            peak, peak_d = p, d
        else:
            dd = p / peak - 1
            if cur is None:
                cur = {'peak': peak_d, 'peak_price': peak, 'trough': d, 'depth': dd, 'recovery': None}
            elif dd < cur['depth']:
                cur.update(trough=d, depth=dd)
    if cur:
        eps.append(cur)
    return {'ath': peak, 'ath_date': peak_d, 'start': rows[0][0],
            'episodes': [e for e in eps if e['depth'] <= EPISODE_MIN_DEPTH]}


def get_stats(cfg, symbol, cache):
    """하루 한 번만 이력을 새로 받는다. 실패하면 예전 캐시라도 쓴다."""
    today = dt.date.today().isoformat()
    c = cache.get(symbol)
    if c and c['date'] == today:
        return c['stats']
    try:
        rows, resolution = fetch_history(cfg, symbol)
        stats = analyze(rows)
        stats['resolution'] = resolution
        cache[symbol] = {'date': today, 'stats': stats}
        return stats
    except Exception:
        if c:
            log.exception('%s 이력 갱신 실패 — %s 캐시 사용', symbol, c['date'])
            return c['stats']
        raise


# ── 통계 문구 ────────────────────────────────────────────────────────

def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def fmt_days(n):
    if n >= 365:
        return f'{n / 365.25:.1f}년'
    if n >= 60:
        return f'{n / 30.44:.0f}개월'
    return f'{n}일'


def level_summary(stats, level):
    """-level% 이상 낙폭이 과거 몇 번, 얼마나 자주, 회복에 얼마나 걸렸나 (끝난 구간만)."""
    past = [e for e in stats['episodes'] if e['recovery'] and e['depth'] <= -level / 100]
    years = _days(stats['start'], dt.date.today().isoformat()) / 365.25
    recs = [_days(e['peak'], e['recovery']) for e in past]
    return {
        'count': len(past),
        'freq': f'약 {years / len(past):.0f}년에 1회' if past else '없음',
        'median': fmt_days(int(statistics.median(recs))) if recs else '-',
        'max': fmt_days(max(recs)) if recs else '-',
    }


# ── 알림 판정 ────────────────────────────────────────────────────────

def new_ticker_state():
    return {'level': 0, 'max_level': 0, 'daily_key': None, 'ath_seen': 0, 'ath_seen_date': None,
            'price_hits': [], 'last': None}


def evaluate(t, q, stats, st, hyst):
    """알림 목록을 돌려주고 st를 갱신한다. 같은 구간에서는 한 번만 알린다."""
    price = q['price']
    if price > st['ath_seen']:
        st['ath_seen'], st['ath_seen_date'] = price, dt.date.today().isoformat()
    # 이력이 월봉 대체 계산이거나 오늘 신고가면 이력 최고가보다 모니터가 직접 본 값이 더 높다
    if st['ath_seen'] > stats['ath']:
        ath, ath_date = st['ath_seen'], st['ath_seen_date']
    else:
        ath, ath_date = stats['ath'], stats['ath_date']
    dd = min(price / ath - 1, 0)
    ddp = -dd * 100
    levels = sorted(t['levels'])
    alerts = []

    hit = max([lv for lv in levels if ddp >= lv], default=0)
    if dd == 0 and st['max_level']:
        alerts.append({'kind': 'ath', 'level': st['max_level']})
        st['level'] = st['max_level'] = 0
    elif hit > st['level']:
        alerts.append({'kind': 'drop', 'level': hit})
        st['level'] = hit
        st['max_level'] = max(st['max_level'], hit)
    elif st['level'] and ddp < st['level'] - hyst:
        # 경계에서 오르내릴 때 반복 알림이 없도록 hyst만큼 올라와야 해제
        new = max([lv for lv in levels if ddp >= lv - hyst], default=0)
        alerts.append({'kind': 'recover', 'level': st['level'], 'new_level': new})
        st['level'] = new

    chg = (price / q['prevClose'] - 1) if q.get('prevClose') else 0
    # 같은 거래일에 한 번만 — 미국장은 한국 날짜로 자정을 넘기므로 장 시작 시각을 키로 쓴다
    key = str(q.get('regularStart') or dt.date.today().isoformat())
    if chg * 100 <= -t['daily_drop_pct'] and st['daily_key'] != key:
        alerts.append({'kind': 'daily', 'level': st['level']})
        st['daily_key'] = key

    # 가격선 (분석 문서의 내재가치·목표매수가·분할 가격) — 처음 내려갈 때 한 번, 여러 개를 한꺼번에
    # 뚫으면 가장 낮은 선 하나로 알린다. 해제는 hyst% 위로 올라왔을 때.
    hits = set(st['price_hits'])
    crossed = [pa for pa in t.get('price_alerts', []) if price <= pa['price'] and pa['price'] not in hits]
    if crossed:
        low = min(crossed, key=lambda pa: pa['price'])
        alerts.append({'kind': 'price', 'level': st['level'], 'price': low['price'], 'label': low['label']})
        hits.update(pa['price'] for pa in crossed)
    up = [p for p in hits if price > p * (1 + hyst / 100)]
    if up:
        alerts.append({'kind': 'price_up', 'level': st['level'], 'price': max(up)})
        hits.difference_update(up)
    st['price_hits'] = sorted(hits)

    st['last'] = {'price': price, 'prev_close': q.get('prevClose'), 'change': chg, 'dd': dd,
                  'ath': ath, 'ath_date': ath_date, 'currency': q.get('currency', ''),
                  'market': q.get('marketState'), 'resolution': stats.get('resolution'),
                  'checked': dt.datetime.now().strftime('%Y-%m-%d %H:%M')}
    return alerts


# ── 메일 ────────────────────────────────────────────────────────────

def send_mail(cfg, subject, html):
    em = cfg['email']
    pw = load_password()
    if not (em['sender'] and em['recipient'] and pw):
        raise RuntimeError('메일 설정(보내는 주소·받는 주소·앱 비밀번호)이 비어 있습니다')
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = formataddr(('폭락 알림 모니터', em['sender']))
    msg['To'] = em['recipient']
    with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as s:
        s.starttls()
        s.login(em['sender'], pw)
        s.send_message(msg)


_CSS_TABLE = 'border-collapse:collapse;font-size:13px;margin:6px 0 14px'
_TD = 'border:1px solid #ddd;padding:4px 8px;text-align:right'
_TH = 'border:1px solid #ddd;padding:4px 8px;background:#f3f3f3'


def _table(head, rows):
    h = ''.join(f'<th style="{_TH}">{c}</th>' for c in head)
    b = ''.join('<tr>' + ''.join(f'<td style="{_TD}">{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table style="{_CSS_TABLE}"><tr>{h}</tr>{b}</table>'


def _money(v, cur):
    return f'{v:,.0f} {cur}' if cur == 'KRW' else f'{v:,.2f} {cur}'


def _pct(v):
    return f'{v * 100:+.1f}%'


def ticker_report(t, stats, last, focus_level, brief=False):
    """종목 한 개의 현재 상태 + 깊이별 과거 기록 + 과거 사례 표. brief면 현재 상태·내재가치·가격선까지만."""
    cur = last['currency']
    parts = [_table(['현재가', '전일 대비', '사상 최고가', '최고가 대비'], [[
        _money(last['price'], cur), _pct(last['change']),
        f'{_money(last["ath"], cur)}<br><small>{last["ath_date"]}</small>', f'<b>{_pct(last["dd"])}</b>']])]

    if t.get('iv_base'):
        iv = t['iv_base']
        parts.append(_table(['보수 내재가치', '기본 내재가치', '낙관 내재가치', '안전마진 (기본 대비)'], [[
            _money(t['iv_low'], cur) if t.get('iv_low') else '-', f'<b>{_money(iv, cur)}</b>',
            _money(t['iv_high'], cur) if t.get('iv_high') else '-',
            f'<b>{(iv - last["price"]) / iv * 100:+.1f}%</b>']]))

    if t.get('price_alerts'):
        note =f' <small>({t["valuation_note"]})</small>' if t.get('valuation_note') else ''
        parts.append(f'<b>가격 알림선</b>{note}')
        parts.append(_table(['가격', '의미', '현재가 대비', '상태'], [[
            _money(pa['price'], cur), f'<span style="text-align:left">{pa["label"]}</span>',
            _pct(pa['price'] / last['price'] - 1), '<b>도달</b>' if last['price'] <= pa['price'] else '-']
            for pa in sorted(t['price_alerts'], key=lambda pa: -pa['price'])]))
    if brief:
        return ''.join(parts)

    rows = []
    for lv in sorted(t['levels']):
        s = level_summary(stats, lv)
        rows.append([f'-{lv}% 이상', f'{s["count"]}회', s['freq'], s['median'], s['max']])
    parts.append(f'<b>낙폭 깊이별 과거 기록</b> <small>({stats["start"][:7]} 이후, {stats.get("resolution", "")} 기준)</small>')
    parts.append(_table(['낙폭', '횟수', '빈도', '회복 중앙값', '최장 회복'], rows))

    lv = focus_level or min(t['levels'])
    cases = [e for e in stats['episodes'] if e['depth'] <= -lv / 100]
    if cases:
        parts.append(f'<b>-{lv}% 이상 빠졌던 사례</b>')
        parts.append(_table(['고점', '바닥', '최대 낙폭', '회복', '회복 기간'], [[
            e['peak'], e['trough'], _pct(e['depth']), e['recovery'] or '진행 중',
            fmt_days(_days(e['peak'], e['recovery'])) if e['recovery'] else '-'] for e in reversed(cases)]))
    return ''.join(parts)


def _wrap(title, body):
    return (f'<div style="font-family:Malgun Gothic,Apple SD Gothic Neo,sans-serif;color:#222">'
            f'<h2 style="margin:0 0 10px;font-size:18px">{title}</h2>{body}'
            f'<p style="color:#888;font-size:11px;margin-top:18px">drawdown-monitor · '
            f'{dt.datetime.now():%Y-%m-%d %H:%M} 자동 발송</p></div>')


def build_alert(t, stats, last, a, extra=''):
    nm = f'{t["name"]}({t["symbol"]})'
    dd = _pct(last['dd'])
    if a['kind'] == 'drop':
        s = level_summary(stats, a['level'])
        subject = f'[폭락알림] {nm} 고점 대비 -{a["level"]}% 구간 진입 (현재 {dd})'
        lead = (f'{nm}이 사상 최고가 대비 <b>-{a["level"]}%</b> 아래로 내려왔습니다. '
                f'이 깊이의 낙폭은 과거 <b>{s["count"]}회</b>({s["freq"]}) 있었고, '
                f'고점 회복까지 중앙값 {s["median"]}, 최장 {s["max"]} 걸렸습니다.')
    elif a['kind'] == 'recover':
        subject = f'[회복] {nm} -{a["level"]}% 구간 위로 회복 (현재 {dd})'
        lead = f'{nm}이 -{a["level"]}% 구간을 벗어났습니다 (해제 여유 반영).'
    elif a['kind'] == 'ath':
        subject = f'[신고가] {nm} 사상 최고가 회복'
        lead = f'{nm}이 -{a["level"]}% 낙폭을 지나 사상 최고가를 다시 넘었습니다.'
    elif a['kind'] == 'price':
        cur = last['currency']
        subject = f'[가격선] {nm} {_money(a["price"], cur)} 이하 — {a["label"]} (현재 {_money(last["price"], cur)})'
        lead = (f'{nm}이 <b>{_money(a["price"], cur)}</b> 아래로 내려왔습니다 — <b>{a["label"]}</b>.<br>'
                '목표가 도달 ≠ 자동 매수: ① 분석이 최신 분기 실적을 반영했는지 ② 하락 원인이 시장·업종 공통인지 '
                '개별 악재인지(개별이면 일시적/구조적 4문항) 먼저 확인하세요.'
                + (f'<br>{t["memo"]}' if t.get('memo') else ''))
    elif a['kind'] == 'price_up':
        cur = last['currency']
        subject = f'[가격선 해제] {nm} {_money(a["price"], cur)} 위로 회복 (현재 {_money(last["price"], cur)})'
        lead = f'{nm}이 {_money(a["price"], cur)} 가격선 위로 올라왔습니다 (해제 여유 반영).'
    else:
        subject = f'[급락] {nm} 하루 {_pct(last["change"])} (고점 대비 {dd})'
        lead = f'{nm}이 전일 종가 대비 <b>{_pct(last["change"])}</b> 하락했습니다.'
    return subject, _wrap(subject, f'<p>{lead}</p>' + extra + ticker_report(t, stats, last, a['level']))


# ── 하락 원인 판별 (진입과 청산 원칙 ①-2) ─────────────────────────────

def _close_on(cfg, symbol, date):
    """date 이후 첫 거래일 종가 (최근 1년 일봉 안에서만)."""
    h = _get(cfg, f'/history/{urllib.parse.quote(symbol, safe="")}?range=1y')
    for ts, c in zip(h['t'], h['c']):
        if dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() >= date:
            return c
    return None


def _verdict(mine, med):
    gap = (mine - med) * 100
    if gap <= -3:
        return (f'비교군 중앙값({_pct(med)})보다 {-gap:.1f}%p 더 빠짐 → <b>개별 요인 의심</b>: '
                '실적 발표·추정치 변화 확인, 개별 악재면 일시적/구조적 4문항')
    if med <= -0.015:
        return f'비교군도 함께 하락(중앙값 {_pct(med)}) → <b>시장·업종 공통 요인</b>: 논제와 무관, 분할 규칙대로'
    return f'비교군 중앙값 {_pct(med)}와 뚜렷한 차이 없음'


def earnings_text(st):
    e = st.get('earnings') or {}
    if not e.get('last') and not e.get('next'):
        return ''
    today = dt.date.today().isoformat()
    s = f'최근 실적 발표 {e.get("last") or "-"} · 다음 {e.get("next") or "-"}{" (추정)" if e.get("estimated") else ""}'
    if e.get('last') and 0 <= _days(e['last'], today) <= 7:
        s += ' → <b>실적 발표 직후</b>: 분석 문서 R1~R3 임계값 대조 (유형 ② 기울기 변화인지)'
    elif e.get('next') and 0 <= _days(today, e['next']) <= 7:
        s += ' → 실적 발표 직전'
    return s


def cause_section(cfg, t, st):
    """하락 알림에 붙이는 원인 판별: 같은 날·고점 이후로 지수·동종 종목과 비교 + 실적 발표일 위치."""
    last = st['last']
    today = dt.date.today().isoformat()
    since = last['ath_date'] if _days(last['ath_date'], today) <= 360 else None
    rows, day, per = [], [], []
    for sym in t.get('compare', []):
        try:
            q = fetch_quote(cfg, sym)
            base = _close_on(cfg, sym, since) if since else None
        except Exception as e:  # noqa: BLE001 — 비교 종목 하나가 실패해도 알림은 보낸다
            log.warning('비교 종목 %s 조회 실패: %s', sym, e)
            rows.append([sym, '조회 실패', '-'])
            continue
        chg = q['price'] / q['prevClose'] - 1 if q.get('prevClose') else 0
        p = q['price'] / base - 1 if base else None
        day.append(chg)
        if p is not None:
            per.append(p)
        rows.append([f'{q["name"]} ({sym})', _pct(chg), _pct(p) if p is not None else '-'])

    notes = []
    if day:
        notes.append('오늘: ' + _verdict(last['change'], statistics.median(day)))
    if per:
        notes.append('고점 이후: ' + _verdict(last['dd'], statistics.median(per)))
    if earnings_text(st):
        notes.append('실적: ' + earnings_text(st))
    if not rows and not notes:
        return ''
    me = [f'<b>{t["name"]} ({t["symbol"]})</b>', f'<b>{_pct(last["change"])}</b>',
          f'<b>{_pct(last["dd"])}</b>' if since else '-']
    html = '<b>하락 원인 판별</b> <small>(원칙 ①-2: 같은 업종도 빠졌나 · 지수 대비는 · 실적 발표 부근인가)</small>'
    if rows:
        html += _table(['비교', '오늘', f'고점({since}) 이후' if since else '고점 이후'], [me] + rows)
    html += '<ul style="font-size:13px;margin:0 0 6px">' + ''.join(f'<li>{n}</li>' for n in notes) + '</ul>'
    return html + '<p style="font-size:11px;color:#888;margin:0 0 14px">자동 판정은 참고용 — 판단 근거는 관찰 지표입니다.</p>'


# ── SEC 공시 · 실적 발표일 ──────────────────────────────────────────

SEC_UA = 'drawdown-monitor personal-use'
SEC_FORMS = ('8-K', '8-K/A', '10-Q', '10-K')
SEC_ITEMS = {
    '1.01': '중요 계약 체결', '1.02': '중요 계약 해지', '1.03': '파산·회생', '1.05': '사이버보안 사고',
    '2.01': '인수·매각 완료', '2.02': '실적 발표', '2.03': '채무 발생(채권 발행 등)', '2.05': '구조조정·감원',
    '2.06': '자산 손상', '3.01': '상장 폐지 관련 통지', '4.01': '감사인 변경', '4.02': '과거 재무제표 신뢰 불가',
    '5.02': '임원·이사 변동', '5.03': '정관 변경', '5.07': '주주총회 결과', '7.01': '공정공시(Reg FD)',
    '8.01': '기타 중요 사건',
}
# 관문 탈락으로 이어질 수 있는 8-K 항목 — v2 장부 종목은 이것만 따로 메일 (파산·사이버 사고·구조조정·손상·상장폐지·감사인·재작성)
SEC_SERIOUS = {'1.03', '1.05', '2.05', '2.06', '3.01', '4.01', '4.02'}


def fetch_filings(cik):
    """SEC EDGAR 최근 공시 중 8-K·10-Q·10-K 30건 (최신순)."""
    req = urllib.request.Request(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json',
                                 headers={'User-Agent': SEC_UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        rc = json.load(r)['filings']['recent']
    out = []
    for i, form in enumerate(rc['form']):
        if form in SEC_FORMS:
            out.append({'form': form, 'date': rc['filingDate'][i], 'items': rc['items'][i],
                        'acc': rc['accessionNumber'][i], 'doc': rc['primaryDocument'][i]})
            if len(out) >= 30:
                break
    return out


def _filing_desc(f):
    if f['form'].startswith('10-Q'):
        return '분기보고서'
    if f['form'].startswith('10-K'):
        return '연간보고서'
    items = [i for i in f['items'].split(',') if i and i != '9.01']   # 9.01은 첨부 서류 목록
    return ', '.join(SEC_ITEMS.get(i, f'항목 {i}') for i in items) or '첨부 서류'


def _is_earnings(f):
    return f['form'].startswith('8-K') and '2.02' in f['items'].split(',')


_MONTHS = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}


def fetch_earnings_date(symbol):
    """나스닥 API의 다음 실적 발표 예정일(ISO). 지수·선물·한국 종목은 None.
    응답 예: "Earnings announcement* for V: Oct 27, 2026" (* = 회사 확정 전 예상일일 수 있음)"""
    if '^' in symbol or '=' in symbol or re.match(r'^\d{6}\.(KS|KQ)$', symbol):
        return None
    req = urllib.request.Request(f'https://api.nasdaq.com/api/analyst/{urllib.parse.quote(symbol)}/earnings-date',
                                 headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = ((json.load(r).get('data') or {}).get('announcement') or '')
    m = re.search(r'([A-Z][a-z]{2})\w*\s+(\d{1,2}),\s*(\d{4})', text)
    return dt.date(int(m[3]), _MONTHS[m[1]], int(m[2])).isoformat() if m and m[1] in _MONTHS else None


def update_nasdaq_earnings(symbol, st):
    """하루 한 번만 받는다. 실패하면 이전 값을 그대로 둔다."""
    today = dt.date.today().isoformat()
    if (st.get('nasdaq_earn') or {}).get('date') == today:
        return
    try:
        st['nasdaq_earn'] = {'next': fetch_earnings_date(symbol), 'date': today}
    except Exception as e:  # noqa: BLE001
        log.warning('%s 실적일 조회 실패: %s', symbol, e)


def update_earnings(t, st, filings):
    """최근 실적 발표일(8-K 2.02)과 다음 발표 예상일.
    우선순위: 설정에 넣은 날짜 > 나스닥 예정일 > SEC 기록 추정
    (작년 같은 분기 발표일 + 364일(같은 요일) — 없으면 직전 발표일 + 91일)."""
    today = dt.date.today()
    dates = sorted({f['date'] for f in filings if _is_earnings(f)} | set(st.get('earnings_history', [])))
    st['earnings_history'] = dates[-8:]
    last = dates[-1] if dates else None
    manual = t.get('next_earnings')
    nasdaq = (st.get('nasdaq_earn') or {}).get('next')
    if manual and manual >= today.isoformat():
        nxt, est = manual, False
    elif nasdaq and nasdaq >= today.isoformat():
        nxt, est = nasdaq, False
    elif last:
        target = dt.date.fromisoformat(last) + dt.timedelta(days=91)
        prior = [dt.date.fromisoformat(d) for d in dates
                 if abs((dt.date.fromisoformat(d) + dt.timedelta(days=364) - target).days) <= 21]
        nxt, est = ((prior[-1] + dt.timedelta(days=364)) if prior else target).isoformat(), True
    else:
        nxt, est = None, False
    st['earnings'] = {'last': last, 'next': nxt, 'estimated': est}


def filing_alerts(cfg, t, st):
    """새 공시 메일과 실적 D-3 메일. (subject, html, 실패 시 되돌릴 상태) 목록을 돌려준다.
    처음 조회할 때는 기존 공시를 '본 것'으로만 기록하고 알리지 않는다."""
    filings = fetch_filings(t['cik'])
    update_earnings(t, st, filings)
    nm = f'{t["name"]}({t["symbol"]})'
    cur_html = ticker_report(t, None, st['last'], None, brief=True) if st.get('last') else ''
    mails = []

    seen = st.get('sec_seen')
    new = [f for f in filings if seen is not None and f['acc'] not in seen]
    undo = {'sec_seen': seen}
    st['sec_seen'] = [f['acc'] for f in filings]
    serious = [f for f in new if set(f['items'].split(',')) & SEC_SERIOUS]
    if t.get('group') == 'v2':
        # v2 장부 종목: 실적 공시는 하루 요약(_run)으로 모으고, 그 밖의 공시는 중대 항목만 — 20종목 전부 받으면 너무 많다
        new = [f for f in new if _is_earnings(f) or f in serious]
    if new:
        earn = [f for f in new if _is_earnings(f)]
        if serious and t.get('group') == 'v2':
            subject = f'[중대 공시] {nm} ' + ' / '.join(f'{f["form"]} {_filing_desc(f)}' for f in serious[:3])
            lead = ('관문 탈락으로 이어질 수 있는 공시입니다(파산·손상·상장폐지 통지·감사인 변경·재무제표 신뢰 불가 등). '
                    'v2는 분기 재점검 때만 매매하지만, 이런 공시는 원문을 먼저 읽어 두세요.')
        elif earn:
            subject = f'[실적 발표] {nm} 분기 실적 공시 ({earn[0]["date"]}) — R1~R3 점검할 차례'
            lead = ('실적이 발표됐습니다. 원칙: <b>분석 문서 5단계 R1~R3 관찰 지표를 임계값과 대조</b> → '
                    '필요하면 내재가치 갱신(2회 연속 하향이면 분할매수 정지) → 논제 점검 로그에 한 줄. '
                    '내재가치·가격선을 바꾸면 이 모니터 설정 화면에도 반영하세요.')
        else:
            subject = f'[공시] {nm} ' + ' / '.join(f'{f["form"]} {_filing_desc(f)}' for f in new[:3])
            lead = '새 공시가 올라왔습니다. 뉴스가 아니라 회사가 낸 원문입니다 — R1~R3와 관련 있는지만 확인하세요.'
        rows = [[f['date'], f['form'], f'<span style="text-align:left">{_filing_desc(f)}</span>',
                 f'<a href="https://www.sec.gov/Archives/edgar/data/{int(t["cik"])}/'
                 f'{f["acc"].replace("-", "")}/{f["doc"]}">원문</a>'] for f in new]
        body = f'<p>{lead}</p>' + _table(['제출일', '종류', '내용', '링크'], rows)
        if earnings_text(st):
            body += f'<p style="font-size:13px">{earnings_text(st)}</p>'
        mails.append((subject, _wrap(subject, body + cur_html), undo))
    return mails + earnings_reminder(t, st)


def earnings_reminder(t, st):
    """실적 D-3 메일 (CIK 유무와 무관 — 실적일만 있으면 된다)."""
    nm = f'{t["name"]}({t["symbol"]})'
    cur_html = ticker_report(t, None, st['last'], None, brief=True) if st.get('last') else ''
    mails = []
    e = st.get('earnings') or {}
    if e.get('next'):
        left = _days(dt.date.today().isoformat(), e['next'])
        if 0 <= left <= 3 and st.get('earn_remind') != e['next']:
            est = ' (추정 — 정확한 날짜는 설정 화면에 입력)' if e['estimated'] else ''
            subject = f'[실적 D-{left}] {nm} 실적 발표 예정 {e["next"]}'
            lead = (f'{nm} 실적 발표가 <b>{e["next"]}</b>{est}입니다.<br>'
                    '준비: 분석 문서 5단계 R1~R3 관찰 지표와 임계값을 미리 확인해 두세요. '
                    '발표 전후 급락은 원칙 ①-2 3번(실적 발표 부근) — 유형 ② 기울기 변화인지부터 봅니다.'
                    + (f'<br>{t["memo"]}' if t.get('memo') else ''))
            mails.append((subject, _wrap(subject, f'<p>{lead}</p>' + cur_html), {'earn_remind': st.get('earn_remind')}))
            st['earn_remind'] = e['next']
    return mails


# ── 분석 문서(md) 동기화 ─────────────────────────────────────────────
# md가 판정의 원본이다(INFRA.txt 8번). 실적 발표 후 md만 고치면 내재가치·가격선이 다음 점검에서 따라온다.

def _analysis_dir(cfg):
    return os.path.normpath(os.path.join(BASE, cfg.get('analysis_dir', os.path.join('..', '..', '02.종목분석'))))


def _frontmatter(text):
    if not text.startswith('---'):
        return {}
    fm = {}
    for line in text[3:text.find('\n---', 3)].splitlines():
        k, sep, v = line.partition(':')
        if sep:
            fm[k.strip()] = v.strip()
    return fm


def _num(s):
    v = float(str(s).replace(',', '').replace('$', ''))
    return int(v) if v == int(v) else v


def _nice(p):
    """분할 가격을 보기 좋게 반올림 (100 이상은 5 단위)."""
    step = 5 if p >= 100 else 0.5 if p >= 10 else 0.05
    return _num(round(round(p / step) * step, 2))


def read_analysis(cfg, symbol):
    """가장 최근 분석 md에서 보수·기본·낙관 내재가치, 목표매수가, 분할 가격, 마지막 점검일을 읽는다."""
    d = _analysis_dir(cfg)
    best = None
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith('.md'):
            continue
        with open(os.path.join(d, name), encoding='utf-8') as f:
            text = f.read()
        fm = _frontmatter(text)
        if fm.get('ticker', '').upper() == symbol.upper() and (best is None or fm.get('date', '') >= best[1].get('date', '')):
            best = (name, fm, text)
    if not best:
        return None
    name, fm, text = best
    base, target = _num(fm['intrinsicValue']), _num(fm['targetPrice'])

    # 4단계 시나리오 표: "| 보수 ... | **$352** | ..." 행의 굵은 금액
    sc = {}
    for line in text.splitlines():
        for key, word in (('iv_low', '보수'), ('iv_base', '기본'), ('iv_high', '낙관')):
            m = re.findall(r'\*\*\$([\d,.]+)\*\*', line) if line.startswith(f'| {word}') else None
            if m and key not in sc:
                sc[key] = _num(m[-1])
    # 문서에 분할 계획이 적혀 있으면 그 가격 ("$284 → $250 부근 → $220 부근"), 없으면 원칙의 -12%씩
    m = re.search(r'추가매수 계획[^\n]*?\$([\d,.]+)\s*→\s*\$([\d,.]+)[^→\n]*→\s*\$([\d,.]+)', text)
    splits = [_num(m.group(2)), _num(m.group(3))] if m else [_nice(target * 0.88), _nice(target * 0.88 ** 2)]
    logs = re.findall(r'^\| (\d{4}-\d{2}-\d{2}) \|', text, re.M)   # 논제 점검 로그의 날짜
    return {'file': name, 'date': fm.get('date', ''), 'checked': max(logs) if logs else fm.get('date', ''),
            'verdict': fm.get('verdict', ''), 'iv_low': sc.get('iv_low'), 'iv_base': base,
            'iv_high': sc.get('iv_high'), 'target': target, 'splits': splits}


GRADE_BY_MOS = {10: 'S', 15: 'A', 20: '일반'}   # 02 §1 품질 등급별 안전마진


def _target_label(a):
    """목표매수가 문구 — md의 목표가 ÷ 기본 내재가치에서 안전마진(→등급)을 읽는다."""
    mos = round((1 - a['target'] / a['iv_base']) * 100)
    grade = GRADE_BY_MOS.get(mos)
    head = f'등급 {grade} · 안전마진 {mos}%' if grade else f'안전마진 {mos}%'
    return f'목표매수가({head}) — 1회차 매수 (목표 비중의 1/3~1/2)'


def _price_lines(a):
    lines = [(a['iv_base'], '기본 내재가치 이하 — 매수 준비, 하락 원인 확인 시작'),
             (a['target'], _target_label(a)),
             (a['splits'][0], '2회차 분할매수 (논제 재점검 후)'),
             (a['splits'][1], '3회차 분할매수 (논제 재점검 후)')]
    if a['iv_low']:
        lines.append((a['iv_low'], "보수 내재가치 이하 — 확신도 '높음' 재평가"))
    out, seen = [], set()
    for p, label in sorted(lines, key=lambda x: -x[0]):
        if p not in seen:
            seen.add(p)
            out.append({'price': p, 'label': label})
    return out


IV_KEYS = (('iv_low', '보수 내재가치'), ('iv_base', '기본 내재가치'), ('iv_high', '낙관 내재가치'), ('target_price', '목표매수가'))


def sync_valuations(cfg, state):
    """md_sync가 켜진 종목의 내재가치·가격선을 md에 맞춘다. 값이 바뀌면 메일 목록과 함께 True를 돌려준다.
    기본 내재가치 하향은 연속 횟수를 센다 — 2회 연속이면 원칙상 분할매수 정지·논제 재작성."""
    mails, changed = [], False
    for t in cfg['tickers']:
        if not t.get('md_sync'):
            continue
        try:
            a = read_analysis(cfg, t['symbol'])
        except Exception as e:  # noqa: BLE001 — 문서 형식이 깨져도 시세 점검은 계속
            log.warning('%s 분석 문서 읽기 실패: %s', t['symbol'], e)
            continue
        if not a:
            log.warning('%s 분석 문서(md)를 찾지 못함 — %s', t['symbol'], _analysis_dir(cfg))
            continue
        new = {'iv_low': a['iv_low'], 'iv_base': a['iv_base'], 'iv_high': a['iv_high'], 'target_price': a['target'],
               'price_alerts': _price_lines(a),
               'valuation_note': f'{a["file"]} · 분석 {a["date"]}, 마지막 점검 {a["checked"]}'}
        new = {k: v for k, v in new.items() if v is not None}
        old = {k: t.get(k) for k in new}
        if old == new:
            continue
        moved = [(k, label) for k, label in IV_KEYS if k in new and old.get(k) is not None and old[k] != new[k]]
        t.update(new)
        changed = True
        st = state.setdefault('tickers', {}).setdefault(t['symbol'], new_ticker_state())
        st['price_hits'] = [p for p in st.get('price_hits', []) if p in {pa['price'] for pa in new['price_alerts']}]
        if not moved:   # 처음 동기화이거나 문구·점검일만 바뀜 — 조용히 반영
            log.info('%s 분석 문서 동기화 (값 변화 없음): %s', t['symbol'], a['file'])
            continue

        down = old.get('iv_base') is not None and new['iv_base'] < old['iv_base']
        up = old.get('iv_base') is not None and new['iv_base'] > old['iv_base']
        st['iv_downgrades'] = st.get('iv_downgrades', 0) + 1 if down else 0 if up else st.get('iv_downgrades', 0)
        nm = f'{t["name"]}({t["symbol"]})'
        n = st['iv_downgrades']
        tag = (f' (⚠️ 하향 {n}회 연속)' if n >= 2 else ' (하향)') if down else ' (상향)' if up else ''
        subject = f'[내재가치 변경] {nm} 기본 ${_num(old.get("iv_base") or 0)} → ${new["iv_base"]}{tag}'
        rows = [[label, f'${old[k]}' if old.get(k) is not None else '-', f'<b>${new[k]}</b>',
                 _pct(new[k] / old[k] - 1) if old.get(k) else '-'] for k, label in IV_KEYS if k in new]
        warn = ''
        if st['iv_downgrades'] >= 2:
            warn = ('<p style="color:#c0392b"><b>⚠️ 원칙 ③: 기본 내재가치 2회 연속 하향 → 다음 분할매수 금지 + 논제 전면 재작성.</b><br>'
                    '하향 근거가 "성장률·마진 가정을 낮췄다"이면 그 자체가 구조적 훼손 신호입니다. '
                    '(일회성 요인·계산 수정이면 횟수에서 제외)</p>')
        body = (f'<p>분석 문서 <b>{a["file"]}</b>(판정: {a["verdict"]}, 마지막 점검 {a["checked"]})의 값이 바뀌어 '
                '모니터의 내재가치·가격선을 갱신했습니다.</p>' + warn
                + _table(['항목', '이전', '변경', '변화'], rows)
                + '<b>새 가격 알림선</b>' + _table(['가격', '의미'], [[f'${pa["price"]}', pa['label']] for pa in new['price_alerts']]))
        mails.append((subject, _wrap(subject, body)))
        log.info('%s 내재가치 변경: %s', t['symbol'], subject)
    return mails, changed


# ── 실행 ────────────────────────────────────────────────────────────

def _acquire_lock():
    """스케줄 실행과 UI의 '지금 점검'이 겹치지 않게 한다. 15분 넘은 잠금은 비정상 종료로 보고 지운다."""
    try:
        if time.time() - os.path.getmtime(LOCK_PATH) > 900:
            os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass
    try:
        os.close(os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL))
        return True
    except FileExistsError:
        return False


ALERT_KEYS = ('level', 'max_level', 'price_hits', 'daily_key', 'earn_remind')


def reset_alerts(symbol=None):
    """알림 상태 초기화 — 다음 점검에서 현재 조건에 맞는 알림이 다시 나간다.
    시세 기록·최고가·공시 기록은 그대로 둔다 (지우면 과거 공시 메일이 쏟아진다). symbol이 없으면 전체."""
    if not _acquire_lock():
        raise RuntimeError('점검이 실행 중입니다. 잠시 후 다시 시도하세요.')
    try:
        state = load_json(STATE_PATH, {})
        fresh = new_ticker_state()
        done = []
        for sym, st in state.get('tickers', {}).items():
            if symbol in (None, sym):
                st.update({k: copy.deepcopy(fresh.get(k)) for k in ALERT_KEYS})
                done.append(sym)
        save_json(STATE_PATH, state)
        log.info('알림 상태 초기화: %s', ', '.join(done) or '(대상 없음)')
        return done
    finally:
        os.remove(LOCK_PATH)


def run_check():
    """한 번 점검. 결과 요약 문자열을 돌려준다 (UI 표시용)."""
    if not _acquire_lock():
        log.info('다른 점검이 실행 중 — 건너뜀')
        return '다른 점검이 실행 중이라 건너뛰었습니다.'
    try:
        return _run(load_config())
    finally:
        os.remove(LOCK_PATH)


def _run(cfg):
    state = load_json(STATE_PATH, {})
    cache = load_json(CACHE_PATH, {})
    tstate = state.setdefault('tickers', {})
    errors, sent, reports, digest = [], [], [], []

    # v2 장부 보유 종목을 감시 목록에 맞춘다 (분기 재점검으로 바뀐 종목이 이번 점검부터 따라온다)
    led = read_ledger()
    v2_changed = bool(led) and sync_v2(cfg, led)

    # 분석 문서가 바뀌었으면 내재가치·가격선부터 맞춘다 (이번 점검의 가격선 판정에 바로 쓰인다)
    iv_mails, iv_changed = sync_valuations(cfg, state)
    if iv_changed or v2_changed:
        save_json(CONFIG_PATH, cfg)
    for subject, html in iv_mails:
        try:
            send_mail(cfg, subject, html)
            sent.append(subject)
            log.info('메일 발송: %s', subject)
        except Exception as e:  # noqa: BLE001
            log.error('메일 발송 실패 (%s): %s', subject, e)
            errors.append(f'메일 실패: {e}')

    for t in [t for t in cfg['tickers'] if t.get('enabled', True)]:
        sym = t['symbol']
        try:
            q = fetch_quote(cfg, sym)
            stats = get_stats(cfg, sym, cache)
        except Exception as e:  # noqa: BLE001
            log.error('%s 조회 실패: %s', sym, e)
            errors.append(f'{sym}: {e}')
            continue
        first = sym not in tstate
        st = tstate[sym] = {**new_ticker_state(), **tstate.get(sym, {})}
        before = copy.deepcopy(st)
        alerts = evaluate(t, q, stats, st, cfg.get('hysteresis_pct', 3))
        if first:   # 처음 감시하는 종목은 지금 있는 낙폭 구간·가격선을 기록만 한다 (이미 빠져 있던 걸 새 소식처럼 보내지 않게)
            alerts = [a for a in alerts if a['kind'] == 'daily']
            log.info('%s 감시 시작 — 현재 구간 -%s%% 기록만', sym, st['level'])
        update_market_cap(sym, st)
        last = st['last']
        log.info('%s %.2f 전일 %+.2f%% 고점대비 %+.2f%% 단계 -%s%%',
                 sym, last['price'], last['change'] * 100, last['dd'] * 100, st['level'])
        reports.append((t, stats, last, st))

        # 공시·실적일을 먼저 갱신한다 — 하락 알림의 원인 판별에 실적 발표일이 들어간다
        sec_mails = []
        update_nasdaq_earnings(sym, st)
        if t.get('cik'):
            try:
                sec_mails = filing_alerts(cfg, t, st)
            except Exception as e:  # noqa: BLE001 — 공시 조회 실패는 시세 알림을 막지 않는다
                log.warning('%s 공시 조회 실패: %s', sym, e)
        else:   # CIK 없는 종목은 공시 메일 없이 실적일·D-3만
            update_earnings(t, st, [])
            sec_mails = earnings_reminder(t, st)

        cause = None
        for a in alerts:
            if a['kind'] in ('recover', 'price_up') and not cfg['email'].get('send_recovery', True):
                continue
            extra = ''
            if a['kind'] in ('drop', 'daily', 'price'):
                if cause is None:   # 비교 종목 조회는 하락 알림이 있을 때만, 한 번
                    cause = cause_section(cfg, t, st)
                extra = cause
            subject, html = build_alert(t, stats, last, a, extra)
            try:
                send_mail(cfg, subject, html)
                sent.append(subject)
                log.info('메일 발송: %s', subject)
            except Exception as e:  # noqa: BLE001
                # 알림 단계를 되돌려 다음 실행에서 다시 보내게 한다
                log.error('메일 발송 실패 (%s): %s', subject, e)
                errors.append(f'메일 실패: {e}')
                for k in ('level', 'max_level', 'daily_key', 'price_hits'):
                    st[k] = before[k]
                break

        for subject, html, undo in sec_mails:
            if t.get('group') == 'v2' and subject.startswith('[실적'):
                digest.append((t, subject, undo, st))   # 실적 공시·D-3는 하루 한 통으로 모은다
                continue
            try:
                send_mail(cfg, subject, html)
                sent.append(subject)
                log.info('메일 발송: %s', subject)
            except Exception as e:  # noqa: BLE001
                log.error('메일 발송 실패 (%s): %s', subject, e)
                errors.append(f'메일 실패: {e}')
                st.update(undo)

    # 원화 환산용 환율 — 화면의 '현재가(원)' 열에 쓴다. 실패해도 점검 결과에는 영향 없음
    try:
        fx = fetch_quote(cfg, 'KRW=X')
        state['fx'] = {'USDKRW': fx['price'], 'checked': dt.datetime.now().strftime('%Y-%m-%d %H:%M')}
    except Exception as e:  # noqa: BLE001
        log.warning('환율(KRW=X) 조회 실패: %s', e)

    if digest:
        _v2_digest(cfg, digest, sent, errors)
    if led and (state.get('fx') or {}).get('USDKRW'):
        try:
            rows, total = v2_snapshot(led, tstate, state['fx']['USDKRW'])
            _v2_weight_alerts(cfg, state, rows, total, sent)
            _v2_monthly(cfg, state, led, rows, total, sent)
        except Exception as e:  # noqa: BLE001 — 장부 점검 실패가 시세 알림을 막지 않는다
            log.error('v2 장부 점검 실패: %s', e)

    _fail_watch(cfg, state, [e for e in errors if not e.startswith('메일')])
    _weekly_summary(cfg, state, reports)
    save_json(CACHE_PATH, cache)
    save_json(STATE_PATH, state)

    msg = f'점검 완료: {len(reports)}종목, 메일 {len(sent)}통'
    return msg + (('\n오류:\n' + '\n'.join(errors)) if errors else '')


def _fail_watch(cfg, state, errors):
    """시세 조회 실패만 센다 (메일 실패는 메일로 알릴 수 없으니 로그로만 남긴다)."""
    if not errors:
        state['fail_count'] = 0
        return
    state['fail_count'] = state.get('fail_count', 0) + 1
    if state['fail_count'] == FAIL_ALERT_AFTER:
        try:
            send_mail(cfg, '[폭락알림] 모니터 이상 — 시세 조회 연속 실패',
                      _wrap('모니터 이상', f'<p>{FAIL_ALERT_AFTER}회 연속 조회에 실패했습니다.</p><pre>'
                            + '\n'.join(errors) + '</pre>'))
        except Exception as e:  # noqa: BLE001
            log.error('이상 알림 발송 실패: %s', e)


def _weekly_summary(cfg, state, reports):
    """매주 월요일 아침 7시 이후 첫 점검에서 전체 요약을 보낸다 — 모니터가 살아 있다는 신호."""
    now = dt.datetime.now()
    today = now.date().isoformat()
    if not (cfg['email'].get('weekly_summary', True) and reports and now.weekday() == 0 and now.hour >= 7
            and state.get('weekly_date') != today):
        return
    def nxt(st):
        e = st.get('earnings') or {}
        return (e['next'] + (' (추정)' if e.get('estimated') else '')) if e.get('next') else '-'

    def mos(t, l):
        return f'{(t["iv_base"] - l["price"]) / t["iv_base"] * 100:+.1f}%' if t.get('iv_base') else '-'

    rows = [[f'{t["name"]} ({t["symbol"]})', _money(l['price'], l['currency']), cap_text(st.get('mcap')),
             _pct(l['change']), f'<b>{_pct(l["dd"])}</b>', mos(t, l), nxt(st)] for t, _, l, st in reports]
    body = '<p>모니터가 정상 동작 중입니다.</p>' + _table(
        ['종목', '현재가', '시가총액', '전일 대비', '최고가 대비', '안전마진', '다음 실적'], rows)
    try:
        send_mail(cfg, f'[폭락알림] 주간 요약 {today}', _wrap(f'주간 요약 {today}', body))
        state['weekly_date'] = today
    except Exception as e:  # noqa: BLE001
        log.error('주간 요약 발송 실패: %s', e)


# ── v2 시뮬레이터 장부 (01.가치투자 체크리스트/06 · public/reports/PORTFOLIO.html) ──────────────
# 장부 원본은 PORTFOLIO.html의 데이터 블록. 분기 재점검(체크리스트 검증/src/quarterly.py, 작업 V2QuarterlyReview)이 고친다.
# 이 모니터는 읽기만 한다: 감시 목록 맞추기 · 실적 하루 요약 · 비중 10% 초과 · 월간 성적표(S&P500 대비)

LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(BASE)), 'public', 'reports', 'PORTFOLIO.html')
V2_TRIM = 0.10
V2_REVIEW_MONTHS = (1, 4, 7, 10)   # 분기 재점검: 이 달 1일 07:00 (미국 3·6·9·12월 말 종가 확정 뒤)
V2_PAGE = 'https://value-investing-checklist.onrender.com/reports/PORTFOLIO.html'


def read_ledger():
    try:
        with open(LEDGER_PATH, encoding='utf-8') as f:
            m = re.search(r'// <DATA>\nvar DEFAULT_DATA = (.*?);\n// </DATA>', f.read(), re.S)
        return json.loads(m.group(1)) if m else None
    except (OSError, ValueError) as e:
        log.warning('v2 장부 읽기 실패: %s', e)
        return None


def next_review(today=None):
    today = today or dt.date.today()
    for y in (today.year, today.year + 1):
        for m in V2_REVIEW_MONTHS:
            d = dt.date(y, m, 1)
            if d > today:
                return d.isoformat()


def sync_v2(cfg, led):
    """장부 보유 종목 = 감시 목록의 group 'v2'. 바뀌었으면 True (config 저장 필요)."""
    held = {h['code']: h for h in led['holdings']}
    changed = False
    keep = []
    for t in cfg['tickers']:
        if t.get('group') == 'v2' and t['symbol'] not in held:
            log.info('v2 감시 해제(장부에서 빠짐): %s', t['symbol'])
            changed = True
            continue
        keep.append(t)
    cfg['tickers'] = keep
    have = {t['symbol']: t for t in keep}
    by_sector = {}
    for h in led['holdings']:
        by_sector.setdefault(h['sector'], []).append(h['code'])
    for code, h in held.items():
        compare = ['^GSPC'] + [c for c in by_sector[h['sector']] if c != code][:3]   # 원인 판별 비교군: 지수 + 같은 업종 보유 종목
        memo = f'[v2 장부] 선정 {h["rank"]}위 · 등급 {h["grade"]} · {h["shares"]}주 · {h.get("industry", "")}'
        t = have.get(code)
        if t is None:
            keep.append({'symbol': code, 'name': h['name'], 'enabled': True, 'group': 'v2', 'levels': [15, 25, 35, 50],
                         'daily_drop_pct': 6, 'cik': h.get('cik'), 'compare': compare, 'memo': memo})
            log.info('v2 감시 추가: %s', code)
            changed = True
            continue
        if t.get('group') != 'v2':
            # v1 감시판에 있던 종목(ADP 등)을 v2로 넘긴다 — v1 가격선(목표가 대기)은 v2에서 쓰지 않는다
            for k in ('price_alerts', 'iv_low', 'iv_base', 'iv_high', 'target_price', 'valuation_note', 'md_sync', 'grade'):
                t.pop(k, None)
            t.update(group='v2', enabled=True, cik=h.get('cik') or t.get('cik'))
            changed = True
        if t.get('memo') != memo or t.get('compare') != compare:
            t.update(memo=memo, compare=compare)
            changed = True
    return changed


def v2_snapshot(led, tstate, fx):
    """종목별 원화 평가액·비중. 시세가 없으면 평단으로 대신한다."""
    rows = []
    for h in led['holdings']:
        last = (tstate.get(h['code']) or {}).get('last')
        krw = last['price'] * fx if last else h['avgPrice']
        rows.append({**h, 'krw': krw, 'val': krw * h['shares'], 'change': last['change'] if last else None})
    total = sum(r['val'] for r in rows) + led['cash']
    for r in rows:
        r['w'] = r['val'] / total
    return rows, total


def _v2_send(cfg, subject, body, sent):
    try:
        send_mail(cfg, subject, _wrap(subject, body))
        sent.append(subject)
        log.info('메일 발송: %s', subject)
        return True
    except Exception as e:  # noqa: BLE001
        log.error('메일 발송 실패 (%s): %s', subject, e)
        return False


def _v2_digest(cfg, items, sent, errors):
    """v2 종목의 실적 공시·실적 D-3를 한 통으로. 실패하면 각 종목의 알림 상태를 되돌려 다음 점검에서 다시."""
    today = dt.date.today().isoformat()
    rows = [[f'{t["name"]} ({t["symbol"]})', subj.split('] ', 1)[0].lstrip('['),
             f'<span style="text-align:left">{subj.split("] ", 1)[-1]}</span>',
             f'<a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(t["cik"])}&type=8-K">공시 목록</a>'
             if t.get('cik') else '-'] for t, subj, _, _ in items]
    body = ('<p>v2는 실적 발표로 사고팔지 않습니다 — 새 숫자는 <b>분기 재점검(다음: ' + next_review() + ')</b> 때 순위에 '
            '반영됩니다. 지금 볼 것은 관문 탈락 신호뿐입니다: 적자 전환, 매출·EPS 역성장, 큰 손상·일회성, 부채 급증.</p>'
            + _table(['종목', '구분', '내용', '원문'], rows))
    subject = f'[v2 실적] {today} — ' + ', '.join(t['name'] for t, _, _, _ in items[:4]) + (f' 외 {len(items) - 4}' if len(items) > 4 else '')
    if not _v2_send(cfg, subject, body, sent):
        errors.append('메일 실패: v2 실적 요약')
        for _, _, undo, st in items:
            st.update(undo)


def _v2_weight_alerts(cfg, state, rows, total, sent):
    """비중 10% 초과 — 처음 넘을 때 한 번. 9% 아래로 내려오면 해제."""
    v2 = state.setdefault('v2', {})
    over = set(v2.get('over', []))
    for r in rows:
        if r['w'] > V2_TRIM and r['code'] not in over:
            subject = f'[v2 비중] {r["name"]}({r["code"]}) {r["w"] * 100:.1f}% — 10% 초과'
            body = (f'<p>{r["name"]} 비중이 총자산의 <b>{r["w"] * 100:.1f}%</b>가 됐습니다(기준 5%, 조정 경계 10%). '
                    f'다음 분기 재점검({next_review()})에서 자동으로 5%로 줄입니다 — 지금 할 일은 없습니다.</p>')
            if _v2_send(cfg, subject, body, sent):
                over.add(r['code'])
        elif r['w'] < V2_TRIM - 0.01:
            over.discard(r['code'])
    v2['over'] = sorted(over)


def _v2_monthly(cfg, state, led, rows, total, sent):
    """매달 1일 아침 7시 이후 첫 점검 — 장부 성적표. 비교 기준은 같은 날 같은 원화를 SPY에 넣었을 때."""
    now = dt.datetime.now()
    key = now.strftime('%Y-%m')
    v2 = state.setdefault('v2', {})
    if v2.get('monthly') == key or now.hour < 7 or not cfg['email'].get('weekly_summary', True):
        return
    start = led['start']
    if key <= start['date'][:7]:   # 시작한 달에는 보내지 않는다
        v2['monthly'] = key
        return
    if not v2.get('spy_base'):
        v2['spy_base'] = _close_on(cfg, 'SPY', start.get('priceDate', start['date']))
    fx = state['fx']['USDKRW']
    spy = fetch_quote(cfg, 'SPY')['price']
    my = total / start['capital'] - 1
    bench = spy * fx / (v2['spy_base'] * start['fx']) - 1
    gap = (my - bench) * 100
    top = sorted(rows, key=lambda r: -r['w'])
    tbl = _table(['종목', '비중', '평단 대비', '전일 대비'], [
        [f'{r["name"]} ({r["code"]})', f'{r["w"] * 100:.1f}%', _pct(r['krw'] / r['avgPrice'] - 1),
         _pct(r['change']) if r['change'] is not None else '-'] for r in top])
    review = (f'<p><b>이번 달은 분기 재점검 달입니다</b> — 오늘({now.year}-{now.month:02d}-01) 07:00에 자동 실행되고 결과 메일이 따로 갑니다. 위 표는 재점검 전 장부입니다.</p>'
              if now.month in V2_REVIEW_MONTHS else f'<p>다음 분기 재점검: {next_review()}</p>')
    body = (f'<p>{start["date"]} 시작 이후 (원화, 환율 포함)</p>'
            + _table(['', '수익률', '평가액'], [
                ['<b>v2 장부</b>', f'<b>{_pct(my)}</b>', f'{total:,.0f}원'],
                ['S&amp;P500 (SPY, 같은 날 같은 금액)', _pct(bench), f'{start["capital"] * (1 + bench):,.0f}원'],
                ['차이', f'<b>{gap:+.1f}%p</b>', f'{start["capital"] * (my - bench):+,.0f}원']])
            + review + tbl + f'<p><a href="{V2_PAGE}">보유 현황 화면</a> · 가상 시뮬레이터 기록이며 투자 권유가 아닙니다.</p>')
    if _v2_send(cfg, f'[v2 월간] {key} — v2 {_pct(my)} / S&P500 {_pct(bench)} ({gap:+.1f}%p)', body, sent):
        v2['monthly'] = key


def send_test_mail(cfg):
    send_mail(cfg, '[폭락알림] 테스트 메일', _wrap('테스트 메일', '<p>메일 설정이 정상입니다.</p>'))


# ── 윈도 작업 스케줄러 ───────────────────────────────────────────────

def _powershell(script):
    # 경로에 한글이 있어 인코딩 문제가 없도록 -EncodedCommand(UTF-16LE base64)로 넘긴다.
    # 출력은 리디렉션되면 콘솔 코드페이지(한국어 윈도는 CP949)로 나오므로 oem으로 읽는다.
    import base64
    import subprocess
    enc = base64.b64encode(('$ProgressPreference="SilentlyContinue"\n' + script).encode('utf-16-le')).decode()
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', enc],
                       capture_output=True, timeout=60, creationflags=0x08000000)  # CREATE_NO_WINDOW
    out = (r.stdout or b'').decode('oem', 'replace').strip()
    err = (r.stderr or b'').decode('oem', 'replace').strip()
    if r.returncode:
        raise RuntimeError(err or out or f'powershell 종료 코드 {r.returncode}')
    return out


def _pythonw():
    import sys
    return os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')


def task_register():
    script = os.path.join(BASE, 'monitor.py')
    return _powershell(f"""
$a = New-ScheduledTaskAction -Execute '{_pythonw()}' -Argument '"{script}"' -WorkingDirectory '{BASE}'
$now = Get-Date
$start = $now.Date.AddHours($now.Hour).AddMinutes(30 * [math]::Ceiling($now.Minute / 30))
$t = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 30)
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
     -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s `
     -Description '폭락 알림 모니터 - 30분마다 시세 점검' -Force | Out-Null
'등록 완료 - 첫 실행 ' + $start.ToString('yyyy-MM-dd HH:mm')
""")


def task_unregister():
    return _powershell(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false; '해제 완료'")


def task_status():
    return _powershell(f"""
$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if (-not $t) {{ '등록 안 됨'; return }}
$i = $t | Get-ScheduledTaskInfo
$r = if ($i.LastTaskResult -eq 0) {{ '정상(0)' }} elseif ($i.LastTaskResult -eq 267011) {{ '아직 실행 전' }} else {{ '코드 ' + $i.LastTaskResult }}
'상태: ' + $t.State + '  |  마지막 실행: ' + $i.LastRunTime + ' (' + $r + ')  |  다음 실행: ' + $i.NextRunTime
""")
