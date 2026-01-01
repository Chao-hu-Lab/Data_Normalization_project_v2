# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# PyInstaller Spec File for Metabolomics Data Normalization
# =============================================================================
# Build command: pyinstaller build/MetabolomicsNormalization.spec
# =============================================================================

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all submodules for packages that need them
hiddenimports = []
hiddenimports += collect_submodules('sklearn')
hiddenimports += collect_submodules('statsmodels')
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('metabolomics')
hiddenimports += [
    'sklearn.utils._typedefs',
    'sklearn.utils._heap',
    'sklearn.utils._sorting',
    'sklearn.utils._vector_sentinel',
    'scipy.special._cdflib',
    'scipy.special._ufuncs_cxx',
    'scipy.linalg.cython_blas',
    'scipy.linalg.cython_lapack',
    'scipy.integrate',
    'scipy.integrate._odepack',
    'scipy.integrate._quadpack',
    'metabolomics.processors.istd',
    'metabolomics.processors.qc_lowess',
    'metabolomics.processors.batch_effect',
    'metabolomics.processors.normalization',
    'metabolomics.utils',
    'metabolomics.gui',
]

# Data files to include (paths relative to project root)
datas = [
    ('src/metabolomics', 'metabolomics'),
    ('docs', 'docs'),
]

# Add assets if exists
if os.path.exists('build/assets'):
    datas.append(('build/assets', 'assets'))

# Check for icon
icon_path = 'build/assets/icon.ico' if os.path.exists('build/assets/icon.ico') else None

a = Analysis(
    ['src/metabolomics/gui/app.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'unittest',
        'pydoc',
        'doctest',
        'test',
        'tests',
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
    name='MetabolomicsNormalization',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
