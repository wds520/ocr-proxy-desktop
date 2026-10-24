# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

root = Path(SPECPATH)

datas = [(str(root / 'src' / 'app.ico'), '.')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on']
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(root / 'src' / 'app.py')],
    pathex=[str(root / 'src'), str(root / 'vendor')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas', 'scipy', 'IPython', 'pytest', 'notebook'],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows' unversioned ICU API. An unrelated Poppler directory on
# the build host's PATH contains ICU 78 with suffixed exports; bundling it
# causes QtCore to fail before the UI opens. Use the Windows system ICU.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OCRProxyDesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(root / 'src' / 'app.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OCRProxyDesktop',
)
