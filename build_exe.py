"""
build_exe.py  -  Retro Rewind VHS Converter  |  Build Script

Produces a SINGLE .exe file (no folder needed).
Users just double-click RetroRewindVHS.exe.

Usage:
    python build_exe.py           # build only
    python build_exe.py --sign    # build + self-sign (Windows only, needs signtool)

Requirements:
    pip install pyinstaller pillow opencv-python numpy
"""

import subprocess
import sys
import os
import shutil
import argparse
from pathlib import Path

APP_NAME    = "RetroRewindVHS"
ENTRY_POINT = "app.py"
ICON_ICO    = "icon.ico"
ICON_PNG    = "icon.png"
VERSION     = "1.0.0.0"   # used for self-signing


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"OK  PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def find_cascade():
    try:
        import cv2
        path = os.path.join(cv2.data.haarcascades,
                            "haarcascade_frontalface_default.xml")
        if os.path.isfile(path):
            print(f"OK  Cascade XML: {path}")
            return path
    except Exception:
        pass
    print("WARN  Haar cascade not found — face detection disabled in bundle")
    return None


def build():
    check_pyinstaller()

    here = Path(__file__).parent.resolve()
    os.chdir(here)

    cascade = find_cascade()

    # ------------------------------------------------------------------
    # Core PyInstaller arguments
    # ------------------------------------------------------------------
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name",        APP_NAME,
        "--onefile",                  # ← single .exe, no folder
        "--windowed",                 # no console window
        "--clean",
        "--noconfirm",

        # Hidden imports PyInstaller misses
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.filedialog",
        "--hidden-import", "tkinter.messagebox",

        # Bundle source files that get imported at runtime
        "--add-data", f"vhs_engine.py{os.pathsep}.",
        "--add-data", f"icon.png{os.pathsep}.",     # for iconphoto()
        "--add-data", f"icon.ico{os.pathsep}.",     # fallback
    ]

    # Bundle Haar cascade if found
    if cascade:
        args += ["--add-data", f"{cascade}{os.pathsep}."]

    # Set .exe icon (visible in Explorer and taskbar)
    if Path(ICON_ICO).exists():
        args += ["--icon", ICON_ICO]

    args.append(ENTRY_POINT)

    print("\nBuilding single-file executable...\n")
    result = subprocess.run(args)

    if result.returncode != 0:
        print("\nBuild FAILED. Check errors above.")
        sys.exit(1)

    exe = here / "dist" / f"{APP_NAME}.exe"
    print(f"\nBuild complete!")
    print(f"  Output: {exe}")
    print(f"  Size:   {exe.stat().st_size / 1024 / 1024:.1f} MB")
    return exe


# ------------------------------------------------------------------
# SELF-SIGNING  (Windows only)
# Creates a self-signed certificate and signs the exe.
# Users will still see a SmartScreen warning the FIRST time they run
# it, but it won't be blocked outright — they can click "More info"
# then "Run anyway". After enough users run it, SmartScreen reputation
# builds and the warning disappears automatically.
# ------------------------------------------------------------------

def self_sign(exe_path: Path):
    """
    Self-sign the exe using Windows signtool + a self-signed certificate.
    Requires: Windows SDK (signtool.exe) and PowerShell.
    """
    print("\nSelf-signing executable...")

    # Find signtool.exe
    signtool = _find_signtool()
    if not signtool:
        print("WARN  signtool.exe not found. Skipping signing.")
        print("      Install Windows SDK from: https://developer.microsoft.com/windows/downloads/windows-sdk/")
        return

    cert_name = "RetroRewindVHS"
    pfx_path  = Path("retro_rewind_selfsigned.pfx")
    pfx_pass  = "retro_rewind_build"

    # Step 1: Create self-signed cert via PowerShell
    print("  Creating self-signed certificate...")
    ps_cmd = (
        f'$cert = New-SelfSignedCertificate '
        f'-Subject "CN={cert_name}" '
        f'-Type CodeSigning '
        f'-CertStoreLocation Cert:\\CurrentUser\\My; '
        f'$pwd = ConvertTo-SecureString -String "{pfx_pass}" -Force -AsPlainText; '
        f'Export-PfxCertificate -Cert $cert -FilePath "{pfx_path.resolve()}" -Password $pwd'
    )
    r = subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not pfx_path.exists():
        print(f"WARN  Could not create certificate:\n{r.stderr[:300]}")
        return

    # Step 2: Sign the exe
    print(f"  Signing {exe_path.name}...")
    r2 = subprocess.run([
        signtool, "sign",
        "/f",  str(pfx_path),
        "/p",  pfx_pass,
        "/fd", "SHA256",
        "/t",  "http://timestamp.digicert.com",
        "/v",
        str(exe_path),
    ], capture_output=True, text=True)

    pfx_path.unlink(missing_ok=True)   # delete temp PFX

    if r2.returncode == 0:
        print("  Signed OK.")
        print("\n  NOTE: Users will still see a SmartScreen warning since this is")
        print("  a self-signed cert. They click 'More info' then 'Run anyway'.")
        print("  SmartScreen reputation builds over time as more users run it.")
    else:
        print(f"  Signing failed:\n{r2.stderr[:400]}")


def _find_signtool():
    # Common SDK locations
    candidates = [
        r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe",
        r"C:\Program Files (x86)\Windows Kits\10\bin\x86\signtool.exe",
        r"C:\Program Files\Windows Kits\10\bin\x64\signtool.exe",
    ]
    # Also search versioned paths
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits.exists():
        for v in sorted(kits.iterdir(), reverse=True):
            st = v / "x64" / "signtool.exe"
            if st.exists():
                candidates.insert(0, str(st))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("signtool")


# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sign", action="store_true",
                        help="Self-sign the exe after building (Windows only)")
    args = parser.parse_args()

    exe = build()

    if args.sign:
        if sys.platform != "win32":
            print("WARN  --sign only works on Windows. Skipping.")
        else:
            self_sign(exe)

    print(f"\nDone. Distribute:  dist/{APP_NAME}.exe")
    print("Just share that single file — no zip, no folder needed.")
