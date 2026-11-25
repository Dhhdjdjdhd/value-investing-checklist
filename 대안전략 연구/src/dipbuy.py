"""H. 국내 대형주 "고점 대비 −40% 이후 진입" (00_연구계획 §H).

실행: py src/dipbuy.py -> results/H_events.csv, H_summary.txt, H_now.csv
"""
import numpy as np
import pandas as pd

from alloc import RES, build, yahoo

CODES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차", "000270": "기아", "005490": "POSCO홀딩스",
    "051910": "LG화학", "006400": "삼성SDI", "012330": "현대모비스", "055550": "신한지주", "017670": "SK텔레콤",
    "015760": "한국전력", "033780": "KT&G", "066570": "LG전자", "003550": "LG", "009150": "삼성전기",
    "011170": "롯데케미칼", "010950": "S-Oil", "000810": "삼성화재", "086790": "하나금융지주", "030200": "KT",
    "034220": "LG디스플레이", "011200": "HMM", "010140": "삼성중공업", "042660": "한화오션", "047040": "대우건설",
    "000720": "현대건설", "004020": "현대제철", "036460": "한국가스공사", "010130": "고려아연", "009540": "HD한국조선해양",
}
END = "2026-10"
H = 36
KS_DIV = 0.019


def bench():
    D = build()
    k11 = yahoo("^KS11").reindex(D.index).pct_change(fill_method=None) + KS_DIV / 12
    k200 = yahoo("069500.KS", True).reindex(D.index).pct_change(fill_method=None)
    ks = k200.where(D.index >= "2009-05", k11)
    return pd.DataFrame({"K": ks, "S": D.un, "cash": D.cash}).loc[:END]


def growth(r, a, n):
    """월수익 r 에서 a 달 말에 사서 n 개월 뒤 말까지의 배수."""
    i = r.index.get_loc(a)
    seg = r.iloc[i + 1:i + 1 + n]
    return float((1 + seg.fillna(0)).prod()) if len(seg) == n else np.nan


def split_plan(close, adj, cash, a, ath):
    """P1: 1/3씩 고점의 60/50/40%에서, 12개월 안에 못 산 몫은 12개월째 말. 대기 자금은 CD91."""
    idx = close.index
    i0 = idx.get_loc(a)
    if i0 + H >= len(idx):
        return np.nan
    lv = [0.6, 0.5, 0.4]
    shares, money, done = 0.0, 1.0, [False] * 3
    for k in range(0, H + 1):
        m = idx[i0 + k]
        if k > 0:
            money *= 1 + (cash.get(m, 0) or 0)
        for j in range(3):
            if not done[j] and (close.iloc[i0 + k] <= ath * lv[j] or k == 12):
                amt = min(1 / 3, money) if j < 2 else money
                shares += amt / adj.iloc[i0 + k]
                money -= amt
                done[j] = True
    return shares * adj.iloc[i0 + H] + money


def main():
    B = bench()
    rows, now = [], []
    for code, name in CODES.items():
        c = yahoo(f"{code}.KS").loc[:END]
        a = yahoo(f"{code}.KS", True).loc[:END]
        df = pd.DataFrame({"c": c, "a": a}).dropna()
        df = df[df.index >= "2000-01"]
        if len(df) < 60:
            print("데이터 부족", code, name, len(df))
            continue
        first = df.index[0]
        # Yahoo 수정주가가 음수인 구간(SK하이닉스 2000~2002)은 배당 없는 종가 수익으로 대신한다
        ok = (df.a > 0) & (df.a.shift(1) > 0)
        ra = df.a.pct_change().where(ok, df.c.pct_change())
        df["a"] = (1 + ra.fillna(0)).cumprod()
        if (~ok).iloc[1:].any():
            print(f"{code} {name}: 수정주가 이상 {int((~ok).iloc[1:].sum())}개월 → 종가 수익으로 대체")
        ath = df.c.cummax()
        dd = df.c / ath - 1
        now.append({"code": code, "name": name, "start": first, "close": df.c.iloc[-1], "ath": ath.iloc[-1],
                    "dd_now": dd.iloc[-1]})
        armed = True
        for m in df.index:
            if m < "2000-07":
                continue
            if not armed and df.c[m] >= 0.8 * ath[m]:
                armed = True
            if armed and dd[m] <= -0.4:
                armed = False
                i = df.index.get_loc(m)
                fut = df.c.iloc[i + 1:i + 1 + H]
                rec = df.c.iloc[i + 1:]
                back = rec[rec >= df.c[m]]
                full = i + H < len(df) and pd.Period(m) + H <= pd.Period(END)
                r = {"code": code, "name": name, "month": m, "year": m[:4], "dd": dd[m], "full36": full,
                     "P0_12": growth(ra, m, 12) - 1, "P0_36": growth(ra, m, 36) - 1, "P0_60": growth(ra, m, 60) - 1,
                     "P1_36": split_plan(df.c, df.a, B.cash, m, ath[m]) - 1,
                     "K_36": growth(B.K, m, 36) - 1, "S_36": growth(B.S, m, 36) - 1,
                     "K_12": growth(B.K, m, 12) - 1, "S_12": growth(B.S, m, 12) - 1,
                     "further_dd": (fut.min() / df.c[m] - 1) if len(fut) else np.nan,
                     "months_to_recover": (df.index.get_loc(back.index[0]) - i) if len(back) else np.nan}
                rows.append(r)
    E = pd.DataFrame(rows)
    E["P0-K"], E["P0-S"], E["P1-P0"] = E.P0_36 - E.K_36, E.P0_36 - E.S_36, E.P1_36 - E.P0_36
    E.to_csv(RES / "H_events.csv", index=False, encoding="utf-8-sig")
    N = pd.DataFrame(now).sort_values("dd_now")
    N.to_csv(RES / "H_now.csv", index=False, encoding="utf-8-sig")

    F = E[E.full36].dropna(subset=["P0_36", "K_36", "S_36"])
    out = [f"사건 {len(E)}건 (36개월 완료 {len(F)}건, 종목 {E.code.nunique()}개)"]

    def verdict(col):
        med, win = F[col].median(), (F[col] > 0).mean()
        ymed = F.groupby("year")[col].median().median()
        ok = med > 0 and win >= 0.6 and ymed > 0
        return f"{col}: 중앙값 {med:+.1%}, 이긴 비율 {win:.0%}, 연도별 중앙값의 중앙값 {ymed:+.1%} → {'지지' if ok else '근거 부족'}"

    out += [verdict("P0-K"), verdict("P0-S")]
    d = F["P1-P0"].dropna()
    out.append(f"P1-P0: 중앙값 {d.median():+.1%}, 이긴 비율 {(d > 0).mean():.0%} → "
               f"{'분할이 낫다' if d.median() > 0 and (d > 0).mean() >= 0.5 else '분할이 낫지 않다'}")
    q = lambda s: f"25% {s.quantile(.25):+.0%} / 중앙 {s.median():+.0%} / 75% {s.quantile(.75):+.0%}"
    out.append(f"P0 36개월 수익: {q(F.P0_36)}  | 코스피 {q(F.K_36)} | S&P {q(F.S_36)}")
    out.append(f"P0 12개월 수익: {q(F.P0_12)} | 60개월: {q(F.P0_60.dropna())}")
    out.append(f"사건 후 추가 최대 하락(36개월 안): {q(E.further_dd.dropna())}, −20% 넘게 더 빠진 비율 {(E.further_dd < -0.2).mean():.0%}")
    out.append(f"사건 가격 회복까지 개월: 중앙 {E.months_to_recover.median():.0f}, 회복 못 한 사건 {E.months_to_recover.isna().sum()}건")
    out.append(f"36개월 뒤 손실(P0<0) 비율 {(F.P0_36 < 0).mean():.0%}, −50% 이하 {(F.P0_36 <= -0.5).mean():.0%}")
    out.append("\n연도별 (36개월 완료):")
    g = F.groupby("year").agg(n=("code", "size"), P0=("P0_36", "median"), K=("K_36", "median"), S=("S_36", "median"),
                              P0K=("P0-K", "median"), win=("P0-K", lambda s: (s > 0).mean()))
    out.append(g.to_string(float_format=lambda x: f"{x:+.0%}"))
    out.append("\n삼성전자·SK하이닉스 사건:")
    cols = ["name", "month", "dd", "P0_12", "P0_36", "P1_36", "K_36", "S_36", "further_dd", "months_to_recover"]
    s = E[E.code.isin(["005930", "000660"])][cols].copy()
    s["months_to_recover"] = s.months_to_recover.map(lambda x: "-" if pd.isna(x) else f"{x:.0f}개월")
    out.append(s.to_string(index=False, float_format=lambda x: f"{x:+.0%}"))
    txt = "\n".join(out)
    (RES / "H_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)
    print("\n현재 위치 (2026-10 말):")
    print(N.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


if __name__ == "__main__":
    main()
