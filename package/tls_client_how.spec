# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = collect_submodules('tls_client')
datas  = collect_data_files('tls_client')

hidden += ['authorisor']

a = Analysis(
    ['app.py'],
    pathex=['D:/codecoon_server_manager'],
    binaries=[        
        (
            r"C:\Users\for\AppData\Local\Programs\Python\Python313\Lib\site-packages\tls_client\dependencies\tls-client-64.dll",
            "tls_client/dependencies"
        ),
    ],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('v', None, 'OPTION')],
    name='N부동산매물추출',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
