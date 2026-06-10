# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for a portable Windows build of FlatCAM Evo.
# Build with: pyinstaller --noconfirm flatcam.spec  (or run build_windows.ps1)

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

# tclCommands modules are discovered at runtime via pkgutil.walk_packages,
# so the analysis cannot see them as imports — collect them all explicitly.
hiddenimports = collect_submodules('tclCommands') + [
    'vispy.app.backends._pyqt6',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_agg',
    'svg.path',
]

# The app chdirs to the directory containing appMain.py (= _internal in a
# PyInstaller 6 onedir build) and resolves these paths relative to it.
# preprocessors/*.py are loaded as source files via SourceFileLoader, so they
# must ship as plain .py data files, not frozen modules.
datas = [
    ('assets', 'assets'),
    ('preprocessors', 'preprocessors'),
    ('locale', 'locale'),
    ('config', 'config'),
    ('doc', 'doc'),
]

# vispy resolves its GLSL shaders and fonts on disk at import time;
# there is no bundled PyInstaller hook for it.
datas += collect_data_files('vispy')

# ortools loads its native DLLs from ortools/.libs relative to the package
# directory; the analysis only picks up the .pyd extension modules.
binaries = collect_dynamic_libs('ortools')

a = Analysis(
    ['flatcam.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FlatCAM_Evo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/resources/flatcam_icon256.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='FlatCAM_Evo',
)
