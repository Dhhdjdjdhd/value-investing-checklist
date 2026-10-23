"""내재가치(총액 기준) — 01 템플릿 4단계 공통 기본값의 기계적 근사.

기본: 할인율 9%, 종료 PER = 10년 회계연도말 PER 중앙값 × 0.6 (상한 22),
      성장률 1~5년 = 10년 EPS CAGR × haircut (0 이상, 상한 g_cap), 6~10년 = 1~5년 × g2_ratio,
      기준 이익 = 최근 회계연도 GAAP 순이익.
보수/낙관: 할인율 ±0.5%p, 종료 PER ∓3배, 성장률 ×0.7 / ×1.2
"""
import numpy as np

VDEFAULT = dict(disc=0.09, tpe_mult=0.6, tpe_cap=22.0, haircut=0.8, g_cap=0.15, g2_ratio=0.6,
                base="ni")  # base: ni(GAAP) | fcf_sbc(FCF−SBC) | min


def dcf(base, g1, g2, disc, tpe):
    v, e = 0.0, base
    for n in range(1, 11):
        e *= 1 + (g1 if n <= 5 else g2)
        v += e / (1 + disc) ** n
    return v + e * tpe / (1 + disc) ** 10


def per_median(per):
    per = per[np.isfinite(per) & (per > 0)]
    if len(per) < 3:
        return np.nan
    m = np.median(per)
    per = per[per < 2 * m]  # 일회성으로 EPS가 왜곡된 해 제외
    return np.median(per)


def intrinsic(base_ni, base_fcf, eps_cagr, per_hist, V=VDEFAULT, rev_cagr=np.nan):
    """(보수, 기본, 낙관) 내재가치 총액."""
    if V["base"] == "ni":
        base = base_ni
    elif V["base"] == "fcf_sbc":
        base = base_fcf
    else:
        base = min(base_ni, base_fcf) if np.isfinite(base_fcf) else base_ni
    pm = per_median(per_hist)
    if not (np.isfinite(base) and base > 0 and np.isfinite(pm)):
        return np.nan, np.nan, np.nan
    tpe = min(pm * V["tpe_mult"], V["tpe_cap"])
    # EPS CAGR을 못 구하면(시작·끝 EPS가 음수 등) 매출 CAGR로 대체 (B10)
    g = eps_cagr if np.isfinite(eps_cagr) else (rev_cagr if np.isfinite(rev_cagr) else 0.0)
    g1 = float(np.clip(g * V["haircut"], 0, V["g_cap"]))
    g2 = g1 * V["g2_ratio"]
    d = V["disc"]
    base_v = dcf(base, g1, g2, d, tpe)
    cons = dcf(base, g1 * 0.7, g2 * 0.7, d + 0.005, max(tpe - 3, 5))
    opt = dcf(base, g1 * 1.2, g2 * 1.2, d - 0.005, tpe + 3)
    return cons, base_v, opt
