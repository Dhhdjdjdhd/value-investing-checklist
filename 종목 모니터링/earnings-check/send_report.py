"""분석 결과 HTML 파일을 드로다운 모니터의 Gmail 설정(Credential Manager 앱 비밀번호)으로 보낸다.
사용: py send_report.py "<제목>" <본문.html> [--dry]"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'drawdown-monitor'))
import core  # noqa: E402

subject, path = sys.argv[1], sys.argv[2]
body = open(path, encoding='utf-8').read()
html = core._wrap(subject, body)
if '--dry' in sys.argv:
    print(f'[dry] {subject} ({len(html)}자)')
else:
    core.send_mail(core.load_config(), subject, html)
    print('메일 발송:', subject)
