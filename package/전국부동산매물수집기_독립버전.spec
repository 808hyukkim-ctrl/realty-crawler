# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\loanyfn\\Desktop\\독립버전크롤링\\package\\dist_obf_standalone\\app_v1_site_standalone.py'],
    pathex=[],
    binaries=[],
    datas=[('regions.json', '.'), ('regions_bbox.json', '.'), ('naver_rls.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='전국부동산매물수집기_독립버전',
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
)
