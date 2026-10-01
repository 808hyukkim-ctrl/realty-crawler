@echo off
chcp 65001 > nul
title 온하우스 매물수집기 - 자동 실행 해제

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
echo  '온하우스 자동수집' 로 등록된 작업을 모두 해제합니다.
echo  (프로그램과 수집한 엑셀은 그대로 남습니다)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$x = @(Get-ScheduledTask | Where-Object { $_.TaskName -eq '온하우스 자동수집' -or $_.TaskName -like '온하우스 자동수집 - *' }); if ($x.Count -eq 0) { Write-Host '  등록된 작업이 없습니다.' } else { foreach ($t in $x) { Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false; Write-Host ('  해제: ' + $t.TaskName) } }"
echo.
echo  해제했습니다. 다시 켜려면 자동실행_설정.bat 을 실행하세요.
echo.
pause
