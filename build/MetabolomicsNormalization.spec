# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# PyInstaller Spec File for Metabolomics Data Normalization
# =============================================================================
# Build command: pyinstaller build/MetabolomicsNormalization.spec
# =============================================================================

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Resolve paths relative to project root (spec lives in build/).
spec_path = globals().get('__file__') or sys.argv[0]
here = os.path.abspath(os.path.dirname(spec_path))
project_root = os.path.abspath(os.path.join(here, os.pardir))

# Collect all submodules for packages that need them
hiddenimports = []
hiddenimports += collect_submodules('sklearn')
hiddenimports += collect_submodules('statsmodels')
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('skbio')
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
    'metabolomics.processors.qc_batch_scaling',
    'metabolomics.processors.normalization',
    'metabolomics.utils',
    'metabolomics.gui_qt',
]

# Data files to include (paths relative to project root)
datas = [
    (os.path.join(project_root, 'src', 'metabolomics'), 'metabolomics'),
    (os.path.join(project_root, 'docs'), 'docs'),
]

# Add assets if exists
assets_path = os.path.join(project_root, 'build', 'assets')
if os.path.exists(assets_path):
    datas.append((assets_path, 'assets'))

# Check for icon
icon_path = os.path.join(assets_path, 'icon.ico') if os.path.exists(os.path.join(assets_path, 'icon.ico')) else None

a = Analysis(
    [os.path.join(project_root, 'src', 'metabolomics', 'gui_qt', 'app.py')],
    pathex=[os.path.join(project_root, 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
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
