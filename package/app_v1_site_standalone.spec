# -*- mode: python ; coding: utf-8 -*-
"""
전국부동산매물수집기 - 독립 실행 버전 (외부 인증 모듈 의존 없음)
Windows에서 아래 명령으로 빌드하세요:
    pyinstaller app_v1_site_standalone.spec
"""
import os

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

datas_list = [
    (os.path.join(SPEC_DIR, 'regions.json'), '.'),
    (os.path.join(SPEC_DIR, 'regions_bbox.json'), '.'),
    (os.path.join(SPEC_DIR, 'naver_rls.json'), '.'),
]

asset_ico = os.path.join(SPEC_DIR, 'asset', 'CodeCoon_profile.ico')
if os.path.exists(asset_ico):
    datas_list.append((asset_ico, 'asset'))

a = Analysis(
    [os.path.join(SPEC_DIR, 'app_v1_site_standalone.py')],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=datas_list,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'PySide2', 'PySide2.QtCore', 'PySide2.QtGui', 'PySide2.QtWidgets',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='전국부동산매물수집기_독립버전.exe',
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
