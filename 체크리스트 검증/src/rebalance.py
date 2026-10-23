"""분기 재점검 — 새 순위표(results/screen_now.csv)로 v2 시뮬레이터 장부를 규칙대로 바꾼다.

규칙 (01.가치투자 체크리스트/06 · backtest.simulate 의 rebalance+buffer 와 같은 순서)
  ① 보유 종목은 순위 30위 안이면 유지, 밖이거나 관문 탈락(순위표에 없음)이면 전량 매도
  ② 빈 칸은 유지 종목을 뺀 상위 순서대로 채워 20종목
  ③ 유지 종목 중 비중 10% 초과는 5%로 축소
  ④ 새 종목은 총자산의 5%에 가장 가까운 정수 주. 현금이 모자라면 5%를 넘는 보유분부터 5%까지 줄여 마련
  ⑤ 그래도 남는 현금은 5%에 못 미친 종목부터 1주씩 채운다 (5.5% 넘지 않게)
체결가 = 순위표의 최신 종가(price_date), 순위표에 없는 매도 종목은 Yahoo 최신가. 환율 = Yahoo KRW=X.
실행: py src/rebalance.py [--dry-run]   -> PORTFOLIO.html 데이터 블록 갱신, 요약을 표준출력·results/rebalance_last.json에
"""
import datetime as dt
import json
import sys

from build_portfolio import N, W, ROOT, load_screen, meta, quote, read_ledger, reason, write_ledger

KEEP_RANK = int(1.5 * N)   # 30위 — 완충 구간
TRIM_W = 0.10


def main(dry=False):
    led = read_ledger()
    s = load_screen()
    by = {r.ticker: r for _, r in s.iterrows()}
    fx = quote("KRW=X")
    today = dt.date.today().isoformat()
    hold = {h["code"]: h for h in led["holdings"]}

    def px_usd(code):
        return float(by[code].price) if code in by else float(quote(code))

    px = {c: round(px_usd(c) * fx) for c in set(hold) | set(s.ticker.head(KEEP_RANK + N))}
    trades, cash = [], led["cash"]

    def trade(act, code, n, krw, note):
        nonlocal cash
        h = hold.get(code)
        pnl = (krw - h["avgPrice"]) * n if act != "buy" and h else None
        cash += krw * n if act != "buy" else -krw * n
        trades.append({"date": today, "act": act, "code": code, "name": (h or {}).get("name") or meta(by[code])["name"],
                       "shares": n, "price": krw, "pnl": pnl, "note": note})

    # ① 유지 / 매도
    cand = list(s.ticker)
    kept = [c for c in hold if c in cand[:KEEP_RANK]]
    new = kept + [c for c in cand if c not in kept][:N - len(kept)]
    for c in [c for c in hold if c not in new]:
        r = by.get(c)
        why = f"순위 {int(r['rank'])}위 — 30위 밖" if r is not None else "관문 탈락·시총 미달 (순위표에 없음)"
        trade("sell", c, hold[c]["shares"], px[c], why)
        del hold[c]

    def total():
        return cash + sum(h["shares"] * px[c] for c, h in hold.items())

    # ③ 10% 초과 축소
    for c, h in hold.items():
        T = total()
        if h["shares"] * px[c] > T * TRIM_W:
            keep_n = max(1, round(T * W / px[c]))
            trade("trim", c, h["shares"] - keep_n, px[c], f"비중 {h['shares'] * px[c] / T * 100:.1f}% → 5%")
            h["shares"] = keep_n

    # ④ 새 종목
    buys = [c for c in new if c not in hold]
    T = total()
    want = {c: max(1, round(T * W / px[c])) for c in buys}
    need = sum(want[c] * px[c] for c in buys) - cash
    for c, h in sorted(hold.items(), key=lambda kv: -kv[1]["shares"] * px[kv[0]]):
        if need <= 0:
            break
        over = h["shares"] - max(1, round(T * W / px[c]))
        k = min(over, -(-need // px[c]))   # 필요한 만큼만(올림)
        if k > 0:
            trade("trim", c, k, px[c], "새 종목 매수 자금 — 5% 초과분 축소")
            h["shares"] -= k
            need -= k * px[c]
    for c in buys:
        r = by[c]
        n = want[c]
        while n > 1 and n * px[c] > cash:
            n -= 1
        if n * px[c] > cash:
            print(f"현금 부족으로 {c} 매수 생략")
            continue
        hold[c] = {**meta(r), "entryDate": today, "shares": n, "avgPrice": px[c],
                   "entryReason": reason(r, float(r.price), fx, px[c], n, T * W, r.price_date)}
        trade("buy", c, n, px[c], f"신규 편입 {int(r['rank'])}위")

    # ⑤ 남는 현금(매도·축소 대금)은 5%에 가장 못 미친 종목부터 1주씩 — 5.5%를 넘기지 않는 선에서 (현금 대기 없음)
    T = total()
    adds = {}
    while True:
        gap = {c: T * W - h["shares"] * px[c] for c, h in hold.items()
               if px[c] <= cash and (h["shares"] + 1) * px[c] <= T * (W + 0.005)}
        if not gap or max(gap.values()) <= 0:
            break
        c = max(gap, key=gap.get)
        hold[c]["shares"] += 1
        cash -= px[c]
        adds[c] = adds.get(c, 0) + 1
    for c, k in adds.items():   # 추가매수는 평단을 가중평균으로 갱신하고 한 줄로 기록
        h = hold[c]
        old = h["shares"] - k
        h["avgPrice"] = round((h["avgPrice"] * old + px[c] * k) / h["shares"])
        trades.append({"date": today, "act": "add", "code": c, "name": h["name"], "shares": k, "price": px[c],
                       "pnl": None, "note": "남는 현금으로 5%까지 채움"})

    # 순위·지표 갱신 (유지 종목도 최신 순위표 값으로)
    for c, h in hold.items():
        if c in by:
            h.update({k: v for k, v in meta(by[c]).items() if k not in ("name", "sector", "industry")})
    led["holdings"] = sorted(hold.values(), key=lambda h: h["rank"])
    led["cash"] = int(cash)
    led["trades"] = (led["trades"] + trades)[-200:]
    led["lastReview"] = {"date": today, "fx": round(fx, 2), "priceDate": str(s.price_date.iloc[0]),
                         "sold": sum(t["act"] == "sell" for t in trades), "bought": sum(t["act"] == "buy" for t in trades)}
    T = total()
    summary = {"review": led["lastReview"], "total": int(T), "cash": int(cash), "trades": trades,
               "weights": {c: round(h["shares"] * px[c] / T * 100, 2) for c, h in hold.items()}}
    if not dry:
        write_ledger(led)
        (ROOT / "results" / "rebalance_last.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "weights"}, ensure_ascii=False, indent=1))
    w = summary["weights"].values()
    print(f"보유 {len(hold)}종목 · 비중 {min(w):.1f}~{max(w):.1f}% · 현금 {cash / T * 100:.1f}%")
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main("--dry-run" in sys.argv)
