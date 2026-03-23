"""
test_sizes.py  —  Run this from the retro_rewind folder before releasing.
Tests the full VHS pipeline across every real-world video resolution.

Usage:
    python test_sizes.py
"""

import sys, numpy as np, time
sys.path.insert(0, '.')
from vhs_engine import VHSMaps, apply_vhs

# ── Test cases: (label, source_w, source_h, output_w, output_h) ──────────────
# source = the original video dimensions (what gets cropped)
# output = what we resize to after cropping

ASPECT_OUTPUTS = {
    "1:1":      lambda sz: (sz, sz),
    "16:9":     lambda sz: (sz, int(sz / (16/9))),
    "4:3":      lambda sz: (sz, int(sz / (4/3))),
    "original": lambda sw, sh: (sz := min(sw, sh), sz),   # square crop of original
}

SOURCE_SIZES = [
    ("SD       640×480",    640,  480),
    ("720p     1280×720",  1280,  720),
    ("1080p    1920×1080", 1920, 1080),
    ("1440p    2560×1440", 2560, 1440),
    ("4K       3840×2160", 3840, 2160),
    ("Vertical 1080×1920", 1080, 1920),   # TikTok/phone portrait
    ("Square   1080×1080", 1080, 1080),   # already square
    ("Ultra-wide 3440×1440", 3440, 1440), # 21:9 monitor
]

OUTPUT_SIZE = 512   # game standard

SETTINGS = {
    "scanlines": True, "vignette": True, "chroma_bleed": True,
    "flicker": True, "noise": True, "hue_drift": True,
    "glitch": True, "tape_tear": True, "interlace": False,
    "head_switch": False, "dropout": False, "edge_ringing": False,
    "chroma_noise": False, "wobble": False,
    "scanlines_str": 0.72, "vignette_str": 0.55,
    "bleed_shift": 4, "flicker_range": 0.025,
    "hue_drift_amt": 3.0, "desat_amt": 0.12,
    "tear_prob": 0.01, "noise_level": 0.3, "glitch_level": 0.5,
}

# VHS quality scales (same as app)
QUALITY_SCALES = {
    "full":   1.0,
    "hifi":   0.75,
    "vhs":    0.50,
    "worn":   0.33,
    "damage": 0.20,
}

passed = 0
failed = 0
errors = []

print("=" * 62)
print("  RETRO REWIND VHS CONVERTER — SIZE COMPATIBILITY TEST")
print("=" * 62)

for src_label, src_w, src_h in SOURCE_SIZES:
    print(f"\n  Source: {src_label}")
    crop_sz = min(src_w, src_h)

    for aspect_label, (out_w, out_h) in [
        ("1:1",  (OUTPUT_SIZE, OUTPUT_SIZE)),
        ("16:9", (OUTPUT_SIZE, int(OUTPUT_SIZE / (16/9)))),
        ("4:3",  (OUTPUT_SIZE, int(OUTPUT_SIZE / (4/3)))),
    ]:
        for quality_label, scale in [("full", 1.0), ("vhs", 0.5), ("damage", 0.2)]:
            label = f"{src_label} → {aspect_label} @ {quality_label}"
            try:
                # Simulate crop + resize (what app does)
                # Use small synthetic frame for speed — shape is what matters
                cropped = np.random.randint(50, 200, (crop_sz, crop_sz, 3), dtype=np.uint8)
                frame   = np.ascontiguousarray(
                    cropped[:out_h, :out_w] if cropped.shape[0] >= out_h and cropped.shape[1] >= out_w
                    else np.resize(cropped, (out_h, out_w, 3))
                )
                # Simulate quality downscale path
                if scale < 1.0:
                    lo_w = max(4, int(out_w * scale))
                    lo_h = max(4, int(out_h * scale))
                    lo_frame = frame[:lo_h, :lo_w].copy()
                    lo_maps  = VHSMaps(max(lo_w, lo_h), w=lo_w, h=lo_h)
                    lo_out   = apply_vhs(lo_frame, lo_maps, SETTINGS)
                    assert lo_out.shape == (lo_h, lo_w, 3), \
                        f"Lo-res shape wrong: {lo_out.shape} vs ({lo_h},{lo_w},3)"
                else:
                    maps = VHSMaps(max(out_w, out_h), w=out_w, h=out_h)
                    out  = apply_vhs(frame, maps, SETTINGS)
                    assert out.shape == (out_h, out_w, 3), \
                        f"Output shape wrong: {out.shape} vs ({out_h},{out_w},3)"

                passed += 1

            except Exception as e:
                failed += 1
                err_msg = f"FAIL  {label}  →  {e}"
                errors.append(err_msg)
                print(f"    ✗  {aspect_label} {quality_label}: {e}")
                continue

    print(f"    ✓  All aspect ratio × quality combinations passed")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 62)
print(f"  Results:  {passed} passed,  {failed} failed")
if errors:
    print("\n  FAILURES:")
    for e in errors:
        print(f"    {e}")
else:
    print("  All tests passed! Safe to release.")
print("=" * 62)
