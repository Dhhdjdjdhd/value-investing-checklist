"""환율 헤지 알림선 월간 갱신 — 작업 스케줄러(FxLinesMonthly)가 매달 1일 07:10에 실행.

규칙(2026-11-25 사용자 결정, 근거: 대안전략 연구 §M 격자):
  - 헤지: 원/달러가 최근 5년(완료된 월말 60개) 평균의 +20% 이상 → 360750 전부 449180(환헤지)로
  - 복귀: 5년 평균의 +5% 아래 → 다시 360750
  - 24개월 조항: 헤지 후 24개월이 지나도 복귀선 위면 복귀하고, 복귀선 아래로 한 번 내려오기 전까지 재헤지 안 함
    (이 조항은 자동 알림이 없다 — 전환한 날짜를 기록해 둘 것)

하는 일: 5년 평균을 다시 계산해 config.json의 KRW=X 가격선(위·아래)을 고치고,
바뀌었으면 메일로 알린다. 이미 복귀선 아래에 있으면 새 복귀선을 '이미 지난 선'으로 표시해 헛알림을 막는다.
실행: py fx_lines.py [--dry]
"""
import datetime as dt
import json
import shutil
import sys
import urllib.request

import core

UP, DN, MONTHS = 0.20, 0.05, 60
SYM = 'KRW=X'


def month_end_avg():
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{SYM}?range=10y&interval=1mo'
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
    r = r['chart']['result'][0]
    rows = [(dt.date.fromtimestamp(t), c) for t, c in zip(r['timestamp'], r['indicators']['quote'][0]['close'])
            if c and 800 < c < 2000]
    this_month = dt.date.today().replace(day=1)
    done = [c for d, c in rows if d < this_month][-MONTHS:]  # 이번 달(미완료) 제외
    if len(done) < MONTHS:
        raise RuntimeError(f'월말 자료 부족: {len(done)}개')
    return sum(done) / len(done), rows[-1][1]


def main(dry=False):
    core.setup_logging()
    avg, last = month_end_avg()
    enter, exit_ = round(avg * (1 + UP) / 10) * 10, round(avg * (1 + DN) / 10) * 10
    cfg = core.load_config()
    t = next(x for x in cfg['tickers'] if x.get('symbol') == SYM) if isinstance(cfg['tickers'], list) else cfg['tickers'][SYM]
    old_enter = (t.get('price_alerts_above') or [{}])[0].get('price')
    old_exit = (t.get('price_alerts') or [{}])[0].get('price')
    today = dt.date.today().isoformat()
    msg = f'5년 평균 {avg:,.1f}원 → 헤지선 {enter:,} / 복귀선 {exit_:,} (기존 {old_enter} / {old_exit}, 현재 {last:,.1f})'
    print(msg)
    if dry or (enter == old_enter and exit_ == old_exit):
        core.log.info('환율선 변경 없음: ' + msg)
        return
    shutil.copy(core.CONFIG_PATH, core.CONFIG_PATH.replace('config.json', f'config.backup_{today.replace("-", "")}_fx.json'))
    t['price_alerts_above'] = [{'price': enter, 'label': f'360750 전부를 449180(KODEX 미국S&P500(H))로 환헤지 전환 (연금 계좌) — 5년 평균 {avg:,.0f}원의 +20%'}]
    t['price_alerts'] = [{'price': exit_, 'label': f'환헤지 중이었다면 449180 → 360750(환노출) 복귀 — 5년 평균 {avg:,.0f}원의 +5%'}]
    t['valuation_note'] = (f'환율 규칙(2026-11-25 변경, 대안전략 연구 §M): 5년 평균(완료 월말 60개)의 +20% 이상이면 전부 헤지, '
                           f'+5% 아래면 복귀. 매달 1일 fx_lines.py가 선을 다시 계산(마지막 {today}: 평균 {avg:,.1f}). '
                           '헤지 후 24개월 지나도 복귀선 위면 복귀, 이후 복귀선 아래로 한 번 내려오기 전까지 재헤지 안 함. '
                           '이전 규칙: 1,500 헤지 / 1,400 복귀(2026-11-17~25).')
    core.save_json(core.CONFIG_PATH, cfg)
    # 상태 정리: 이미 복귀선 아래면 '지난 선'으로 표시(헛알림 방지), 없어진 선은 지움
    st = core.load_json(core.STATE_PATH, {}) if hasattr(core, 'STATE_PATH') else None
    if st and SYM in st.get('tickers', {}):
        s = st['tickers'][SYM]
        s['price_hits'] = [exit_] if last <= exit_ else []
        s['above_hits'] = [p for p in s.get('above_hits', []) if p == enter]
        core.save_json(core.STATE_PATH, st)
    core.log.info('환율선 갱신: ' + msg)
    core.send_mail(cfg, f'[환율] 헤지 알림선 갱신 — {enter:,} / {exit_:,}원',
                   f'<p>{msg}</p><p>헤지: 5년 평균 +20% 이상이면 360750 → 449180(연금 계좌, 전부)<br>'
                   f'복귀: 5년 평균 +5% 아래면 449180 → 360750<br>24개월 조항은 자동 알림이 없음 — 전환 날짜를 기록해 둘 것.</p>')


if __name__ == '__main__':
    main(dry='--dry' in sys.argv)
