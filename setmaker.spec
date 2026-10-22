# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller para la versión portable (modo carpeta / onedir).
# Uso:  pyinstaller setmaker.spec --noconfirm

block_cipher = None

# Módulos de Qt que SETMAKER no usa (reduce tamaño de la carpeta)
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.QtDesigner", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtTest",
    "tkinter", "unittest", "pytest",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SETMAKER",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # sin ventana negra de consola
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SETMAKER",
)
