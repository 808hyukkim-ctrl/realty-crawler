# -*- mode: python ; coding: utf-8 -*-
"""
Cython .pyd + PyInstaller (v1 site, 회원 로그인 없이 codecoon 인증만)

의존성 번들: launcher → cython_bundle_deps.py
"""
import os
import glob
import site

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
STAGE = os.path.join(SPEC_DIR, "dist_cython_build_v1_site_no_auth")

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

a = Analysis(
    [os.path.join(STAGE, 'launcher_cython_v1_site_no_auth.py')],
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
    name='전국부동산매물수집기_v1_no_auth.exe',
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
