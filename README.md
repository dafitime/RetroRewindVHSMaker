# 📼 Retro Rewind VHS Converter

Convert any MP4 into a face-tracked 512×512 video with authentic VHS effects.
Built for the **Retro Rewind Video Store Simulator**.

---

## Features

- **Hybrid subject tracker** – tries face detection first, then motion, then center
- **Variable VHS intensity** – dial from clean to completely wrecked
- **Effects stack**: noise, chroma bleed, hue drift, barrel warp, scanlines, vignette, glitches, tracking tears
- **GUI app** with progress bar and live status
- **Output**: 512×512 MP4 with original audio preserved

---

## Quick Start (Run from Source)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg
- **Windows**: Download from https://ffmpeg.org/download.html → add to PATH
- **Mac**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 3. Run the app
```bash
python app.py
```

---

## Package as a Standalone App (Share with Anyone)

### Install PyInstaller
```bash
pip install pyinstaller
```

### Build the executable
```bash
python build_exe.py
```

This creates `dist/RetroRewindVHS/` — a self-contained folder.

### Distribute it
1. The script also auto-copies `ffmpeg` into the dist folder (if found in PATH)
2. Zip up `dist/RetroRewindVHS/`
3. Share the zip — recipients just unzip and double-click `RetroRewindVHS.exe`

---

## File Structure

```
retro_rewind/
├── app.py            ← GUI application (run this)
├── vhs_engine.py     ← Processing core (tracker + VHS effects)
├── requirements.txt  ← Python dependencies
├── build_exe.py      ← PyInstaller packaging script
└── README.md
```

---

## Tuning Parameters

Edit the top of `vhs_engine.py` to adjust behavior:

| Setting | Default | What it does |
|---|---|---|
| `smooth_frames` | 40 | Crop pan smoothness. Higher = slower, more cinematic |
| `fallback_bias` | 0.5 | Where to crop when no subject found (0=left, 0.5=center, 1=right) |
| `OUTPUT_SIZE` | 512 | Output resolution (change in `app.py` too if you adjust) |

VHS intensity is controlled by the slider in the GUI (0.0–1.0).

---

## Requirements

- Python 3.10+
- opencv-python
- numpy
- FFmpeg (system install)
- tkinter (included with standard Python)
