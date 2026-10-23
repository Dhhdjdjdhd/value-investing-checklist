"""체크리스트 정량 판정: 회계연도 행마다 '그 시점까지 10년(최소 5년)' 이력으로 계산.

파라미터 P(dict)로 문턱을 바꿔 최적화한다. 기본값 = 문서(00·01·02·04) 그대로.
"""
import numpy as np
import pandas as pd

DEFAULT = dict(
    roic_min=0.15,          # 3단계·스크린 D
    roic_s=0.20,            # S ①
    ltd_ni_warn=4.0, ltd_ni_fail=6.0,
    fcf_ratio_warn=0.8,     # (FCF−SBC)/순이익 3년 평균
    dilution_warn=0.02,     # 5년 연평균 주식수 증가율
    cyc_0710=0.30, cyc_10y=0.20, use_cyclical=True,
    min_years=5,
)


def _cagr(a, b, n):
    return (b / a) ** (1 / n) - 1 if a > 0 and b > 0 and n > 0 else np.nan


def row_features(g, P=DEFAULT):
    """g: 한 회사의 연도 정렬 DataFrame. 각 행 시점의 판정 지표를 반환."""
    out = []
    cy = g.cy.values
    for i in range(len(g)):
        lo = max(0, i - 9)
        w = g.iloc[lo:i + 1]
        n = len(w)
        r = {"idx": g.index[i]}
        r["n_years"] = n
        roic = w.roic.values
        r["roic_last"] = roic[-1]
        r["roic_med5"] = np.nanmedian(roic[-5:]) if np.isfinite(roic[-5:]).any() else np.nan
        r["roic_min10"] = np.nanmin(roic) if np.isfinite(roic).sum() >= min(n, 8) else np.nan
        eps = w.eps_c.values
        ni = w.ni.values
        rev = w.rev.values
        r["eps5_up"] = n >= 6 and eps[-1] > eps[-6] if n >= 6 else (n >= 5 and eps[-1] > eps[0])
        r["rev5_up"] = n >= 6 and rev[-1] > rev[-6] if n >= 6 else (n >= 5 and rev[-1] > rev[0])
        k = n - 1
        r["eps_cagr"] = _cagr(eps[0], eps[-1], k)
        r["rev_cagr"] = _cagr(rev[0], rev[-1], k)
        r["eps_cagr5"] = _cagr(eps[-6], eps[-1], 5) if n >= 6 else np.nan
        # EPS 10년 일관 우상향: 매년 전년 이상, 코로나(cy 2020·2021) 단일 연도 예외 1회
        drops = [j for j in range(1, n) if not (eps[j] >= eps[j - 1])]
        covid = [j for j in drops if cy[lo + j] in (2020, 2021)]
        r["eps_consistent"] = n >= 8 and (len(drops) == 0 or (len(drops) == 1 and len(covid) == 1))
        r["eps_drops"] = len(drops)
        # 경기순환(숫자): FY2007~10 영업이익 고점 대비 저점 −30%, 10년 내 전년 대비 −20% 감익(2020 제외)
        op = w.op.values
        cyw = cy[lo:i + 1]
        m0710 = (cyw >= 2007) & (cyw <= 2010)
        c1 = False
        if m0710.sum() >= 3:
            seg = op[m0710]
            pk = np.nanmax(seg)
            if pk > 0:
                after = seg[np.nanargmax(seg):]
                c1 = np.nanmin(after) <= pk * (1 - P["cyc_0710"])
        yoy = [(op[j] / op[j - 1] - 1) for j in range(1, n) if op[j - 1] > 0 and cyw[j] != 2020]
        c2 = any(x <= -P["cyc_10y"] for x in yoy)
        r["cyc_0710"], r["cyc_10y"] = c1, c2
        r["cyclical"] = (c1 or c2) if P["use_cyclical"] else False
        # 3단계 지표
        f3 = np.nansum(w.fcf_sbc.values[-3:])
        n3 = np.nansum(ni[-3:])
        r["fcf_ratio"] = f3 / n3 if n3 > 0 else np.nan
        sh = w.sh_adj.values
        r["dilution"] = _cagr(sh[-6], sh[-1], 5) if n >= 6 else np.nan
        r["ni_last"] = ni[-1]
        out.append(r)
    return pd.DataFrame(out).set_index("idx")


def grade(feat, P=DEFAULT):
    """3단계 통과 여부와 등급(S/A/G=일반/X=탈락)."""
    f = feat
    roic_low = ~(f.roic_med5 >= P["roic_min"])
    fail = ((f.n_years < P["min_years"]) | (f.ni_last <= 0)
            | ~f.eps5_up.astype(bool) | ~f.rev5_up.astype(bool) | (f.ltd_ni > P["ltd_ni_fail"]))
    if P.get("roic_mode", "fail") == "fail":  # 스크린 D: 우주 조건 / 'warn': 템플릿 3단계 ⚠️ 1개
        fail |= roic_low
    warn = ((f.ltd_ni > P["ltd_ni_warn"]).astype(int)
            + (roic_low.astype(int) if P.get("roic_mode", "fail") == "warn" else 0)
            + (f.fcf_ratio < P["fcf_ratio_warn"]).astype(int)
            + (f.dilution > P["dilution_warn"]).astype(int)
            + (f.eps_drops >= 2).astype(int))
    cyc = (f.cyc_0710.astype(bool) | f.cyc_10y.astype(bool)) if P["use_cyclical"] else pd.Series(False, index=f.index)
    s = ((f.roic_min10 >= P["roic_s"]) & f.eps_consistent.astype(bool) & (warn == 0) & ~cyc)
    a = (warn <= 1) & ~cyc
    g = np.where(fail, "X", np.where(s, "S", np.where(a, "A", "G")))
    return pd.Series(g, index=f.index), warn
