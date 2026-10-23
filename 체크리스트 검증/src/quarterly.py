"""v2 분기 재점검 자동 실행기 — 작업 스케줄러 'V2QuarterlyReview'가 1·4·7·10월 2일 새벽에 실행한다.

순서 (단계마다 완료 표시 → 중간에 멈춰도 다시 실행하면 이어서)
  1 SEC companyfacts 새로 고침   fetch_sec.py cf_refresh <분기>
  2 주가 새로 고침               fetch_prices.py --refresh <기준일>
  3 패널                         build_panel.py first
  4 순위표                       final.py --screen-only -> results/screen_now.csv
  5 장부 교체                    rebalance.py -> PORTFOLIO.html
  6 감시판                       build_watch.py -> WATCH.html
  7 커밋·푸시                    (바뀐 파일만)
  8 결과 메일
실패하면 실패 메일을 보내고 멈춘다. 메모리 부족(종료코드 2)은 10분 쉬고 최대 6번 다시 시도.
실행: py src/quarterly.py [--tag 2027Q1] [--no-push] [--no-mail]
로그: logs/quarterly_<분기>.log, 진행: results/quarterly_state.json
"""
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SRC = ROOT / "src"
STATE = ROOT / "results" / "quarterly_state.json"
MON = REPO / "종목 모니터링" / "drawdown-monitor"
GIT = r"C:\Program Files\Git\cmd\git.exe"
SITE = "https://value-investing-checklist.onrender.com/reports"
PY = sys.executable.replace("pythonw.exe", "python.exe")   # 스케줄러는 pythonw로 띄운다 — 자식은 콘솔 python으로
COMMIT_FILES = ["public/reports/PORTFOLIO.html", "public/reports/WATCH.html",
                "체크리스트 검증/results/screen_now.csv", "체크리스트 검증/results/rebalance_last.json"]

LOG = None


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args, cwd=ROOT, retries=6):
    """종료코드 2(메모리 부족)·3(시간 제한)이면 쉬었다가 이어서 다시 실행."""
    for attempt in range(retries + 1):
        log("$ " + " ".join(map(str, args)))
        with LOG.open("a", encoding="utf-8") as f:
            r = subprocess.run(args, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, creationflags=0x08000000,
                               env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        if r.returncode == 0:
            return
        if r.returncode in (2, 3) and attempt < retries:
            log(f"종료코드 {r.returncode} — {'10분 쉬고' if r.returncode == 2 else '바로'} 이어서")
            time.sleep(600 if r.returncode == 2 else 1)
            continue
        raise RuntimeError(f"{args[1] if len(args) > 1 else args[0]} 실패 (종료코드 {r.returncode})")


def git(*a):
    r = subprocess.run([GIT, "-c", "core.quotepath=false", *a], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", creationflags=0x08000000)
    log(f"git {' '.join(a[:2])}: {(r.stdout + r.stderr).strip()[:300]}")
    if r.returncode:
        raise RuntimeError(f"git {a[0]} 실패")
    return r.stdout


def mail(subject, html):
    sys.path.insert(0, str(MON))
    import core   # drawdown-monitor의 Gmail 설정·앱 비밀번호(자격 증명 관리자) 재사용
    core.send_mail(core.load_config(), subject, html)
    log(f"메일 발송: {subject}")


def report_html(tag):
    s = json.loads((ROOT / "results" / "rebalance_last.json").read_text(encoding="utf-8"))
    td = "border:1px solid #ddd;padding:4px 8px"
    act = {"sell": "매도", "trim": "축소", "buy": "신규", "add": "추가"}

    def pnl(t):
        return "" if t["pnl"] is None else f"{t['pnl']:+,}원"

    rows = "".join(
        f"<tr><td style='{td}'>{act[t['act']]}</td><td style='{td}'>{t['name']} ({t['code']})</td>"
        f"<td style='{td};text-align:right'>{t['shares']}주</td><td style='{td};text-align:right'>{t['price']:,}원</td>"
        f"<td style='{td};text-align:right'>{pnl(t)}</td><td style='{td}'>{t['note']}</td></tr>" for t in s["trades"])
    main_trades = [t for t in s["trades"] if t["act"] in ("sell", "buy")]
    head = (f"매도 {s['review']['sold']} · 신규 {s['review']['bought']}종목" if main_trades else "종목 교체 없음 — 20종목 모두 30위 안")
    w = s["weights"]
    return (f"<div style='font-family:Malgun Gothic,sans-serif;font-size:14px;color:#222'>"
            f"<h2 style='font-size:18px'>v2 분기 재점검 {tag} — {head}</h2>"
            f"<p>순위표 기준 {s['review']['priceDate']} 종가 · 환율 {s['review']['fx']:,}원 · "
            f"총자산 {s['total']:,}원 · 현금 {s['cash']:,}원 · 비중 {min(w.values()):.1f}~{max(w.values()):.1f}%</p>"
            + (f"<table style='border-collapse:collapse;font-size:13px'><tr><th style='{td}'>구분</th><th style='{td}'>종목</th>"
               f"<th style='{td}'>수량</th><th style='{td}'>체결가</th><th style='{td}'>실현손익</th><th style='{td}'>사유</th></tr>{rows}</table>"
               if rows else "<p>매매 없음.</p>")
            + f"<p>보유 현황: {SITE}/PORTFOLIO.html<br>감시판(선정 20 + 유지 구간 10): {SITE}/WATCH.html</p>"
            "<p style='color:#666;font-size:12px'>정성 거부권(능력범위 밖·회계 의심)은 사람 몫입니다 — 새로 들어온 종목 중 "
            "빼야 할 것이 있으면 build_watch.py VETO에 넣고 다시 돌리면 됩니다. 가상 시뮬레이터 기록이며 투자 권유가 아닙니다.</p></div>")


def main():
    global LOG
    if sys.stdout:   # 스케줄러(pythonw)로 뜨면 표준출력이 없다 — 기록은 로그 파일로만
        sys.stdout.reconfigure(encoding="utf-8")
    today = dt.date.today()
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else f"{today.year}Q{(today.month - 1) // 3 + 1}"
    (ROOT / "logs").mkdir(exist_ok=True)
    LOG = ROOT / "logs" / f"quarterly_{tag}.log"
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    done = st.setdefault(tag, {"done": []})["done"]
    cutoff = (today - dt.timedelta(days=4)).isoformat()
    steps = [
        ("sec", lambda: run([PY, SRC / "fetch_sec.py", "cf_refresh", tag, "--max-minutes", "50"], retries=20)),
        ("prices", lambda: run([PY, SRC / "fetch_prices.py", "--refresh", cutoff, "--max-minutes", "50"], retries=20)),
        ("panel", lambda: run([PY, SRC / "build_panel.py", "first"], cwd=SRC)),
        ("screen", lambda: run([PY, SRC / "final.py", "--screen-only"], cwd=SRC)),
        ("rebalance", lambda: run([PY, SRC / "rebalance.py"], cwd=SRC, retries=0)),
        ("watch", lambda: run([PY, SRC / "build_watch.py"], cwd=SRC, retries=0)),
    ]
    log(f"=== v2 분기 재점검 {tag} 시작 (완료된 단계: {done or '없음'})")
    try:
        for name, fn in steps:
            if name in done:
                continue
            fn()
            done.append(name)
            STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        if "push" not in done and "--no-push" not in sys.argv:
            git("add", "--", *COMMIT_FILES)
            if git("diff", "--cached", "--name-only", "--", *COMMIT_FILES).strip():
                # 경로를 지정해 커밋 — 사용자가 따로 올려 둔(staged) 변경은 섞지 않는다
                git("commit", "-q", "-m", f"v2 분기 재점검 {tag}: 순위표·보유 현황·감시판 자동 갱신\n\n"
                    "체크리스트 검증/src/quarterly.py (작업 스케줄러 V2QuarterlyReview) 자동 커밋", "--", *COMMIT_FILES)
                git("push", "-q", "origin", "HEAD")
            done.append("push")
            STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        if "mail" not in done and "--no-mail" not in sys.argv:
            mail(f"[v2 분기 재점검] {tag} 완료", report_html(tag))
            done.append("mail")
            STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"=== {tag} 완료")
    except Exception as e:  # noqa: BLE001
        log(f"!!! 실패: {e}")
        tail = "".join(LOG.read_text(encoding="utf-8").splitlines(True)[-40:])
        try:
            mail(f"[v2 분기 재점검] {tag} 실패 — {e}",
                 f"<p>분기 재점검이 <b>{e}</b>에서 멈췄습니다. 다시 실행하면 완료된 단계는 건너뜁니다:<br>"
                 f"<code>py \"{SRC / 'quarterly.py'}\" --tag {tag}</code></p><pre style='font-size:12px'>{tail}</pre>")
        except Exception as e2:  # noqa: BLE001
            log(f"실패 메일도 못 보냄: {e2}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
