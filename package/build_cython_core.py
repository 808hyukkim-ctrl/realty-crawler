"""
Cython + PyInstaller 빌드 공통 로직 (프리셋은 build_cli.py).
"""
from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass

# .pyd 안의 import는 PyInstaller가 못 읽으므로 cython_bundle_deps.py가 대신 import 한다.
# 그 import가 분석 그래프에 잡히려면 빌드 인터프리터에 실제로 설치돼 있어야 한다.
RUNTIME_MODULES = (
    "PySide6",
    "curl_cffi",
    "requests",
    "bs4",
    "lxml",
    "tls_client",
    "pandas",
    "openpyxl",
    "dotenv",  # codecoon_server_manager.authorisor
    "getmac",  # codecoon_server_manager.authorisor
)


@dataclass(frozen=True)
class CythonBuildConfig:
    stage_subdir: str
    source_files: tuple[str, ...]
    launcher_basename: str
    bundle_deps_basename: str
    setup_package_name: str
    spec_basename: str
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
                "탐색기/터미널에서 해당 폴더를 점유 중인 프로세스를 종료 후 다시 시도하세요."
            ) from last_err
    os.makedirs(path, exist_ok=True)


def _write_setup_py(stage: str, files: tuple[str, ...], setup_name: str) -> None:
    names = [f.replace(".py", "") for f in files]
    ext_lines = ",\n    ".join([f'Extension("{n}", ["{n}.py"])' for n in names])
    content = f'''# -*- coding: utf-8 -*-
from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    {ext_lines}
]
setup(
    name="{setup_name}",
    ext_modules=cythonize(
        extensions,
        compiler_directives={{"language_level": "3", "annotation_typing": False}},
        nthreads=0,
    ),
    zip_safe=False,
)
'''
    with open(os.path.join(stage, "setup.py"), "w", encoding="utf-8") as f:
        f.write(content)


def _find_vcvars64() -> str | None:
    bases = []
    for key in ("ProgramFiles(x86)", "ProgramFiles"):
        v = os.environ.get(key)
        if v:
            bases.append(v)
    if r"C:\Program Files (x86)" not in bases:
        bases.append(r"C:\Program Files (x86)")
    if r"C:\Program Files" not in bases:
        bases.append(r"C:\Program Files")
    candidates: list[str] = []
    for base in bases:
        pattern = os.path.join(
            base,
            "Microsoft Visual Studio",
            "*",
            "*",
            "VC",
            "Auxiliary",
            "Build",
            "vcvars64.bat",
        )
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0]


def _run_build_ext_inplace(stage: str) -> int:
    cmd = [sys.executable, "setup.py", "build_ext", "--inplace"]
    if sys.platform != "win32":
        return subprocess.run(cmd, cwd=stage).returncode

    if shutil.which("cl"):
        return subprocess.run(cmd, cwd=stage).returncode

    vcvars = _find_vcvars64()
    if not vcvars:
        print(
            "\n[MSVC 없음] Cython .pyd 링크에 Visual C++ 빌드 도구가 필요합니다.\n"
            "  1) https://visualstudio.microsoft.com/visual-cpp-build-tools/\n"
            "  2) 설치 시 워크로드: 「C++를 사용한 데스크톱 개발」또는 MSVC v14x + Windows SDK\n"
            "  3) 설치 후 터미널을 다시 열고 이 스크립트를 재실행하세요.\n"
        )
        return 1

    exe = sys.executable.replace('"', '""')
    bat = vcvars.replace('"', '""')
    st = stage.replace('"', '""')
    inner = f'call "{bat}" && cd /d "{st}" && "{exe}" setup.py build_ext --inplace'
    print(f"  (PATH에 cl 없음 → vcvars 로드: {vcvars})")
    return subprocess.run(inner, shell=True).returncode


def install_dependencies(project_dir: str) -> int:
    """requirements.txt + 빌드 도구를 설치하고, 번들에 필요한 모듈이 다 있는지 확인한다."""
    req = os.path.join(project_dir, "requirements.txt")
    if os.path.isfile(req):
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req, "-q"], check=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "cython", "setuptools", "wheel", "pyinstaller", "-q"],
        check=True,
    )

    missing = [m for m in RUNTIME_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        print(
            f"\n[의존성 없음] 다음 패키지가 빌드 인터프리터에 없습니다: {', '.join(missing)}\n"
            f"  인터프리터: {sys.executable}\n"
            "  PyInstaller는 설치되지 않은 패키지를 조용히 번들에서 제외하므로,\n"
            "  이대로 빌드하면 exe 실행 시 ModuleNotFoundError가 납니다.\n"
            "  requirements.txt 설치 후 다시 시도하거나, 앱 의존성이 설치된 인터프리터로 실행하세요.\n"
            "  (dotenv/getmac은 pip install -e D:\\codecoon_server_manager 로 함께 들어옵니다)\n"
        )
        return 1
    return 0


def run_cython_build(project_dir: str, cfg: CythonBuildConfig) -> int:
    os.chdir(project_dir)
    stage = os.path.join(project_dir, cfg.stage_subdir)
    launcher_src = os.path.join(project_dir, cfg.launcher_basename)
    bundle_src = os.path.join(project_dir, cfg.bundle_deps_basename)
    launcher_dst = os.path.join(stage, cfg.launcher_basename)
    bundle_dst = os.path.join(stage, cfg.bundle_deps_basename)

    if not os.path.isfile(launcher_src):
        print(f"없음: {launcher_src}")
        return 1
    if not os.path.isfile(bundle_src):
        print(f"없음: {bundle_src}")
        return 1

    print("[1/5] 빌드/런타임 의존성 설치 및 확인...")
    if install_dependencies(project_dir) != 0:
        return 1

    print(f"\n[2/5] {cfg.stage_subdir} 준비 및 소스 복사...")
    _safe_recreate_dir(stage, cfg.stage_subdir)
    for f in cfg.source_files:
        src = os.path.join(project_dir, f)
        if not os.path.isfile(src):
            print(f"없음: {src}")
            return 1
        shutil.copy2(src, os.path.join(stage, f))
    shutil.copy2(launcher_src, launcher_dst)
    shutil.copy2(bundle_src, bundle_dst)
    _write_setup_py(stage, cfg.source_files, cfg.setup_package_name)

    print("\n[3/5] Cython + MSVC로 .pyd 빌드 (setup.py build_ext --inplace)...")
    rc = _run_build_ext_inplace(stage)
    if rc != 0:
        print(
            "Cython 빌드 실패. Visual Studio Build Tools 설치 후 재시도하거나, "
            "「x64 Native Tools Command Prompt for VS」에서 실행해 보세요."
        )
        return 1

    print("\n[4/5] 컴파일된 .py 원본 제거...")
    for f in cfg.source_files:
        p = os.path.join(stage, f)
        if os.path.isfile(p):
            os.remove(p)

    print("\n[5/5] PyInstaller...")
    spec_path = os.path.join(project_dir, cfg.spec_basename)
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_path, "--noconfirm"],
        cwd=project_dir,
    )
    if result.returncode != 0:
        print("PyInstaller 빌드 실패")
        return 1

    print(f"\n{cfg.done_message}")
    return 0
