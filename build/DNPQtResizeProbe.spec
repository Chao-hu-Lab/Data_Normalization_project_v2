# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the disposable P0 Qt resize kill-gate."""

import os
import sys


spec_path = globals().get("__file__") or sys.argv[0]
here = os.path.abspath(os.path.dirname(spec_path))
project_root = os.path.abspath(os.path.join(here, os.pardir))

a = Analysis(
    [
        os.path.join(
            project_root,
            "src",
            "metabolomics",
            "gui_qt",
            "p0_resize_probe.py",
        )
    ],
    pathex=[os.path.join(project_root, "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "test", "tests"],
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
    name="DNPQtResizeProbe",
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
