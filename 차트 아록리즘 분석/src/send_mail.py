"""최종보고서를 메일로 발송. drawdown-monitor의 Gmail 설정(config.json + 윈도우 자격증명)을 재사용.

실행: py src/send_mail.py "<제목>" <본문 HTML 파일>
"""
import json
import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

MON = Path(__file__).resolve().parents[2] / "종목 모니터링" / "drawdown-monitor"
sys.path.insert(0, str(MON))
import core  # noqa: E402


def main():
    subject, html_path = sys.argv[1], Path(sys.argv[2])
    cfg = json.loads((MON / "config.json").read_text(encoding="utf-8"))
    em = cfg["email"]
    pw = core.load_password()
    msg = MIMEText(html_path.read_text(encoding="utf-8"), "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("차트 알고리즘 연구", em["sender"]))
    msg["To"] = em["recipient"]
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(em["sender"], pw)
        s.send_message(msg)
    print("sent")


if __name__ == "__main__":
    main()
