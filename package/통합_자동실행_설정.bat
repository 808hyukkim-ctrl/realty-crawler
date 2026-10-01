@echo off
chcp 65001 > nul
title 전국부동산매물수집기 - 자동 실행 등록

rem 관리자 권한이 아니면 스스로 다시 실행 (작업 스케줄러 등록·절전 깨우기 설정에 필요)
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo.
    echo  관리자 권한으로 다시 실행합니다. 잠시 후 뜨는 "사용자 계정 컨트롤" 창에서 [예]를 눌러 주세요.
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try {{ Start-Process -FilePath 'cmd.exe' -ArgumentList ('/c ' + [char]34 + [char]34 + '%~f0' + [char]34 + [char]34) -Verb RunAs -ErrorAction Stop; exit 0 }} catch {{ Write-Host ('[실패] 관리자 권한 실행이 취소되었거나 막혔습니다: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }}"
    if errorlevel 1 (
        echo.
        echo  이 창을 닫고, 파일을 마우스 오른쪽 버튼으로 눌러 "관리자 권한으로 실행"을 선택해 보세요.
        echo.
        pause
    )
    exit /b
)
cd /d "%~dp0"
echo.
echo ============================================================
echo   전국부동산매물수집기 - 자동 실행 등록
echo ============================================================
echo.
echo  이 PC가 자고 있어도 정해진 시각에 깨어나 수집하고,
echo  메일과 텔레그램으로 보낸 뒤 프로그램이 스스로 닫힙니다.
echo.
echo  [준비물]  프로그램에서 아래 세 가지를 먼저 해두세요.
echo    1. 라이선스 창에서 아이디/비밀번호 기억 체크
echo    2. 예약 탭에서 예약을 만들고 켜 두기 (시각·요일·수집 조건이 그대로 등록됩니다)
echo    3. '자동 전송' 탭에 메일 또는 텔레그램 입력 후 저장
echo.
echo  프로그램 예약 탭에 켜 둔 예약을 그대로(시각·요일) 작업 스케줄러에 등록합니다.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$dir = '%~dp0';" ^
  "$exe = Join-Path $dir '전국부동산매물수집기_독립버전_260921.exe';" ^
  "$log = Join-Path $dir '자동실행_등록.log';" ^
  "try { Start-Transcript -Path $log -Force | Out-Null } catch { };" ^
  "try {" ^
  "if (-not (Test-Path $exe)) { throw ('실행 파일을 찾을 수 없습니다: ' + $exe) };" ^
  "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew;" ^
  "Get-ScheduledTask | Where-Object { $_.TaskName -eq '매물수집 자동실행' -or $_.TaskName -like '매물수집 자동실행 - *' } | ForEach-Object { Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false };" ^
  "$sf = Join-Path $dir 'schedules.json';" ^
  "if (-not (Test-Path $sf)) { throw '예약 파일(schedules.json)이 없습니다. 프로그램 예약 탭에서 예약을 먼저 만들어 주세요.' };" ^
  "$jobs = @((Get-Content $sf -Raw -Encoding UTF8 | ConvertFrom-Json).jobs | Where-Object { $_.enabled });" ^
  "if ($jobs.Count -eq 0) { throw '켜져 있는 예약이 없습니다. 프로그램 예약 탭에서 예약을 만들고 켜 주세요.' };" ^
  "$map = @{ mon='Monday'; tue='Tuesday'; wed='Wednesday'; thu='Thursday'; fri='Friday'; sat='Saturday'; sun='Sunday' };" ^
  "foreach ($j in $jobs) {" ^
  "  $safe = ($j.name -replace '[\\/:*?<>|]', '_');" ^
  "  $tn = '매물수집 자동실행 - ' + $safe;" ^
  "  $a = New-ScheduledTaskAction -Execute $exe -Argument ('--run-job ' + [char]34 + $j.name + [char]34) -WorkingDirectory $dir;" ^
  "  $days = @($j.days);" ^
  "  if ($days.Count -eq 0 -or $days -contains 'daily') { $t = New-ScheduledTaskTrigger -Daily -At $j.schedule_time; $dtxt = '매일' }" ^
  "  else { $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek @($days | ForEach-Object { $map[$_] } | Where-Object { $_ }) -At $j.schedule_time; $dtxt = ($days -join ',') };" ^
  "  Register-ScheduledTask -TaskName $tn -Action $a -Trigger $t -Settings $s -Description '전국부동산매물수집기 예약 자동 수집 후 메일/텔레그램 전송' -Force | Out-Null;" ^
  "  Write-Host ('  등록됨  ' + $j.schedule_time + '  ' + $dtxt + '  [' + $j.name + ']') -ForegroundColor Green;" ^
  "};" ^
  "Write-Host '';" ^
  "Write-Host ('총 ' + $jobs.Count + '개 예약을 작업 스케줄러에 등록했습니다. 프로그램을 꺼 두어도 그 시각에 PC가 켜져(또는 깨어나) 실행합니다.') -ForegroundColor Green;" ^
  "try { powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null; powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null; powercfg /setactive SCHEME_CURRENT | Out-Null; Write-Host '깨우기 타이머도 켰습니다. 퇴근할 때 전원을 끄지 말고 절전/그대로 두세요.' } catch { Write-Host '(깨우기 타이머 설정은 건너뜀)' };" ^
  "} catch { Write-Host ''; Write-Host ('[실패] ' + $_.Exception.Message) -ForegroundColor Red; try { Stop-Transcript | Out-Null } catch { }; exit 1 };" ^
  "try { Stop-Transcript | Out-Null } catch { };"
if errorlevel 1 (
    echo.
    echo  등록에 실패했습니다. 위 빨간 글씨와 같은 폴더의 자동실행_등록.log 를 확인해 주세요.
    echo.
    pause
    exit /b 1
)
echo.
echo  [확인]  시작 메뉴에서 "작업 스케줄러"를 열면 '매물수집 자동실행' 로 시작하는 작업이 보입니다.
echo  [지금 시험]  아래에서 y 를 누르면 첫 번째 작업을 지금 한 번 돌려봅니다.
echo.
set "TESTRUN=n"
set /p TESTRUN=" 지금 한 번 시험 실행할까요? (y/n) : "
if /i "%TESTRUN%"=="y" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$n = @(Get-ScheduledTask | Where-Object { $_.TaskName -eq '매물수집 자동실행' -or $_.TaskName -like '매물수집 자동실행 - *' } | Select-Object -First 1); if ($n.Count -gt 0) { Start-ScheduledTask -TaskName $n[0].TaskName; Write-Host ('  실행했습니다: ' + $n[0].TaskName) } else { Write-Host '  등록된 작업이 없습니다.' }"
    echo  작업 표시줄에 창이 최소화된 채로 뜨고, 끝나면 스스로 닫힙니다.
)
echo.
echo  예약을 바꾸면 이 파일을 다시 실행하세요(기존 등록은 자동으로 갈아끼웁니다).
echo  끄고 싶으면 같은 폴더의  자동실행_해제.bat  을 실행하세요.
echo.
pause
