@echo off
chcp 65001 > nul
title 중개업소 신규개업 수집 - 등록 해제

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo 관리자 권한으로 다시 실행합니다...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  '중개업소 신규개업 수집' 등록을 해제합니다.
echo  (프로그램과 수집한 엑셀은 그대로 남습니다)
echo.
schtasks /delete /tn "중개업소 신규개업 수집" /f
echo.
echo  해제했습니다. 다시 켜려면 자동실행_설정.bat 을 실행하세요.
echo.
pause
