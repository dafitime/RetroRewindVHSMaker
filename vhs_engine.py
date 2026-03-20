"""
vhs_engine.py  -  Retro Rewind VHS Processing Core

Crop strategy
─────────────
Rather than tracking frame-by-frame (which always jitters), we do a fast
two-pass approach:

  PASS 1 – ANALYSE  (analyse_crop)
    Sample ~60 evenly-spaced frames from the video.
    For each sample, detect the best subject position using:
      1. Face detection   → weighted heavily (faces are the subject)
      2. Saliency/edges   → fallback for non-face content
      3. Center           → final fallback
    Collect all candidate (cx, cy) pairs, take the median,
    then lock that single position for the whole video.

  PASS 2 – RENDER  (run_conversion in app.py)
    Crop every frame at exactly that locked position.
    Zero movement. Rock solid.

For very long videos (>10 min) we optionally allow a slow scene-cut
detection that smoothly transitions the locked crop between scenes —
but even then each "scene crop" is locked for the whole scene.

VHS effects
───────────
All effects are individually toggled and have intensity sliders.
"""

import cv2
import numpy as np
import random
import os
import sys


# ──────────────────────────────────────────────────────────────
#  CASCADE LOADER
# ──────────────────────────────────────────────────────────────

def _find_cascade():
    filename   = "haarcascade_frontalface_default.xml"
    candidates = []
    try:
        candidates.append(os.path.join(cv2.data.haarcascades, filename))
    except AttributeError:
        pass
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, filename))
        candidates.append(os.path.join(sys._MEIPASS, "cv2", "data", filename))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, filename))
    for base in [
        r"C:\opencv\build\etc\haarcascades",
        r"C:\tools\opencv\etc\haarcascades",
        "/usr/share/opencv4/haarcascades",
        "/usr/share/opencv/haarcascades",
        "/usr/local/share/opencv4/haarcascades",
        "/opt/homebrew/share/opencv4/haarcascades",
    ]:
        candidates.append(os.path.join(base, filename))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


# ──────────────────────────────────────────────────────────────
#  CROP ANALYSER  –  one-time analysis pass
# ──────────────────────────────────────────────────────────────

class CropAnalyser:
    """
    Sample the video, find the best single (cx, cy) to lock the crop on.
    Returns a CropPlan — a list of (frame_index, crop_x, crop_y) tuples.

    For short videos: one single locked crop for the whole thing.
    For longer videos: detects hard scene cuts and locks a crop per scene,
    with a slow linear interpolation between scene crops (over ~90 frames)
    so transitions are barely noticeable.
    """

    SAMPLE_COUNT    = 60     # frames to analyse in pass 1
    FACE_WEIGHT     = 3.0    # faces count 3× more than saliency hits
    SCENE_CUT_THRESH = 35.0  # mean absolute diff to call a scene cut
    MIN_SCENE_FRAMES = 90    # ignore scene cuts shorter than this

    def __init__(self):
        cascade_path      = _find_cascade()
        self._face_enabled = False
        if cascade_path:
            det = cv2.CascadeClassifier(cascade_path)
            if not det.empty():
                self._det          = det
                self._face_enabled = True

    # ── subject detection on a single frame ─────────────────

    def _best_subject(self, frame):
        """
        Return (cx, cy) of the most important subject in this frame.

        Strategy:
          1. Face detection — most reliable for people content
          2. Person/upper-body detection — catches faces missed by frontal detector
          3. Motion-weighted centroid — for action content without people
          4. Centre-weighted saliency — bias toward the middle (where directors put subjects)
             rather than raw edge energy (which just finds subtitles and bright edges)
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Face detection (half-res for better recall than quarter-res)
        if self._face_enabled:
            try:
                scale = 0.5
                small = cv2.resize(gray, (0, 0), fx=scale, fy=scale)
                faces = self._det.detectMultiScale(
                    small, scaleFactor=1.1, minNeighbors=4, minSize=(25, 25)
                )
                if len(faces) > 0:
                    faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
                    x, y, fw2, fh2 = faces[0]
                    cx = int((x + fw2/2) / scale)
                    cy = int((y + fh2/2) / scale)
                    # Sanity check: face should be within the frame bounds
                    if 0 < cx < w and 0 < cy < h:
                        return cx, cy
            except cv2.error:
                pass

        # 2. Centre-weighted saliency — combine edge energy with a Gaussian
        #    that weights the image centre heavily. This is much more reliable
        #    than raw edge energy which lights up on subtitles/borders.
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))

        # Build a centre-bias Gaussian weight map
        Y, X = np.ogrid[:h, :w]
        cx0, cy0 = w / 2.0, h / 2.0
        # Sigma = 40% of the smaller dimension
        sig = min(w, h) * 0.40
        gauss = np.exp(-((X - cx0)**2 + (Y - cy0)**2) / (2 * sig**2))

        # Exclude the top 10% and bottom 10% of the frame
        # (letterbox bars, subtitles, and channel logos live there)
        margin_h = int(h * 0.10)
        gauss[:margin_h, :]  = 0
        gauss[h-margin_h:, :] = 0

        weighted = lap * gauss

        # Find the centroid of the weighted saliency map
        total_w = weighted.sum()
        if total_w < 1e-6:
            return w // 2, h // 2

        cx_f = float((weighted * X).sum() / total_w)
        cy_f = float((weighted * Y).sum() / total_w)

        # Clamp away from the very edges
        margin_w = int(w * 0.05)
        margin_h2 = int(h * 0.05)
        cx_f = np.clip(cx_f, margin_w, w - margin_w)
        cy_f = np.clip(cy_f, margin_h2, h - margin_h2)

        return int(cx_f), int(cy_f)

    # ── scene cut detection ──────────────────────────────────

    def _find_scene_cuts(self, cap, total_frames):
        """
        Quick pass: sample every ~15 frames, flag large brightness jumps
        as scene cuts. Returns sorted list of frame indices where cuts occur.
        """
        cuts  = []
        step  = max(1, total_frames // 300)   # sample ~300 points
        prev  = None

        for i in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (64, 36))
            if prev is not None:
                diff = float(np.mean(np.abs(small.astype(np.float32) - prev.astype(np.float32))))
                if diff > self.SCENE_CUT_THRESH:
                    cuts.append(i)
            prev = small

        # Merge cuts that are too close together
        merged = []
        for c in cuts:
            if not merged or c - merged[-1] >= self.MIN_SCENE_FRAMES:
                merged.append(c)
        return merged

    # ── main analysis ────────────────────────────────────────

    def analyse_single(self, video_path: str, status_cb=None):
        """
        Sample the whole video (~60 frames evenly spread), collect all
        subject positions, return the MEDIAN (cx, cy) as one locked crop.
        Much more robust than using only the first keyframe.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None

        total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop_sz = min(orig_w, orig_h)
        half    = crop_sz // 2

        if status_cb:
            status_cb("Analysing video for best crop position…")

        n_samples = min(60, total)
        step      = max(1, total // n_samples)
        cxs, cys  = [], []

        for i, fi in enumerate(range(0, total, step)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                continue
            sx, sy = self._best_subject(frame)
            cxs.append(sx)
            cys.append(sy)
            if status_cb and i % 10 == 0:
                pct = int(i / n_samples * 100)
                status_cb(f"Analysing…  {pct}%")

        cap.release()

        if not cxs:
            return None

        # Median is robust against outlier detections (e.g. a subtitle frame)
        median_cx = int(np.median(cxs))
        median_cy = int(np.median(cys))

        # Clamp so crop window stays inside frame
        median_cx = int(np.clip(median_cx, half, orig_w - half))
        median_cy = int(np.clip(median_cy, half, orig_h - half))

        # Return as (crop_x, crop_y) top-left
        return median_cx - half, median_cy - half

    def analyse(self, video_path: str, status_cb=None):
        """
        Analyse the video and return a CropPlan:
          list of (frame_idx, crop_x, crop_y)  sorted by frame_idx.

        crop_x, crop_y = top-left corner of the 512×512 (or crop_size) window.
        The caller interpolates between keyframes if needed.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None

        total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop_sz = min(orig_w, orig_h)
        half    = crop_sz // 2

        def clamp(cx, cy):
            cx = int(np.clip(cx, half, orig_w - half))
            cy = int(np.clip(cy, half, orig_h - half))
            return cx - half, cy - half

        if status_cb:
            status_cb("Analysing video for best crop…")

        # ── find scene cuts ──────────────────────────────────
        cuts = self._find_scene_cuts(cap, total)
        # Build scene boundaries: list of (start_frame, end_frame)
        boundaries = []
        prev = 0
        for c in cuts:
            boundaries.append((prev, c))
            prev = c
        boundaries.append((prev, total))

        # ── for each scene, sample frames and find median subject ──
        crop_plan = []   # list of (frame_idx, crop_x, crop_y)

        for scene_idx, (scene_start, scene_end) in enumerate(boundaries):
            scene_len = scene_end - scene_start
            n_samples = max(3, min(self.SAMPLE_COUNT // max(len(boundaries), 1), 20))
            step      = max(1, scene_len // n_samples)

            cxs, cys = [], []
            for i in range(scene_start, scene_end, step):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if not ret:
                    break
                sx, sy = self._best_subject(frame)
                cxs.append(sx)
                cys.append(sy)

            if cxs:
                # Median is robust against outlier detections
                median_cx = int(np.median(cxs))
                median_cy = int(np.median(cys))
            else:
                median_cx = orig_w // 2
                median_cy = orig_h // 2

            crop_x, crop_y = clamp(median_cx, median_cy)
            crop_plan.append((scene_start, crop_x, crop_y))

            if status_cb:
                pct = int((scene_idx + 1) / len(boundaries) * 100)
                status_cb(f"Analysing…  scene {scene_idx+1}/{len(boundaries)}  ({pct}%)")

        cap.release()
        return CropPlan(crop_plan, total, crop_sz)


# ──────────────────────────────────────────────────────────────
#  CROP PLAN  –  returned by CropAnalyser, queried per frame
# ──────────────────────────────────────────────────────────────

class CropPlan:
    """
    Holds the locked crop positions. For each frame, returns (crop_x, crop_y).
    Between scene keyframes, linearly interpolates over BLEND_FRAMES so
    transitions are smooth rather than a jump cut.
    """
    BLEND_FRAMES = 90   # frames over which to blend between scene crops

    def __init__(self, keyframes, total_frames, crop_size):
        # keyframes: list of (frame_idx, crop_x, crop_y)
        self._kf    = sorted(keyframes, key=lambda k: k[0])
        self._total = total_frames
        self._crop  = crop_size

    def get(self, frame_idx: int):
        """Return (crop_x, crop_y) for the given frame index."""
        if not self._kf:
            return 0, 0

        if len(self._kf) == 1:
            return self._kf[0][1], self._kf[0][2]

        # Find surrounding keyframes
        prev_kf = self._kf[0]
        next_kf = self._kf[-1]
        for i, kf in enumerate(self._kf):
            if kf[0] <= frame_idx:
                prev_kf = kf
            if kf[0] > frame_idx:
                next_kf = kf
                break

        if prev_kf is next_kf:
            return prev_kf[1], prev_kf[2]

        dist_from_cut = frame_idx - prev_kf[0]

        # Only blend for BLEND_FRAMES after the scene cut
        if dist_from_cut < self.BLEND_FRAMES:
            t   = dist_from_cut / self.BLEND_FRAMES
            # Ease in-out cubic
            t   = t * t * (3 - 2 * t)
            cx  = int(prev_kf[1] + t * (next_kf[1] - prev_kf[1]))
            cy  = int(prev_kf[2] + t * (next_kf[2] - prev_kf[2]))
            return cx, cy

        return prev_kf[1], prev_kf[2]


# ──────────────────────────────────────────────────────────────
#  PRE-COMPUTED EFFECT MAPS
# ──────────────────────────────────────────────────────────────

class VHSMaps:
    def __init__(self, size: int = 512, w: int = None, h: int = None):
        """
        size  — used when w/h not given (square output, the normal case)
        w, h  — explicit dimensions for non-square use (e.g. preview canvases)
        """
        if w is None:
            w = size
        if h is None:
            h = size

        # Scanlines – every other row darkened (subtle)
        self.scanlines       = np.ones((h, w, 3), np.float32)
        self.scanlines[::2] *= 0.85    # subtle base — slider scales from here

        # Vignette
        cx, cy = w / 2.0, h / 2.0
        Y, X   = np.ogrid[:h, :w]
        dist   = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        vig    = 1.0 - 0.55 * np.clip(dist, 0, 1) ** 2.0   # softer falloff
        self.vignette = vig[:, :, np.newaxis].astype(np.float32)


# ──────────────────────────────────────────────────────────────
#  VHS EFFECT PIPELINE
# ──────────────────────────────────────────────────────────────
#
#  settings keys (including all new intensity sliders):
#    "crop_mode"        : str (center/single/scene)
#    "aspect"           : str (1:1/16:9/4:3/original)
#    "scanlines"        : bool
#    "vignette"         : bool
#    "chroma_bleed"     : bool
#    "flicker"          : bool
#    "hue_drift"        : bool
#    "tape_tear"        : bool
#    "noise"            : bool
#    "glitch"           : bool
#    "scanlines_str"    : float (0..1)  - darkness factor
#    "vignette_str"     : float (0..1)  - strength
#    "bleed_shift"      : int (pixels)  - chroma shift amount
#    "flicker_range"    : float (0..0.1)
#    "hue_drift_amt"    : float (0..10) - degrees
#    "desat_amt"        : float (0..0.5) - desaturation range
#    "tear_prob"        : float (0..0.02)
#    "noise_level"      : float (0..1)
#    "glitch_level"     : float (0..1)
#
# ──────────────────────────────────────────────────────────────

_DEFAULTS = {
    "scanlines"   : True,
    "vignette"    : True,
    "chroma_bleed": True,
    "flicker"     : True,
    "hue_drift"   : True,
    "noise"       : True,
    "noise_level" : 0.20,
    "glitch"      : False,
    "glitch_level": 0.25,
    "tape_tear"   : False,
    # new intensity keys
    "scanlines_str"   : 0.72,
    "vignette_str"    : 0.55,
    "bleed_shift"     : 4,
    "flicker_range"   : 0.025,
    "hue_drift_amt"   : 3.0,
    "desat_amt"       : 0.12,
    "tear_prob"       : 0.006,
}


# ──────────────────────────────────────────────────────────────
#  GPU DETECTION  (OpenCL via cv2.UMat — works on AMD/Intel/NVIDIA)
# ──────────────────────────────────────────────────────────────

def detect_gpu():
    """
    Returns (has_gpu: bool, device_name: str).

    Uses OpenCV's OpenCL backend (cv2.UMat) — built into the standard
    opencv-python pip package.  Works on:
      • NVIDIA  (via OpenCL, no CUDA build needed)
      • AMD     (via ROCm OpenCL or AMDGPU-PRO)
      • Intel   (integrated + Arc, via Intel OpenCL runtime)
      • Apple   (Metal via OpenCL on older macOS)

    No special OpenCV build required — just the regular pip package.
    """
    try:
        # Check if OpenCL is available at all
        if not cv2.ocl.haveOpenCL():
            return False, "No OpenCL GPU detected — CPU only"

        cv2.ocl.setUseOpenCL(True)

        if not cv2.ocl.useOpenCL():
            return False, "OpenCL available but disabled — CPU only"

        # Try a tiny UMat operation to verify it actually works
        test = np.zeros((4, 4, 3), np.float32)
        u    = cv2.UMat(test)
        _    = cv2.UMat.get(u)   # round-trip — throws if broken

        # Get device info string
        dev_info = cv2.ocl.Device.getDefault()
        name     = dev_info.name() if dev_info.available() else "OpenCL GPU"
        vendor   = dev_info.vendorName() if dev_info.available() else ""
        label    = f"{vendor} {name}".strip() if vendor else name
        return True, label

    except Exception:
        return False, "No OpenCL GPU detected — CPU only"


def apply_vhs(frame: np.ndarray, maps: VHSMaps, settings: dict,
              use_gpu: bool = False) -> np.ndarray:
    """
    Apply VHS effects. If use_gpu=True and CUDA is available, uses the GPU
    for the expensive float operations (noise, colour ops, channel shifts).
    Falls back to CPU silently if GPU ops fail.
    """
    s   = {**_DEFAULTS, **settings}
    h, w = frame.shape[:2]

    if use_gpu:
        try:
            return _apply_vhs_gpu(frame, maps, s, h, w)
        except Exception:
            pass   # silent CPU fallback

    out = frame.astype(np.float32)
    h, w = frame.shape[:2]

    # ── Brightness flicker ──────────────────────────────────
    if s["flicker"]:
        out *= 1.0 + random.uniform(-s["flicker_range"], s["flicker_range"])

    # ── Chroma bleed ────────────────────────────────────────
    if s["chroma_bleed"]:
        shift = max(1, int(round(s["bleed_shift"])))   # clamp to min 1 to avoid empty slice
        if shift < out.shape[1]:
            out[:, shift:,  0] = out[:, :-shift, 0]
            out[:, :-shift, 2] = out[:, shift:,  2]

    # ── Luminance noise ─────────────────────────────────────
    if s["noise"]:
        sigma = 3.0 + s["noise_level"] * 19.0
        noise = np.random.normal(0, sigma, out.shape).astype(np.float32)
        out  += noise

    # ── Hue drift + desaturation ────────────────────────────
    if s["hue_drift"]:
        u8  = np.clip(out, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(u8, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 0]  = (hsv[:, :, 0] + random.uniform(-s["hue_drift_amt"], s["hue_drift_amt"])) % 180
        hsv[:, :, 1] *= random.uniform(1.0 - s["desat_amt"], 1.0)
        out = cv2.cvtColor(
            np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR
        ).astype(np.float32)

    # ── Scanlines (intensity adjustable) ────────────────────
    if s["scanlines"]:
        # scale the darkening factor: base map has 0.72 on even rows
        base_dark = 0.85
        target_dark = 1.0 - s["scanlines_str"] * (1.0 - base_dark)
        scan_map = maps.scanlines.copy()
        scan_map[::2] = target_dark
        out *= scan_map

    # ── Vignette (intensity adjustable) ─────────────────────
    if s["vignette"]:
        # maps.vignette is 1.0 - 0.55 * dist^2
        vig = 1.0 - s["vignette_str"] * (1.0 - maps.vignette)
        out *= vig

    # ── Tracking glitch bands ───────────────────────────────
    if s["glitch"]:
        t    = s["glitch_level"]
        prob = 0.005 + t * 0.045     # 0.5 % … 5 % per frame
        if random.random() < prob:
            n_lines = random.randint(1, max(2, int(t * 14)))
            y0      = random.randint(0, h - n_lines)
            gshift  = random.randint(int(-40 * t), int(40 * t))
            strip   = out[y0:y0 + n_lines].copy()
            out[y0:y0 + n_lines] = np.roll(strip, gshift, axis=1)

    # ── Tape tear ───────────────────────────────────────────
    if s["tape_tear"] and random.random() < s["tear_prob"]:
        jy      = random.randint(0, h - 1)
        out[jy] = np.clip(out[jy] * random.uniform(1.4, 2.2), 0, 255)

    return np.clip(out, 0, 255).astype(np.uint8)


# ──────────────────────────────────────────────────────────────
#  GPU-ACCELERATED VHS  (OpenCV OpenCL via cv2.UMat)
#
#  Works on any OpenCL-capable GPU:
#    NVIDIA (no CUDA build needed), AMD, Intel integrated/Arc
#  Uses the standard opencv-python pip package — no special build.
#
#  Strategy: wrap the frame in cv2.UMat once, run all cv2.*
#  operations through UMat (they execute on GPU via OpenCL
#  transparently), then get() once at the end.
#  Pure-numpy ops (noise, hue shift) drop to CPU briefly —
#  this is still a big win because resize + multiply are GPU.
# ──────────────────────────────────────────────────────────────

def _apply_vhs_gpu(frame: np.ndarray, maps: VHSMaps, s: dict,
                   h: int, w: int) -> np.ndarray:
    """
    OpenCL/UMat GPU path. cv2 operations on UMat objects run on the GPU.
    Falls back gracefully to CPU for ops that need numpy random values.
    """
    # Enable OpenCL for this call
    cv2.ocl.setUseOpenCL(True)

    # Upload frame to GPU as float32 UMat
    u_frame = cv2.UMat(frame.astype(np.float32))

    # ── Flicker — GPU scalar multiply ───────────────────────
    if s["flicker"]:
        factor = 1.0 + random.uniform(-s["flicker_range"], s["flicker_range"])
        u_frame = cv2.multiply(u_frame, factor)

    # ── Chroma bleed — CPU (indexed slice, no UMat equivalent) ─
    if s["chroma_bleed"]:
        shift = int(s["bleed_shift"])
        if shift > 0:
            cpu = cv2.UMat.get(u_frame)
            cpu[:, shift:,  0] = cpu[:, :-shift, 0]
            cpu[:, :-shift, 2] = cpu[:, shift:,  2]
            u_frame = cv2.UMat(cpu)

    # ── Noise — CPU (numpy random, re-upload) ───────────────
    if s["noise"]:
        sigma = 3.0 + s["noise_level"] * 19.0
        cpu   = cv2.UMat.get(u_frame)
        cpu  += np.random.normal(0, sigma, cpu.shape).astype(np.float32)
        u_frame = cv2.UMat(cpu)

    # ── Hue drift — GPU cvtColor then CPU hue shift ─────────
    if s["hue_drift"]:
        cpu = cv2.UMat.get(u_frame)
        u8  = np.clip(cpu, 0, 255).astype(np.uint8)
        # cvtColor on UMat runs on GPU
        u_hsv = cv2.cvtColor(cv2.UMat(u8), cv2.COLOR_BGR2HSV)
        hsv   = cv2.UMat.get(u_hsv).astype(np.float32)
        hsv[:, :, 0] = (hsv[:, :, 0] + random.uniform(
            -s["hue_drift_amt"], s["hue_drift_amt"])) % 180
        hsv[:, :, 1] *= random.uniform(1.0 - s["desat_amt"], 1.0)
        u_bgr   = cv2.cvtColor(cv2.UMat(np.clip(hsv, 0, 255).astype(np.uint8)),
                               cv2.COLOR_HSV2BGR)
        u_frame = cv2.UMat(cv2.UMat.get(u_bgr).astype(np.float32))

    # ── Scanlines — GPU multiply ─────────────────────────────
    if s["scanlines"]:
        base_dark   = 0.72
        target_dark = 1.0 - s["scanlines_str"] * (1.0 - base_dark)
        scan_map    = maps.scanlines.copy()
        scan_map[::2] = target_dark
        u_scan  = cv2.UMat(scan_map)
        u_frame = cv2.multiply(u_frame, u_scan)

    # ── Vignette — GPU multiply ──────────────────────────────
    if s["vignette"]:
        vig_map = (1.0 - s["vignette_str"] * (1.0 - maps.vignette)).astype(np.float32)
        u_vig   = cv2.UMat(vig_map)
        u_frame = cv2.multiply(u_frame, u_vig)

    # ── Glitch + tape tear — CPU ─────────────────────────────
    if s["glitch"] or s["tape_tear"]:
        cpu = cv2.UMat.get(u_frame)
        if s["glitch"]:
            t    = s["glitch_level"]
            prob = 0.005 + t * 0.045
            if random.random() < prob:
                n_lines = random.randint(1, max(2, int(t * 14)))
                y0      = random.randint(0, h - n_lines)
                gshift  = random.randint(int(-40 * t), int(40 * t))
                cpu[y0:y0+n_lines] = np.roll(cpu[y0:y0+n_lines], gshift, axis=1)
        if s["tape_tear"] and random.random() < s["tear_prob"]:
            jy      = random.randint(0, h - 1)
            cpu[jy] = np.clip(cpu[jy] * random.uniform(1.4, 2.2), 0, 255)
        u_frame = cv2.UMat(cpu)

    # Download from GPU + clip
    result = cv2.UMat.get(u_frame)
    return np.clip(result, 0, 255).astype(np.uint8)
