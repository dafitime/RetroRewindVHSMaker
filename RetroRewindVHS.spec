# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[('D:\\ffmpeg\\ffmpeg-2024-09-05-git-3d0d0f68d5-essentials_build\\bin\\ffmpeg.exe', '.'), ('D:\\ffmpeg\\ffmpeg-2024-09-05-git-3d0d0f68d5-essentials_build\\bin\\ffprobe.exe', '.')],
    datas=[('vhs_engine.py', '.'), ('icon.png', '.'), ('icon.ico', '.'), ('C:\\Users\\DJ_In\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python310\\site-packages\\cv2\\data\\haarcascade_frontalface_default.xml', '.')],
    hiddenimports=['cv2', 'numpy', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox'],
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
    [],
    exclude_binaries=True,
    name='RetroRewindVHS',
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
    version='version_info.txt',
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RetroRewindVHS',
)
