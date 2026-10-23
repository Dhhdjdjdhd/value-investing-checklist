"""99_최종보고서.md -> results/report_mail.html (메일 본문용, 인라인 스타일)

실행: py src/build_mail.py
"""
import markdown

from common import RESULTS, ROOT

CSS = """
body{font-family:'Malgun Gothic',sans-serif;font-size:14px;line-height:1.6;color:#222;max-width:900px}
h1{font-size:20px;border-bottom:2px solid #333;padding-bottom:4px}
h2{font-size:17px;margin-top:24px;border-bottom:1px solid #ccc}
h3{font-size:15px}
table{border-collapse:collapse;font-size:12px;margin:8px 0 16px}
th,td{border:1px solid #ccc;padding:4px 8px}
th{background:#f3f3f3}
code,pre{background:#f6f6f6;font-size:12px}
"""


def main():
    md = (ROOT / "99_최종보고서.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    note = ("<p style='color:#666'>전체 자료: E:\\value-investing-checklist\\차트 아록리즘 분석 "
            "(00~05 문서, results\\ 표·차트, src\\ 코드)</p>")
    html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{note}{body}</body></html>"
    (RESULTS / "report_mail.html").write_text(html, encoding="utf-8")
    print("written", RESULTS / "report_mail.html")


if __name__ == "__main__":
    main()
