# -*- mode: python ; coding: utf-8 -*-
"""
Cython .pyd + PyInstaller (무료체험)

의존성 번들: launcher → cython_bundle_deps_free_trial.py
데이터·경로·tls dll 보강만 여기서 지정.
"""
import os
import glob
import site

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
STAGE = os.path.join(SPEC_DIR, "dist_cython_build_free_trial")

datas_list = [
    ('regions.json', '.'),
    ('regions_bbox.json', '.'),
    ('naver_rls.json', '.'),
]

bin_list = []
for sp in site.getsitepackages():
    _dll_pattern = os.path.join(sp, 'tls_client', 'dependencies', 'tls-client-64.dll')
    _dll_matches = glob.glob(_dll_pattern)
    if _dll_matches:
        bin_list.append((_dll_matches[0], 'tls_client/dependencies'))
        break

asset_ico = os.path.join(SPEC_DIR, 'asset', 'CodeCoon_profile.ico')
if os.path.exists(asset_ico):
    datas_list.append(('asset/CodeCoon_profile.ico', 'asset'))

# PySide6 는 자동 훅에 맡기되, 안 쓰는 무거운 Qt 모듈/DLL 은 build_pyside6_trim 으로 제외한다.
import sys
if SPEC_DIR not in sys.path:
    sys.path.insert(0, SPEC_DIR)
from build_pyside6_trim import PYSIDE6_UNUSED_QT, drop_heavy_qt_binaries

a = Analysis(
    [os.path.join(STAGE, 'launcher_cython_free_trial.py')],
    pathex=[SPEC_DIR, STAGE, r'D:\codecoon_server_manager'],
    binaries=bin_list,
    datas=datas_list,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PySide2',
        'PySide2.QtCore',
        'PySide2.QtGui',
        'PySide2.QtWidgets',
    ] + PYSIDE6_UNUSED_QT,
    noarchive=False,
    optimize=0,
)
# 자동 훅이 넣더라도 대용량 미사용 DLL 은 이름으로 제거
a.binaries = drop_heavy_qt_binaries(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='전국부동산매물수집기_v1_무료체험.exe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='asset/CodeCoon_profile.ico' if os.path.exists(asset_ico) else None,
)
