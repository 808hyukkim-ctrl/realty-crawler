# -*- mode: python ; coding: utf-8 -*-
"""
Cython 없이 PyInstaller 단독 빌드 (v2 무료체험)
"""
import os
import glob
import site

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

datas_list = [
    (os.path.join(SPEC_DIR, 'regions.json'), '.'),
    (os.path.join(SPEC_DIR, 'regions_bbox.json'), '.'),
    (os.path.join(SPEC_DIR, 'naver_rls.json'), '.'),
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
    datas_list.append((asset_ico, 'asset'))

# PySide6 는 collect_all 로 통째로 넣지 않는다(QtWebEngine 193MB 등 포함 시 300MB+, 빌드도 느려짐).
# PyInstaller 자동 훅이 실제 import(QtCore/QtGui/QtWidgets)만 수집하게 두고,
# 안 쓰는 무거운 Qt 모듈/DLL 은 build_pyside6_trim 으로 제외한다.
import sys
if SPEC_DIR not in sys.path:
    sys.path.insert(0, SPEC_DIR)
from build_pyside6_trim import PYSIDE6_UNUSED_QT, drop_heavy_qt_binaries

hidden_list = []

a = Analysis(
    [os.path.join(SPEC_DIR, 'app_v2_free_trial.py')],
    pathex=[SPEC_DIR, r'D:\codecoon_server_manager'],
    binaries=bin_list,
    datas=datas_list,
    hiddenimports=hidden_list,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'PySide2', 'PySide2.QtCore', 'PySide2.QtGui', 'PySide2.QtWidgets',
    ] + PYSIDE6_UNUSED_QT,
    noarchive=False,
    optimize=0,
)
# 자동 훅이 넣더라도 대용량 미사용 DLL(WebEngine 193MB, opengl32sw, ffmpeg 등)은 이름으로 제거
a.binaries = drop_heavy_qt_binaries(a.binaries)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='전국부동산매물수집기_v2_무료체험.exe',
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
    icon=asset_ico if os.path.exists(asset_ico) else None,
)
