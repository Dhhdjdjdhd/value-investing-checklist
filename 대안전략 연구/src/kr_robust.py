"""J. I 후속 견고성 점검 (00_연구계획 §I 후속). 실행: py src/kr_robust.py -> results/J_summary.txt"""
import sys

import numpy as np
import pandas as pd

import kr_quant as Q
from alloc import RES
from dipbuy import bench


def run_custom(R, sig, pick, reb):
    months = [m for m in R.index if "2002-12" <= m < Q.END]
    w, out = pd.Series(dtype=float), {}
    for t in months:
        nxt = R.index[R.index.get_loc(t) + 1]
        cost = 0.0
        if (reb(t) or w.empty) and sig.get(t) is not None:
            names = pick(sig[t])
            new = pd.Series(1 / len(names), index=names)
            cost = new.sub(w, fill_value=0).abs().sum() * Q.COST
            w = new
        r = R.loc[nxt, w.index].fillna(0)
        out[nxt] = (1 - cost) * (1 + float((w * r).sum())) - 1
        w = w * (1 + r)
        w = w / w.sum()
    return pd.Series(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    C, R, D, _, _ = Q.panel()
    B = bench()
    sig = {t: Q.signals(C, R, D, t) for t in R.index if "2002-12" <= t < Q.END}
    ew, _ = Q.run_rule("EW", C, R, D, sig)
    d = lambda s, p: Q.stats(s, B.cash, *p)["Sharpe"] - Q.stats(ew, B.cash, *p)["Sharpe"]
    out = ["J1 고배당 변형 (ΔSharpe 학습 / 검증, 전체 CAGR):"]
    allpos = True
    for n in (10, 20, 30):
        for rn, reb in (("분기", lambda t: Q.is_reb(t, "Q")), ("연1회 4월", lambda t: t[5:] == "04")):
            s = run_custom(R, sig, lambda x, n=n: x.dy.nlargest(n).index, reb)
            a, b = d(s, Q.IS), d(s, Q.OOS)
            allpos &= a > 0 and b > 0
            out.append(f"  {n}종목 {rn}: {a:+.2f} / {b:+.2f}, CAGR {Q.stats(s, B.cash, *Q.ALL)['CAGR']:.1%}, "
                       f"MDD {Q.stats(s, B.cash, *Q.ALL)['MDD']:.0%}")
    out.append(f"  → {'견고' if allpos else '우연 가능성'}")

    s = run_custom(R, sig, lambda x: x[x.vol <= x.vol.quantile(0.7)].dy.nlargest(20).index, lambda t: Q.is_reb(t, "Q"))
    a, b = d(s, Q.IS), d(s, Q.OOS)
    st = Q.stats(s, B.cash, *Q.ALL)
    out += ["", f"J2 고배당+고변동성 제외: ΔSharpe {a:+.2f} / {b:+.2f}, CAGR {st['CAGR']:.1%}, MDD {st['MDD']:.0%} → "
                f"{'추천' if a >= 0.10 and b > 0 else '보류' if a >= 0.10 else '탈락'}"]
    J2 = s

    rc, rp = R["005930"], R["005935"]
    disc = 1 - C["005935"] / C["005930"]
    out += ["", "J3 우선주 스위칭 변형 (연수익 차이 vs 보통주, 학습 / 검증):"]
    wins = 0
    for k in (24, 36, 60):
        for how in ("mean", "median"):
            ref = getattr(disc.rolling(k, min_periods=k), how)()
            h = (disc > ref).astype(float).where(ref.notna()).shift(1)
            sw = h.diff().abs().fillna(0)
            t1 = (h * rp + (1 - h) * rc - sw * Q.COST * 2).where(h.notna())
            x = [Q.stats(t1, B.cash, *p)["CAGR"] - Q.stats(rc, B.cash, *p)["CAGR"] for p in (Q.IS, Q.OOS)]
            wins += x[0] > 0 and x[1] > 0
            out.append(f"  {k}개월 {how}: {x[0]:+.1%} / {x[1]:+.1%}")
    out.append(f"  → 6개 중 {wins}개가 둘 다 우위 → {'견고' if wins >= 5 else '우연 가능성'}")

    dv = D["005930"].rolling(12).sum() / C["005930"]
    med = dv.rolling(60, min_periods=60).median()
    h = (dv >= med).astype(float).where(med.notna()).shift(1)
    j4 = (h * rc + (1 - h) * B.K.reindex(rc.index)).where(h.notna())
    out += ["", "J4 삼성전자 배당수익률 밴드 (참고):"]
    for tag, p in (("학습", Q.IS), ("검증", Q.OOS), ("전체", Q.ALL)):
        st = {k: Q.stats(v, B.cash, *p) for k, v in (("밴드", j4), ("삼성", rc), ("코스피", B.K))}
        out.append(f"  {tag}: " + " | ".join(f"{k} {v['CAGR']:.1%} / {v['MDD']:.0%}" for k, v in st.items()))
    out.append(f"  삼성 보유 비율 {h.loc[Q.ALL[0]:Q.END].mean():.0%}, 현재 배당수익률 {dv.iloc[-1]:.2%} (60개월 중앙 {med.iloc[-1]:.2%})")
    txt = "\n".join(out)
    (RES / "J_summary.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
