"""
통합 빌드 CLI: `python build_cli.py cython v1` / `python build_cli.py plain v1` /
`python build_cli.py obfuscate v2` 등.

예전 이름의 호환용 래퍼는 deprecated/ 폴더에 있다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from build_cython_core import CythonBuildConfig, run_cython_build, install_dependencies
from build_obfuscate_core import ObfuscateBuildConfig, run_obfuscate_build

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

CYTHON_PRESETS: dict[str, CythonBuildConfig] = {
    "v1": CythonBuildConfig(
        stage_subdir="dist_cython_build",
        source_files=(
            "app_v1_main.py",
            "app_main_common.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v1.py",
        bundle_deps_basename="cython_bundle_deps.py",
        setup_package_name="v1_cython",
        spec_basename="app_v1_cython.spec",
        done_message="완료: dist\\전국 부동산 매물 수집기 v1.exe (Cython .pyd + PyInstaller)",
    ),
    "v1-ft": CythonBuildConfig(
        stage_subdir="dist_cython_build_free_trial",
        source_files=(
            "app_v1_main.py",
            "app_main_common.py",
            "free_trial_app_shared.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_free_trial.py",
        bundle_deps_basename="cython_bundle_deps_free_trial.py",
        setup_package_name="v1_free_trial_cython",
        spec_basename="app_v1_free_trial_cython.spec",
        done_message="완료: dist\\전국_부동산_매물_수집기_v1_무료체험.exe (Cython .pyd + PyInstaller)",
    ),
    "v1-site": CythonBuildConfig(
        stage_subdir="dist_cython_build_v1_site",
        source_files=(
            "app_v1_site_main.py",
            "app_main_common.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v1_site.py",
        bundle_deps_basename="cython_bundle_deps.py",
        setup_package_name="v1_site_cython",
        spec_basename="app_v1_site_cython.spec",
        done_message="완료: dist\\전국부동산매물수집기_v1_site.exe (Cython .pyd + PyInstaller)",
    ),
    "v1-site-noauth": CythonBuildConfig(
        stage_subdir="dist_cython_build_v1_site_no_auth",
        source_files=(
            "app_v1_site_main.py",
            "app_main_common.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v1_site_no_auth.py",
        bundle_deps_basename="cython_bundle_deps.py",
        setup_package_name="v1_site_no_auth_cython",
        spec_basename="app_v1_site_no_auth_cython.spec",
        done_message="완료: dist\\전국부동산매물수집기_v1_no_auth.exe (Cython .pyd + PyInstaller)",
    ),
    "v1-site-ft": CythonBuildConfig(
        stage_subdir="dist_cython_build_v1_site_free_trial",
        source_files=(
            "app_v1_site_main.py",
            "app_main_common.py",
            "free_trial_app_shared.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v1_site_free_trial.py",
        bundle_deps_basename="cython_bundle_deps_free_trial.py",
        setup_package_name="v1_site_free_trial_cython",
        spec_basename="app_v1_site_free_trial_cython.spec",
        done_message="완료: dist\\전국부동산매물수집기_v1_site_무료체험.exe (Cython .pyd + PyInstaller)",
    ),
    "v2": CythonBuildConfig(
        stage_subdir="dist_cython_build_v2",
        source_files=(
            "app_v2_main.py",
            "app_main_common.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v2.py",
        bundle_deps_basename="cython_bundle_deps.py",
        setup_package_name="app_v2_cython",
        spec_basename="app_v2_cython.spec",
        done_message="완료: dist\\전국부동산매물수집기_v2.exe (Cython .pyd + PyInstaller)",
    ),
    "v2-ft": CythonBuildConfig(
        stage_subdir="dist_cython_build_v2_free_trial",
        source_files=(
            "app_v2_main.py",
            "app_main_common.py",
            "free_trial_app_shared.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        launcher_basename="launcher_cython_v2_free_trial.py",
        bundle_deps_basename="cython_bundle_deps_free_trial.py",
        setup_package_name="v2_free_trial_cython",
        spec_basename="app_v2_free_trial_cython.spec",
        done_message="완료: dist\\전국부동산매물수집기_v2_무료체험.exe (Cython .pyd + PyInstaller)",
    ),
}

# Cython/난독화 없이 원본 .py를 그대로 PyInstaller에 넘기는 스펙 (MSVC 불필요).
PLAIN_PRESETS: dict[str, str] = {
    "v1": "app_v1_plain.spec",
    "v1-ft": "app_v1_free_trial_plain.spec",
    "v1-site": "app_v1_site_plain.spec",
    "v1-site-ft": "app_v1_site_free_trial_plain.spec",
    "v2": "app_v2_plain.spec",
    "v2-ft": "app_v2_free_trial_plain.spec",
}

OBFUSCATE_PRESETS: dict[str, ObfuscateBuildConfig] = {
    "standalone": ObfuscateBuildConfig(
        dist_subdir="dist_obf_standalone",
        source_files=(
            "app_v1_site_standalone.py",
            "app_v1_site_main.py",
            "app_main_common.py",
            "license_gate.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        entry_script_basename="app_v1_site_standalone.py",
        pyinstaller_exe_name="전국부동산매물수집기_독립버전",
        done_message="완료: dist\\전국부동산매물수집기_독립버전.exe (난독화 적용)",
    ),
    "v2": ObfuscateBuildConfig(
        dist_subdir="dist_obf_v2",
        source_files=(
            "app_v2.py",
            "app_v2_main.py",
            "app_main_common.py",
            "member_app_shared.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        entry_script_basename="app_v2.py",
        pyinstaller_exe_name="전국부동산매물수집기_v2",
        done_message="완료: dist\\전국부동산매물수집기_v2.exe (난독화 적용)",
    ),
    "v2-ft": ObfuscateBuildConfig(
        dist_subdir="dist_obf_v2_free_trial",
        source_files=(
            "app_v2_free_trial.py",
            "app_v2_main.py",
            "app_main_common.py",
            "free_trial_app_shared.py",
            "schedule_manager.py",
            "schedule_dialog.py",
            "schedule_mixin.py",
            "daangn_realty_crawler.py",
            "peterpan_crawler.py",
            "onhouse_crawler.py",
            "naver_crawler.py",
        ),
        entry_script_basename="app_v2_free_trial.py",
        pyinstaller_exe_name="전국부동산매물수집기_v2_무료체험",
        done_message="완료: dist\\전국부동산매물수집기_v2_무료체험.exe (난독화 적용)",
    ),
}


def run_cython(target: str) -> int:
    cfg = CYTHON_PRESETS.get(target)
    if not cfg:
        print(f"알 수 없는 cython 타깃: {target}")
        print("사용 가능:", ", ".join(sorted(CYTHON_PRESETS)))
        return 1
    return run_cython_build(PROJECT_DIR, cfg)


def run_plain(target: str) -> int:
    spec = PLAIN_PRESETS.get(target)
    if not spec:
        print(f"알 수 없는 plain 타깃: {target}")
        print("사용 가능:", ", ".join(sorted(PLAIN_PRESETS)))
        return 1

    print("[1/2] 빌드/런타임 의존성 설치 및 확인...")
    if install_dependencies(PROJECT_DIR) != 0:
        return 1

    print("\n[2/2] PyInstaller...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", os.path.join(PROJECT_DIR, spec), "--noconfirm"],
        cwd=PROJECT_DIR,
    )
    if result.returncode != 0:
        print("PyInstaller 빌드 실패")
        return 1

    print(f"\n완료: dist\\ ({spec}, Cython/난독화 없음)")
    return 0


def run_obfuscate(target: str) -> int:
    cfg = OBFUSCATE_PRESETS.get(target)
    if not cfg:
        print(f"알 수 없는 obfuscate 타깃: {target}")
        print("사용 가능:", ", ".join(sorted(OBFUSCATE_PRESETS)))
        return 1
    return run_obfuscate_build(PROJECT_DIR, cfg)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="전국부동산매물수집기 통합 빌드 (Cython / 난독화)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("cython", help="Cython .pyd + PyInstaller (spec 기반)")
    pc.add_argument(
        "target",
        choices=sorted(CYTHON_PRESETS.keys()),
        help="v1 | v1-ft | v1-site | v1-site-noauth | v1-site-ft | v2 | v2-ft",
    )

    pp = sub.add_parser("plain", help="Cython/난독화 없이 PyInstaller 단독 (spec 기반)")
    pp.add_argument(
        "target",
        choices=sorted(PLAIN_PRESETS.keys()),
        help="v1 | v1-ft | v1-site | v1-site-ft | v2 | v2-ft",
    )

    po = sub.add_parser("obfuscate", help="python-minifier 난독화 + PyInstaller onefile")
    po.add_argument("target", choices=sorted(OBFUSCATE_PRESETS.keys()), help="standalone | v2 | v2-ft")

    pl = sub.add_parser("list", help="사용 가능한 타깃 출력")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "list":
        print("cython:", ", ".join(sorted(CYTHON_PRESETS.keys())))
        print("plain:", ", ".join(sorted(PLAIN_PRESETS.keys())))
        print("obfuscate:", ", ".join(sorted(OBFUSCATE_PRESETS.keys())))
        return 0
    if args.cmd == "cython":
        return run_cython(args.target)
    if args.cmd == "plain":
        return run_plain(args.target)
    if args.cmd == "obfuscate":
        return run_obfuscate(args.target)
    return 1


if __name__ == "__main__":
    sys.exit(main())
