# -*- coding: utf-8 -*-
r"""자동실행_설정.bat / 자동실행_해제.bat 생성기.

사용:  python make_autorun_bats.py            → package/ 에 템플릿 4종 생성
       python make_autorun_bats.py --deploy   → Desktop\스크랩핑 파일\ 각 exe 폴더에도 복사

2026-10-01 변경
- 관리자 승격을 cmd.exe /c ""경로"" 로 바꿈 (폴더 이름에 공백이 있어도 동작, 취소/실패 시 창이 닫히지 않고 메시지 표시)
- 예약(schedules.json)에 켜 둔 예약을 그대로 작업 스케줄러에 1:1 등록 (예약마다 --run-job "이름", 요일/시각 그대로)
- 진행 내용을 자동실행_등록.log 에 남김
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY_ROOT = os.path.join(os.path.expanduser("~"), "Desktop", "스크랩핑 파일")

VARIANTS = {
    # key: (템플릿 파일 접두어, 배포 폴더, exe 이름, 예약 json, 작업 이름 접두어, 화면 제목, 준비물 안내)
    "tonghap": dict(
        prefix="통합", folder="전국부동산매물수집기_신규빌드_260921",
        exe="전국부동산매물수집기_독립버전_260921.exe", sched="schedules.json",
        task="매물수집 자동실행", title="전국부동산매물수집기",
        prep=["라이선스 창에서 아이디/비밀번호 기억 체크",
              "예약 탭에서 예약을 만들고 켜 두기 (시각·요일·수집 조건이 그대로 등록됩니다)",
              "'자동 전송' 탭에 메일 또는 텔레그램 입력 후 저장"]),
    "tonghap_nohosu": dict(
        prefix="통합_호수없음", folder="전국부동산매물수집기_신규빌드_260921_호수없음",
        exe="전국부동산매물수집기_독립버전_호수없음.exe", sched="schedules.json",
        task="매물수집 자동실행_호수없음", title="전국부동산매물수집기(호수없음)",
        prep=["라이선스 창에서 아이디/비밀번호 기억 체크",
              "예약 탭에서 예약을 만들고 켜 두기 (시각·요일·수집 조건이 그대로 등록됩니다)",
              "'자동 전송' 탭에 메일 또는 텔레그램 입력 후 저장"]),
    "onhouse": dict(
        prefix="온하우스", folder="온하우스매물수집기_260921",
        exe="온하우스매물수집기_독립버전.exe", sched="onhouse_schedules.json",
        task="온하우스 자동수집", title="온하우스 매물수집기",
        prep=["아이디/비밀번호 저장 체크",
              "예약을 만들고 켜 두기 (시각·요일·수집 조건이 그대로 등록됩니다)",
              "자동 전송 칸에 메일 또는 텔레그램 입력"]),
    "vworld": dict(
        prefix="vworld", folder="중개업소_신규개업수집기_260921",
        exe="중개업소_신규개업수집기.exe", sched=None,
        task="중개업소 신규개업 수집", title="중개업소 신규개업 수집기",
        prep=["브이월드 아이디/비밀번호 입력 (자동으로 받을 때 필요)",
              "지역과 개업일 기간을 정하고 [지금 뽑기]로 한 번 돌려보기 (그 설정이 저장됩니다)",
              "'보내기 · 자동화' 탭에서 메일 또는 텔레그램 입력 후 테스트 전송"]),
}

# ── 공통 조각 ──────────────────────────────────────────────────────────
HEADER = """@echo off
chcp 65001 > nul
title {title} - {what}
"""

# 관리자 승격: .bat 경로에 공백/한글이 있어도 안전하게 cmd.exe /c ""경로"" 로 넘긴다.
# UAC 에서 '아니오'를 누르거나 실패하면 메시지를 보여 주고 창을 닫지 않는다.
ELEVATE = """
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
"""

# PowerShell 본문은 큰따옴표 없이 작성한다(배치 → powershell -Command 로 넘길 때 깨지지 않도록).
PS_COMMON_HEAD = [
    "$ErrorActionPreference = 'Stop';",
    "$dir = '%~dp0';",
    "$exe = Join-Path $dir '{exe}';",
    "$log = Join-Path $dir '자동실행_등록.log';",
    "try {{ Start-Transcript -Path $log -Force | Out-Null }} catch {{ }};",
    "try {{",
    "if (-not (Test-Path $exe)) {{ throw ('실행 파일을 찾을 수 없습니다: ' + $exe) }};",
    "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew;",
    "Get-ScheduledTask | Where-Object {{ $_.TaskName -eq '{task}' -or $_.TaskName -like '{task} - *' }} | ForEach-Object {{ Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false }};",
]

PS_JOBS = [
    "$sf = Join-Path $dir '{sched}';",
    "if (-not (Test-Path $sf)) {{ throw '예약 파일({sched})이 없습니다. 프로그램 예약 탭에서 예약을 먼저 만들어 주세요.' }};",
    "$jobs = @((Get-Content $sf -Raw -Encoding UTF8 | ConvertFrom-Json).jobs | Where-Object {{ $_.enabled }});",
    "if ($jobs.Count -eq 0) {{ throw '켜져 있는 예약이 없습니다. 프로그램 예약 탭에서 예약을 만들고 켜 주세요.' }};",
    "$map = @{{ mon='Monday'; tue='Tuesday'; wed='Wednesday'; thu='Thursday'; fri='Friday'; sat='Saturday'; sun='Sunday' }};",
    "foreach ($j in $jobs) {{",
    "  $safe = ($j.name -replace '[\\\\/:*?<>|]', '_');",
    "  $tn = '{task} - ' + $safe;",
    "  $a = New-ScheduledTaskAction -Execute $exe -Argument ('--run-job ' + [char]34 + $j.name + [char]34) -WorkingDirectory $dir;",
    "  $days = @($j.days);",
    "  if ($days.Count -eq 0 -or $days -contains 'daily') {{ $t = New-ScheduledTaskTrigger -Daily -At $j.schedule_time; $dtxt = '매일' }}",
    "  else {{ $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek @($days | ForEach-Object {{ $map[$_] }} | Where-Object {{ $_ }}) -At $j.schedule_time; $dtxt = ($days -join ',') }};",
    "  Register-ScheduledTask -TaskName $tn -Action $a -Trigger $t -Settings $s -Description '{title} 예약 자동 수집 후 메일/텔레그램 전송' -Force | Out-Null;",
    "  Write-Host ('  등록됨  ' + $j.schedule_time + '  ' + $dtxt + '  [' + $j.name + ']') -ForegroundColor Green;",
    "}};",
    "Write-Host '';",
    "Write-Host ('총 ' + $jobs.Count + '개 예약을 작업 스케줄러에 등록했습니다. 프로그램을 꺼 두어도 그 시각에 PC가 켜져(또는 깨어나) 실행합니다.') -ForegroundColor Green;",
]

PS_RUNALL = [
    "$a = New-ScheduledTaskAction -Execute $exe -Argument '--run-all' -WorkingDirectory $dir;",
    "$t = New-ScheduledTaskTrigger -Daily -At '%RUNTIME%';",
    "Register-ScheduledTask -TaskName '{task}' -Action $a -Trigger $t -Settings $s -Description '{title} 자동 수집 후 메일/텔레그램 전송' -Force | Out-Null;",
    "Write-Host ('등록 완료 - 매일 %RUNTIME% 에 실행됩니다.') -ForegroundColor Green;",
]

PS_COMMON_TAIL = [
    "try {{ powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null; powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null; powercfg /setactive SCHEME_CURRENT | Out-Null; Write-Host '깨우기 타이머도 켰습니다. 퇴근할 때 전원을 끄지 말고 절전/그대로 두세요.' }} catch {{ Write-Host '(깨우기 타이머 설정은 건너뜀)' }};",
    "}} catch {{ Write-Host ''; Write-Host ('[실패] ' + $_.Exception.Message) -ForegroundColor Red; try {{ Stop-Transcript | Out-Null }} catch {{ }}; exit 1 }};",
    "try {{ Stop-Transcript | Out-Null }} catch {{ }};",
]

PS_TESTRUN = (
    "$n = @(Get-ScheduledTask | Where-Object {{ $_.TaskName -eq '{task}' -or $_.TaskName -like '{task} - *' }} | Select-Object -First 1); "
    "if ($n.Count -gt 0) {{ Start-ScheduledTask -TaskName $n[0].TaskName; Write-Host ('  실행했습니다: ' + $n[0].TaskName) }} else {{ Write-Host '  등록된 작업이 없습니다.' }}"
)

PS_UNREG = (
    "$x = @(Get-ScheduledTask | Where-Object {{ $_.TaskName -eq '{task}' -or $_.TaskName -like '{task} - *' }}); "
    "if ($x.Count -eq 0) {{ Write-Host '  등록된 작업이 없습니다.' }} else {{ foreach ($t in $x) {{ Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false; Write-Host ('  해제: ' + $t.TaskName) }} }}"
)


def ps_block(lines, v):
    """여러 줄 PowerShell 을 배치의 ^ 이어쓰기 형태로 만든다."""
    out = ["powershell -NoProfile -ExecutionPolicy Bypass -Command ^"]
    body = [ln.format(**v) for ln in lines]
    for i, ln in enumerate(body):
        sep = " ^" if i < len(body) - 1 else ""
        out.append('  "' + ln + '"' + sep)
    return "\n".join(out) + "\n"


def make_setup(v, elevate=True):
    s = HEADER.format(title=v["title"], what="자동 실행 등록")
    if elevate:
        s += ELEVATE
    else:
        s += '\ncd /d "%~dp0"\n'
    s += "echo.\necho ============================================================\n"
    s += "echo   {title} - 자동 실행 등록\necho ============================================================\necho.\n".format(**v)
    s += "echo  이 PC가 자고 있어도 정해진 시각에 깨어나 수집하고,\necho  메일과 텔레그램으로 보낸 뒤 프로그램이 스스로 닫힙니다.\necho.\n"
    s += "echo  [준비물]  프로그램에서 아래 세 가지를 먼저 해두세요.\n"
    for i, p in enumerate(v["prep"], 1):
        s += "echo    {0}. {1}\n".format(i, p)
    s += "echo.\n"
    if v["sched"]:
        s += "echo  프로그램 예약 탭에 켜 둔 예약을 그대로(시각·요일) 작업 스케줄러에 등록합니다.\necho.\n\n"
        s += ps_block(PS_COMMON_HEAD + PS_JOBS + PS_COMMON_TAIL, v)
    else:
        s += 'set "RUNTIME=08:30"\nset /p RUNTIME=" 매일 몇 시에 돌릴까요? (예: 08:30, 그냥 엔터=08:30) : "\nif "%RUNTIME%"=="" set "RUNTIME=08:30"\n\n'
        s += ps_block(PS_COMMON_HEAD + PS_RUNALL + PS_COMMON_TAIL, v)
    s += "if errorlevel 1 (\n    echo.\n    echo  등록에 실패했습니다. 위 빨간 글씨와 같은 폴더의 자동실행_등록.log 를 확인해 주세요.\n    echo.\n    pause\n    exit /b 1\n)\n"
    s += "echo.\n"
    s += 'echo  [확인]  시작 메뉴에서 "작업 스케줄러"를 열면 \'{task}\' 로 시작하는 작업이 보입니다.\n'.format(**v)
    s += "echo  [지금 시험]  아래에서 y 를 누르면 첫 번째 작업을 지금 한 번 돌려봅니다.\necho.\n"
    s += 'set "TESTRUN=n"\nset /p TESTRUN=" 지금 한 번 시험 실행할까요? (y/n) : "\nif /i "%TESTRUN%"=="y" (\n'
    s += '    powershell -NoProfile -ExecutionPolicy Bypass -Command "' + PS_TESTRUN.format(**v) + '"\n'
    s += "    echo  작업 표시줄에 창이 최소화된 채로 뜨고, 끝나면 스스로 닫힙니다.\n)\n"
    s += "echo.\necho  예약을 바꾸면 이 파일을 다시 실행하세요(기존 등록은 자동으로 갈아끼웁니다).\n"
    s += "echo  끄고 싶으면 같은 폴더의  자동실행_해제.bat  을 실행하세요.\necho.\npause\n"
    return s


def make_remove(v):
    s = HEADER.format(title=v["title"], what="자동 실행 해제")
    s += ELEVATE
    s += "echo.\necho  '{task}' 로 등록된 작업을 모두 해제합니다.\necho  (프로그램과 수집한 엑셀은 그대로 남습니다)\necho.\n".format(**v)
    s += 'powershell -NoProfile -ExecutionPolicy Bypass -Command "' + PS_UNREG.format(**v) + '"\n'
    s += "echo.\necho  해제했습니다. 다시 켜려면 자동실행_설정.bat 을 실행하세요.\necho.\npause\n"
    return s


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\r\n", "\n").replace("\n", "\r\n"))
    print("wrote", path)


def main():
    deploy = "--deploy" in sys.argv
    for key, v in VARIANTS.items():
        write(os.path.join(HERE, v["prefix"] + "_자동실행_설정.bat"), make_setup(v))
        write(os.path.join(HERE, v["prefix"] + "_자동실행_해제.bat"), make_remove(v))
        if deploy:
            d = os.path.join(DEPLOY_ROOT, v["folder"])
            if os.path.isdir(d):
                write(os.path.join(d, "자동실행_설정.bat"), make_setup(v))
                write(os.path.join(d, "자동실행_해제.bat"), make_remove(v))
            else:
                print("skip (no folder)", d)
    if "--test" in sys.argv:
        # 승격 없이 돌아가는 시험용(작업 이름 접두어를 바꿔 실제 등록과 섞이지 않게 함)
        i = sys.argv.index("--test")
        out = sys.argv[i + 1]
        key = sys.argv[i + 2] if len(sys.argv) > i + 2 else "tonghap"
        v = dict(VARIANTS[key]); v["task"] = "zz테스트 " + v["task"]
        write(out, make_setup(v, elevate=False))


if __name__ == "__main__":
    main()
