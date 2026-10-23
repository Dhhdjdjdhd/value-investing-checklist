# 전체 재실행: 사건연구 -> 후보표 -> ETF 점검 -> 전략 탐색 -> 대안 전략
Set-Location $PSScriptRoot
py event_study.py
py report_events.py
py etf_check.py
py strategy_search.py
py strategy2.py
