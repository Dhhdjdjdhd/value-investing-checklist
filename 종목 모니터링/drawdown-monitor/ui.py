"""폭락 알림 모니터 — 설정 화면 (종목 추가·삭제, 메일 설정, 스케줄 등록, 로그 보기)."""
import datetime as dt
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import core

FONT = ('Malgun Gothic', 10)
SYMBOL_HINT = '예) MSFT · GOOGL · GC=F(금 선물) · SI=F(은) · ^GSPC(S&P500) · 005930.KS(삼성전자) · 360750.KS'


def _levels_text(levels):
    return ', '.join(str(v) for v in levels)


def _iv_text(v):
    """내재가치 표시 — $100 미만(KO $64.7 등)은 소수 한 자리까지."""
    return '-' if not v else f'{v:,.0f}' if v >= 100 else f'{v:,.1f}'


_UNIT = {'T': 1e12, 'B': 1e9, '조': 1e12, '억': 1e8}


def _sort_key(text):
    """화면 문자열을 정렬 키로 — 숫자('1,234.56 USD', '+1.2%', '$1.81T', '529 (-12%)')는 숫자로, 날짜·이름은 문자로."""
    s = str(text).strip()
    if re.match(r'^\d{4}-\d\d-\d\d', s):
        return (1, s)
    m = re.match(r'^\$?([+-]?[\d,]*\.?\d+)\s*(T|B|조|억)?', s)
    if m:
        return (0, float(m[1].replace(',', '')) * _UNIT.get(m[2], 1))
    return (1, s)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('폭락 알림 모니터')
        self.geometry('1550x600')
        self.minsize(900, 480)
        self.option_add('*Font', FONT)
        ttk.Style(self).configure('Treeview', rowheight=24, font=FONT)
        ttk.Style(self).configure('Treeview.Heading', font=(FONT[0], 10, 'bold'))

        self.cfg = core.load_config()
        self.jobs = queue.Queue()

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=8, pady=(8, 0))
        nb.add(self._tickers_tab(nb), text='  종목  ')
        nb.add(self._v2_tab(nb), text='  v2 장부  ')
        nb.add(self._mail_tab(nb), text='  메일  ')
        nb.add(self._task_tab(nb), text='  스케줄 · 로그  ')

        self.status = tk.StringVar(value='준비')
        ttk.Label(self, textvariable=self.status, anchor='w', foreground='#555').pack(fill='x', padx=10, pady=4)

        self.refresh_tickers()
        self.refresh_v2()
        self.after(200, self._poll)
        self.background(core.task_status, lambda r: self.task_var.set(r))

    # ── 공통 ──
    def background(self, fn, done=None, busy=None):
        """오래 걸리는 작업(네트워크·메일·PowerShell)은 화면이 멈추지 않게 별도 스레드에서 돌린다."""
        if busy:
            self.status.set(busy)

        def work():
            try:
                self.jobs.put((done, fn(), None))
            except Exception as e:  # noqa: BLE001
                self.jobs.put((done, None, e))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        while not self.jobs.empty():
            done, result, err = self.jobs.get()
            if err:
                self.status.set('오류')
                messagebox.showerror('오류', str(err), parent=self)
            else:
                self.status.set('완료')
                if done:
                    done(result)
        self.after(200, self._poll)

    def save_config(self):
        core.save_json(core.CONFIG_PATH, self.cfg)
        self.status.set('설정 저장됨')

    # ── 종목 탭 ──
    def _tickers_tab(self, parent):
        f = ttk.Frame(parent, padding=8)
        cols = [('on', '사용', 50), ('sym', '심볼', 90), ('name', '이름', 140), ('levels', '고점대비 낙폭(%)', 120),
                ('daily', '하루급락', 70), ('price', '현재가', 110), ('price_krw', '현재가(원)', 110),
                ('cap', '시가총액', 85), ('chg', '전일 대비', 80),
                ('dd', '고점 대비', 80), ('iv_low', '보수', 70), ('iv', '내재가치(기본)', 100),
                ('iv_high', '낙관', 70), ('mos', '안전마진', 75),
                ('stage', '알림 단계', 75), ('next', '다음 가격선', 120), ('earn', '다음 실적', 105),
                ('checked', '마지막 점검', 125)]
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show='headings', selectmode='browse')
        self.col_labels = {key: label for key, label, _ in cols}
        for key, label, w in cols:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=w, anchor='w' if key in ('sym', 'name', 'levels', 'checked') else 'center')
        self.tree.tag_configure('off', foreground='#aaa')
        self.tree.tag_configure('alert', foreground='#c0392b')
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.tree.bind('<Double-1>', self._on_double)
        # 머리글: 클릭 = 정렬(다시 누르면 반대 방향, 세 번째는 해제), 끌어 놓기 = 열 순서 변경. 둘 다 config의 ui에 저장
        self.tree.bind('<ButtonPress-1>', self._head_press, add='+')
        self.tree.bind('<B1-Motion>', self._head_motion, add='+')
        self.tree.bind('<ButtonRelease-1>', self._head_release, add='+')
        self._drag_col = None
        order = [c for c in (self.cfg.get('ui') or {}).get('columns') or [] if c in self.col_labels]
        if order:
            # 저장된 순서 이후에 새로 생긴 열은 기본 순서상 바로 뒤 열의 앞에 끼워 넣는다 (저장 순서를 버리지 않는다).
            # 뒤 열 기준이라 보수는 내재가치 앞, 낙관은 그 뒤에 붙는다 — 뒤 열이 없으면 맨 끝
            keys = list(self.col_labels)
            for k in reversed(keys):
                if k not in order:
                    nxt = next((n for n in keys[keys.index(k) + 1:] if n in order), None)
                    order.insert(order.index(nxt) if nxt else len(order), k)
            self.tree['displaycolumns'] = order
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

        bar = ttk.Frame(f)
        bar.grid(row=1, column=0, sticky='w', pady=(8, 0))
        for text, cmd in [('추가', self.add_ticker), ('수정', self.edit_ticker), ('삭제', self.delete_ticker),
                          ('사용 켜기/끄기', self.toggle_ticker), ('▲', lambda: self.move(-1)), ('▼', lambda: self.move(1)),
                          ('화면 새로고침', self.refresh_tickers), ('알림 상태 초기화', self.reset_alerts),
                          ('지금 점검 실행', self.run_now)]:
            ttk.Button(bar, text=text, command=cmd).pack(side='left', padx=(0, 6))
        ttk.Label(f, text='"지금 점검 실행"은 실제 점검과 같습니다 — 조건에 맞으면 메일이 나갑니다. '
                          '현재가·고점 대비는 마지막 점검 결과입니다.', foreground='#777').grid(row=2, column=0, sticky='w', pady=(6, 0))
        return f

    def refresh_tickers(self):
        # 모니터가 분석 문서(md) 동기화로 config.json을 고쳤을 수 있으니 매번 디스크에서 다시 읽는다
        self.cfg = core.load_config()
        full = core.load_json(core.STATE_PATH, {})
        state = full.get('tickers', {})
        usdkrw = (full.get('fx') or {}).get('USDKRW')   # 마지막 점검 때 받은 원/달러 환율
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.cfg['tickers']):
            st = state.get(t['symbol'], {})
            last = st.get('last') or {}
            on = t.get('enabled', True)
            tags = ('off',) if not on else (('alert',) if st.get('level') or st.get('price_hits') else ())
            below = [pa['price'] for pa in t.get('price_alerts', []) if last and pa['price'] < last['price']]
            nxt = f'{max(below):,.0f} ({max(below) / last["price"] - 1:+.1%})' if below else '-'
            iv = t.get('iv_base')
            mos = f'{(iv - last["price"]) / iv:+.1%}' if iv and last else '-'
            e = st.get('earnings') or {}
            earn = (e['next'] + (' 추정' if e.get('estimated') else '')) if e.get('next') else '-'
            cur = last.get('currency', '') if last else ''
            krw = (last['price'] if cur == 'KRW' else last['price'] * usdkrw if cur == 'USD' and usdkrw else None) if last else None
            krw_text = f'{krw:,.0f}원' if krw is not None else '-'
            self.tree.insert('', 'end', iid=str(i), tags=tags, values=(
                '●' if on else '○', t['symbol'], t['name'], _levels_text(t['levels']), f'-{t["daily_drop_pct"]}%',
                f'{last["price"]:,.2f} {last.get("currency", "")}' if last else '-',
                krw_text,
                core.cap_text(st.get('mcap')),
                f'{last["change"] * 100:+.1f}%' if last else '-',
                f'{last["dd"] * 100:+.1f}%' if last else '-',
                _iv_text(t.get('iv_low')), _iv_text(iv), _iv_text(t.get('iv_high')), mos,
                f'-{st["level"]}%' if st.get('level') else '-',
                nxt, earn, last.get('checked', '-')))
        self._apply_sort()

    # ── 표 머리글: 정렬 · 열 끌어 옮기기 ──
    def _ui(self):
        return self.cfg.setdefault('ui', {})

    def _display_cols(self):
        cols = list(self.tree['displaycolumns'])
        return list(self.tree['columns']) if cols in ([], ['#all']) else cols

    def _col_at(self, x):
        idx = int(self.tree.identify_column(x)[1:]) - 1   # '#3' → 2 (표시 순서 기준)
        cols = self._display_cols()
        return cols[idx] if 0 <= idx < len(cols) else None

    def _head_press(self, e):
        self._drag_col = self._col_at(e.x) if self.tree.identify_region(e.x, e.y) == 'heading' else None

    def _head_motion(self, e):
        if self._drag_col:
            moved = self.tree.identify_region(e.x, e.y) == 'heading' and self._col_at(e.x) != self._drag_col
            self.tree.configure(cursor='exchange' if moved else '')

    def _head_release(self, e):
        src, self._drag_col = self._drag_col, None
        self.tree.configure(cursor='')
        if not src or self.tree.identify_region(e.x, e.y) != 'heading':
            return
        dst = self._col_at(e.x)
        if dst == src:
            self._toggle_sort(src)
        elif dst:
            cols = self._display_cols()
            right = cols.index(dst) > cols.index(src)   # 오른쪽으로 끌면 놓은 열의 뒤, 왼쪽이면 앞
            cols.remove(src)
            cols.insert(cols.index(dst) + right, src)
            self.tree['displaycolumns'] = cols
            self._ui()['columns'] = cols
            self.save_config()

    def _toggle_sort(self, col):
        """오름차순 → 내림차순 → 해제(설정 파일 순서)."""
        cur = self._ui().get('sort')
        if not cur or cur[0] != col:
            self._ui()['sort'] = [col, False]
        elif not cur[1]:
            self._ui()['sort'] = [col, True]
        else:
            self._ui().pop('sort', None)
        self.save_config()
        self.refresh_tickers()

    def _apply_sort(self):
        sort = self._ui().get('sort')
        for key, label in self.col_labels.items():
            mark = (' ▼' if sort[1] else ' ▲') if sort and sort[0] == key else ''
            self.tree.heading(key, text=label + mark)
        if not sort or sort[0] not in self.col_labels:
            return
        col, desc = sort
        rows = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children('')]
        have = [(_sort_key(v), iid) for v, iid in rows if v.strip() not in ('', '-')]
        none = [iid for v, iid in rows if v.strip() in ('', '-')]
        have.sort(key=lambda r: r[0], reverse=desc)
        for pos, iid in enumerate([iid for _, iid in have] + none):   # 값 없는 행('-')은 방향과 무관하게 맨 아래
            self.tree.move(iid, '', pos)

    def _on_double(self, e):
        if self.tree.identify_region(e.x, e.y) == 'cell':
            self.edit_ticker()

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('알림', '종목을 먼저 선택하세요.', parent=self)
            return None
        return int(sel[0])

    def add_ticker(self):
        TickerDialog(self, None, self._on_ticker_saved)

    def edit_ticker(self):
        i = self._selected()
        if i is not None:
            TickerDialog(self, i, self._on_ticker_saved)

    def _on_ticker_saved(self, index, t):
        if index is None:
            self.cfg['tickers'].append(t)
        else:
            self.cfg['tickers'][index] = t
        self.save_config()
        self.refresh_tickers()

    def delete_ticker(self):
        i = self._selected()
        if i is not None and messagebox.askyesno('삭제', f'{self.cfg["tickers"][i]["symbol"]} 을(를) 목록에서 뺄까요?', parent=self):
            del self.cfg['tickers'][i]
            self.save_config()
            self.refresh_tickers()

    def toggle_ticker(self):
        i = self._selected()
        if i is not None:
            t = self.cfg['tickers'][i]
            t['enabled'] = not t.get('enabled', True)
            self.save_config()
            self.refresh_tickers()
            self.tree.selection_set(str(i))

    def move(self, d):
        i = self._selected()
        if i is None or not 0 <= i + d < len(self.cfg['tickers']):
            return
        ts = self.cfg['tickers']
        ts[i], ts[i + d] = ts[i + d], ts[i]
        self._ui().pop('sort', None)   # ▲▼는 설정 파일 순서를 바꾼다 — 정렬 중이면 결과가 안 보이므로 정렬 해제
        self.save_config()
        self.refresh_tickers()
        self.tree.selection_set(str(i + d))

    def reset_alerts(self):
        """선택한 종목(선택이 없으면 전체)의 알림 상태를 지운다 — 다음 점검에서 같은 알림이 다시 나간다."""
        sel = self.tree.selection()
        sym = self.cfg['tickers'][int(sel[0])]['symbol'] if sel else None
        target = sym or '전체 종목'
        if not messagebox.askyesno(
                '알림 상태 초기화',
                f'{target}의 알림 상태(구간 단계·가격선 도달·급락·실적 D-3 기록)를 지울까요?\n\n'
                '다음 점검에서 지금 조건에 맞는 알림이 다시 나갑니다.\n'
                '시세 기록·최고가·공시 기록은 그대로 둡니다.', parent=self):
            return

        def done(syms):
            self.refresh_tickers()
            messagebox.showinfo('완료', f'초기화: {", ".join(syms) or "대상 없음"}\n'
                                       '"지금 점검 실행"을 누르면 바로 알림이 나갑니다.', parent=self)
        core.setup_logging()
        self.background(lambda: core.reset_alerts(sym), done, busy='초기화 중…')

    def run_now(self):
        def done(msg):
            self.refresh_tickers()
            self.refresh_v2()
            messagebox.showinfo('점검 결과', msg, parent=self)
        core.setup_logging()
        self.background(core.run_check, done, busy='점검 중… (사이트가 잠들어 있으면 1분쯤 걸립니다)')

    # ── 메일 탭 ──
    def _mail_tab(self, parent):
        f = ttk.Frame(parent, padding=16)
        em = self.cfg['email']
        self.v_sender = tk.StringVar(value=em['sender'])
        self.v_recipient = tk.StringVar(value=em['recipient'])
        self.v_pw = tk.StringVar()
        self.v_recovery = tk.BooleanVar(value=em.get('send_recovery', True))
        self.v_weekly = tk.BooleanVar(value=em.get('weekly_summary', True))
        self.v_hyst = tk.StringVar(value=str(self.cfg.get('hysteresis_pct', 3)))
        self.pw_state = tk.StringVar(value='저장됨 ✓' if core.load_password() else '미설정')

        rows = [('보내는 Gmail', ttk.Entry(f, textvariable=self.v_sender, width=40)),
                ('받는 주소', ttk.Entry(f, textvariable=self.v_recipient, width=40))]
        for r, (label, w) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky='w', pady=4)
            w.grid(row=r, column=1, sticky='w', pady=4)

        ttk.Label(f, text='앱 비밀번호').grid(row=2, column=0, sticky='w', pady=4)
        pw = ttk.Frame(f)
        pw.grid(row=2, column=1, sticky='w')
        ttk.Entry(pw, textvariable=self.v_pw, show='•', width=24).pack(side='left')
        ttk.Label(pw, textvariable=self.pw_state, foreground='#2e7d32').pack(side='left', padx=8)
        ttk.Label(f, text='Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호(16자리). '
                          '비밀번호는 파일이 아니라 윈도 자격 증명 관리자에 저장됩니다.\n'
                          '바꿀 때만 입력하세요 — 비워 두면 기존 값을 유지합니다.',
                  foreground='#777').grid(row=3, column=1, sticky='w', pady=(0, 10))

        ttk.Checkbutton(f, text='회복 알림도 받기 (구간 해제·신고가 회복)', variable=self.v_recovery).grid(row=4, column=1, sticky='w')
        ttk.Checkbutton(f, text='매주 월요일 아침 요약 메일 (모니터 정상 동작 확인용)', variable=self.v_weekly).grid(row=5, column=1, sticky='w')
        ttk.Label(f, text='해제 여유 (%p)').grid(row=6, column=0, sticky='w', pady=(10, 4))
        hy = ttk.Frame(f)
        hy.grid(row=6, column=1, sticky='w', pady=(10, 4))
        ttk.Spinbox(hy, from_=0, to=10, textvariable=self.v_hyst, width=5).pack(side='left')
        ttk.Label(hy, text='예: 3이면 -20% 구간은 -17% 위로 올라와야 해제', foreground='#777').pack(side='left', padx=8)

        bar = ttk.Frame(f)
        bar.grid(row=7, column=1, sticky='w', pady=(16, 0))
        ttk.Button(bar, text='저장', command=self.save_mail).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='테스트 메일 보내기', command=self.test_mail).pack(side='left')
        return f

    def save_mail(self):
        try:
            hyst = float(self.v_hyst.get())
        except ValueError:
            messagebox.showerror('오류', '해제 여유는 숫자로 입력하세요.', parent=self)
            return False
        self.cfg['email'].update(sender=self.v_sender.get().strip(), recipient=self.v_recipient.get().strip(),
                                 send_recovery=self.v_recovery.get(), weekly_summary=self.v_weekly.get())
        self.cfg['hysteresis_pct'] = hyst
        pw = self.v_pw.get().replace(' ', '')
        if pw:
            core.save_password(self.cfg['email']['sender'], pw)
            self.v_pw.set('')
            self.pw_state.set('저장됨 ✓')
        self.save_config()
        return True

    def test_mail(self):
        if self.save_mail():
            self.background(lambda: core.send_test_mail(self.cfg),
                            lambda _: messagebox.showinfo('완료', '테스트 메일을 보냈습니다. 받은편지함을 확인하세요.', parent=self),
                            busy='테스트 메일 보내는 중…')

    # ── v2 장부 탭 — 시뮬레이터 장부(PORTFOLIO.html)를 마지막 점검 시세로 본다 ──
    QUARTERLY = os.path.join(os.path.dirname(os.path.dirname(core.BASE)), '체크리스트 검증', 'src', 'quarterly.py')

    def _v2_tab(self, parent):
        f = ttk.Frame(parent, padding=8)
        self.v2_head = tk.StringVar(value='')
        self.v2_sub = tk.StringVar(value='')
        ttk.Label(f, textvariable=self.v2_head, font=(FONT[0], 12, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(f, textvariable=self.v2_sub, foreground='#555').grid(row=1, column=0, sticky='w', pady=(2, 6))
        cols = [('rank', '순위', 45), ('name', '종목', 150), ('sector', '업종', 95), ('grade', '등급', 45),
                ('shares', '보유', 60), ('avg', '평단(원)', 95), ('cur', '현재가(원)', 95), ('val', '평가액(원)', 110),
                ('ret', '수익률', 70), ('w', '비중', 60), ('chg', '전일 대비', 70), ('dd', '고점 대비', 70),
                ('earn', '다음 실적', 105), ('entry', '진입일', 90)]
        self.v2_tree = ttk.Treeview(f, columns=[c[0] for c in cols], show='headings', selectmode='browse')
        for key, label, w in cols:
            self.v2_tree.heading(key, text=label)
            self.v2_tree.column(key, width=w, anchor='w' if key in ('name', 'sector') else 'center')
        self.v2_tree.tag_configure('over', foreground='#c0392b')
        self.v2_tree.tag_configure('up', foreground='#c0392b')
        self.v2_tree.tag_configure('down', foreground='#1f5fbf')
        self.v2_tree.grid(row=2, column=0, sticky='nsew')
        f.rowconfigure(2, weight=1)
        f.columnconfigure(0, weight=1)
        bar = ttk.Frame(f)
        bar.grid(row=3, column=0, sticky='w', pady=(8, 0))
        ttk.Button(bar, text='화면 새로고침', command=self.refresh_v2).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='보유 현황 웹 화면 열기', command=lambda: os.startfile(core.V2_PAGE)).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='분기 재점검 지금 실행…', command=self.run_quarterly).pack(side='left', padx=(0, 6))
        ttk.Label(f, text='현재가는 마지막 점검(30분마다) 시세 · 빨강 = 이익 / 파랑 = 손실 (국내 관행) · 비중이 10%를 넘으면 빨간 글씨 — '
                          '분기 재점검이 5%로 되돌립니다. 장부는 분기 재점검만 고칩니다(이 화면은 읽기 전용).',
                  foreground='#777').grid(row=4, column=0, sticky='w', pady=(6, 0))
        return f

    def refresh_v2(self):
        led = core.read_ledger()
        self.v2_tree.delete(*self.v2_tree.get_children())
        if not led:
            self.v2_head.set('v2 장부를 읽지 못했습니다 — public/reports/PORTFOLIO.html 확인')
            return
        full = core.load_json(core.STATE_PATH, {})
        tstate = full.get('tickers', {})
        fx = (full.get('fx') or {}).get('USDKRW') or led['start'].get('fx')
        rows, total = core.v2_snapshot(led, tstate, fx)
        cost = sum(r['avgPrice'] * r['shares'] for r in rows)
        pnl = sum(r['val'] for r in rows) - cost
        start = led['start']
        ret = total / start['capital'] - 1
        self.v2_head.set(f'총자산 {total:,.0f}원  ({ret:+.2%}, {start["date"]} 시작 {start["capital"] / 1e8:g}억)   ·   '
                         f'평가손익 {pnl:+,.0f}원   ·   현금 {led["cash"]:,.0f}원 ({led["cash"] / total:.1%})')
        lr = led.get('lastReview')
        self.v2_sub.set(f'보유 {len(rows)}종목 · 비중 {min(r["w"] for r in rows):.1%}~{max(r["w"] for r in rows):.1%} · '
                        f'마지막 재점검 {lr["date"] + " (매도 " + str(lr["sold"]) + " · 신규 " + str(lr["bought"]) + ")" if lr else "없음"} · '
                        f'다음 재점검 {core.next_review()} 07:00 (작업 V2QuarterlyReview) · 환율 {fx:,.2f}원')
        for r in rows:
            st = tstate.get(r['code']) or {}
            last = st.get('last') or {}
            e = st.get('earnings') or {}
            rr = r['krw'] / r['avgPrice'] - 1
            tags = ('over',) if r['w'] > core.V2_TRIM else (('up',) if rr > 0 else ('down',) if rr < 0 else ())
            self.v2_tree.insert('', 'end', values=(
                r['rank'], f'{r["name"]} ({r["code"]})', r['sector'], r['grade'], f'{r["shares"]}주',
                f'{r["avgPrice"]:,.0f}', f'{r["krw"]:,.0f}', f'{r["val"]:,.0f}', f'{rr:+.1%}', f'{r["w"]:.1%}',
                f'{r["change"]:+.1%}' if r['change'] is not None else '-',
                f'{last["dd"]:+.1%}' if last.get('dd') is not None else '-',
                (e['next'] + (' 추정' if e.get('estimated') else '')) if e.get('next') else '-',
                r.get('entryDate', '-')), tags=tags)

    def run_quarterly(self):
        if not messagebox.askyesno(
                '분기 재점검', 'SEC 재무·주가를 새로 받고(약 2시간) 순위를 다시 계산해 장부를 규칙대로 바꾼 뒤 '
                '커밋·푸시하고 결과 메일을 보냅니다.\n원래는 1·4·7·10월 1일 07:00에 자동으로 돕니다.\n\n지금 실행할까요?', parent=self):
            return
        import subprocess
        subprocess.Popen([core._pythonw(), self.QUARTERLY], cwd=os.path.dirname(os.path.dirname(self.QUARTERLY)))
        self.status.set('분기 재점검을 백그라운드에서 시작했습니다 — 진행은 체크리스트 검증/logs/quarterly_<분기>.log, 끝나면 메일')

    # ── 스케줄·로그 탭 ──
    def _task_tab(self, parent):
        f = ttk.Frame(parent, padding=8)
        self.task_var = tk.StringVar(value='확인 중…')
        ttk.Label(f, textvariable=self.task_var).pack(anchor='w')
        bar = ttk.Frame(f)
        bar.pack(anchor='w', pady=6)
        ttk.Button(bar, text='스케줄 등록 (30분마다)', command=lambda: self._task(core.task_register)).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='스케줄 해제', command=lambda: self._task(core.task_unregister)).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='상태 확인', command=lambda: self.background(core.task_status, self.task_var.set)).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='로그 새로고침', command=self.load_log).pack(side='left')
        ttk.Label(f, text='※ 이 PC가 켜져 있을 때만 동작합니다. 미국장은 한국 시간 밤 10:30~새벽 6:00입니다.',
                  foreground='#777').pack(anchor='w')
        self.log_box = ScrolledText(f, font=('Consolas', 9), wrap='none')
        self.log_box.pack(fill='both', expand=True, pady=(6, 0))
        self.load_log()
        return f

    def _task(self, fn):
        def done(msg):
            messagebox.showinfo('스케줄', msg, parent=self)
            self.background(core.task_status, self.task_var.set)
        self.background(fn, done, busy='작업 스케줄러 처리 중…')

    def load_log(self):
        self.log_box.delete('1.0', 'end')
        if os.path.exists(core.LOG_PATH):
            with open(core.LOG_PATH, encoding='utf-8', errors='replace') as fh:
                self.log_box.insert('end', ''.join(fh.readlines()[-300:]))
            self.log_box.see('end')
        else:
            self.log_box.insert('end', '(아직 로그가 없습니다)')


class TickerDialog(tk.Toplevel):
    def __init__(self, app, index, on_save):
        super().__init__(app)
        self.app, self.index, self.on_save = app, index, on_save
        t = app.cfg['tickers'][index] if index is not None else {
            'symbol': '', 'name': '', 'enabled': True, 'levels': [10, 20, 30, 50], 'daily_drop_pct': 5}
        self.enabled = t.get('enabled', True)
        self.extra = {k: t[k] for k in ('memo', 'target_price', 'group') if k in t}   # 화면에 없는 항목은 그대로 보존
        self.title('종목 수정' if index is not None else '종목 추가')
        self.transient(app)
        self.resizable(False, False)

        self.v_sym = tk.StringVar(value=t['symbol'])
        self.v_name = tk.StringVar(value=t['name'])
        self.v_levels = tk.StringVar(value=_levels_text(t['levels']))
        self.v_daily = tk.StringVar(value=str(t['daily_drop_pct']))
        self.v_check = tk.StringVar()

        f = ttk.Frame(self, padding=16)
        f.pack()
        ttk.Label(f, text='심볼').grid(row=0, column=0, sticky='w', pady=4)
        sym = ttk.Frame(f)
        sym.grid(row=0, column=1, sticky='w')
        ttk.Entry(sym, textvariable=self.v_sym, width=16).pack(side='left')
        ttk.Button(sym, text='시세 확인', command=self.check).pack(side='left', padx=6)
        ttk.Label(f, text=SYMBOL_HINT, foreground='#777').grid(row=1, column=1, sticky='w')
        ttk.Label(f, textvariable=self.v_check, foreground='#2e7d32').grid(row=2, column=1, sticky='w', pady=(0, 6))

        for r, (label, var, hint) in enumerate([
                ('이름', self.v_name, '메일 제목에 쓰는 이름'),
                ('고점대비 낙폭 (%)', self.v_levels, '사상 최고가 대비 몇 % 빠지면 알릴지, 쉼표로 구분 (예: 15, 25, 35, 50)'),
                ('하루 급락 (%)', self.v_daily, '전일 종가 대비 이만큼 빠지면 알림 (예: 5)')], start=3):
            ttk.Label(f, text=label).grid(row=r * 2, column=0, sticky='w', pady=(4, 0))
            ttk.Entry(f, textvariable=var, width=36).grid(row=r * 2, column=1, sticky='w', pady=(4, 0))
            ttk.Label(f, text=hint, foreground='#777').grid(row=r * 2 + 1, column=1, sticky='w')

        self.v_sync = tk.BooleanVar(value=t.get('md_sync', False))
        ttk.Checkbutton(f, text='분석 문서(02.종목분석/*.md)와 자동 동기화 — 켜면 아래 가격선·내재가치는 md 값으로 덮어씀',
                        variable=self.v_sync).grid(row=24, column=1, sticky='w', pady=(10, 0))
        ttk.Label(f, text='가격 알림선').grid(row=12, column=0, sticky='nw', pady=(8, 0))
        self.t_prices = tk.Text(f, width=48, height=6, font=FONT)
        self.t_prices.grid(row=12, column=1, sticky='w', pady=(8, 0))
        self.t_prices.insert('1.0', '\n'.join(f'{pa["price"]:g}, {pa["label"]}' for pa in t.get('price_alerts', [])))
        ttk.Label(f, text='한 줄에 "가격, 의미" (예: 385, 목표매수가 — 1회차 매수). 이 가격 아래로 처음 내려가면 알림.',
                  foreground='#777').grid(row=13, column=1, sticky='w')
        self.v_note = tk.StringVar(value=t.get('valuation_note', ''))
        ttk.Label(f, text='근거 메모').grid(row=14, column=0, sticky='w', pady=(6, 0))
        ttk.Entry(f, textvariable=self.v_note, width=48).grid(row=14, column=1, sticky='w', pady=(6, 0))
        ttk.Label(f, text='메일에 함께 표시 (예: 2026-07-26 분석, 08-14 실적 점검)', foreground='#777').grid(row=15, column=1, sticky='w')

        ttk.Label(f, text='내재가치').grid(row=16, column=0, sticky='w', pady=(6, 0))
        ivf = ttk.Frame(f)
        ivf.grid(row=16, column=1, sticky='w', pady=(6, 0))
        self.v_iv = {}
        for key, label in [('iv_low', '보수'), ('iv_base', '기본'), ('iv_high', '낙관')]:
            self.v_iv[key] = tk.StringVar(value=f'{t[key]:g}' if t.get(key) else '')
            ttk.Label(ivf, text=label).pack(side='left', padx=(0, 4))
            ttk.Entry(ivf, textvariable=self.v_iv[key], width=9).pack(side='left', padx=(0, 12))
        ttk.Label(f, text='분석 문서 4단계의 시나리오별 내재가치. 기본으로 안전마진을 계산합니다 (비워도 됨).',
                  foreground='#777').grid(row=17, column=1, sticky='w')

        self.v_compare = tk.StringVar(value=', '.join(t.get('compare', [])))
        self.v_cik = tk.StringVar(value=str(t.get('cik', '')))
        self.v_earn = tk.StringVar(value=t.get('next_earnings', ''))
        for r, (label, var, hint) in enumerate([
                ('비교 종목', self.v_compare, '하락 알림에 원인 판별용으로 함께 표시 — 지수·동종 종목 (예: ^GSPC, ^NDX, GOOGL)'),
                ('SEC CIK', self.v_cik, '미국 종목의 SEC 회사 번호 — 넣으면 8-K·10-Q 공시와 실적 발표를 알림 (MSFT 789019)'),
                ('다음 실적 발표일', self.v_earn, 'YYYY-MM-DD. 비워 두면 SEC 공시 기록으로 추정 (D-3에 준비 알림)')], start=9):
            ttk.Label(f, text=label).grid(row=r * 2, column=0, sticky='w', pady=(6, 0))
            ttk.Entry(f, textvariable=var, width=48).grid(row=r * 2, column=1, sticky='w', pady=(6, 0))
            ttk.Label(f, text=hint, foreground='#777').grid(row=r * 2 + 1, column=1, sticky='w')

        bar = ttk.Frame(f)
        bar.grid(row=30, column=1, sticky='e', pady=(14, 0))
        ttk.Button(bar, text='저장', command=self.save).pack(side='left', padx=(0, 6))
        ttk.Button(bar, text='취소', command=self.destroy).pack(side='left')
        self.grab_set()

    def check(self):
        sym = self.v_sym.get().strip().upper()
        self.v_sym.set(sym)
        self.v_check.set('확인 중…')

        def done(q):
            self.v_check.set(f'✓ {q["name"]} — {q["price"]:,.2f} {q.get("currency", "")} ({q.get("source", "")})')
            if not self.v_name.get().strip():
                self.v_name.set(q['name'])

        def fail():
            try:
                return core.fetch_quote(self.app.cfg, sym)
            except Exception:
                self.v_check.set('')
                raise
        self.app.background(fail, done)

    def save(self):
        sym = self.v_sym.get().strip().upper()
        try:
            levels = sorted({int(x) for x in self.v_levels.get().replace(' ', '').split(',') if x})
            daily = float(self.v_daily.get())
            if not sym or not levels or not all(0 < v < 100 for v in levels) or daily <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('입력 확인', '심볼을 입력하고, 기준선은 1~99 사이 정수를 쉼표로, 하루 급락은 양수로 입력하세요.', parent=self)
            return
        prices = []
        for line in self.t_prices.get('1.0', 'end').splitlines():
            if not line.strip():
                continue
            p, _, label = line.partition(',')
            try:
                prices.append({'price': float(p.replace('$', '').strip()), 'label': label.strip() or '가격선'})
            except ValueError:
                messagebox.showerror('입력 확인', f'가격 알림선을 읽을 수 없습니다: "{line}"\n"가격, 의미" 형식으로 입력하세요.', parent=self)
                return
        ivs = {}
        for key, var in self.v_iv.items():
            s = var.get().replace('$', '').replace(',', '').strip()
            if s:
                try:
                    ivs[key] = float(s)
                except ValueError:
                    messagebox.showerror('입력 확인', '내재가치는 숫자로 입력하세요.', parent=self)
                    return
        compare = [s.strip().upper() for s in self.v_compare.get().split(',') if s.strip()]
        cik, earn = self.v_cik.get().strip(), self.v_earn.get().strip()
        try:
            if cik:
                cik = int(cik)
            if earn:
                dt.date.fromisoformat(earn)
        except ValueError:
            messagebox.showerror('입력 확인', 'SEC CIK는 숫자, 다음 실적 발표일은 YYYY-MM-DD 형식으로 입력하세요.', parent=self)
            return
        opt = {k: v for k, v in (('compare', compare), ('cik', cik), ('next_earnings', earn)) if v}
        dup = [i for i, t in enumerate(self.app.cfg['tickers']) if t['symbol'] == sym and i != self.index]
        if dup:
            messagebox.showerror('중복', f'{sym} 은(는) 이미 목록에 있습니다.', parent=self)
            return
        self.on_save(self.index, {'symbol': sym, 'name': self.v_name.get().strip() or sym, 'enabled': self.enabled,
                                  'levels': levels, 'daily_drop_pct': daily,
                                  'price_alerts': sorted(prices, key=lambda pa: -pa['price']),
                                  'valuation_note': self.v_note.get().strip(), **ivs, **opt, **self.extra,
                                  'md_sync': self.v_sync.get()})
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
