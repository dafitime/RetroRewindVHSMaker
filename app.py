"""
app.py  -  Retro Rewind VHS Converter  |  GUI Application
Run:  python app.py

Features:
  - Fully responsive layout (resizes like a webpage)
  - Mousewheel scrolling on all platforms
  - Live effect preview panel — shows what each setting does visually on hover
  - Per-effect toggles + intensity sliders
  - Two-pass locked crop (no jitter)
  - Video preview player
"""

import os, sys, threading, subprocess, tempfile, shutil, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from vhs_engine import CropAnalyser, CropPlan, VHSMaps, apply_vhs, detect_gpu


# ──────────────────────────────────────────────────────────────
#  THEME
# ──────────────────────────────────────────────────────────────
BG       = "#0a0a0f"   # deep dark navy
BG2      = "#111118"   # panel bg
BG3      = "#16161f"   # input / section bg
BG4      = "#1e1e2e"   # border fill
BORDER   = "#2a2a3e"   # border lines
ACCENT   = "#cc0033"   # red action
ACCENT2  = "#e8c840"   # gold highlight (from CSS --acc)
TEXT     = "#f0f0ff"   # bright white-blue text
TEXT_DIM = "#7070a0"   # muted (from CSS --mut2 lightened)
LED      = "#40e880"   # green LED (from CSS --grn)
FT       = "Courier New"

def _font(size=10, bold=False):
    return (FT, size, "bold") if bold else (FT, size)


def _find_ffmpeg():
    """
    Locate the ffmpeg binary.
    Priority:
      1. Bundled inside PyInstaller _MEIPASS  (always works when distributed)
      2. System PATH  (works when running from source)
    Returns the full path string, or None if not found.
    """
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    # 1. PyInstaller bundle
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, exe)
        if os.path.isfile(bundled):
            return bundled

    # 2. Beside the running script/exe (user dropped ffmpeg next to the app)
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    beside = os.path.join(here, exe)
    if os.path.isfile(beside):
        return beside

    # 3. System PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    return None


def _set_icon(window):
    """
    Set the window icon robustly — works in dev, PyInstaller onedir,
    and PyInstaller onefile (_MEIPASS). Uses iconphoto() which works
    everywhere unlike iconbitmap() which breaks in bundles.
    """
    # Search all possible locations for icon.png or icon.ico
    search_dirs = [
        os.path.dirname(os.path.abspath(__file__)),   # dev: beside app.py
    ]
    if hasattr(sys, "_MEIPASS"):
        search_dirs.insert(0, sys._MEIPASS)            # PyInstaller bundle

    # Try PNG first (iconphoto), then ICO fallback
    for d in search_dirs:
        png = os.path.join(d, "icon.png")
        ico = os.path.join(d, "icon.ico")
        if os.path.isfile(png):
            try:
                img = tk.PhotoImage(file=png)
                window.iconphoto(True, img)
                window._icon_ref = img   # prevent GC
                return
            except Exception:
                pass
        if os.path.isfile(ico):
            try:
                # iconbitmap works on Windows when path is absolute
                window.iconbitmap(ico)
                return
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────
#  LIVE EFFECT PREVIEW  (SVG-style drawn on a tk.Canvas)
# ──────────────────────────────────────────────────────────────

class EffectPreviewCanvas(tk.Canvas):
    """
    A canvas that draws a live animated preview of a VHS effect.
    Call .show(effect_key) to switch to a different effect demo.
    Call .show(None) to show the idle / logo state.
    """

    W = 380
    H = 300

    # demo frame — a simple gradient face-like image
    _BASE = None

    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=BG3, highlightthickness=1,
                         highlightbackground=BORDER, **kw)
        self._effect     = None
        self._after_id   = None
        self._idle_after = None   # timer to return to idle after hover leaves
        self._frame      = 0
        self._photo      = None
        self._strength   = None   # None = animate, float = locked to slider
        self._build_base()
        self._draw_idle()

    # ── base image (synthetic gradient "scene") ──────────────

    def _build_base(self):
        if EffectPreviewCanvas._BASE is not None:
            return
        W, H = self.W, self.H
        img = np.zeros((H, W, 3), np.uint8)

        # SMPTE color bars (BGR)
        top_h = int(H * 0.67)
        mid_h = int(H * 0.08)

        # Top bars: grey, yellow, cyan, green, magenta, red, blue
        top_bars = [
            (192, 192, 192),
            (  0, 206, 206),
            (200, 200,   0),
            (  0, 192,   0),
            (192,   0, 192),
            (  0,   0, 192),
            (192,   0,   0),
        ]
        n = len(top_bars)
        bar_w = W / n
        for i, col in enumerate(top_bars):
            x0 = int(i * bar_w)
            x1 = int((i + 1) * bar_w)
            img[:top_h, x0:x1] = col

        # Middle thin strip
        mid_bars = [
            (  0,   0, 192),
            ( 20,  20,  20),
            (192,   0, 192),
            ( 20,  20,  20),
            (200, 200,   0),
            ( 20,  20,  20),
            (192, 192, 192),
        ]
        y0m, y1m = top_h, top_h + mid_h
        for i, col in enumerate(mid_bars):
            x0 = int(i * bar_w)
            x1 = int((i + 1) * bar_w)
            img[y0m:y1m, x0:x1] = col

        # Bottom PLUGE section
        y0b = top_h + mid_h
        sp = [int(W * p) for p in (0.14, 0.40, 0.60, 0.75, 0.88)]
        img[y0b:, :sp[0]]       = ( 29,   0,   7)
        img[y0b:, sp[0]:sp[1]]  = (255, 255, 255)
        img[y0b:, sp[1]:sp[2]]  = ( 80,   0,  60)
        img[y0b:, sp[2]:sp[3]]  = ( 10,  10,  10)
        img[y0b:, sp[3]:sp[4]]  = ( 22,  22,  22)
        img[y0b:, sp[4]:]       = ( 10,  10,  10)

        EffectPreviewCanvas._BASE = img

    # ── rendering helpers ────────────────────────────────────

    def _to_photo(self, arr):
        """Convert numpy BGR array to a tk.PhotoImage via PPM."""
        rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        ppm  = b"P6\n" + f"{w} {h}\n255\n".encode() + rgb.tobytes()
        return tk.PhotoImage(data=ppm)

    def _apply_effect(self, base, strength):
        """
        Apply the current effect at the given strength (0.0 = invisible, 1.0 = max).
        When driven by hover animation, strength ping-pongs 0→1→0.
        When driven by a slider, strength is the slider value directly.
        """
        out = base.astype(np.float32)
        key = self._effect
        s   = max(0.0, min(1.0, strength))

        if key == "scanlines":
            mask = np.ones_like(out)
            # s=0 → no scanlines (mask stays 1.0), s=1 → dark (0.3)
            dark = 1.0 - s * 0.70
            mask[::2] *= dark
            out *= mask

        elif key == "vignette":
            h, w = out.shape[:2]
            cx2, cy2 = w/2, h/2
            Y, X = np.ogrid[:h, :w]
            dist = np.sqrt(((X-cx2)/cx2)**2 + ((Y-cy2)/cy2)**2)
            vig = 1.0 - s * 0.92 * np.clip(dist, 0, 1)**1.6
            out *= vig[:, :, np.newaxis]

        elif key == "chroma_bleed":
            shift = max(1, int(s * 18))
            if shift < out.shape[1]:
                out[:, shift:,  0] = out[:, :-shift, 0]
                out[:, :-shift, 2] = out[:, shift:,  2]

        elif key == "flicker":
            # s=0 → no change, s=1 → dramatic flicker
            import random
            out *= 1.0 - s * 0.55 * abs(np.sin(np.random.uniform(0, np.pi)))

        elif key == "hue_drift":
            u8  = np.clip(out, 0, 255).astype(np.uint8)
            hsv = cv2.cvtColor(u8, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 0] = (hsv[:, :, 0] + s * 45) % 180
            hsv[:, :, 1] *= 1.0 - s * 0.65
            out = cv2.cvtColor(np.clip(hsv,0,255).astype(np.uint8),
                               cv2.COLOR_HSV2BGR).astype(np.float32)

        elif key == "noise":
            sigma = s * 55
            if sigma > 0.5:
                noise = np.random.normal(0, sigma, out.shape).astype(np.float32)
                out  += noise

        elif key == "glitch":
            if s > 0.05:
                h2 = out.shape[0]
                for _ in range(max(1, int(s * 7))):
                    y0     = np.random.randint(0, h2 - 3)
                    nl     = np.random.randint(1, max(2, int(s * 12)))
                    gshift = np.random.randint(int(-50*s), int(50*s)+1)
                    out[y0:y0+nl] = np.roll(out[y0:y0+nl], gshift, axis=1)

        elif key == "tape_tear":
            if s > 0.05:
                h2 = out.shape[0]
                jy = int(h2 * 0.45)
                brightness = 1.0 + s * 2.0
                out[jy:jy+max(1,int(s*4))] = np.clip(
                    out[jy:jy+max(1,int(s*4))] * brightness, 0, 255)

        elif key in ("crop_center", "crop_single", "crop_scene"):
            h2, w2 = out.shape[:2]
            bar   = int(h2 * 0.12)
            out[:bar]    *= 0.2
            out[h2-bar:] *= 0.2
            out_u8 = np.clip(out, 0, 255).astype(np.uint8)
            # Use strength to pulse the box brightness (0=dim, 1=bright)
            bri  = int(120 + 135 * s)
            if key == "crop_center":
                bw2 = h2 - 2*bar
                bx  = w2//2 - bw2//2
                cv2.rectangle(out_u8, (bx, bar), (bx+bw2, h2-bar), (0, bri, 255), 2)
                cv2.putText(out_u8, "CENTER", (bx+4, bar+16),
                            cv2.FONT_HERSHEY_PLAIN, 0.9, (0, bri, 255), 1)
            elif key == "crop_single":
                bw2 = h2 - 2*bar
                bx  = int(w2*0.45) - bw2//2
                cv2.rectangle(out_u8, (bx, bar), (bx+bw2, h2-bar), (bri, 220, 0), 2)
                cv2.putText(out_u8, "LOCKED", (bx+4, bar+16),
                            cv2.FONT_HERSHEY_PLAIN, 0.9, (bri, 220, 0), 1)
            else:
                bw2  = (h2 - 2*bar) // 2
                bx1  = int(w2 * 0.12)
                bx2  = int(w2 * 0.55)
                col1 = (0, int(bri*0.8), 255)
                col2 = (255, int(bri*0.8), 0)
                cv2.rectangle(out_u8, (bx1, bar), (bx1+bw2, h2-bar), col1, 2)
                cv2.rectangle(out_u8, (bx2, bar), (bx2+bw2, h2-bar), col2, 2)
                cv2.putText(out_u8, "S1", (bx1+2, bar+14),
                            cv2.FONT_HERSHEY_PLAIN, 0.8, col1, 1)
                cv2.putText(out_u8, "S2", (bx2+2, bar+14),
                            cv2.FONT_HERSHEY_PLAIN, 0.8, col2, 1)
            return np.clip(out_u8.astype(np.float32), 0, 255)

        elif key in ("ar_1:1", "ar_16:9", "ar_4:3", "ar_original"):
            h2, w2 = out.shape[:2]
            out_u8 = np.clip(out * 0.35, 0, 255).astype(np.uint8)
            ratios = {"ar_1:1":(1,1),"ar_16:9":(16,9),"ar_4:3":(4,3),"ar_original":(16,9)}
            rw, rh = ratios[key]
            if rw >= rh:
                bw2 = int(w2 * 0.78); bh2 = int(bw2 * rh / rw)
            else:
                bh2 = int(h2 * 0.78); bw2 = int(bh2 * rw / rh)
            bx = (w2 - bw2) // 2
            by = (h2 - bh2) // 2
            region = cv2.resize(EffectPreviewCanvas._BASE, (bw2, bh2))
            out_u8[by:by+bh2, bx:bx+bw2] = region
            bri2 = int(120 + 135 * s)
            cv2.rectangle(out_u8, (bx, by), (bx+bw2, by+bh2), (0, bri2, bri2), 2)
            cv2.putText(out_u8, key.replace("ar_",""), (bx+4, by+bh2-6),
                        cv2.FONT_HERSHEY_PLAIN, 1.0, (0, bri2, bri2), 1)
            return np.clip(out_u8.astype(np.float32), 0, 255)

        return out

    def _draw_idle(self):
        """Show branded idle state."""
        self.delete("all")
        cx, cy = self.W // 2, self.H // 2
        # Dark background
        self.create_rectangle(0, 0, self.W, self.H, fill=BG3, outline="")
        # VHS cassette outline
        self.create_rectangle(40, 60, self.W-40, self.H-50,
                              outline=BORDER, width=1, fill=BG4)
        # Reels
        self.create_oval(75, 90, 115, 130, outline=TEXT_DIM, width=1)
        self.create_oval(145, 90, 185, 130, outline=TEXT_DIM, width=1)
        self.create_oval(88, 103, 102, 117, fill=BORDER, outline="")
        self.create_oval(158, 103, 172, 117, fill=BORDER, outline="")
        # Label
        self.create_text(cx, 155, text="HOVER AN EFFECT",
                         font=_font(8, bold=True), fill=TEXT_DIM)
        self.create_text(cx, 170, text="TO PREVIEW",
                         font=_font(8), fill=TEXT_DIM)
        self._effect = None

    def show(self, effect_key):
        """Switch to animating effect_key, or idle after a short hold if None."""
        if effect_key is None:
            # Cancel any pending idle timer first
            if self._idle_after:
                self.after_cancel(self._idle_after)
            # Hold current preview for 2 s then fade to idle
            self._idle_after = self.after(2000, self._go_idle)
            return
        # Cancel pending idle if user moved to another effect
        if self._idle_after:
            self.after_cancel(self._idle_after)
            self._idle_after = None
        if effect_key == self._effect and self._strength is None:
            return   # already animating this
        self._effect   = effect_key
        self._frame    = 0
        self._strength = None
        self._stop_anim()
        self._tick()

    def _go_idle(self):
        self._idle_after = None
        # Only go idle if no slider is driving us
        if self._strength is None:
            self._stop_anim()
            self._draw_idle()

    def show_strength(self, effect_key, strength):
        """
        Show effect_key at a fixed strength (0.0–1.0) driven by a slider.
        Freezes the animation at that strength level — no looping t.
        strength=0 → no effect visible.  strength=1 → full effect.
        """
        if self._effect != effect_key:
            self._effect = effect_key
            self._frame  = 0
            self._stop_anim()
        self._strength = strength
        # Render one frame immediately at this strength
        self._render_at(strength)

    def _render_at(self, strength):
        """Render one still frame at the given strength (0–1)."""
        if self._BASE is None or self._effect is None:
            return
        out    = self._apply_effect(self._BASE.copy(), strength)
        out_u8 = np.clip(out, 0, 255).astype(np.uint8)
        pct    = int(strength * 100)
        cv2.putText(out_u8, f"{self._effect.upper().replace('_',' ')}  {pct}%",
                    (6, 16), cv2.FONT_HERSHEY_PLAIN, 0.85, (204, 0, 51), 1)
        self._photo = self._to_photo(out_u8)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._photo)

    def _stop_anim(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._idle_after:
            self.after_cancel(self._idle_after)
            self._idle_after = None

    def _tick(self):
        if self._effect is None:
            return
        # If strength is locked by slider, stop animating — just hold
        if self._strength is not None:
            return
        t      = (self._frame % 60) / 60.0   # 0→1 cycle
        # Map t so it goes 0→1→0 (ping-pong) for smoother demo loop
        t_ping = abs(np.sin(t * np.pi))
        out    = self._apply_effect(self._BASE.copy(), t_ping)
        out_u8 = np.clip(out, 0, 255).astype(np.uint8)
        cv2.putText(out_u8, self._effect.upper().replace("_", " "),
                    (6, 16), cv2.FONT_HERSHEY_PLAIN, 0.85, (204, 0, 51), 1)
        self._photo = self._to_photo(out_u8)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._photo)
        self._frame   += 1
        self._after_id = self.after(33, self._tick)   # ~30 fps




# ──────────────────────────────────────────────────────────────
#  COMBINED PREVIEW  — applies ALL active effects, loops forever
# ──────────────────────────────────────────────────────────────

class CombinedPreviewCanvas(tk.Canvas):
    """
    Continuously loops, applying every enabled VHS effect at current
    slider values to the SMPTE base image.  Updates whenever
    refresh_settings(settings) is called (on every slider/toggle change).
    Runs at ~20 fps so it's smooth but not CPU-heavy.
    """

    W = 380
    H = 220

    PREVIEW_FRAMES = 30   # frames extracted from video for preview loop

    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg="#000000", highlightthickness=1,
                         highlightbackground=BORDER, **kw)
        self._settings    = {}
        self._after_id    = None
        self._photo       = None
        self._frame       = 0
        self._maps        = None
        self._video_frames = []    # list of BGR numpy arrays from loaded video
        self._base        = self._build_colorbars()
        self._start()

    def load_video(self, path: str):
        """Extract evenly-spaced preview frames from the video file."""
        try:
            cap   = cv2.VideoCapture(path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total < 1:
                cap.release()
                return
            step   = max(1, total // self.PREVIEW_FRAMES)
            frames = []
            for i in range(0, total, step):
                if len(frames) >= self.PREVIEW_FRAMES:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if not ret:
                    continue
                # Resize to canvas size
                resized = cv2.resize(frame, (self.W, self.H),
                                     interpolation=cv2.INTER_LINEAR)
                frames.append(resized)
            cap.release()
            if frames:
                self._video_frames = frames
                self._frame = 0
        except Exception:
            pass

    def _build_colorbars(self):
        """SMPTE color bar test card — ideal for seeing all VHS effects."""
        W, H = self.W, self.H
        img  = np.zeros((H, W, 3), np.uint8)
        bars = [
            (191,191,191),(191,191,0),(0,191,191),(0,191,0),
            (191,0,191),(191,0,0),(0,0,191),
        ]
        bar_w = W // len(bars)
        top_h = int(H * 0.67)
        for i, c in enumerate(bars):
            img[:top_h, i*bar_w:(i+1)*bar_w] = c
        bot = [(0,0,191),(19,19,19),(191,0,191),(19,19,19),
               (0,191,191),(19,19,19),(117,117,117)]
        for i, c in enumerate(bot):
            img[top_h:, i*bar_w:(i+1)*bar_w] = c
        cv2.putText(img, "COLOR BARS - HOVER EFFECTS ABOVE TO SEE INDIVIDUAL / ALL EFFECTS HERE",
                    (4, H-6), cv2.FONT_HERSHEY_PLAIN, 0.65, (180,180,180), 1)
        return img

    def refresh_settings(self, settings: dict):
        self._settings = dict(settings)

    def _get_maps(self):
        if self._maps is None:
            from vhs_engine import VHSMaps
            # Must pass w,h explicitly — VHSMaps defaults to square which
            # won't match our 380x220 canvas and causes silent shape errors
            self._maps = VHSMaps(w=self.W, h=self.H)
        return self._maps

    def _start(self):
        self._tick()

    def _tick(self):
        try:
            from vhs_engine import apply_vhs
            maps = self._get_maps()

            # Use video frames when loaded, fall back to color bars
            if self._video_frames:
                idx   = self._frame % len(self._video_frames)
                frame = self._video_frames[idx].copy()
                is_video = True
            else:
                frame    = self._base.copy()
                is_video = False

            if self._settings:
                out    = apply_vhs(frame, maps, self._settings)
                out_u8 = np.clip(out, 0, 255).astype(np.uint8)
                if self._settings.get("rec_overlay", False):
                    cv2.circle(out_u8, (12, 12), 6, (0, 0, 204), -1)
                    cv2.putText(out_u8, "REC", (22, 17),
                                cv2.FONT_HERSHEY_PLAIN, 0.9, (0, 0, 204), 1)
                label = "LIVE PREVIEW" if is_video else "COLOR BARS — LOAD VIDEO FOR PREVIEW"
                cv2.putText(out_u8, label,
                            (4, self.H - 5), cv2.FONT_HERSHEY_PLAIN, 0.7,
                            (160, 160, 160), 1)
            else:
                out_u8 = frame.copy()
                cv2.putText(out_u8, "LOAD VIDEO — ADJUST SLIDERS TO SEE LIVE PREVIEW",
                            (4, self.H - 5), cv2.FONT_HERSHEY_PLAIN, 0.65,
                            (80, 80, 80), 1)

            rgb  = cv2.cvtColor(out_u8, cv2.COLOR_BGR2RGB)
            ppm  = b"P6\n" + f"{self.W} {self.H}\n255\n".encode() + rgb.tobytes()
            self._photo = tk.PhotoImage(data=ppm)
            self.delete("all")
            self.create_image(0, 0, anchor="nw", image=self._photo)
        except Exception as e:
            self.delete("all")
            self.create_text(self.W // 2, self.H // 2,
                             text=f"Preview error: {str(e)[:60]}",
                             fill="#cc0033", font=("Courier New", 7),
                             justify="center")

        self._frame   += 1
        self._after_id = self.after(50, self._tick)   # 20 fps

    def stop(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

# ──────────────────────────────────────────────────────────────
#  SCROLLABLE FRAME  (proper responsive scrollable container)
# ──────────────────────────────────────────────────────────────

class ScrollableFrame(tk.Frame):
    """
    A frame that fills its parent and lets its content scroll vertically.
    Mousewheel works on Windows, Mac, and Linux.
    Content is placed inside .inner.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, **kw)

        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self._vbar   = tk.Scrollbar(self, orient="vertical",
                                    command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vbar.set)

        self._vbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self._canvas, bg=BG)
        self._win  = self._canvas.create_window((0, 0), window=self.inner,
                                                anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Mousewheel — bind to canvas AND inner frame
        for w in (self._canvas, self.inner):
            w.bind("<MouseWheel>",     self._on_mousewheel_win)   # Windows
            w.bind("<Button-4>",       self._on_scroll_up)        # Linux
            w.bind("<Button-5>",       self._on_scroll_down)      # Linux

        # Also bind globally so hovering any child widget scrolls too
        self.bind_all("<MouseWheel>", self._on_mousewheel_win)
        self.bind_all("<Button-4>",   self._on_scroll_up)
        self.bind_all("<Button-5>",   self._on_scroll_down)

    def _on_inner_configure(self, _event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Stretch inner frame to canvas width (responsive)
        self._canvas.itemconfig(self._win, width=event.width)

    def _on_mousewheel_win(self, event):
        # Windows: event.delta is ±120 multiples
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_scroll_up(self, _event):
        self._canvas.yview_scroll(-1, "units")

    def _on_scroll_down(self, _event):
        self._canvas.yview_scroll(1, "units")


# ──────────────────────────────────────────────────────────────
#  REUSABLE WIDGETS
# ──────────────────────────────────────────────────────────────

class ToggleRow(tk.Frame):
    """Checkbox + label.  Calls hover_cb(effect_key) / hover_cb(None) on enter/leave."""
    def __init__(self, parent, label, default=True, hover_key=None, hover_cb=None, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self.var = tk.BooleanVar(value=default)
        self._box = tk.Checkbutton(
            self, variable=self.var,
            bg=BG2, activebackground=BG2, selectcolor=BG4,
            fg=ACCENT2, activeforeground=ACCENT2,
            relief="flat", borderwidth=0, cursor="hand2",
        )
        self._box.pack(side="left", padx=(8, 4))
        lbl = tk.Label(self, text=label, font=_font(10), fg=TEXT, bg=BG2)
        lbl.pack(side="left")

        if hover_cb and hover_key:
            for w in (self, self._box, lbl):
                w.bind("<Enter>", lambda e, k=hover_key: hover_cb(k))
                w.bind("<Leave>", lambda e: hover_cb(None))


class SliderRow(tk.Frame):
    """
    Custom canvas slider with:
      - Lighter, more visible trough (#3a3a3a filled, #555 outline)
      - Yellow vertical line at the default position
      - Small grey tick at the midpoint
      - Snaps to default when within 4 % of it
      - Live percentage tooltip while dragging
      - Value label always visible on the right
    """
    TROUGH_H   = 6      # trough height px
    THUMB_W    = 12     # thumb width px
    THUMB_H    = 20     # thumb height px
    SNAP_PCT   = 0.04   # snap zone (fraction of range)
    TIP_OFFSET = 18     # tooltip y-offset above thumb centre

    def __init__(self, parent, label, default=0.5, to=1.0,
                 hover_key=None, hover_cb=None, strength_cb=None, fmt=None, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self.var          = tk.DoubleVar(value=default)
        self._fmt         = fmt
        self._to          = float(to)
        self._default     = float(default)
        self._strength_cb = strength_cb
        self._hover_key   = hover_key
        self._dragging    = False
        self._enabled     = True   # tracks enabled/disabled state
        self._tip_win     = None   # tooltip Toplevel

        # Label
        lbl = tk.Label(self, text=label, font=_font(9), fg=TEXT, bg=BG2,
                       width=18, anchor="w")
        lbl.pack(side="left", padx=(28, 4))
        self._lbl = lbl   # keep ref so set_enabled can dim it

        # Value readout (right side)
        self._val_lbl = tk.Label(self, text="", font=_font(9, bold=True),
                                 fg=ACCENT2, bg=BG2, width=6, anchor="e")
        self._val_lbl.pack(side="right", padx=(4, 8))

        # Canvas track
        self._canvas = tk.Canvas(self, bg=BG2, highlightthickness=0,
                                 height=self.THUMB_H + 6, cursor="hand2")
        self._canvas.pack(side="left", fill="x", expand=True, pady=2)

        self._canvas.bind("<Configure>",       self._redraw)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Double-Button-1>", self._on_double)   # reset on dbl-click

        self._redraw()
        self._update_label()

        if hover_cb and hover_key:
            for w in (self, lbl, self._canvas, self._val_lbl):
                w.bind("<Enter>", lambda e, k=hover_key: hover_cb(k))
                w.bind("<Leave>", lambda e: hover_cb(None))

    # ── geometry helpers ─────────────────────────────────────

    def _track_x(self):
        """Returns (x_left, x_right) of the usable track area."""
        w = self._canvas.winfo_width()
        pad = self.THUMB_W // 2 + 2
        return pad, max(pad + 1, w - pad)

    def _val_to_x(self, val):
        x0, x1 = self._track_x()
        return int(x0 + (val / self._to) * (x1 - x0))

    def _x_to_val(self, x):
        x0, x1 = self._track_x()
        frac = max(0.0, min(1.0, (x - x0) / max(1, x1 - x0)))
        raw  = frac * self._to
        # Snap to default if within SNAP_PCT of range
        snap_zone = self.SNAP_PCT * self._to
        if abs(raw - self._default) <= snap_zone:
            raw = self._default
        return raw

    # ── drawing ──────────────────────────────────────────────

    def _redraw(self, _event=None):
        """Always route through _redraw_state so disabled style is respected."""
        self._redraw_state(self._enabled)

    # ── interaction ──────────────────────────────────────────

    def _set_val(self, v):
        self.var.set(v)
        self._redraw()
        self._update_label()
        if self._strength_cb and self._hover_key:
            norm = v / self._to if self._to > 0 else v
            self._strength_cb(self._hover_key, norm)

    def _on_press(self, event):
        self._dragging = True
        self._set_val(self._x_to_val(event.x))

    def _on_drag(self, event):
        if not self._dragging:
            return
        v = self._x_to_val(event.x)
        self._set_val(v)
        self._show_tip(event)

    def _on_release(self, event):
        self._dragging = False
        self._hide_tip()
        self._redraw()

    def _on_double(self, _event):
        """Double-click resets to default."""
        self._set_val(self._default)

    # ── tooltip ──────────────────────────────────────────────

    def _show_tip(self, event):
        v    = self.var.get()
        text = self._fmt(v) if self._fmt else f"{v / self._to * 100:.0f}%"
        if self._tip_win is None:
            self._tip_win = tk.Toplevel(self)
            self._tip_win.overrideredirect(True)
            self._tip_win.configure(bg="#1a1a1a")
            self._tip_lbl = tk.Label(self._tip_win, text="",
                                     font=_font(9, bold=True),
                                     fg=ACCENT2, bg="#1a1a1a",
                                     padx=6, pady=2)
            self._tip_lbl.pack()
        self._tip_lbl.config(text=text)
        # Position above the thumb
        rx = self._canvas.winfo_rootx() + event.x
        ry = self._canvas.winfo_rooty() - self.TIP_OFFSET
        self._tip_win.geometry(f"+{rx - 16}+{ry - 10}")
        self._tip_win.lift()

    def _hide_tip(self):
        if self._tip_win:
            self._tip_win.destroy()
            self._tip_win = None

    def _update_label(self):
        v = self.var.get()
        if self._fmt:
            self._val_lbl.config(text=self._fmt(v))
        else:
            self._val_lbl.config(text=f"{v / self._to * 100:.0f}%")

    def set_enabled(self, enabled: bool):
        """Gray out (disable) or restore the slider row."""
        self._enabled = enabled
        lbl_col = TEXT_DIM if enabled else "#353535"
        val_col = ACCENT2  if enabled else "#353535"
        if enabled:
            self._canvas.config(cursor="hand2")
            self._val_lbl.config(fg=val_col)
            self._lbl.config(fg=lbl_col)
            for widget in (self,):
                pass
            self._canvas.bind("<ButtonPress-1>",   self._on_press)
            self._canvas.bind("<B1-Motion>",       self._on_drag)
            self._canvas.bind("<ButtonRelease-1>", self._on_release)
            self._canvas.bind("<Double-Button-1>", self._on_double)
        else:
            self._canvas.config(cursor="")
            self._val_lbl.config(fg=val_col)
            self._lbl.config(fg=lbl_col)
            self._canvas.unbind("<ButtonPress-1>")
            self._canvas.unbind("<B1-Motion>")
            self._canvas.unbind("<ButtonRelease-1>")
            self._canvas.unbind("<Double-Button-1>")
        self._redraw_state(enabled)

    def _redraw_state(self, enabled: bool):
        """Redraw track with dimmed colours when disabled."""
        c  = self._canvas
        w  = c.winfo_width()
        h  = c.winfo_height()
        if w < 2:
            c.after(50, lambda: self._redraw_state(enabled))
            return
        c.delete("all")
        x0, x1  = self._track_x()
        cy       = h // 2
        th       = self.TROUGH_H
        thumb_x  = self._val_to_x(self.var.get())

        if enabled:
            trough_fill    = "#3c3c3c"
            trough_outline = "#585858"
            filled_fill    = ACCENT
            thumb_fill     = "#d0d0d0"
            thumb_outline  = "#888888"
            grip_col       = "#666666"
            def_col        = "#e8c000"
            mid_col        = "#666666"
        else:
            trough_fill    = "#252525"
            trough_outline = "#333333"
            filled_fill    = "#3a2020"
            thumb_fill     = "#404040"
            thumb_outline  = "#505050"
            grip_col       = "#383838"
            def_col        = "#665500"
            mid_col        = "#383838"

        c.create_rectangle(x0, cy - th//2, x1, cy + th//2,
                           fill=trough_fill, outline=trough_outline, width=1)
        if thumb_x > x0:
            c.create_rectangle(x0, cy - th//2 + 1, thumb_x, cy + th//2 - 1,
                               fill=filled_fill, outline="")
        mid_x = (x0 + x1) // 2
        c.create_line(mid_x, cy - th//2 - 3, mid_x, cy + th//2 + 3,
                      fill=mid_col, width=1)
        def_x = self._val_to_x(self._default)
        c.create_line(def_x, cy - th//2 - 5, def_x, cy + th//2 + 5,
                      fill=def_col, width=2)
        tx  = thumb_x
        tw  = self.THUMB_W // 2
        th2 = self.THUMB_H // 2
        c.create_rectangle(tx - tw + 1, cy - th2 + 1, tx + tw + 1, cy + th2 + 1,
                           fill="#111111", outline="")
        c.create_rectangle(tx - tw, cy - th2, tx + tw, cy + th2,
                           fill=thumb_fill, outline=thumb_outline, width=1)
        for dx in (-2, 0, 2):
            c.create_line(tx + dx, cy - th2 + 4, tx + dx, cy + th2 - 4,
                          fill=grip_col, width=1)


class RadioGroup(tk.Frame):
    """Group of radio buttons.  Hover callbacks per option."""
    def __init__(self, parent, options, default, hover_cb=None, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self.var = tk.StringVar(value=default)
        for text, value, hover_key in options:
            rb = tk.Radiobutton(
                self, text=text, variable=self.var, value=value,
                bg=BG2, fg=TEXT, selectcolor=BG4,
                activebackground=BG2, activeforeground=LED,
                font=_font(9), cursor="hand2",
            )
            rb.pack(anchor="w", padx=(20, 0))
            if hover_cb and hover_key:
                rb.bind("<Enter>", lambda e, k=hover_key: hover_cb(k))
                rb.bind("<Leave>", lambda e: hover_cb(None))


# ──────────────────────────────────────────────────────────────
#  WORKER
# ──────────────────────────────────────────────────────────────

def run_conversion(input_path, output_path, settings,
                   progress_cb, status_cb, done_cb,
                   stop_event=None):
    """
    Fast pipeline:
      • INTER_LINEAR resize (3–4× faster than LANCZOS4, barely visible difference)
      • Pipe raw BGR frames directly into FFmpeg stdin — no temp file, no double-encode
      • Worker thread pool processes VHS effects while the next frame is being decoded
      • Pre-built scanline/vignette maps cached once outside the loop
    """
    import queue
    import concurrent.futures

    WORKER_THREADS = max(2, min(4, (os.cpu_count() or 2)))

    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            done_cb(False, "Could not open video file.")
            return

        orig_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        orig_aspect = orig_w / orig_h
        fps         = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total       = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        crop_sz     = min(orig_w, orig_h)
        half        = crop_sz // 2

        def clamp(cx, cy):
            cx = int(np.clip(cx, half, orig_w - half))
            cy = int(np.clip(cy, half, orig_h - half))
            return cx - half, cy - half

        out_sz  = settings.get("out_size", 512)
        aspect  = settings.get("aspect", "1:1")
        if aspect == "1:1":
            out_w = out_h = out_sz
        elif aspect == "16:9":
            out_w, out_h = out_sz, int(out_sz / (16/9))
        elif aspect == "4:3":
            out_w, out_h = out_sz, int(out_sz / (4/3))
        else:
            if orig_aspect >= 1.0:
                out_w, out_h = out_sz, int(out_sz / orig_aspect)
            else:
                out_h, out_w = out_sz, int(out_sz * orig_aspect)

        # ── Crop plan ────────────────────────────────────────
        crop_mode = settings.get("crop_mode", "center")

        class FixedCropPlan:
            def __init__(self, cx, cy):
                self.cx, self.cy = cx, cy
            def get(self, _):
                return self.cx, self.cy

        if crop_mode == "center":
            crop_plan = FixedCropPlan(*clamp(orig_w // 2, orig_h // 2))
        elif crop_mode == "single":
            analyser = CropAnalyser()
            result   = analyser.analyse_single(input_path, status_cb=status_cb)
            if result is None:
                done_cb(False, "Could not analyse video.")
                return
            crop_plan = FixedCropPlan(result[0], result[1])
        else:
            analyser  = CropAnalyser()
            crop_plan = analyser.analyse(input_path, status_cb=status_cb)
            if crop_plan is None:
                done_cb(False, "Could not analyse video.")
                return

        cap.release()
        cap  = cv2.VideoCapture(input_path)
        maps = VHSMaps(max(out_w, out_h), w=out_w, h=out_h)

        use_gpu = settings.get("use_gpu", False)

        # ── Pre-build scanline map once (avoid per-frame copy) ──
        if settings.get("scanlines", True):
            base_dark   = 0.72
            target_dark = 1.0 - settings.get("scanlines_str", 0.72) * (1.0 - base_dark)
            _scan_map   = maps.scanlines.copy()
            _scan_map[::2] = target_dark
            maps._cached_scan = _scan_map

        if settings.get("vignette", True):
            maps._cached_vig = (
                1.0 - settings.get("vignette_str", 0.55) * (1.0 - maps.vignette)
            ).astype(np.float32)

        # ── Write to temp file, then mux audio with FFmpeg ──────
        # cv2.VideoWriter always handles BGR correctly.
        # Pipe approaches have color ordering issues on some Windows FFmpeg builds.
        _ffmpeg = _find_ffmpeg()
        if not _ffmpeg:
            done_cb(False,
                    "FFmpeg not found.\n\n"
                    "If you downloaded the app from GitHub, make sure you downloaded\n"
                    "the full release zip (not just the .exe) — FFmpeg is included.\n\n"
                    "Or install FFmpeg from https://ffmpeg.org/download.html")
            cap.release()
            return

        tmp_dir  = tempfile.mkdtemp()
        # Write PNG-encoded frames to a binary stream.
        # PNG is lossless, OpenCV writes correct RGB internally,
        # and FFmpeg reads image2pipe+png with zero color ambiguity.
        # This is the only approach that works identically on all platforms.
        png_path = os.path.join(tmp_dir, "frames.png_stream")
        png_file = open(png_path, "wb")

        # ── Process frames with thread pool ──────────────────
        # Decode → crop/resize on main thread (OpenCV not thread-safe for cap.read)
        # VHS effects on worker threads (numpy is thread-safe)
        # Write to FFmpeg stdin in frame order

        _rec = settings.get("rec_overlay", False)

        # VHS tape quality — scale factors that simulate tape resolution
        _quality_scales = {
            "full":   1.0,
            "hifi":   0.75,
            "vhs":    0.50,
            "worn":   0.33,
            "damage": 0.20,
        }
        _quality = settings.get("vhs_quality", "vhs")
        _scale   = _quality_scales.get(_quality, 0.50)

        def process_frame(frame_data):
            """Downscale → VHS effects → upscale → optional REC overlay."""
            h0, w0 = frame_data.shape[:2]

            # Downscale to simulate tape resolution (nearest for blocky look)
            if _scale < 1.0:
                lo_w = max(4, int(w0 * _scale))
                lo_h = max(4, int(h0 * _scale))
                lo   = cv2.resize(frame_data, (lo_w, lo_h),
                                  interpolation=cv2.INTER_LINEAR)
                # Build maps matching the ACTUAL lo frame dimensions, not a square
                lo_maps = VHSMaps(max(lo_w, lo_h), w=lo_w, h=lo_h)
                vhs_lo  = apply_vhs(lo, lo_maps, settings, use_gpu=use_gpu)
                # Scale back up with nearest-neighbor (preserves blocky pixel look)
                out_frame = cv2.resize(vhs_lo, (w0, h0),
                                       interpolation=cv2.INTER_NEAREST)
            else:
                out_frame = apply_vhs(frame_data, maps, settings, use_gpu=use_gpu)
            if _rec:
                import time as _t
                ts = _t.strftime("%H:%M:%S")
                cv2.circle(out_frame, (10, 10), 5, (0, 0, 200), -1)
                cv2.putText(out_frame, f"REC  {ts}", (20, 14),
                            cv2.FONT_HERSHEY_PLAIN, 0.85, (0, 0, 200), 1)
            return out_frame

        t0 = time.time()
        fi = 0
        errors = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_THREADS) as pool:
            futures = queue.Queue(maxsize=WORKER_THREADS * 2)

            def submit_frame(frame):
                fut = pool.submit(process_frame, frame)
                futures.put(fut)

            def flush_one():
                """Wait for oldest frame result and write to temp file."""
                if futures.empty():
                    return
                fut = futures.get()
                try:
                    result_frame = fut.result()
                    # Use Pillow for PNG encoding — PIL.Image.fromarray takes
                    # explicit RGB array, no BGR/RGB ambiguity on any platform.
                    import io as _io
                    from PIL import Image as _PILImage
                    rgb = cv2.cvtColor(result_frame, cv2.COLOR_BGR2RGB)
                    pil_img = _PILImage.fromarray(rgb)
                    buf = _io.BytesIO()
                    pil_img.save(buf, format='PNG')
                    png_file.write(buf.getvalue())
                except Exception as e:
                    errors.append(str(e))

            while True:
                if stop_event and stop_event.is_set():
                    # Drain remaining futures cleanly
                    while not futures.empty():
                        try: futures.get().cancel()
                        except: pass
                    cap.release()
                    try: png_file.close()
                    except: pass
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    if os.path.exists(output_path):
                        try: os.remove(output_path)
                        except: pass
                    done_cb(False, "__cancelled__")
                    return

                ret, frame = cap.read()
                if not ret:
                    break

                cx, cy  = crop_plan.get(fi)
                cropped = frame[cy:cy + crop_sz, cx:cx + crop_sz]
                # INTER_LINEAR: 3-4× faster than LANCZOS4, difference invisible at VHS quality
                scaled  = cv2.resize(cropped, (out_w, out_h),
                                     interpolation=cv2.INTER_LINEAR)

                # If pool is full, flush oldest before submitting new
                if futures.full():
                    flush_one()

                submit_frame(scaled)
                fi += 1

                if fi % 15 == 0:
                    pct = (fi / total * 100) if total > 0 else 0
                    el  = time.time() - t0
                    fp  = fi / el if el > 0 else 0
                    eta = (total - fi) / fp if fp > 0 else 0
                    progress_cb(pct)
                    status_cb(
                        f"Frame {fi}/{total}  |  "
                        f"{fp:.1f} fps  |  "
                        f"ETA {eta:.0f}s  |  "
                        f"{WORKER_THREADS} threads"
                    )

            # Flush all remaining futures
            while not futures.empty():
                flush_one()

        cap.release()
        png_file.close()
        status_cb("Encoding…")

        _popen_kwargs = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if sys.platform == "win32":
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _si.wShowWindow = subprocess.SW_HIDE
            _popen_kwargs["startupinfo"] = _si
            _popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        # If output already exists, back it up first
        if os.path.exists(output_path):
            backup = output_path.replace(".mp4", "_backup.mp4")
            try:
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(output_path, backup)
                status_cb(f"Backed up existing file → {os.path.basename(backup)}")
            except Exception:
                pass

        # FFmpeg reads PNG stream — image2pipe+png is color-unambiguous on all platforms
        result = subprocess.run([
            _ffmpeg, "-y",
            "-f", "image2pipe",
            "-vcodec", "png",
            "-r", str(fps),
            "-i", png_path,
            "-i", input_path,
            "-map", "0:v:0",
            "-map", "1:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ], **_popen_kwargs)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        if errors:
            done_cb(False, f"Frame processing error: {errors[0]}")
        elif result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-600:]
            done_cb(False, f"FFmpeg error:\n{err}")
        else:
            done_cb(True, output_path)

    except Exception as e:
        import traceback
        done_cb(False, traceback.format_exc()[-800:])


# ──────────────────────────────────────────────────────────────
#  MAIN APPLICATION
# ──────────────────────────────────────────────────────────────

class RetroRewindApp(tk.Tk):

    MIN_W = 600

    def __init__(self):
        super().__init__()
        self.title("Retro Rewind  |  VHS Converter")
        self.configure(bg=BG)
        self.minsize(self.MIN_W, 480)
        self.geometry("1200x860")
        self.resizable(True, True)

        _set_icon(self)

        self._input_path   = tk.StringVar()
        self._output_path  = tk.StringVar()
        self._game_folder  = tk.StringVar()
        self._rr_category  = tk.StringVar(value="Action")
        self._auto_name    = tk.BooleanVar(value=True)
        self._game_folder.trace_add("write", self._update_output_path)
        self._rr_category.trace_add("write", self._update_output_path)
        self._rr_category.trace_add("write", self._refresh_combined)
        self._auto_name.trace_add("write", self._update_output_path)
        self._input_path.trace_add("write", self._update_output_path)
        self._progress    = tk.DoubleVar(value=0.0)
        self._status_text = tk.StringVar(value="Ready.")
        self._running     = False
        self._last_output = None
        self._fx          = {}
        self._stop_event  = threading.Event()
        self._gpu_avail, self._gpu_name = detect_gpu()
        self._use_gpu     = tk.BooleanVar(value=self._gpu_avail)

        self._build_ui()
        self.bind("<Configure>", self._on_resize)

    # ── TOP LEVEL LAYOUT ────────────────────────────────────

    def _build_ui(self):
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")   # top bar

        # ── header (always visible, above scroll) ──
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(hdr, text="📼 RETRO REWIND", font=_font(18, bold=True),
                 fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(hdr, text="  VHS CONVERTER", font=_font(11),
                 fg=TEXT_DIM, bg=BG).pack(side="left", pady=(4, 0))

        tk.Label(self,
                 text="Locked crop · per-effect controls · responsive layout",
                 font=_font(8), fg=TEXT_DIM, bg=BG).pack(anchor="w", padx=18)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=18, pady=6)

        # ── main body: two-column (left=controls, right=preview) ──
        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True)
        self._body.columnconfigure(0, weight=3, minsize=380)
        self._body.columnconfigure(1, weight=2, minsize=0)
        self._body.rowconfigure(0, weight=1)

        # LEFT: scrollable controls
        self._scroll = ScrollableFrame(self._body)
        self._scroll.grid(row=0, column=0, sticky="nsew")

        # RIGHT: preview panel (hides below certain width)
        self._preview_panel = tk.Frame(self._body, bg=BG2,
                                       highlightthickness=1,
                                       highlightbackground=BORDER)
        self._preview_panel.grid(row=0, column=1, sticky="nsew", padx=(0,0))
        self._build_preview_panel(self._preview_panel)

        # ── bottom bar (always visible) ──
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=18, pady=(4, 2))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("VHS.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        borderwidth=0, thickness=10)
        ttk.Progressbar(bottom, variable=self._progress, maximum=100,
                        style="VHS.Horizontal.TProgressbar").pack(fill="x")
        tk.Label(self, textvariable=self._status_text,
                 font=_font(8), fg=TEXT_DIM, bg=BG).pack(pady=(2, 2))

        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x", side="bottom")
        tk.Label(self,
                 text="RETRO REWIND VIDEO STORE  ·  VHS CONVERTER  ·  v1.2",
                 font=_font(8), fg=TEXT_DIM, bg=BG).pack(side="bottom", pady=2)

        # Build the scrollable content
        self._build_controls(self._scroll.inner)

    def _build_preview_panel(self, parent):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # ── TOP PANE: hovered effect preview ──
        tk.Label(parent, text="EFFECT PREVIEW",
                 font=_font(8, bold=True), fg=ACCENT2, bg=BG2).pack(pady=(8, 2))
        self._preview = EffectPreviewCanvas(parent)
        self._preview.pack(anchor="center", pady=(0, 2))

        # Fixed-height description label — never causes layout shift
        self._preview_lbl = tk.Label(parent, text=" ",
                                     font=_font(8), fg=TEXT_DIM, bg=BG2,
                                     wraplength=340, justify="center",
                                     height=2, anchor="n")
        self._preview_lbl.pack(fill="x", padx=10)
        self._preview_lbl.update_idletasks()

        # ── DIVIDER ──
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(4, 0))

        # ── BOTTOM PANE: live combined all-effects preview ──
        tk.Label(parent, text="LIVE PREVIEW  (all active effects)",
                 font=_font(8, bold=True), fg=ACCENT2, bg=BG2).pack(pady=(6, 2))
        self._combined = CombinedPreviewCanvas(parent)
        self._combined.pack(anchor="center", pady=(0, 8))

    # ── LIVE COLOR BAR PREVIEW ──────────────────────────────


    def _on_resize(self, _event):
        """Hide/show preview panel based on window width."""
        w = self.winfo_width()
        if w < 750:
            self._preview_panel.grid_remove()
            self._body.columnconfigure(1, weight=0, minsize=0)
        else:
            self._preview_panel.grid()
            self._body.columnconfigure(1, weight=2, minsize=240)

    def _on_effect_hover(self, key):
        """Called when mouse enters/leaves an effect control."""
        DESCRIPTIONS = {
            "scanlines"   : "Dark horizontal bands mimic CRT scan lines",
            "vignette"    : "Darkens the edges like an old CRT tube",
            "chroma_bleed": "RGB channels shift apart — classic VHS colour smear",
            "flicker"     : "Random brightness pulses like a dying tube",
            "hue_drift"   : "Colour temperature wanders like a warm tape",
            "noise"       : "Luminance grain — the tape hiss of video",
            "glitch"      : "Horizontal band shifts — tracking errors",
            "tape_tear"   : "A bright line tears across the frame",
            "crop_center" : "Crop from the exact center — always stable",
            "crop_single" : "Analyse the whole video, lock on the main subject",
            "crop_scene"  : "Lock a fresh crop per scene cut, blend between them",
            "ar_1:1"      : "Square output — perfect for the game grid",
            "ar_16:9"     : "Widescreen — letterboxed from the original",
            "ar_4:3"      : "Classic TV ratio — the authentic VHS shape",
            "ar_original" : "Keep original aspect ratio unchanged",
        }
        if key:
            self._preview.show(key)
            self._preview_lbl.config(text=DESCRIPTIONS.get(key, " "))
        else:
            # Defer idle — preview stays visible for 2 s after mouse leaves
            self._preview.show(None)
            self._preview_lbl.config(text=" ")   # space not "" — preserves height

    def _on_strength_change(self, key, strength):
        """Called when a slider moves — show effect at that exact strength."""
        self._preview.show_strength(key, strength)
        self._preview_lbl.config(text=f"{key.replace('_',' ').upper()}  —  {int(strength*100)}%  ")
        self._refresh_combined()

    def _notify_combined(self):
        """Push current settings to the combined preview canvas."""
        try:
            self._combined.refresh_settings(self._build_settings())
        except Exception:
            pass

    # ── CONTROLS (inside scrollable area) ───────────────────

    def _build_controls(self, p):
        """p = self._scroll.inner"""
        hcb = self._on_effect_hover

        def sep():
            tk.Frame(p, bg=BORDER, height=1).pack(fill="x", padx=18, pady=6)

        def section(text):
            fr = tk.Frame(p, bg=BG)
            fr.pack(fill="x", padx=18, pady=(10, 2))
            tk.Frame(fr, bg=ACCENT2, width=3, height=13).pack(side="left", padx=(0, 6))
            tk.Label(fr, text=text, font=_font(8, bold=True),
                     fg=ACCENT2, bg=BG).pack(side="left")

        # ── INPUT / OUTPUT ──
        section("INPUT FILE")
        self._file_row(p, self._input_path, "Browse…", self._browse_input, primary=True)
        section("OUTPUT DESTINATION")
        dest_box = tk.Frame(p, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        dest_box.pack(fill="x", padx=18, pady=(0, 6))

        # Game folder row
        gf_row = tk.Frame(dest_box, bg=BG2)
        gf_row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(gf_row, text="Game folder", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2, width=12, anchor="w").pack(side="left")
        tk.Entry(gf_row, textvariable=self._game_folder, font=_font(9),
                 fg=TEXT, bg=BG3, insertbackground=ACCENT,
                 relief="flat", highlightthickness=1,
                 highlightcolor=ACCENT, highlightbackground=BORDER).pack(
                     side="left", fill="x", expand=True, ipady=4, padx=(4, 4))
        tk.Button(gf_row, text="Auto-detect", command=self._detect_game_folder,
                  font=_font(8), fg=TEXT_DIM, bg=BG3,
                  activebackground=BG2, relief="flat", cursor="hand2", padx=8
                  ).pack(side="right", padx=(0, 4))
        tk.Button(gf_row, text="Browse", command=self._browse_game_folder,
                  font=_font(8), fg=TEXT_DIM, bg=BG3,
                  activebackground=BG2, relief="flat", cursor="hand2", padx=8
                  ).pack(side="right")

        # Genre buttons
        tk.Label(dest_box, text="  GENRE  (saves to VHS\\Genre\\RR_Channel_Genre.mp4)",
                 font=_font(8, bold=True), fg=ACCENT2, bg=BG2).pack(
                     anchor="w", padx=8, pady=(4, 2))

        # Starter genres (unlocked from start) vs locked
        STARTER_GENRES = {"Public", "Scifi", "Police"}
        ALL_GENRES = ["Action","Adult","Drama","Fantasy","Horror",
                      "Kid","Police","Public","Romance","Scifi"]

        self._genre_btns = {}
        genre_frame = tk.Frame(dest_box, bg=BG2)
        genre_frame.pack(fill="x", padx=8, pady=(0, 4))

        # Two rows of genre buttons
        row_a = tk.Frame(genre_frame, bg=BG2)
        row_a.pack(fill="x", pady=1)
        row_b = tk.Frame(genre_frame, bg=BG2)
        row_b.pack(fill="x", pady=1)

        for i, genre in enumerate(ALL_GENRES):
            parent_row = row_a if i < 5 else row_b
            is_starter = genre in STARTER_GENRES
            # Starters get a green tint, others get dark background
            idle_bg = "#0a2a0a" if is_starter else BG3
            idle_fg = LED if is_starter else TEXT
            tip = " ★ Starter" if is_starter else ""
            btn = tk.Button(
                parent_row,
                text=genre + tip,
                command=lambda g=genre: self._select_genre(g),
                font=_font(8),
                fg=idle_fg, bg=idle_bg,
                activebackground=ACCENT2, activeforeground=BG,
                relief="flat", cursor="hand2",
                padx=8, pady=5,
            )
            btn.pack(side="left", padx=2)
            self._genre_btns[genre] = btn

        # Auto-name checkbox
        an_row = tk.Frame(dest_box, bg=BG2)
        an_row.pack(fill="x", padx=8, pady=(2, 2))
        tk.Checkbutton(an_row, text="Auto-name output  (RR_Channel_Genre.mp4 in game folder)",
                       variable=self._auto_name,
                       bg=BG2, activebackground=BG2, selectcolor=BG4,
                       fg=ACCENT2, activeforeground=ACCENT2,
                       relief="flat", font=_font(9), cursor="hand2"
                       ).pack(side="left")

        # Select the first starter genre by default
        self._rr_category.set("Public")
        self.after(100, lambda: self._select_genre("Public"))

        # Output path display
        op_row = tk.Frame(dest_box, bg=BG2)
        op_row.pack(fill="x", padx=8, pady=(2, 6))
        tk.Label(op_row, text="Output file", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2, width=12, anchor="w").pack(side="left")
        tk.Entry(op_row, textvariable=self._output_path, font=_font(9),
                 fg=TEXT, bg=BG3, insertbackground=ACCENT, relief="flat",
                 highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER
                 ).pack(side="left", fill="x", expand=True, ipady=4, padx=(4, 4))
        tk.Button(op_row, text="Save As…", command=self._browse_output,
                  font=_font(8), fg=TEXT_DIM, bg=BG3,
                  activebackground=BG2, relief="flat", cursor="hand2", padx=8
                  ).pack(side="right")

        sep()

        # ── CROP MODE ──
        section("CROP MODE")
        crop_box = tk.Frame(p, bg=BG2, highlightthickness=1,
                            highlightbackground=BORDER)
        crop_box.pack(fill="x", padx=18, pady=(0, 6))
        self._crop_mode = RadioGroup(crop_box, [
            ("Center  (stable, fastest — recommended)", "center", "crop_center"),
            ("Single locked subject  (analyses whole video)", "single", "crop_single"),
            ("Per-scene adaptive  (slow, for long videos)", "scene",  "crop_scene"),
        ], default="center", hover_cb=hcb)
        self._crop_mode.pack(fill="x", padx=4, pady=6)

        sep()

        # ── OUTPUT ASPECT ──
        section("OUTPUT ASPECT RATIO")
        ar_box = tk.Frame(p, bg=BG2, highlightthickness=1,
                          highlightbackground=BORDER)
        ar_box.pack(fill="x", padx=18, pady=(0, 6))
        self._aspect = RadioGroup(ar_box, [
            ("Square 1:1  (default for the game)", "1:1",      "ar_1:1"),
            ("Widescreen 16:9",                    "16:9",     "ar_16:9"),
            ("Classic 4:3",                        "4:3",      "ar_4:3"),
            ("Original",                           "original", "ar_original"),
        ], default="1:1", hover_cb=hcb)
        self._aspect.pack(fill="x", padx=4, pady=6)

        sep()

        # ── VHS EFFECTS ──
        section("VHS EFFECTS")
        fx_box = tk.Frame(p, bg=BG2, highlightthickness=1,
                          highlightbackground=BORDER)
        fx_box.pack(fill="x", padx=18, pady=(0, 6))

        tk.Label(fx_box, text="  ON / OFF", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(anchor="w", padx=8, pady=(6, 2))

        toggle_frame = tk.Frame(fx_box, bg=BG2)
        toggle_frame.pack(fill="x", padx=4)
        lc = tk.Frame(toggle_frame, bg=BG2)
        rc = tk.Frame(toggle_frame, bg=BG2)
        lc.pack(side="left", fill="both", expand=True)
        rc.pack(side="left", fill="both", expand=True)

        def tog(parent, key, label, default=True):
            row = ToggleRow(parent, label, default=default,
                            hover_key=key, hover_cb=hcb)
            row.pack(fill="x", pady=1)
            self._fx[key] = row.var
            row.var.trace_add("write", self._refresh_combined)
            return row

        t_scanlines = tog(lc, "scanlines",    "Scanlines")
        t_vignette  = tog(lc, "vignette",     "Vignette")
        t_chroma    = tog(lc, "chroma_bleed", "Chroma Bleed")
        t_flicker   = tog(rc, "flicker",      "Brightness Flicker")
        t_tear      = tog(rc, "tape_tear",    "Tape Tear Lines", default=True)
        t_hue       = tog(lc, "hue_drift",    "Hue / Colour Drift", default=False)

        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=6)

        tk.Label(fx_box, text="  INTENSITY SLIDERS", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(anchor="w", padx=8, pady=(0, 4))

        scb = self._on_strength_change  # strength callback

        def sld(label, key_attr, default, to=1.0, hover_key=None, fmt=None):
            hk = hover_key or key_attr
            row = SliderRow(fx_box, label, default=default, to=to,
                            hover_key=hk, hover_cb=hcb,
                            strength_cb=scb, fmt=fmt)
            row.pack(fill="x", pady=1)
            setattr(self, key_attr, row.var)
            row.var.trace_add("write", self._refresh_combined)
            return row

        s_scanlines = sld("Scanline darkness",  "_scanlines_str_var",  0.25, hover_key="scanlines")
        s_vignette  = sld("Vignette strength",  "_vignette_str_var",   0.05, hover_key="vignette")
        s_chroma    = sld("Chroma shift",        "_bleed_shift_var",    4.0,  to=12.0,
                          hover_key="chroma_bleed", fmt=lambda v: f"{v:.0f}px")
        s_flicker   = sld("Flicker range",       "_flicker_range_var",  0.025, to=0.10,
                          hover_key="flicker", fmt=lambda v: f"{v*100:.1f}%")
        s_hue       = sld("Hue drift (°)",       "_hue_drift_amt_var",  3.0,  to=12.0,
                          hover_key="hue_drift", fmt=lambda v: f"{v:.0f}°")
        s_desat     = sld("Desaturation",        "_desat_amt_var",      0.12, to=0.5,
                          hover_key="hue_drift")
        s_tear      = sld("Tape tear prob",      "_tear_prob_var",      0.006, to=0.025,
                          hover_key="tape_tear", fmt=lambda v: f"{v*100:.1f}%")

        # Additional VHS authenticity effects
        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(fx_box, text="  AUTHENTICITY", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(anchor="w", padx=8, pady=(0, 2))

        auth_frame = tk.Frame(fx_box, bg=BG2)
        auth_frame.pack(fill="x", padx=4)
        al = tk.Frame(auth_frame, bg=BG2)
        ar2 = tk.Frame(auth_frame, bg=BG2)
        al.pack(side="left", fill="both", expand=True)
        ar2.pack(side="left", fill="both", expand=True)

        def auth_tog(parent, key, label, default=False):
            row = ToggleRow(parent, label, default=default,
                            hover_key=None, hover_cb=None)
            row.pack(fill="x", pady=1)
            self._fx[key] = row.var
            row.var.trace_add("write", self._refresh_combined)
            return row

        auth_tog(al,  "interlace",    "Interlacing",    default=False)
        auth_tog(al,  "head_switch",  "Head Switching", default=False)
        auth_tog(al,  "dropout",      "Tape Dropout",   default=False)
        auth_tog(ar2, "edge_ringing", "Edge Ringing",   default=False)
        auth_tog(ar2, "chroma_noise", "Chroma Noise",   default=False)
        auth_tog(ar2, "wobble",       "Speed Wobble",   default=False)

        # REC overlay toggle
        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(6, 2))
        t_rec = ToggleRow(fx_box, "REC Overlay  (●  timecode burn-in)", default=False,
                          hover_key=None, hover_cb=None)
        t_rec.pack(fill="x")
        self._fx["rec_overlay"] = t_rec.var
        t_rec.var.trace_add("write", self._refresh_combined)

        # VHS tape quality (internal resolution before effects)
        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(fx_box, text="  VHS TAPE QUALITY", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(anchor="w", padx=8, pady=(0, 2))
        tk.Label(fx_box, text="  Downscale before effects for authentic lo-fi VHS resolution",
                 font=_font(7), fg=TEXT_DIM, bg=BG2).pack(anchor="w", padx=8, pady=(0, 4))

        quality_row = tk.Frame(fx_box, bg=BG2)
        quality_row.pack(fill="x", padx=8, pady=(0, 4))

        self._vhs_quality = tk.StringVar(value="vhs")
        quality_presets = [
            ("Full",        "full",   "No downscale — sharp"),
            ("Hi-Fi VHS",   "hifi",   "75% — VHS Hi-Fi"),
            ("VHS",         "vhs",    "50% — Standard VHS"),
            ("Worn Tape",   "worn",   "33% — Degraded"),
            ("Damaged",     "damage", "20% — Barely watchable"),
        ]
        self._quality_btns = {}
        for label, key, tip in quality_presets:
            is_default = (key == "vhs")
            btn = tk.Button(
                quality_row, text=label,
                command=lambda k=key: self._set_vhs_quality(k),
                font=_font(8, bold=is_default),
                fg=BG if is_default else TEXT_DIM,
                bg=ACCENT if is_default else BG3,
                activebackground=ACCENT2, activeforeground=BG,
                relief="flat", cursor="hand2",
                padx=6, pady=4,
            )
            btn.pack(side="left", padx=2)
            btn.bind("<Enter>", lambda e, t=tip: self._status_text.set(t))
            btn.bind("<Leave>", lambda e: self._status_text.set(""))
            self._quality_btns[key] = btn

        # Output size slider
        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(fx_box, text="  OUTPUT SIZE", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(anchor="w", padx=8, pady=(0, 2))

        size_row = tk.Frame(fx_box, bg=BG2)
        size_row.pack(fill="x", padx=8, pady=(0, 4))

        self._out_size = tk.IntVar(value=512)
        size_presets = [256, 320, 384, 480, 512, 640, 768, 1024]

        size_btn_row = tk.Frame(size_row, bg=BG2)
        size_btn_row.pack(fill="x")

        self._size_btns = {}
        for sz in size_presets:
            is_default = (sz == self._out_size.get())
            is_game_std = (sz == 512)
            btn = tk.Button(
                size_btn_row, text=(str(sz) + " ★") if is_game_std else str(sz),
                command=lambda s=sz: self._set_output_size(s),
                font=_font(8, bold=is_default),
                fg=BG if is_default else TEXT_DIM,
                bg=ACCENT if is_default else ("#8a6000" if is_game_std else BG3),
                activebackground=ACCENT2, activeforeground=BG,
                relief="flat", cursor="hand2",
                padx=6, pady=4,
            )
            btn.pack(side="left", padx=2)
            self._size_btns[sz] = btn

        # Visual size preview bar
        self._size_canvas = tk.Canvas(size_row, bg=BG3, height=32,
                                       highlightthickness=1,
                                       highlightbackground=BORDER)
        self._size_canvas.pack(fill="x", pady=(4, 0))
        self._size_canvas.bind("<Configure>", lambda e: self._draw_size_preview())
        self._draw_size_preview()

        # Noise — toggle + slider pair
        tk.Frame(fx_box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(6, 2))
        t_noise = ToggleRow(fx_box, "Noise / Grain", default=True,
                            hover_key="noise", hover_cb=hcb)
        t_noise.pack(fill="x")
        self._fx["noise"] = t_noise.var
        t_noise.var.trace_add("write", self._refresh_combined)
        s_noise = SliderRow(fx_box, "  grain level", default=0.20,
                            hover_key="noise", hover_cb=hcb, strength_cb=scb)
        s_noise.pack(fill="x")
        self._noise_level = s_noise.var
        s_noise.var.trace_add("write", self._refresh_combined)

        # Glitch — toggle + slider pair
        t_glitch = ToggleRow(fx_box, "Glitch / Tracking Errors", default=True,
                             hover_key="glitch", hover_cb=hcb)
        t_glitch.pack(fill="x", pady=(4, 0))
        self._fx["glitch"] = t_glitch.var
        t_glitch.var.trace_add("write", self._refresh_combined)
        s_glitch = SliderRow(fx_box, "  glitch level", default=0.25,
                             hover_key="glitch", hover_cb=hcb, strength_cb=scb)
        s_glitch.pack(fill="x")
        self._glitch_level = s_glitch.var
        s_glitch.var.trace_add("write", self._refresh_combined)

        # ── Wire each toggle → gray out its slider(s) immediately ──
        def _link(toggle_widget, *slider_widgets):
            def _update(*_):
                on = toggle_widget.var.get()
                for sw in slider_widgets:
                    sw.set_enabled(on)
                self._refresh_combined()
            toggle_widget.var.trace_add("write", _update)
            _update()   # set initial state right away

        _link(t_scanlines, s_scanlines)
        _link(t_vignette,  s_vignette)
        _link(t_chroma,    s_chroma)
        _link(t_flicker,   s_flicker)
        _link(t_hue,       s_hue, s_desat)
        _link(t_tear,      s_tear)
        _link(t_noise,     s_noise)
        _link(t_glitch,    s_glitch)

        tk.Frame(fx_box, bg=BG, height=6).pack()

        # Seed the combined preview with initial settings
        self.after(200, self._notify_combined)

        sep()

        # ── GPU / CPU SELECTOR ──
        hw_frame = tk.Frame(p, bg=BG2, highlightthickness=1,
                            highlightbackground=BORDER)
        hw_frame.pack(fill="x", padx=18, pady=(0, 6))

        hw_row = tk.Frame(hw_frame, bg=BG2)
        hw_row.pack(fill="x", padx=8, pady=6)

        tk.Label(hw_row, text="RENDER DEVICE  (OpenCL — AMD / Intel / NVIDIA)", font=_font(8, bold=True),
                 fg=ACCENT2, bg=BG2).pack(side="left", padx=(0, 10))

        gpu_cb = tk.Checkbutton(
            hw_row, text="Use GPU (OpenCL)",
            variable=self._use_gpu,
            bg=BG2, activebackground=BG2, selectcolor=BG4,
            fg=LED if self._gpu_avail else TEXT,
            activeforeground=LED,
            font=_font(9), relief="flat", cursor="hand2" if self._gpu_avail else "",
        )
        gpu_cb.pack(side="left")
        if not self._gpu_avail:
            gpu_cb.config(state="disabled")

        gpu_status = self._gpu_name if self._gpu_avail else "No CUDA GPU detected — CPU only"
        tk.Label(hw_row, text=gpu_status,
                 font=_font(8), fg=TEXT_DIM if not self._gpu_avail else LED,
                 bg=BG2).pack(side="left", padx=(8, 0))

        sep()

        # ── ACTION BUTTONS — two rows, centered ──
        btn_cfg_primary = dict(font=_font(12, bold=True), relief="flat",
                               cursor="hand2", padx=24, pady=10)
        btn_cfg_sec     = dict(font=_font(12, bold=True), relief="flat",
                               cursor="hand2", padx=20, pady=10)

        # Row 1: Convert + Stop side by side, centered
        row1 = tk.Frame(p, bg=BG)
        row1.pack(pady=(4, 4))

        self._btn = tk.Button(
            row1, text="▶  CONVERT TO VHS",
            command=self._start_conversion,
            fg="#fff", bg=ACCENT,
            activebackground="#ff3355", activeforeground="#fff",
            **btn_cfg_primary,
        )
        self._btn.pack(side="left", padx=(0, 10))

        self._stop_btn = tk.Button(
            row1, text="⏹  STOP",
            command=self._stop_conversion,
            fg=TEXT, bg=BG4,
            activebackground="#440000", activeforeground=ACCENT,
            state="disabled",
            **btn_cfg_sec,
        )
        self._stop_btn.pack(side="left")

        # Row 2: Preview alone, centered, visually separated
        row2 = tk.Frame(p, bg=BG)
        row2.pack(pady=(0, 8))

        self._preview_btn = tk.Button(
            row2, text="📼  PREVIEW RESULT",
            command=self._open_preview,
            fg=TEXT, bg=BG4,
            activebackground=BG3, activeforeground=ACCENT2,
            state="disabled",
            **btn_cfg_sec,
        )
        self._preview_btn.pack()

        tk.Frame(p, bg=BG, height=6).pack()

        # Populate combined preview with initial settings after all controls built
        self.after(200, self._refresh_combined)

    # ── HELPERS ─────────────────────────────────────────────

    def _refresh_combined(self, *_):
        """Push current settings to the live combined preview canvas."""
        try:
            self._combined.refresh_settings(self._build_settings())
        except Exception:
            pass

    def _set_vhs_quality(self, key):
        self._vhs_quality.set(key)
        for k, btn in self._quality_btns.items():
            is_sel = (k == key)
            btn.config(
                fg=BG if is_sel else TEXT_DIM,
                bg=ACCENT if is_sel else BG3,
                font=_font(8, bold=is_sel),
            )

    def _set_output_size(self, size):
        self._out_size.set(size)
        for sz, btn in self._size_btns.items():
            is_sel     = (sz == size)
            is_std     = (sz == 512)
            lbl        = (str(sz) + " ★") if is_std else str(sz)
            btn.config(
                text=lbl,
                fg=BG if is_sel else TEXT_DIM,
                bg=ACCENT if is_sel else ("#8a6000" if is_std else BG3),
                font=_font(8, bold=is_sel),
            )
        self._draw_size_preview()
        self._refresh_combined()

    def _draw_size_preview(self):
        c = self._size_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.delete("all")
        sz = self._out_size.get()
        max_sz = 1024
        frac = sz / max_sz
        bar_w = max(4, int(w * frac))
        # Background
        c.create_rectangle(0, 0, w, h, fill=BG3, outline="")
        # Filled portion
        c.create_rectangle(0, 0, bar_w, h, fill=ACCENT, outline="")
        # Label
        label = f"{sz} × {sz}  px"
        c.create_text(w // 2, h // 2, text=label,
                      font=_font(8, bold=True), fill=TEXT, anchor="center")

    def _file_row(self, parent, var, btn_text, cmd, primary=True):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=18, pady=(0, 6))
        entry = tk.Entry(row, textvariable=var, font=_font(10),
                         fg=TEXT, bg=BG3, insertbackground=ACCENT,
                         relief="flat", highlightthickness=1,
                         highlightcolor=ACCENT, highlightbackground=BORDER)
        entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        tk.Button(row, text=btn_text, command=cmd,
                  font=_font(9, bold=True),
                  fg=BG if primary else TEXT,
                  bg=ACCENT if primary else BG3,
                  activebackground=ACCENT2, activeforeground=BG,
                  relief="flat", cursor="hand2", padx=10).pack(side="right")

    def _select_genre(self, genre):
        """Select a genre — highlights the button and updates output path."""
        self._rr_category.set(genre)
        for g, btn in self._genre_btns.items():
            STARTER_GENRES = {"Public", "Scifi", "Police"}
            is_sel     = (g == genre)
            is_starter = g in STARTER_GENRES
            idle_bg = "#0a2a0a" if is_starter else BG3
            idle_fg = LED if is_starter else TEXT
            tip = " ★ Starter" if is_starter else ""
            btn.config(
                text=g + tip,
                fg=BG if is_sel else idle_fg,
                bg=ACCENT if is_sel else idle_bg,
                font=_font(8, bold=is_sel),
            )
        self._update_output_path()

    def _detect_game_folder(self):
        """
        Detect the VHS folder: RetroRewind/RetroRewind/Content/Movies/VHS
        Searches all drives and common Steam library locations.
        """
        VHS_SUBPATH = os.path.join("steamapps","common","RetroRewind",
                                   "RetroRewind","Content","Movies","VHS")
        candidates = []
        for drive in ["C:", "D:", "E:", "F:", "G:"]:
            for steam_root in [
                os.path.join(drive, os.sep, "SteamLibrary"),
                os.path.join(drive, os.sep, "Program Files (x86)", "Steam"),
                os.path.join(drive, os.sep, "Program Files", "Steam"),
                os.path.join(drive, os.sep, "Steam"),
            ]:
                candidates.append(os.path.join(steam_root, VHS_SUBPATH))
        for path in candidates:
            if os.path.isdir(path):
                self._game_folder.set(path)
                self._status_text.set(f"Found: {path}")
                self._update_output_path()
                return
        self._status_text.set("Not found — Browse to RetroRewind/RetroRewind/Content/Movies/VHS")

    def _browse_game_folder(self):
        path = filedialog.askdirectory(title="Select Retro Rewind game folder")
        if path:
            self._game_folder.set(path)

    def _update_output_path(self, *_):
        """
        Build output path:
          {VHS_folder}/{Genre}/RR_Channel_{Genre}.mp4
        If no game folder, save beside the input file.
        """
        if not self._auto_name.get():
            return
        cat = self._rr_category.get().strip() or "Action"
        filename = f"RR_Channel_{cat}.mp4"
        game = self._game_folder.get().strip()
        if game and os.path.isdir(game):
            # Save into the genre subfolder inside VHS
            genre_dir = os.path.join(game, cat)
            os.makedirs(genre_dir, exist_ok=True)
            self._output_path.set(os.path.join(genre_dir, filename))
        else:
            inp = self._input_path.get().strip()
            if inp:
                self._output_path.set(str(Path(inp).parent / filename))
            else:
                self._output_path.set(filename)

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select MP4 video",
            filetypes=[("MP4 Video", "*.mp4 *.MP4"), ("All files", "*.*")]
        )
        if path:
            self._input_path.set(path)
            # _update_output_path fires via trace — don't override it here
            # But call it explicitly in case trace doesn't fire on same-value set
            self.after(10, self._update_output_path)
            # Load preview frames in background
            def _load():
                self._combined.load_video(path)
                self.after(0, self._refresh_combined)
            threading.Thread(target=_load, daemon=True).start()

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save VHS output as",
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4")]
        )
        if path:
            self._output_path.set(path)

    def _build_settings(self):
        return {
            "crop_mode"    : self._crop_mode.var.get(),
            "aspect"       : self._aspect.var.get(),
            "scanlines"    : self._fx["scanlines"].get(),
            "vignette"     : self._fx["vignette"].get(),
            "chroma_bleed" : self._fx["chroma_bleed"].get(),
            "flicker"      : self._fx["flicker"].get(),
            "hue_drift"    : self._fx["hue_drift"].get(),
            "tape_tear"    : self._fx["tape_tear"].get(),
            "noise"        : self._fx["noise"].get(),
            "glitch"       : self._fx["glitch"].get(),
            "scanlines_str": self._scanlines_str_var.get(),
            "vignette_str" : self._vignette_str_var.get(),
            "bleed_shift"  : int(self._bleed_shift_var.get()),
            "flicker_range": self._flicker_range_var.get(),
            "hue_drift_amt": self._hue_drift_amt_var.get(),
            "desat_amt"    : self._desat_amt_var.get(),
            "tear_prob"    : self._tear_prob_var.get(),
            "noise_level"  : self._noise_level.get(),
            "glitch_level" : self._glitch_level.get(),
            "rec_overlay"  : self._fx["rec_overlay"].get(),
            "interlace"    : self._fx.get("interlace",    tk.BooleanVar(value=True)).get() if "interlace" in self._fx else True,
            "head_switch"  : self._fx.get("head_switch",  tk.BooleanVar(value=True)).get() if "head_switch" in self._fx else True,
            "dropout"      : self._fx.get("dropout",      tk.BooleanVar(value=False)).get() if "dropout" in self._fx else False,
            "edge_ringing" : self._fx.get("edge_ringing", tk.BooleanVar(value=False)).get() if "edge_ringing" in self._fx else False,
            "chroma_noise" : self._fx.get("chroma_noise", tk.BooleanVar(value=True)).get() if "chroma_noise" in self._fx else True,
            "wobble"       : self._fx.get("wobble",       tk.BooleanVar(value=False)).get() if "wobble" in self._fx else False,
            "out_size"     : self._out_size.get(),
            "vhs_quality"  : self._vhs_quality.get(),
        }

    # ── CONVERSION ──────────────────────────────────────────

    def _start_conversion(self):
        if self._running:
            return
        inp = self._input_path.get().strip()
        out = self._output_path.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror("No input", "Please select a valid MP4 file.")
            return
        if not out:
            messagebox.showerror("No output", "Please set an output file path.")
            return

        self._running = True
        self._stop_event.clear()
        self._btn.config(state="disabled", text="⏳  CONVERTING…")
        self._stop_btn.config(state="normal")
        self._progress.set(0)
        self._status_text.set("Starting…")

        settings = self._build_settings()
        settings["use_gpu"] = self._use_gpu.get()
        threading.Thread(
            target=run_conversion,
            args=(inp, out, settings,
                  self._on_progress, self._on_status, self._on_done,
                  self._stop_event),
            daemon=True,
        ).start()

    def _stop_conversion(self):
        """Signal the worker thread to stop gracefully."""
        self._stop_event.set()
        self._stop_btn.config(state="disabled", text="Stopping…")
        self._status_text.set("Stopping… finishing current frame")

    def _on_progress(self, pct):
        self.after(0, lambda: self._progress.set(pct))

    def _on_status(self, msg):
        self.after(0, lambda: self._status_text.set(msg))

    def _on_done(self, success, msg):
        def _finish():
            self._running = False
            self._btn.config(state="normal", text="▶  CONVERT TO VHS")
            self._stop_btn.config(state="disabled", text="⏹  STOP")
            if success:
                self._progress.set(100)
                self._status_text.set("✓  Done!   " + os.path.basename(msg))
                self._last_output = msg
                self._preview_btn.config(state="normal")
            else:
                if msg == "__cancelled__":
                    self._status_text.set("Stopped.")
                    self._progress.set(0)
                else:
                    self._status_text.set("Error. Check path / FFmpeg.")
                    messagebox.showerror("Conversion failed", msg)
        self.after(0, _finish)

    def _open_preview(self):
        if self._last_output and os.path.isfile(self._last_output):
            VideoPlayerWindow(self, self._last_output)


# ──────────────────────────────────────────────────────────────
#  VIDEO PREVIEW PLAYER
# ──────────────────────────────────────────────────────────────

class VideoPlayerWindow(tk.Toplevel):
    DISPLAY_SIZE = 512

    def __init__(self, parent, video_path):
        super().__init__(parent)
        self.title(f"📼  {os.path.basename(video_path)}")
        self.configure(bg=BG)
        self.resizable(False, False)

        _set_icon(self)

        self._path      = video_path
        self._cap       = cv2.VideoCapture(video_path)
        self._fps       = self._cap.get(cv2.CAP_PROP_FPS) or 24.0
        self._total     = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._delay_ms  = max(1, int(1000 / self._fps))
        self._playing   = False
        self._cur_frame = 0
        self._photo     = None
        self._after_id  = None

        self._build_ui()
        self._seek(0)
        self._play()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        D = self.DISPLAY_SIZE
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        title_row = tk.Frame(self, bg=BG)
        title_row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(title_row, text="📼  PREVIEW", font=_font(11, bold=True),
                 fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(title_row, text=os.path.basename(self._path),
                 font=_font(8), fg=TEXT_DIM, bg=BG).pack(side="left", padx=(10, 0), pady=(3, 0))

        cf = tk.Frame(self, bg=BORDER, padx=2, pady=2)
        cf.pack(padx=12)
        self._canvas = tk.Canvas(cf, width=D, height=D,
                                 bg="#000", highlightthickness=0)
        self._canvas.pack()
        # REC indicator — drawn dynamically in _render, not hardcoded

        sf = tk.Frame(self, bg=BG)
        sf.pack(fill="x", padx=12, pady=(6, 2))
        self._scrub_var = tk.IntVar(value=0)

        # Custom scrub bar — tall, high contrast, timestamp display
        self._scrub_canvas = tk.Canvas(sf, bg=BG, height=28,
                                        highlightthickness=0, cursor="hand2")
        self._scrub_canvas.pack(fill="x", pady=(0, 2))
        self._scrub_canvas.bind("<Configure>",       self._draw_scrub)
        self._scrub_canvas.bind("<ButtonPress-1>",   self._scrub_press)
        self._scrub_canvas.bind("<B1-Motion>",       self._scrub_drag)
        self._scrub_canvas.bind("<ButtonRelease-1>", self._scrub_release)
        self._scrub_dragging = False

        ctrl = tk.Frame(self, bg=BG)
        ctrl.pack(pady=(2, 8))
        bc = dict(font=_font(10, bold=True), relief="flat", cursor="hand2", padx=14, pady=6)
        self._play_btn = tk.Button(ctrl, text="⏸  PAUSE", command=self._toggle_play,
                                   fg=BG, bg=ACCENT, activebackground=ACCENT2, **bc)
        self._play_btn.pack(side="left", padx=(0, 6))
        tk.Button(ctrl, text="⏮  RESTART", command=lambda: self._seek(0),
                  fg=TEXT, bg=BG3, activebackground=BG2, activeforeground=TEXT,
                  **bc).pack(side="left", padx=(0, 6))
        tk.Button(ctrl, text="✕  CLOSE", command=self._on_close,
                  fg=TEXT_DIM, bg=BG2, activebackground=BG3, activeforeground=TEXT,
                  **bc).pack(side="left")

        self._counter_var = tk.StringVar(value="0 / 0")
        tk.Label(self, textvariable=self._counter_var,
                 font=_font(8), fg=TEXT_DIM, bg=BG).pack(pady=(0, 4))
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

    def _display(self, frame):
        """Push a decoded BGR frame to the canvas."""
        D   = self.DISPLAY_SIZE
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if rgb.shape[0] != D or rgb.shape[1] != D:
            rgb = cv2.resize(rgb, (D, D))
        try:
            from PIL import Image, ImageTk
            self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        except ImportError:
            ppm = b"P6\n" + f"{D} {D}\n255\n".encode() + rgb.tobytes()
            self._photo = tk.PhotoImage(data=ppm)
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        # (no hud overlay in player)
        # Update the custom scrub bar
        if hasattr(self, "_scrub_canvas"):
            self._draw_scrub()

    def _render(self, idx):
        """Seek to a specific frame index — used for scrubbing only."""
        if not self._cap.isOpened():
            return
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self._cap.read()
        if not ret:
            return
        self._display(frame)
        self._scrub_var.set(idx)
        if hasattr(self, '_scrub_canvas'):
            self._draw_scrub()
        self._counter_var.set(
            f"{idx+1} / {self._total}  ({idx / max(self._total-1,1)*100:.0f}%)")

    def _seek(self, idx):
        """Jump to idx — cap stays positioned for sequential read from there."""
        self._cur_frame = max(0, min(idx, self._total-1))
        self._render(self._cur_frame)

    def _tick(self):
        """Advance one frame using sequential cap.read() — no per-frame seek."""
        if not self._playing:
            return
        t_start = time.perf_counter()

        ret, frame = self._cap.read()
        if not ret:
            # End of video — loop
            self._cur_frame = 0
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret:
                return

        self._cur_frame = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        self._display(frame)
        self._scrub_var.set(self._cur_frame)
        self._counter_var.set(
            f"{self._cur_frame+1} / {self._total}  "
            f"({self._cur_frame / max(self._total-1,1)*100:.0f}%)")

        # Subtract decode time so speed stays accurate
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        wait = max(1, int(self._delay_ms - elapsed_ms))
        self._after_id = self.after(wait, self._tick)

    def _play(self):
        if self._playing:
            return
        self._playing = True
        self._play_btn.config(text="⏸  PAUSE")
        self._tick()

    def _pause(self):
        self._playing = False
        self._play_btn.config(text="▶  PLAY")
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _toggle_play(self):
        self._pause() if self._playing else self._play()

    def _draw_scrub(self, _event=None):
        c = self._scrub_canvas
        w = c.winfo_width(); h = c.winfo_height()
        if w < 2: return
        c.delete("all")
        total = max(self._total - 1, 1)
        frac  = self._cur_frame / total
        tx    = int(frac * (w - 4)) + 2

        # Trough
        c.create_rectangle(2, h//2-3, w-2, h//2+3,
                           fill="#3a3a3a", outline="#606060", width=1)
        # Filled
        if tx > 2:
            c.create_rectangle(2, h//2-3, tx, h//2+3,
                               fill=ACCENT, outline="")
        # Thumb
        c.create_rectangle(tx-6, 2, tx+6, h-2,
                           fill="#e0e0e0", outline="#aaaaaa", width=1)
        c.create_line(tx, 4, tx, h-4, fill="#888888", width=1)

        # Timestamp
        secs  = int(self._cur_frame / max(self._fps, 1))
        total_secs = int(self._total / max(self._fps, 1))
        ts    = f"{secs//60:02d}:{secs%60:02d} / {total_secs//60:02d}:{total_secs%60:02d}"
        c.create_text(w//2, h//2, text=ts,
                      font=_font(7, bold=True), fill=TEXT_DIM, anchor="center")

    def _scrub_x_to_frame(self, x):
        w = self._scrub_canvas.winfo_width()
        frac = max(0.0, min(1.0, (x - 2) / max(1, w - 4)))
        return int(frac * max(self._total - 1, 1))

    def _scrub_press(self, event):
        self._scrub_dragging = True
        was = self._playing
        self._pause()
        self._seek(self._scrub_x_to_frame(event.x))
        self._draw_scrub()
        self._scrub_was_playing = was

    def _scrub_drag(self, event):
        if not self._scrub_dragging: return
        self._seek(self._scrub_x_to_frame(event.x))
        self._draw_scrub()

    def _scrub_release(self, event):
        self._scrub_dragging = False
        self._seek(self._scrub_x_to_frame(event.x))
        self._draw_scrub()
        if getattr(self, "_scrub_was_playing", False):
            self._play()

    def _on_scrub(self, val):
        # Legacy — kept for compatibility
        pass

    def _on_close(self):
        self._pause()
        if self._cap.isOpened():
            self._cap.release()
        self.destroy()


# ──────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────

def main():
    try:
        import cv2, numpy
    except ImportError as e:
        import tkinter as _tk, tkinter.messagebox as _mb
        _tk.Tk().withdraw()
        _mb.showerror("Missing dependency",
                      f"pip install opencv-python numpy\n\n{e}")
        sys.exit(1)

    if _find_ffmpeg() is None:
        import tkinter as _tk, tkinter.messagebox as _mb
        _tk.Tk().withdraw()
        _mb.showerror(
            "FFmpeg not found",
            "FFmpeg was not found.\n\n"
            "If you downloaded from GitHub, make sure you got the full\n"
            "release zip — FFmpeg is included inside it.\n\n"
            "Or install FFmpeg from https://ffmpeg.org/download.html\n"
            "and add it to your PATH."
        )
        sys.exit(1)

    RetroRewindApp().mainloop()


if __name__ == "__main__":
    main()
