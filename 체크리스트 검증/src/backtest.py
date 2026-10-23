"""체크리스트 포트폴리오 시뮬레이터 (월말 판정 -> 다음 달 보유, 월 수익은 배당 포함 총수익).

진입: 3단계 통과 & 시총≥min_mcap & 제외섹터 아님 & 시총 ≤ 목표가(기본 IV × 등급배수)
비중: 슬롯 N개, 슬롯당 1/N (현금 허용). 우선순위 = 목표가 아래 여유 (목표가−시총)/IV 큰 순
청산(02 §3, 가격 손절 없음):
  ① 논제 붕괴 근사: 새 연간 재무로 3단계 탈락(X) -> 매도
  ③ 갈아타기: 슬롯이 찼고 후보의 여유가 보유 종목 중 최저 여유보다 swap_gap 이상 크면 교체
  ④ 고평가 축소(옵션): 시총 > 낙관 IV × trim_mult 이면 매도
  상장폐지(주가 끊김): 마지막 수익까지 반영 후 현금
비용: 매매 금액의 cost (편도)
"""
import numpy as np
import pandas as pd

from checklist import DEFAULT, grade
from fundamentals import DATA
from valuation import VDEFAULT, intrinsic

PANEL = DATA / "panel"
SDEFAULT = dict(min_mcap=10e9, slots=10, mult={"S": 0.9, "A": 0.85, "G": 0.8}, swap_gap=0.15,
                trim_mult=None, cost=0.001, use_price="iv", allow_grades=("S", "A", "G"),
                rank="room", start="2011-04", end=None, excl_sector=True)


def load(mode="first"):
    ann = pd.read_parquet(PANEL / f"annual_{mode}.parquet")
    mc = pd.read_parquet(PANEL / f"monthly_mcap_{mode}.parquet")
    tri = pd.read_parquet(PANEL / f"monthly_tri_{mode}.parquet")
    dd = pd.read_parquet(PANEL / f"monthly_dd_{mode}.parquet")
    for m in (mc, tri, dd):
        m.columns = m.columns.astype(int)
    # 상품·코인 신탁, 펀드는 기업이 아니므로 유니버스·벤치마크에서 제외 (B14)
    info = ann.drop_duplicates("cik").set_index("cik")
    nm = info["name"].fillna("").str.upper()
    bad = info.index[(info.sic.astype(str).isin(["6221", "6221.0"])) | nm.str.contains(r"\bTRUST\b|\bETF\b|\bFUND\b")]
    keep = [c for c in mc.columns if c not in set(bad)]
    return ann, mc[keep], tri[keep], dd[keep]


def evaluate_rows(ann, P=DEFAULT, V=VDEFAULT):
    g, warn = grade(ann, P)
    ivs = [intrinsic(r.ni, r.fcf_sbc, r.eps_cagr, np.asarray(r.per_hist, dtype=float), V, r.rev_cagr)
           for r in ann[["ni", "fcf_sbc", "eps_cagr", "per_hist", "rev_cagr"]].itertuples()]
    iv = np.array(ivs)
    out = ann[["cik", "cy", "avail", "name", "ticker", "sector_excl", "roic_med5", "roe", "fcf_sbc", "ni",
               "eps_cagr", "opm"]].copy()
    out["grade"], out["warn"] = g.values, warn.values
    out["iv_cons"], out["iv"], out["iv_opt"] = iv[:, 0], iv[:, 1], iv[:, 2]
    return out


def monthly_state(rows, months):
    """월말 t마다 cik별 최신(avail ≤ t) 연도행."""
    r = rows.sort_values("avail")
    grid = pd.DataFrame({"t": months.to_timestamp(how="end").normalize()}).sort_values("t")
    st = pd.merge_asof(grid.assign(k=1).merge(pd.DataFrame({"cik": r.cik.unique(), "k": 1}), on="k").sort_values("t"),
                       r, left_on="t", right_on="avail", by="cik", direction="backward")
    st = st.dropna(subset=["avail"])
    st["m"] = st.t.dt.to_period("M")
    # 재무가 2년 넘게 갱신 안 되면(상장폐지·외국 전환 등) 사용 안 함
    st = st[(st.t - st.avail).dt.days < 730]
    return st


def simulate(ann, mc, tri, dd, P=DEFAULT, V=VDEFAULT, S=SDEFAULT, rows=None, state=None):
    S = {**SDEFAULT, **S}
    if rows is None:
        rows = evaluate_rows(ann, P, V)
    months = mc.index
    if state is None:
        state = monthly_state(rows, months)
    ret = tri.pct_change(fill_method=None)
    m0 = pd.Period(S["start"], "M")
    m1 = pd.Period(S["end"], "M") if S["end"] else months[-1]
    sim_months = [m for m in months if m0 <= m <= m1]
    st_by_m = dict(tuple(state.groupby("m")))
    hold = {}  # cik -> weight
    rets, log, n_hold = [], [], []
    N = S["slots"]
    for k, m in enumerate(sim_months[:-1]):
        nxt = sim_months[k + 1]
        s = st_by_m.get(m)
        cand = pd.DataFrame()
        if s is not None:
            s = s.set_index("cik")
            s = s[s.index.isin(mc.columns)]
            s["mcap"] = mc.loc[m, s.index].values
            s = s.dropna(subset=["mcap"])
            if S["excl_sector"]:
                s = s[~s.sector_excl.fillna(False).astype(bool)]
            s = s[s.mcap >= S["min_mcap"]]
            mult = s.grade.map(S["mult"])
            s["target"] = s.iv * mult
            s["room"] = (s.target - s.mcap) / s.iv
            s["cheap"] = s.iv / s.mcap
            s["dd"] = dd.loc[m, s.index].values if m in dd.index else np.nan
            ok = s.grade.isin(S["allow_grades"])
            if S["use_price"] == "iv":
                ok &= s.iv.notna() & (s.iv > 0) & (s.mcap <= s.target)
            elif S["use_price"] == "dd":  # 스크린 B식: 52주 고점 대비 낙폭
                ok &= s.dd <= -S.get("dd_th", 0.30)
            s["dd_rank"] = -s.dd
            s["fcf_yield"] = s.fcf_sbc / s.mcap
            s["earn_yield"] = s.ni / s.mcap
            # 품질+가치 복합: ROIC 백분위 + FCF 수익률 백분위 (같은 달 통과 종목 안에서)
            okq = s.grade.isin(S["allow_grades"])  # 순위는 통과 종목 안에서 (B14)
            s["qv"] = s.roic_med5.where(okq).rank(pct=True) + s.fcf_yield.where(okq).rank(pct=True)
            cand_key = {"dd": "dd_rank"}.get(S["rank"], S["rank"])
            cand = s[ok].sort_values(cand_key, ascending=False)
            # 청산 ①: 탈락 / ④: 고평가 (판정은 시총 필터 전 전체 상태로 — 시총이 줄었다고 팔지 않음)
            full = st_by_m[m].set_index("cik")
            for c in list(hold):
                if c not in full.index:
                    continue
                row = full.loc[c]
                if row.grade == "X":
                    log.append((m, c, "sell_fail")); hold.pop(c)
                elif S["trim_mult"] and c in s.index and s.at[c, "mcap"] > row.iv_opt * S["trim_mult"]:
                    log.append((m, c, "sell_trim")); hold.pop(c)
            # 정기 재구성(요인 포트폴리오식): rebalance개월마다 상위 N으로 통째 교체
            if S.get("rebalance"):
                if k % S["rebalance"] == 0:
                    new = list(cand.index[:N])
                    if S.get("buffer"):  # 완충: 보유 종목은 순위가 buffer×N 안이면 유지 (회전율·세금 절감)
                        keep_zone = set(cand.index[:int(S["buffer"] * N)])
                        kept = [c for c in hold if c in keep_zone]
                        new = kept + [c for c in cand.index if c not in kept][:max(0, N - len(kept))]
                    for c in list(hold):
                        if c not in new:
                            hold.pop(c); log.append((m, c, "sell_rebal"))
                    for c in new:
                        if c not in hold:
                            hold[c] = 1.0 / N; log.append((m, c, "buy"))
                cand = cand.iloc[0:0]  # 재구성 사이에는 신규 진입 없음
            # 진입
            for c in cand.index:
                if c in hold:
                    continue
                if len(hold) < N:
                    hold[c] = 1.0 / N; log.append((m, c, "buy"))
                elif S["swap_gap"] is not None:
                    held_rooms = {h: s.room.get(h, np.nan) for h in hold}
                    worst = min(held_rooms, key=lambda h: (held_rooms[h] if np.isfinite(held_rooms[h]) else 9))
                    wr = held_rooms[worst]
                    if np.isfinite(wr) and np.isfinite(cand.room[c]) and cand.room[c] - wr >= S["swap_gap"]:
                        hold.pop(worst); log.append((m, worst, "sell_swap"))
                        hold[c] = 1.0 / N; log.append((m, c, "buy"))
        # 다음 달 수익
        r = 0.0
        dead = []
        if S["slots"] >= 500 and hold:  # '통과 종목 전부' 모드: 보유 종목끼리 동일비중
            hold = {c: 1.0 / len(hold) for c in hold}
        for c, w in hold.items():
            x = ret.at[nxt, c] if c in ret.columns else np.nan
            if np.isnan(x):
                # 주가 끊김: 다음 달 이후 데이터가 없으면 청산(수익 0 가정)
                if c not in tri.columns or tri.loc[nxt:, c].notna().sum() == 0:
                    dead.append(c)
                x = 0.0
            r += w * x
        for c in dead:
            hold.pop(c); log.append((nxt, c, "delisted"))
        trades = sum(1 for L in log if L[0] == m)
        r -= trades * (1.0 / (len(hold) or 1) if S["slots"] >= 500 else 1.0 / N) * S["cost"]
        rets.append((nxt, r))
        n_hold.append((nxt, len(hold)))
    rr = pd.Series(dict(rets))
    return rr, pd.DataFrame(log, columns=["m", "cik", "act"]), pd.Series(dict(n_hold))


def perf(r):
    r = r.dropna()
    if r.empty:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    return {"CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * np.sqrt(12),
            "Sharpe": r.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan,
            "MDD": (eq / eq.cummax() - 1).min(), "months": len(r)}


def benchmarks(ann, mc, tri, state, S=SDEFAULT):
    """같은 유니버스 동일비중(시총≥min, 섹터 제외 적용/미적용), 품질만(가격 무시)."""
    S = {**SDEFAULT, **S}
    ret = tri.pct_change(fill_method=None)
    out = {}
    months = [m for m in mc.index if m >= pd.Period(S["start"], "M")]
    ew_all, ew_ex = [], []
    for k, m in enumerate(months[:-1]):
        nxt = months[k + 1]
        big = mc.loc[m][mc.loc[m] >= S["min_mcap"]].index
        rr = ret.loc[nxt, big].fillna(0)
        ew_all.append((nxt, rr.mean()))
    out["EW >=$10B (all)"] = pd.Series(dict(ew_all))
    return out
