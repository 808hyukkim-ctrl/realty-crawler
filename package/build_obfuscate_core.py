"""
python-minifier 난독화 + PyInstaller 공통 로직.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ObfuscateBuildConfig:
    dist_subdir: str
    source_files: tuple[str, ...]
    entry_script_basename: str
    pyinstaller_exe_name: str
    done_message: str


def _on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except Exception:
        pass
    func(path)


def _safe_recreate_dir(path: str, stage_label: str, retries: int = 5, delay_sec: float = 0.7) -> None:
    if os.path.exists(path):
        last_err = None
        for i in range(retries):
            try:
                shutil.rmtree(path, onerror=_on_rm_error)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                print(f"  - {stage_label} 삭제 재시도 {i + 1}/{retries} (잠금 해제 대기)")
                time.sleep(delay_sec * (i + 1))
        if last_err:
            raise PermissionError(
                f"{stage_label} 삭제 실패: {last_err}\n"
                f"탐색기/터미널에서 {stage_label}를 점유 중인 프로세스를 종료 후 다시 시도하세요."
            ) from last_err
    os.makedirs(path, exist_ok=True)


def run_obfuscate_build(project_dir: str, cfg: ObfuscateBuildConfig) -> int:
    os.chdir(project_dir)
    dist_obf = os.path.join(project_dir, cfg.dist_subdir)

    print("[1/4] python-minifier, pyinstaller 설치 확인...")
    subprocess.run([sys.executable, "-m", "pip", "install", "python-minifier", "pyinstaller", "-q"], check=True)

    print(f"\n[2/4] {cfg.dist_subdir} 생성 및 소스 복사...")
    _safe_recreate_dir(dist_obf, cfg.dist_subdir)
    for f in cfg.source_files:
        shutil.copy2(os.path.join(project_dir, f), os.path.join(dist_obf, f))

    print("\n[3/4] python-minifier로 난독화...")
    result = subprocess.run(
        [
            sys.executable, "-m", "python_minifier",
            "--remove-literal-statements",
            "--remove-asserts",
            "--remove-debug",
            "--prefer-single-line",
            "-i",
            *[os.path.join(dist_obf, f) for f in cfg.source_files],
        ],
        cwd=project_dir,
    )
    if result.returncode != 0:
        print("난독화 실패")
        return 1

    print("\n[4/4] PyInstaller 빌드...")
    script_path = os.path.join(dist_obf, cfg.entry_script_basename)
    pyinstaller_args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", cfg.pyinstaller_exe_name,
        "--add-data", "regions.json;.",
        "--add-data", "regions_bbox.json;.",
        "--add-data", "naver_rls.json;.",
    ]
    asset_dir = os.path.join(project_dir, "asset")
    asset_ico = os.path.join(asset_dir, "CodeCoon_profile.ico")
    if os.path.isdir(asset_dir):
        pyinstaller_args += ["--add-data", "asset;asset"]
    if os.path.exists(asset_ico):
        pyinstaller_args += ["--icon", "asset/CodeCoon_profile.ico"]
    pyinstaller_args.append(script_path)
    result = subprocess.run(pyinstaller_args, cwd=project_dir)
    if result.returncode != 0:
        print("빌드 실패")
        return 1

    print(f"\n{cfg.done_message}")
    return 0
