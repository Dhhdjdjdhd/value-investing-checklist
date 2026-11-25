"""[사후 민감도] 이름 조건(TRUST·ETF·FUND) 때문에 파트 C 에서 빠진 일반 기업(리츠, Northern Trust 등)을 되살린 판.

제외는 SIC 6221 과 펀드 성격 종목(BXSL·MSDL 등)만. 원래 판정(C_verdict.csv)과 C_events.csv 는 건드리지 않는다.
실행: py -I src/C_posthoc_reits.py -> results/C_posthoc_reits.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import C_stock as C  # noqa: E402

NAME_RE = r"\bTRUST\b|\bETF\b|\bFUND\b"
REAL_RE = r"\bETF\b|\bFUND\b|ISHARES|SPDR|GRAYSCALE|PROSHARES|INVESCO DB|WISDOMTREE|BITCOIN|ETHEREUM|\bGOLD\b|\bSILVER\b|COMMODIT|ROYALTY"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ann = C.load_ann()
    old = C.fund_ciks(ann)
    comp = pd.read_csv(C.CK / "data" / "sec" / "companies.csv").drop_duplicates("cik").set_index("cik")
    nm = comp["name"].fillna("").astype(str).str.upper()
    sic = pd.to_numeric(comp.sic, errors="coerce")
    real = set(comp.index[sic.eq(6221) | (nm.str.contains(NAME_RE) & (nm.str.contains(REAL_RE) | sic.isin([6199, 6189])))])
    revive = old - real
    man = C.load_manifest()
    man = man[man.cik.isin(revive)]
    spy = C.load_spy()
    _, gdd = C.load_gspc()
    ann_g = dict(tuple(ann.groupby("cik")))
    sector = ann.drop_duplicates("cik").set_index("cik").sector_excl.fillna(False).astype(bool)
    rows, n_ok = [], 0
    for cik, tk in zip(man.cik, man.yahoo):
        if cik not in ann_g:
            continue
        ev, st = C.firm_events(cik, tk, ann_g[cik], spy, gdd)
        n_ok += st == "ok"
        for r in ev:
            r["S"] = "순환·제외섹터" if sector.get(cik, False) else "그 외"
        rows += ev
    add = pd.DataFrame(rows)
    add["period"] = pd.cut(add.year, [2005, 2015, 2021, 2026], labels=["학습", "검증", "최근"]).astype(str)
    base = pd.read_csv(C.RES / "C_events.csv")
    ev = pd.concat([base, add], ignore_index=True)
    orig = pd.read_csv(C.RES / "C_verdict.csv").set_index(["문턱", "변수"])
    out = []
    for th in (30, 50):
        for var, (ga, gb) in C.VARS.items():
            rec = {"문턱": f"−{th}%", "변수": var, "비교": f"{ga} − {gb}"}
            ok_n = ok_diff = ok_ci = True
            signs = []
            for per in ("학습", "검증"):
                d = ev[(ev.th == th) & (ev.period == per)]
                g = C.groups(d)
                a, b = g[ga], g[gb]
                da, db = d[a & d.rec3.notna().values], d[b & d.rec3.notna().values]
                pt, lo, hi = C.boot_diff(d, "rec3", a, b, "cik")
                o = orig.loc[(f"−{th}%", var)]
                rec.update({f"{per} A 회복3년": da.rec3.mean(), f"{per} B 회복3년": db.rec3.mean(), f"{per} 차이": pt,
                            f"{per} 기업군집 90% 하한": lo, f"{per} 기업군집 90% 상한": hi,
                            f"{per} A 사건": len(da), f"{per} B 사건": len(db), f"{per} 원래 차이": o[f"{per} 차이"]})
                if min(len(da), len(db)) < 30 or min(da.cik.nunique(), db.cik.nunique()) < 20:
                    ok_n = False
                ok_diff &= bool(abs(pt) >= 0.10)
                ok_ci &= bool(lo > 0 or hi < 0)
                signs.append(np.sign(pt))
            v = "판정 불가(표본 부족)" if not ok_n else ("유용" if ok_diff and ok_ci and len(set(signs)) == 1 else "유용하지 않음")
            rec["되살린 판 판정"] = v
            rec["원래 판정"] = orig.loc[(f"−{th}%", var), "판정"]
            rec["판정 바뀜"] = "예" if v != rec["원래 판정"] else "아니오"
            out.append(rec)
    res = pd.DataFrame(out)
    res.to_csv(C.RES / "C_posthoc_reits.csv", index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"되살린 기업: 대상 {len(revive)}개 중 주가 있는 {len(man)}개, 사건 계산 가능 {n_ok}개, 추가 사건 {len(add)}개 "
          f"(−30% {int((add.th == 30).sum())}, −50% {int((add.th == 50).sum())}); 여전히 제외(펀드 성격) {len(old & real)}개")
    print(add.groupby(["th", "period", "S"]).size().to_string())
    for r in out:
        print(f"{r['문턱']} {r['변수']}: 학습 {r['학습 A 회복3년']:.1%} vs {r['학습 B 회복3년']:.1%} 차이 {r['학습 차이'] * 100:+.1f}%p (원래 {r['학습 원래 차이'] * 100:+.1f}) "
              f"[{r['학습 기업군집 90% 하한'] * 100:+.1f} ~ {r['학습 기업군집 90% 상한'] * 100:+.1f}] | 검증 {r['검증 A 회복3년']:.1%} vs {r['검증 B 회복3년']:.1%} "
              f"차이 {r['검증 차이'] * 100:+.1f}%p (원래 {r['검증 원래 차이'] * 100:+.1f}) [{r['검증 기업군집 90% 하한'] * 100:+.1f} ~ {r['검증 기업군집 90% 상한'] * 100:+.1f}] "
              f"→ {r['되살린 판 판정']} (원래 {r['원래 판정']})")


if __name__ == "__main__":
    main()
