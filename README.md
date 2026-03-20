# 📼 Retro Rewind VHS Converter

> A standalone video conversion tool built for **Retro Rewind Video Store Simulator**.  
> Turn any MP4 into an authentic VHS-style clip — cropped, degraded, and ready to drop into the game.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## What It Does

Takes a widescreen MP4 and outputs a properly cropped, VHS-degraded video — with full control over every effect. The smart crop system analyses the video and locks onto the main subject so there's zero camera jitter in the output.

---

## Features

### Smart Crop — Zero Jitter
The converter analyses the whole video before rendering, finds the best crop position using face detection → motion tracking → center fallback, then **locks that position for the entire video**. No per-frame tracking means no wobble.

| Mode | Best For |
|---|---|
| **Center** | Fastest — always crops the middle |
| **Single locked subject** | Analyses the video, locks onto the main subject *(recommended)* |
| **Per-scene adaptive** | Detects scene cuts, re-locks per scene |

### VHS Effects — All Individually Controlled

Every effect has its own on/off toggle and intensity slider. Hover any effect to see a live animated demo of exactly what it does.

| Effect | What It Does |
|---|---|
| Scanlines | Dark horizontal CRT bands |
| Vignette | Edge darkening like an old tube TV |
| Chroma Bleed | RGB channels shift apart — classic VHS smear |
| Brightness Flicker | Random brightness pulses |
| Hue / Colour Drift | Colour temperature wanders like a warm tape |
| Noise / Grain | Luminance grain — tape hiss of video |
| Glitch / Tracking Errors | Horizontal band shifts |
| Tape Tear Lines | Bright horizontal tears across the frame |
| REC Overlay | Burns a ● REC timecode into the corner |

### Output Options
- Resolution: **256 / 320 / 384 / 512 / 640 / 768 / 1024 px**
- Aspect ratio: **1:1 (square)**, 16:9, 4:3, or Original
- Original audio is always preserved

### Live Preview Panel
- **Top panel** — hover any effect or slider to see an animated demo of that specific effect
- **Bottom panel** — SMPTE color bar test card showing all active effects combined in real time as you adjust

### Built-in Video Player
When conversion finishes, click **Preview Result** to watch it right inside the tool — play, pause, scrub, loop. No hunting through folders.

### Performance
- Frames piped directly to FFmpeg — no temp files, no double encode
- Thread pool processes VHS effects in parallel while the next frame decodes
- Optional **GPU acceleration** via OpenCV OpenCL — works on AMD, Intel, and NVIDIA without special drivers

---

## Requirements

- **Python 3.10+**
- **FFmpeg** — must be installed and in your PATH
- `opencv-python`
- `numpy`
- `Pillow`
- `tkinter` *(bundled with standard Python)*

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/YOURNAME/retro-rewind-vhs-converter.git
cd retro-rewind-vhs-converter
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

| Platform | Command |
|---|---|
| Windows | Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH |
| macOS | `brew install ffmpeg` |
| Linux | `sudo apt install ffmpeg` |

### 4. Run

```bash
python app.py
```

---

## Building a Standalone Executable

To share with someone who doesn't have Python installed:

```bash
pip install pyinstaller
python build_exe.py
```

This produces a single `RetroRewindVHS.exe` (Windows) or binary (macOS/Linux).  
FFmpeg is automatically bundled if it's found in your PATH.

To also self-sign the exe on Windows (reduces SmartScreen warnings):

```bash
python build_exe.py --sign
```

> **Note:** Self-signing creates a local certificate — users will see a one-time SmartScreen prompt but can click *More info → Run anyway*. The warning clears automatically as more users run it.

---

## How to Use

1. Click **Browse** and select your source `.mp4`
2. Set an output location with **Save As**
3. Choose a **Crop Mode** — *Single locked subject* is recommended for most videos
4. Choose an **Aspect Ratio** — Square 1:1 is the default for the game
5. Choose an **Output Size** — 512px is standard
6. Toggle VHS effects on/off and dial in each intensity slider
7. Hover any effect name to see a live preview of what it does
8. Click **▶ CONVERT TO VHS**
9. When done, click **📼 PREVIEW RESULT**

---

## Project Structure

```
retro-rewind-vhs-converter/
├── app.py              — GUI application (entry point)
├── vhs_engine.py       — Processing core: crop analysis, VHS effects, GPU path
├── build_exe.py        — PyInstaller packaging + optional self-signing
├── requirements.txt    — Python dependencies
├── icon.ico            — App icon (Windows)
├── icon.png            — App icon (cross-platform)
└── README.md
```

---

## GPU Acceleration

The GPU toggle uses **OpenCV OpenCL (UMat)** — built into the standard `opencv-python` pip package. No special CUDA build or drivers needed.

Compatible with:
- NVIDIA (via OpenCL — no CUDA required)
- AMD Radeon
- Intel integrated graphics + Intel Arc

If no compatible GPU is detected, the checkbox is automatically disabled and the app falls back to CPU.

---

## Tips

- **Double-click any slider** to reset it to its default value
- The **yellow line** on each slider marks where the default sits
- Sliders are **disabled** (grayed out) when their effect is toggled off
- **Chroma Bleed + Scanlines** alone goes a long way without being distracting
- For very long videos, use **Per-scene adaptive** crop mode
- The **REC overlay** burns a live timecode into every frame of the output

---

## License

MIT — do whatever you want with it, credit appreciated.

---

*Built with Python, OpenCV, and FFmpeg.*
