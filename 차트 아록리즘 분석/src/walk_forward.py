"""워크포워드(롤링 재선정) 검증 (작업지시 #3, 작성: value-investing-checklist-f9).

- 규칙 후보: strategy_search.make_rules() 160개, 유니버스: 미국 종목+ETF, K=10
- 창: 학습 8년 -> 테스트 2년, 2년씩 이동. 첫 학습 1994~2001 / 첫 테스트 2002~2003.
  마지막 창의 테스트는 2024-01-01 ~ 데이터 끝(2026-10-20)으로 늘림(남는 10개월을 따로 떼지 않음)
- 각 창: 학습 Sharpe 1위(동률이면 CAGR) 규칙의 테스트 구간 일별 수익을 이어붙임 + 상위 3개 동일비중
- 규칙마다 run_trades 는 전체 기간 1회, 창마다 portfolio(start, end) 만 다시 호출
- 비용 민감도: 선택은 편도 0.05% 기준으로 고정하고, 이어붙인 테스트 수익만 0.10% 로 다시 계산

실행: py src/walk_forward.py                      # 계산 + 집계 (중단되면 다시 실행해 이어감)
     py src/walk_forward.py --shard 0/3 (1/3, 2/3) # 병렬 계산만, shard 별 partial 파일
     py src/walk_forward.py --aggregate             # 모든 partial 을 합쳐 집계만
     results/walk_forward.stop 파일을 만들면 실행 중인 계산이 규칙 사이에서 멈춤
산출: results/walk_forward.csv, results/walk_forward_equity.csv, results/walk_forward_grid.csv
"""
import argparse
import sys
import time

import numpy as np
import pandas as pd

import strategy
from common import COST, DATA_END, RESULTS, load_all, market_of
from strategy import portfolio, run_trades, stats
from strategy_search import K, make_rules

TRAIN_YEARS, TEST_YEARS = 8, 2
FIRST_TRAIN = 1994
COSTS = (0.0005, 0.0010)


def windows():
    out = []
    y = FIRST_TRAIN
    while True:
        ts = y + TRAIN_YEARS
        te_year = ts + TEST_YEARS - 1
        if pd.Timestamp(f"{te_year + TEST_YEARS}-12-31") > DATA_END:  # 다음 창이 2년을 못 채우면 이번 테스트를 끝까지
            out.append((pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{ts - 1}-12-31"), pd.Timestamp(f"{ts}-01-01"), DATA_END))
            return out
        out.append((pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{ts - 1}-12-31"),
                    pd.Timestamp(f"{ts}-01-01"), pd.Timestamp(f"{te_year}-12-31")))
        y += TEST_YEARS


class _Cal:
    def __init__(self, index):
        self.index = index


class CalData(dict):
    """portfolio() 가 호출마다 만드는 종목 날짜 합집합(호출당 ~3초)을 미리 계산해 둔 것으로 대신함.
    values() 가 합집합 달력 하나만 돌려주므로 portfolio 결과는 원래 dict 와 똑같다."""

    def __init__(self, data):
        super().__init__(data)
        self._cal = [_Cal(pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in data.values()]))))]

    def values(self):
        return self._cal


PARTIAL = RESULTS / "walk_forward_grid.partial.csv"
STOP_FILE = RESULTS / "walk_forward.stop"  # 이 파일을 만들면 모든 shard 가 규칙 사이에서 정지
MIN_FREE_MB = 1024  # 여유 메모리가 이보다 적으면 규칙 사이에서 멈춤(다시 실행하면 이어서 진행)


def free_mb():
    """Windows 여유 물리 메모리(MB). 다른 OS 에서는 None."""
    if sys.platform != "win32":
        return None
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2**20


def load_trades(data, rule, cache):
    tr = run_trades(data, rule, cache)
    tr["ticker"] = tr["ticker"].astype(object)  # 배정 루프에서 문자열 원소 접근이 빨라짐
    return tr


def run_with_cost(cost, fn):
    base = strategy.COST
    strategy.COST = cost
    try:
        return fn()
    finally:
        strategy.COST = base


def read_partials():
    """기존 partial 과 모든 shard partial 을 합침. 마지막 줄이 깨진 파일(강제 종료)도 읽을 수 있는 만큼 읽음."""
    frames = []
    for p in sorted(RESULTS.glob("walk_forward_grid.partial*.csv")):
        try:
            frames.append(pd.read_csv(p, encoding="utf-8-sig", on_bad_lines="skip"))
        except pd.errors.EmptyDataError:
            pass
    if not frames:
        return pd.DataFrame(columns=["window", "rule"])
    g = pd.concat(frames, ignore_index=True)
    # 창이 다 채워진 규칙만 완료로 인정
    n_win = len(windows())
    full = g.groupby("rule")["window"].nunique()
    return g[g.rule.isin(full[full == n_win].index)].drop_duplicates(["window", "rule"], keep="last")


def compute(data, pdata, rules, wins, shard, t0):
    """규칙별 창 성과를 partial 파일에 이어 씀. 0 = 완료, 2 = 메모리 부족·정지 파일로 중단."""
    i_sh, n_sh = shard
    out = PARTIAL if n_sh == 1 else RESULTS / f"walk_forward_grid.partial.s{i_sh}of{n_sh}.csv"
    cache = {}
    done = set(read_partials().rule)
    todo = [(i, r) for i, r in enumerate(rules) if i % n_sh == i_sh and r.name not in done]
    print(f"shard {i_sh}/{n_sh}: {len(todo)} rules to run, {len(done)} already done", flush=True)
    for k, (i, r) in enumerate(todo, 1):
        if STOP_FILE.exists():
            print(f"STOP: {STOP_FILE.name} 있음. 규칙 사이에서 정지", flush=True)
            return 2
        tr = load_trades(data, r, cache)
        rows = []
        for w, (a, b, c, d) in enumerate(wins):
            s_tr = stats(*portfolio(pdata, tr, K=K, start=a, end=b))
            s_te = stats(*portfolio(pdata, tr, K=K, start=c, end=d))
            rows.append({"window": w, "rule": r.name,
                         **{f"train_{k}": v for k, v in s_tr.items()},
                         **{f"test_{k}": v for k, v in s_te.items()}})
        pd.DataFrame(rows).to_csv(out, mode="a", header=not out.exists(), index=False, encoding="utf-8-sig")
        del tr
        fm = free_mb()
        print(f"[s{i_sh} {k}/{len(todo)}] #{i} {r.name}  ({time.time() - t0:.0f}s, free {fm:,.0f}MB)", flush=True)
        if fm is not None and fm < MIN_FREE_MB:
            print(f"STOP: 여유 메모리 {fm:,.0f}MB < {MIN_FREE_MB}MB. 다시 실행하면 이어서 진행", flush=True)
            return 2
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default="0/1", help="i/n: 규칙 인덱스 %% n == i 인 것만 계산하고 집계는 하지 않음")
    ap.add_argument("--aggregate", action="store_true", help="계산 없이 모든 partial 을 합쳐 집계만")
    args = ap.parse_args()
    i_sh, n_sh = map(int, args.shard.split("/"))

    t0 = time.time()
    data = {t: d for t, d in load_all().items() if market_of(t) == "US"}
    pdata = CalData(data)
    rules = make_rules()
    wins = windows()
    print(f"US tickers: {len(data)}, rules: {len(rules)}, windows: {len(wins)}", flush=True)

    if not args.aggregate:
        rc = compute(data, pdata, rules, wins, (i_sh, n_sh), t0)
        if rc or n_sh > 1:
            return rc
    grid = read_partials()
    missing = [r.name for r in rules if r.name not in set(grid.rule)]
    if missing:
        print(f"집계 불가: 미완료 규칙 {len(missing)}개 (예: {missing[:3]})", flush=True)
        return 1
    grid = grid[grid.rule.isin({r.name for r in rules})]
    grid.to_csv(RESULTS / "walk_forward_grid.csv", index=False, encoding="utf-8-sig")
    rule_by_name = {r.name: r for r in rules}
    cache = {}
    trades = {}  # 선택된 규칙(최대 창 수 x 3개)만 다시 생성

    # 창별 선택
    rets = pd.DataFrame({t: d["close"].pct_change() for t, d in data.items()})
    ew_all = rets.mean(axis=1)
    spy_all = rets["SPY"]
    sel_rows = []
    series = {f"top1_c{c}": [] for c in COSTS} | {f"top3_c{c}": [] for c in COSTS}
    series |= {"ew_bh": [], "spy_bh": []}
    for w, (a, b, c, d) in enumerate(wins):
        g = grid[grid.window == w].copy()
        g["test_pct_rank"] = g["test_Sharpe"].rank(pct=True)
        g = g.sort_values(["train_Sharpe", "train_CAGR"], ascending=False, na_position="last")
        top = g.head(3)
        best = top.iloc[0]
        for nm in top.rule:
            if nm not in trades:
                trades[nm] = load_trades(data, rule_by_name[nm], cache)
        for cost in COSTS:
            daily = {nm: run_with_cost(cost, lambda nm=nm: portfolio(pdata, trades[nm], K=K, start=c, end=d)[0])
                     for nm in top.rule}
            series[f"top1_c{cost}"].append(daily[best.rule])
            series[f"top3_c{cost}"].append(pd.DataFrame(daily).fillna(0).mean(axis=1))
        ew, spy = ew_all.loc[c:d].fillna(0), spy_all.loc[c:d].dropna()
        series["ew_bh"].append(ew)
        series["spy_bh"].append(spy)
        sel_rows.append({
            "window": w, "train": f"{a.year}-{b.year}", "test": f"{c.year}-{d.year}",
            "rule": best.rule, "rule2": top.iloc[1].rule, "rule3": top.iloc[2].rule,
            "train_CAGR": best.train_CAGR, "train_Sharpe": best.train_Sharpe, "train_MDD": best.train_MDD,
            "test_CAGR": best.test_CAGR, "test_Sharpe": best.test_Sharpe, "test_MDD": best.test_MDD,
            "test_trades": best.test_trades, "test_rank_pct": best.test_pct_rank,
            "median_rule_test_Sharpe": g.test_Sharpe.median(),
            **{f"top3_test_{k}": v for k, v in stats(series["top3_c0.0005"][-1]).items() if k in ("CAGR", "Sharpe", "MDD")},
            **{f"ew_test_{k}": v for k, v in stats(ew).items() if k in ("CAGR", "Sharpe", "MDD")},
            **{f"spy_test_{k}": v for k, v in stats(spy).items() if k in ("CAGR", "Sharpe", "MDD")},
        })
    sel = pd.DataFrame(sel_rows)
    sel.to_csv(RESULTS / "walk_forward.csv", index=False, encoding="utf-8-sig")

    stitched = pd.DataFrame({k: pd.concat(v) for k, v in series.items()}).sort_index()
    stitched = stitched.fillna(0)  # 달력 차이(SPY 휴장일 등)는 0 수익
    equity = (1 + stitched).cumprod()
    equity.to_csv(RESULTS / "walk_forward_equity.csv", encoding="utf-8-sig")

    print("\n## 이어붙인 OOS 성과")
    summ = pd.DataFrame({k: stats(stitched[k]) for k in stitched}).T[["CAGR", "MDD", "Sharpe", "exposure"]]
    print(summ.to_string(float_format=lambda x: f"{x:.3f}"))
    yearly = (1 + stitched).groupby(stitched.index.year).prod() - 1
    print("\n## 연도별")
    print(yearly.to_string(float_format=lambda x: f"{x:+.1%}"))
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
