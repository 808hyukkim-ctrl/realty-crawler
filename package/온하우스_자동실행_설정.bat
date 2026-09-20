@echo off
chcp 65001 > nul
title 온하우스 자동수집 - 작업 스케줄러 등록

rem 관리자 권한이 아니면 스스로 다시 실행 (절전 깨우기 설정에 필요)
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo 관리자 권한으로 다시 실행합니다...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo.
echo ============================================================
echo   온하우스 매물수집기 - 자동 실행 등록
echo ============================================================
echo.
echo  이 PC가 자고 있어도 정해진 시각에 깨어나 수집하고,
echo  메일과 텔레그램으로 보낸 뒤 프로그램이 스스로 닫힙니다.
echo.
echo  [준비물]  프로그램에서 아래 세 가지를 먼저 해두세요.
echo    1. 아이디/비밀번호 저장 체크
echo    2. 예약을 하나 이상 만들어 두기 (수집 조건이 예약에 저장됩니다)
echo    3. 자동 전송 칸에 메일 또는 텔레그램 입력
echo.

set "RUNTIME=08:30"
set /p RUNTIME=" 매일 몇 시에 돌릴까요? (예: 08:30, 그냥 엔터=08:30) : "
if "%RUNTIME%"=="" set "RUNTIME=08:30"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe = Join-Path '%~dp0' '온하우스매물수집기_독립버전.exe';" ^
  "if (-not (Test-Path $exe)) { Write-Host '실행 파일을 찾을 수 없습니다.' -ForegroundColor Red; exit 1 };" ^
  "$a = New-ScheduledTaskAction -Execute $exe -Argument '--run-all' -WorkingDirectory '%~dp0';" ^
  "$t = New-ScheduledTaskTrigger -Daily -At '%RUNTIME%';" ^
  "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew;" ^
  "Register-ScheduledTask -TaskName '온하우스 자동수집' -Action $a -Trigger $t -Settings $s -Description '온하우스 매물 자동 수집 후 메일/텔레그램 전송' -Force | Out-Null;" ^
  "powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1;" ^
  "powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1;" ^
  "powercfg /setactive SCHEME_CURRENT;" ^
  "Write-Host '';" ^
  "Write-Host ('등록 완료 - 매일 %RUNTIME% 에 실행됩니다.') -ForegroundColor Green;" ^
  "Write-Host '깨우기 타이머도 켰습니다. 퇴근할 때 전원을 끄지 말고 그냥 두세요.';"

echo.
echo  [확인]  시작 메뉴에서 "작업 스케줄러"를 열면 '온하우스 자동수집' 이 보입니다.
echo  [지금 시험]  아래에서 y 를 누르면 지금 한 번 돌려봅니다.
echo.
set "TESTRUN=n"
set /p TESTRUN=" 지금 한 번 시험 실행할까요? (y/n) : "
if /i "%TESTRUN%"=="y" (
    schtasks /run /tn "온하우스 자동수집"
    echo  실행했습니다. 작업 표시줄에 창이 최소화된 채로 뜨고, 끝나면 스스로 닫힙니다.
)
echo.
echo  끄고 싶으면 같은 폴더의  자동실행_해제.bat  을 실행하세요.
echo.
pause
