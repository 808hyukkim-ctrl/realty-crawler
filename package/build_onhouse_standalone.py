# -*- coding: utf-8 -*-
"""
온하우스 매물수집기 단독 exe 빌드.
  - 소스(onhouse_standalone_app.py, onhouse_crawler.py)를 dist_obf_onhouse/ 로 복사 → python-minifier 난독화
  - PyInstaller onefile/windowed 로 빌드. 결과물은 --out 폴더(기본: 바탕화면\온하우스매물수집기_YYMMDD)
  - 기존 dist/, dist_obf_standalone/, build/ 는 건드리지 않음

사용:  python build_onhouse_standalone.py [--out 출력폴더]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILES = ("onhouse_standalone_app.py", "onhouse_crawler.py", "app_main_common.py", "schedule_manager.py")
ENTRY = "onhouse_standalone_app.py"
EXE_NAME = "온하우스매물수집기_독립버전"
OBF_DIR = os.path.join(PROJECT_DIR, "dist_obf_onhouse")
WORK_DIR = os.path.join(PROJECT_DIR, "build_onhouse")


def main() -> int:
    ap = argparse.ArgumentParser()
    default_out = os.path.join(os.path.expanduser("~"), "Desktop", f"온하우스매물수집기_{datetime.now():%y%m%d}")
    ap.add_argument("--out", default=default_out, help="exe 출력 폴더")
    ap.add_argument("--no-obf", action="store_true", help="난독화 생략(디버깅용)")
    args = ap.parse_args()

    os.chdir(PROJECT_DIR)
    print("[1/4] python-minifier, pyinstaller 확인...")
    subprocess.run([sys.executable, "-m", "pip", "install", "python-minifier", "pyinstaller", "-q"], check=True)

    print(f"[2/4] 소스 복사 → {OBF_DIR}")
    shutil.rmtree(OBF_DIR, ignore_errors=True)
    os.makedirs(OBF_DIR, exist_ok=True)
    for f in SOURCE_FILES:
        shutil.copy2(os.path.join(PROJECT_DIR, f), os.path.join(OBF_DIR, f))

    if not args.no_obf:
        print("[3/4] python-minifier 난독화...")
        r = subprocess.run(
            [sys.executable, "-m", "python_minifier",
             "--remove-literal-statements", "--remove-asserts", "--remove-debug", "--prefer-single-line",
             "-i", *[os.path.join(OBF_DIR, f) for f in SOURCE_FILES]],
            cwd=PROJECT_DIR,
        )
        if r.returncode != 0:
            print("난독화 실패")
            return 1
    else:
        print("[3/4] 난독화 생략")

    print(f"[4/4] PyInstaller 빌드 → {args.out}")
    os.makedirs(args.out, exist_ok=True)
    # 기존 exe가 실행 중/백신 스캔 중이면 덮어쓰기가 막힌다 → 잠시 재시도 후, 그래도 안 되면 시각을 붙인 새 이름으로 저장
    exe_name = EXE_NAME
    target = os.path.join(args.out, EXE_NAME + ".exe")
    if os.path.exists(target):
        for i in range(5):
            try:
                os.remove(target)
                break
            except PermissionError:
                print(f"  - 기존 exe 잠김, 삭제 재시도 {i + 1}/5 (실행 중이면 종료하세요)")
                time.sleep(2)
        if os.path.exists(target):
            exe_name = f"{EXE_NAME}_{datetime.now():%H%M}"
            print(f"  - 기존 exe를 지울 수 없어 새 이름으로 저장합니다: {exe_name}.exe")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", exe_name,
        "--add-data", f"{os.path.join(PROJECT_DIR, 'regions_bbox.json')}{os.pathsep}.",
        "--distpath", args.out,
        "--workpath", WORK_DIR,
        "--specpath", OBF_DIR,
    ]
    for mod in ("PyQt5", "PyQt6", "PySide2"):
        cmd += ["--exclude-module", mod]
    cmd.append(os.path.join(OBF_DIR, ENTRY))
    r = subprocess.run(cmd, cwd=PROJECT_DIR)
    if r.returncode != 0:
        print("빌드 실패")
        return 1
    print(f"\n완료: {os.path.join(args.out, exe_name + '.exe')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
