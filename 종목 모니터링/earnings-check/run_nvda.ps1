# 2026-11-18 07:30 1회 실행 — 엔비디아 실적 확인 후 진입 판단 메일 (예약 작업 NvdaEarningsCheck)
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location 'E:\value-investing-checklist'
$log = Join-Path $here ('run_' + (Get-Date -Format 'yyyyMMdd_HHmm') + '.log')
$prompt = Get-Content (Join-Path $here 'nvda_prompt.md') -Raw -Encoding UTF8
& 'C:\Users\hdrga\.local\bin\claude.exe' -p $prompt --allowedTools 'WebSearch,WebFetch,Read,Write,Edit,Glob,Grep,Bash(py:*),Bash(py *),PowerShell(py *)' --max-turns 120 *>&1 | Out-File $log -Encoding utf8
$code = $LASTEXITCODE
# 분석 메일이 안 나갔으면(메일 HTML 파일이 없으면) 실패 안내 메일
if (-not (Test-Path (Join-Path $here 'nvda_mail.html'))) {
  $fail = Join-Path $here 'fail_mail.html'
  "<p>엔비디아 실적 자동 분석이 끝나지 않았습니다 (종료 코드 $code). 로그: $log</p><p>Claude Code에서 '엔비디아 실적 분석해줘'라고 직접 요청해 주세요.</p>" | Out-File $fail -Encoding utf8
  py (Join-Path $here 'send_report.py') '[실적 판단] 엔비디아 — 자동 분석 실패' $fail
}
