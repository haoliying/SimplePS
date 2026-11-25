# -*- mode: python ; coding: utf-8 -*-
"""命令行版打包配置：生成 SimplePS-cli.exe（带控制台）。"""

block_cipher = None

hidden_imports = [
    "tkinter", "tkinter.ttk", "PIL.Image", "PIL.ImageFont", "PIL.ImageTk",
    "numpy", "cv2", "customtkinter", "darkdetect",
]

try:
    from PyInstaller.utils.hooks import collect_data_files
    ctk_datas = collect_data_files("customtkinter")
except Exception:
    ctk_datas = []

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "torch", "tensorflow"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SimplePS-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon="assets/icon.ico",
)
