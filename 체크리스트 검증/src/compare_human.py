"""엔진 판정 vs 사람 판정(감시판 WATCH.html) 대조: 등급, 기본 내재가치(주당).

실행: py src/compare_human.py [first]  -> results/compare_human.csv
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import evaluate_rows, load

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "results" / "WATCH_before_v2.html"  # 사람 판정 원본(v1 감시판, 2026-10-22) 고정 사본


def human_rows():
    html = WATCH.read_text(encoding="utf-8")
    return [json.loads(x) for x in re.findall(r'\{"t": [^{}]*\}', html)]


def main(V=None):
    mode = sys.argv[1] if len(sys.argv) > 1 else "first"
    ann, mc, tri, dd = load(mode)
    rows = evaluate_rows(ann, V=V) if V else evaluate_rows(ann)
    last = rows.sort_values("avail").groupby("ticker").tail(1).set_index("ticker")
    cap_now = mc.ffill().iloc[-1]
    out = []
    for h in human_rows():
        t = h["t"]
        rec = {"t": t, "g_human": h["g"], "iv_human": h["ivb"], "price": h["price"]}
        if t in last.index:
            r = last.loc[t]
            cap = cap_now.get(r.cik, np.nan)
            rec.update(g_eng=r.grade, fy=r.cy,
                       iv_eng=r.iv / cap * h["price"] if np.isfinite(cap) and cap > 0 else np.nan)
        out.append(rec)
    d = pd.DataFrame(out)
    d["ratio"] = d.iv_eng / d.iv_human
    d.to_csv(ROOT / "results" / "compare_human.csv", index=False, encoding="utf-8-sig")
    print(d.round(2).to_string(index=False))
    print("median ratio", round(d.ratio.median(), 2), "grade match", (d.g_human.map({"S": "S", "A": "A", "일반": "G"}) == d.g_eng).mean())
    return d


if __name__ == "__main__":
    main()
