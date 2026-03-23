"""
build_exe.py  —  Retro Rewind VHS Converter v1.1  |  Build Script

Produces a FOLDER build (--onedir). Far less AV-suspicious than --onefile
because it doesn't extract to a temp directory on launch.

The folder is automatically zipped. Users unzip and run RetroRewindVHS.exe.
FFmpeg is bundled — no separate install needed.

Usage:
    python build_exe.py            # standard build
    python build_exe.py --onefile  # single exe (more AV-suspicious, not recommended)
    python build_exe.py --sign     # sign the exe after building (Windows only)

Requirements:
    pip install pyinstaller pillow opencv-python numpy
    ffmpeg.exe must be in PATH (will be bundled automatically)
"""

import subprocess, sys, os, shutil, argparse, zipfile
from pathlib import Path

APP_NAME    = "RetroRewindVHS"
VERSION     = "1.1"
ENTRY_POINT = "app.py"
ICON_ICO    = "icon.ico"


# ──────────────────────────────────────────────────────────────
#  PRE-BUILD CHECKS
# ──────────────────────────────────────────────────────────────

def check_pyinstaller():
    try:
        import PyInstaller
        print(f"  OK  PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("  Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def find_cascade():
    try:
        import cv2
        path = os.path.join(cv2.data.haarcascades,
                            "haarcascade_frontalface_default.xml")
        if os.path.isfile(path):
            print(f"  OK  Haar cascade: {path}")
            return path
    except Exception:
        pass
    print("  WARN  Haar cascade not found — face detection will be disabled")
    return None


def find_ffmpeg():
    for name in ("ffmpeg.exe", "ffmpeg"):
        found = shutil.which(name)
        if found:
            print(f"  OK  FFmpeg: {found}")
            return Path(found)
    print("  WARN  ffmpeg not in PATH — bundle it manually or users must install it")
    return None


# ──────────────────────────────────────────────────────────────
#  BUILD
# ──────────────────────────────────────────────────────────────

def build(onefile=False):
    print("\n━━━━  PRE-BUILD CHECKS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    check_pyinstaller()
    cascade = find_cascade()
    ffmpeg  = find_ffmpeg()

    here = Path(__file__).parent.resolve()
    os.chdir(here)

    # ── Data files (always bundled) ──────────────────────────
    add_data = [
        "--add-data", f"vhs_engine.py{os.pathsep}.",
        "--add-data", f"icon.png{os.pathsep}.",
        "--add-data", f"icon.ico{os.pathsep}.",
    ]
    if cascade:
        add_data += ["--add-data", f"{cascade}{os.pathsep}."]

    # ── Binaries (ffmpeg + ffprobe) ──────────────────────────
    add_binary = []
    if ffmpeg:
        add_binary += ["--add-binary", f"{ffmpeg}{os.pathsep}."]
        ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        ffprobe = ffmpeg.parent / ffprobe_name
        if ffprobe.exists():
            add_binary += ["--add-binary", f"{ffprobe}{os.pathsep}."]
            print(f"  OK  ffprobe: {ffprobe}")

    # ── PyInstaller args ─────────────────────────────────────
    mode = "--onefile" if onefile else "--onedir"
    mode_label = "single exe (--onefile)" if onefile else "folder (--onedir)"

    args = [
        sys.executable, "-m", "PyInstaller",
        "--name",     APP_NAME,
        mode,
        "--windowed",       # no console window
        "--clean",
        "--noconfirm",
        "--noupx",          # never use UPX — massive AV red flag

        # Version metadata — makes exe look legitimate to SmartScreen
        "--version-file", "version_info.txt",

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

        *add_data,
        *add_binary,
    ]

    if Path(ICON_ICO).exists():
        args += ["--icon", ICON_ICO]

    args.append(ENTRY_POINT)

    print(f"\n━━━━  BUILDING  ({mode_label})  ━━━━━━━━━━━━━━━━━━━━━━━")
    result = subprocess.run(args)

    if result.returncode != 0:
        print("\n  BUILD FAILED — check errors above")
        sys.exit(1)

    if onefile:
        exe = here / "dist" / f"{APP_NAME}.exe"
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"\n  Output: {exe}  ({size_mb:.0f} MB)")
        return exe
    else:
        dist_dir = here / "dist" / APP_NAME
        size_mb  = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file()) / 1024 / 1024
        print(f"\n  Output: {dist_dir}  ({size_mb:.0f} MB total)")
        return dist_dir


# ──────────────────────────────────────────────────────────────
#  ZIP
# ──────────────────────────────────────────────────────────────

def zip_output(output: Path, onefile: bool):
    """Zip the build output into a single distributable archive."""
    zip_name = f"{APP_NAME}_v{VERSION}.zip"
    zip_path = output.parent / zip_name

    print(f"\n━━━━  ZIPPING  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Writing {zip_name}...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if onefile:
            # Single exe — just zip the one file
            zf.write(output, output.name)
        else:
            # Folder — zip everything inside, preserving structure
            for f in sorted(output.rglob("*")):
                if f.is_file():
                    arcname = f"{APP_NAME}/{f.relative_to(output)}"
                    zf.write(f, arcname)

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  Done: {zip_path.name}  ({size_mb:.0f} MB)")
    return zip_path


# ──────────────────────────────────────────────────────────────
#  SELF-SIGN  (Windows only, optional)
# ──────────────────────────────────────────────────────────────

def self_sign(exe_path: Path):
    """
    Creates a self-signed certificate and signs the exe.
    Requires Windows SDK (signtool.exe) + PowerShell.
    Users will still see SmartScreen once, then it clears with reputation.
    """
    print("\n━━━━  SIGNING  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    signtool = _find_signtool()
    if not signtool:
        print("  WARN  signtool.exe not found")
        print("  Install Windows SDK: https://developer.microsoft.com/windows/downloads/windows-sdk/")
        return

    pfx = Path("_rrvhs_temp.pfx")
    pwd = "rrvhs_sign"

    # Create self-signed cert via PowerShell
    ps = (
        f'$c = New-SelfSignedCertificate -Subject "CN=RetroRewindVHS" '
        f'-Type CodeSigning -CertStoreLocation Cert:\\CurrentUser\\My; '
        f'$p = ConvertTo-SecureString -String "{pwd}" -Force -AsPlainText; '
        f'Export-PfxCertificate -Cert $c -FilePath "{pfx.resolve()}" -Password $p'
    )
    r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0 or not pfx.exists():
        print(f"  WARN  Could not create cert: {r.stderr[:200]}")
        return

    # Sign
    r2 = subprocess.run([
        signtool, "sign",
        "/f", str(pfx), "/p", pwd,
        "/fd", "SHA256",
        "/t",  "http://timestamp.digicert.com",
        "/v",  str(exe_path),
    ], capture_output=True, text=True)

    pfx.unlink(missing_ok=True)

    if r2.returncode == 0:
        print("  Signed OK")
        print("  SmartScreen may still warn once — click More info → Run anyway")
        print("  Warning clears automatically as more users run it")
    else:
        print(f"  Signing failed: {r2.stderr[:300]}")


def _find_signtool():
    candidates = [
        r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe",
        r"C:\Program Files\Windows Kits\10\bin\x64\signtool.exe",
    ]
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


# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--onefile", action="store_true",
        help="Build as single .exe instead of folder (higher AV risk)"
    )
    parser.add_argument(
        "--sign", action="store_true",
        help="Self-sign the exe after building (Windows only, needs Windows SDK)"
    )
    cli = parser.parse_args()

    if cli.onefile:
        print("\n  NOTE: --onefile builds are flagged more by AV tools.")
        print("  --onedir (default) is recommended for distribution.\n")

    output_path = build(onefile=cli.onefile)
    zip_path = zip_output(output_path, onefile=cli.onefile)

    # Sign the exe if requested
    if cli.sign:
        if sys.platform != "win32":
            print("\n  WARN  --sign only works on Windows")
        else:
            # If onedir, the exe is inside the folder. If onefile, the output is the exe.
            exe_to_sign = output_path if cli.onefile else output_path / f"{APP_NAME}.exe"
            self_sign(exe_to_sign)

    # Final summary using .format() to avoid f-string syntax errors
    mode_str = "single exe" if cli.onefile else "folder (recommended)"
    user_instr = "download -> run" if cli.onefile else "unzip -> run"
    
    footer = "" if cli.onefile else "\n  To further reduce AV flags:\n  - Keep the 'internal' folder with the EXE.\n  - Distribute as a ZIP, not a raw EXE."

    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BUILD COMPLETE  —  v{version}
  Mode:    {mode}
  Output:  {zip_name}

  Upload {zip_name} to GitHub/Nexus.
  Users: {instr} {app_name}.exe
  FFmpeg is bundled — no extra installs needed.{extra_info}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""".format(
        version=VERSION,
        mode=mode_str,
        zip_name=zip_path.name,
        instr=user_instr,
        app_name=APP_NAME,
        extra_info=footer
    ))
