# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the disposable P3 real-density Qt resize gate."""

import os
import sys


spec_path = globals().get("__file__") or sys.argv[0]
here = os.path.abspath(os.path.dirname(spec_path))
project_root = os.path.abspath(os.path.join(here, os.pardir))

a = Analysis(
    [os.path.join(project_root, "src", "metabolomics", "gui_qt", "app.py")],
    pathex=[os.path.join(project_root, "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
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
    name="DNPQtP3Preview",
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
    icon=None,
)
