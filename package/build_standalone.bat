@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] 필요한 패키지 설치 중...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo 패키지 설치 실패
    pause
    exit /b 1
)

echo [2/3] PyInstaller로 빌드 중... (몇 분 걸릴 수 있습니다)
pyinstaller --noconfirm --clean app_v1_site_standalone.spec
if %ERRORLEVEL% neq 0 (
    echo 빌드 실패
    pause
    exit /b 1
)

echo [3/3] 완료! dist 폴더 안의 전국부동산매물수집기_독립버전.exe 를 실행하세요.
pause
