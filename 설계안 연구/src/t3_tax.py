# T3. 계좌 배치(세금) 시뮬레이션 — 설계서 §T3 (2026-11-26)
# 같은 80/20(연 8% 명목, 그중 분배금 2%p)을 어느 계좌에 넣느냐에 따라 20·30년 뒤 세후 실질 금액이 얼마나 다른가.
# 예측이 아니라 계산이다. 세율 가정은 결과 md에 출처와 함께 적는다.
import sys
from pathlib import Path
import numpy as np, pandas as pd

OUT = Path(__file__).resolve().parents[1] / 'results'
R, Y, INF = 0.08, 0.02, 0.025          # 명목 총수익, 그중 분배금(연), 물가
TURN = 0.05                             # 연 1회 리밸런스로 실현되는 비율(포트폴리오 대비)
C_ETF = 0.00                            # 보수 차이는 과제 밖(계좌 간 같다고 가정)
T_DIV = 0.154                           # 배당·이자소득 원천세
T_KR_ETF = 0.154                        # 국내상장 해외ETF 매매차익(배당소득)
T_US_CG, US_DED = 0.22, 250e4           # 해외주식 양도세, 연 기본공제
COMP_LIMIT = 2000e4                     # 금융소득종합과세 기준
ISA = dict(현행=dict(limit=2000e4, free=200e4, free_s=400e4, rate=0.099, years=3),
           개정안_미확정=dict(limit=4000e4, free=500e4, free_s=1000e4, rate=0.099, years=3))
PEN_CREDIT_CAP, PEN_TOTAL_CAP = 900e4, 1800e4   # 세액공제 한도 / 연금계좌 납입 한도
PEN_CREDIT = {'5500이하': 0.165, '5500초과': 0.132}
PEN_TAX = 0.055                         # 연금소득세(55~69세). 70대 4.4%, 80세+ 3.3%
PEN_LUMP = 0.165                        # 연금 외 수령(일시) 기타소득세
PRIV_PEN_LIMIT, PRIV_PEN_SEP = 1500e4, 0.165    # 사적연금 연 1,500만 초과 시 분리과세 선택


def grow_taxable(monthly, years, gain_tax, dividend_tax, deduction=0.0, comp_marg=None):
    """일반계좌: 분배금 매년 과세, 리밸런스 실현분 과세, 끝에 전부 매도 과세. 월 적립, 월 복리."""
    bal, basis = 0.0, 0.0
    for y in range(years):
        for m in range(12):
            bal += monthly; basis += monthly
            bal *= (1 + (R - Y)) ** (1 / 12)
        div = bal * Y
        fin_income = div
        realized = bal * TURN; g_real = realized * max(0.0, 1 - basis / bal) if bal > 0 else 0.0
        if gain_tax == 'kr':
            fin_income += g_real
            tax = fin_income * T_DIV
            if comp_marg and fin_income > COMP_LIMIT: tax += (fin_income - COMP_LIMIT) * (comp_marg - T_DIV)
        else:  # 미국 직투: 양도세 별도, 공제 250만
            tax = div * dividend_tax + max(0.0, g_real - deduction) * T_US_CG
            if comp_marg and div > COMP_LIMIT: tax += (div - COMP_LIMIT) * (comp_marg - T_DIV)
        bal += div - tax
        basis += div - tax + g_real * 0  # 실현분은 재매수(원가 상향)
        basis += g_real
    gain = max(0.0, bal - basis)
    if gain_tax == 'kr':
        final_tax = gain * T_KR_ETF
    else:
        final_tax = max(0.0, gain - deduction) * T_US_CG   # 일시 매도(공제 1회). 분할 매도는 별도 시나리오
    return bal, bal - final_tax, basis


def grow_us_split(monthly, years, split_years=10):
    """미국 직투, 마지막에 10년 분할 매도(매년 250만 공제 사용)."""
    bal, net, basis = grow_taxable(monthly, years, 'us', T_DIV, US_DED)
    gain = max(0.0, bal - basis); per = gain / split_years
    tax = sum(max(0.0, per - US_DED) * T_US_CG for _ in range(split_years))
    return bal, bal - tax


def grow_isa(monthly, years, isa, serving=False, to_pension=True):
    """ISA 3년 만기마다 (수익−비과세)×9.9%. 만기금은 연금저축으로 이전(한도 없음, 이전액의 10%·최대 300만 추가 세액공제는 보수적으로 제외).
    연 납입이 한도를 넘는 부분은 일반계좌(국내상장 ETF)로."""
    isa_bal, isa_basis, pen_bal, pen_basis, tax_bal, tax_basis = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0  # pen_basis: 연금으로 이전한 원금(비공제 → 인출 시 비과세)
    yr_limit = isa['limit'] / 12
    free = isa['free_s'] if serving else isa['free']
    for y in range(years):
        for m in range(12):
            a = min(monthly, yr_limit); b = monthly - a
            isa_bal += a; isa_basis += a; tax_bal += b; tax_basis += b
            isa_bal *= (1 + R) ** (1 / 12); pen_bal *= (1 + R) ** (1 / 12); tax_bal *= (1 + (R - Y)) ** (1 / 12)
        if tax_bal > 0:
            div = tax_bal * Y; tax_bal += div * (1 - T_DIV); tax_basis += div * (1 - T_DIV)
        if (y + 1) % isa['years'] == 0:
            g = max(0.0, isa_bal - isa_basis); t = max(0.0, g - free) * isa['rate']
            if to_pension: pen_bal += isa_bal - t; pen_basis += isa_bal - t
            else: tax_bal += isa_bal - t; tax_basis += isa_bal - t
            isa_bal = isa_basis = 0.0
    # 끝: ISA 잔액 만기 처리, 연금 이전분은 운용수익만 연금소득세(원금은 비과세), 일반계좌는 매도 과세
    g = max(0.0, isa_bal - isa_basis); isa_net = isa_bal - max(0.0, g - free) * isa['rate']
    pen_net = pen_basis + max(0.0, pen_bal - pen_basis) * (1 - PEN_TAX)  # 이전 원금 비과세, 이전 후 운용수익만 연금소득세
    tax_net = tax_bal - max(0.0, tax_bal - tax_basis) * T_KR_ETF
    return isa_bal + pen_bal + tax_bal, isa_net + pen_net + tax_net


def grow_pension(monthly, years, credit_rate, refund_to='pension', withdraw='annuity', overflow='isa', isa=ISA['현행']):
    """연금저축+IRP: 연 900만까지 세액공제, 1,800만까지 납입. 환급금은 이듬해 연금계좌 비공제 납입(한도 안)으로 재투자.
    초과 적립은 ISA(현행) 또는 일반계좌. 수령: 연금(5.5%, 공제받은 원금+수익) / 일시(16.5%)."""
    pen_bal, pen_credited, pen_uncredited = 0.0, 0.0, 0.0   # 공제받은 납입원금 / 비공제 원금(인출 시 비과세)
    over_bal, over_basis = 0.0, 0.0
    isa_res = None
    yr_pen = min(monthly * 12, PEN_TOTAL_CAP); yr_over = monthly * 12 - yr_pen
    refund = 0.0
    for y in range(years):
        credited = min(yr_pen, PEN_CREDIT_CAP); uncred = yr_pen - credited
        room = PEN_TOTAL_CAP - yr_pen
        add_pen = min(refund, room) if refund_to == 'pension' else 0.0
        to_over = refund - add_pen
        for m in range(12):
            pen_bal += (yr_pen + add_pen) / 12; over_bal += (yr_over + to_over) / 12; over_basis += (yr_over + to_over) / 12
            pen_bal *= (1 + R) ** (1 / 12); over_bal *= (1 + (R - Y)) ** (1 / 12)
        pen_credited += credited; pen_uncredited += uncred + add_pen
        if over_bal > 0:
            div = over_bal * Y; over_bal += div * (1 - T_DIV); over_basis += div * (1 - T_DIV)
        refund = credited * credit_rate
    # 마지막 해 환급금은 일반계좌로
    over_bal += refund; over_basis += refund
    taxable_part = max(0.0, pen_bal - pen_uncredited)       # 비공제 원금은 비과세
    if withdraw == 'annuity':
        pen_net = pen_uncredited + taxable_part * (1 - PEN_TAX)
    else:
        pen_net = pen_uncredited + taxable_part * (1 - PEN_LUMP)
    over_net = over_bal - max(0.0, over_bal - over_basis) * T_KR_ETF
    return pen_bal + over_bal, pen_net + over_net, taxable_part


def real(x, years): return x / (1 + INF) ** years


def alpha_equiv(target_net, monthly, years):
    """일반계좌(국내상장 ETF)가 같은 세후 금액을 내려면 명목수익이 얼마여야 하나 → 초과분 = 연 %p."""
    global R
    r0 = R; lo, hi = 0.0, 0.10
    for _ in range(60):
        mid = (lo + hi) / 2; R = r0 + mid
        _, net, _ = grow_taxable(monthly, years, 'kr', T_DIV)
        if net < target_net: lo = mid
        else: hi = mid
    R = r0
    return (lo + hi) / 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8'); pd.set_option('display.width', 250)
    rows = []
    for monthly in (100e4, 200e4):
        for years in (20, 30):
            base = grow_taxable(monthly, years, 'kr', T_DIV)
            cases = {
                'A 일반·국내상장 ETF': base[:2],
                'A2 일반·국내상장, 종합과세 26.4%': grow_taxable(monthly, years, 'kr', T_DIV, comp_marg=0.264)[:2],
                'B 일반·미국 직투, 일시 매도': grow_taxable(monthly, years, 'us', T_DIV, US_DED)[:2],
                'B2 일반·미국 직투, 10년 분할 매도': grow_us_split(monthly, years),
                'C ISA 현행(200만)→연금 이전, 초과분 일반': grow_isa(monthly, years, ISA['현행']),
                'C2 ISA 현행 서민형(400만)→연금 이전': grow_isa(monthly, years, ISA['현행'], serving=True),
                'C3 ISA 개정안(500만, 미확정)→연금 이전': grow_isa(monthly, years, ISA['개정안_미확정']),
                'D 연금 900만 공제(16.5%)+비공제, 연금 수령': grow_pension(monthly, years, 0.165)[:2],
                'D2 연금 900만 공제(13.2%)+비공제, 연금 수령': grow_pension(monthly, years, 0.132)[:2],
                'D3 연금 공제(16.5%), 일시 인출 16.5%': grow_pension(monthly, years, 0.165, withdraw='lump')[:2],
            }
            for k, (gross, net) in cases.items():
                rows.append(dict(월적립=int(monthly / 1e4), 기간=years, 계좌=k, 매도전잔액_억=gross / 1e8, 세후_억=net / 1e8, 세후실질_억=real(net, years) / 1e8,
                                 A대비_만=(net - base[1]) / 1e4, A대비_pct=(net / base[1] - 1) * 100,
                                 등가알파_pct=alpha_equiv(net, monthly, years) * 100 if k != 'A 일반·국내상장 ETF' else 0.0))
            print('완료', monthly, years, flush=True)
    D = pd.DataFrame(rows); D.to_csv(OUT / 't3_tax.csv', index=False, encoding='utf-8-sig')
    print(D.to_string(index=False, float_format=lambda v: f'{v:,.2f}'))
    # 민감도: 수익률 6/8/10%, 분배 1/2/3%
    sens = []
    for r in (0.06, 0.08, 0.10):
        for y_ in (0.01, 0.02, 0.03):
            R, Y = r, y_
            a = grow_taxable(100e4, 30, 'kr', T_DIV)[1]; d = grow_pension(100e4, 30, 0.165)[1]; c = grow_isa(100e4, 30, ISA['현행'])[1]
            sens.append(dict(수익=r, 분배=y_, A_억=a / 1e8, D연금_억=d / 1e8, C_ISA_억=c / 1e8, D대비A_pct=(d / a - 1) * 100, C대비A_pct=(c / a - 1) * 100))
    S = pd.DataFrame(sens); S.to_csv(OUT / 't3_sens.csv', index=False, encoding='utf-8-sig'); print(S.to_string(index=False, float_format=lambda v: f'{v:,.2f}'))
