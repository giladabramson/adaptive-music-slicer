"""Trace the brand PNGs into SVGs using vtracer.

The PNGs are bounded by the ChatGPT-generated source sheet's resolution.
Tracing them once into SVG lets the browser render the logo at any size,
on any DPI display, without pixelation.

Run after any logo PNG regeneration::

    python landing/scripts/trace_logo.py
"""
from __future__ import annotations

from pathlib import Path
import vtracer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# (input_png, output_svg, kwargs)
JOBS = [
    # Color tracing — preserves the blue waveform + dark/white wordmark.
    (
        ASSETS / "brand-horizontal-large.png",
        ASSETS / "brand-horizontal.svg",
        dict(
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=7,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            splice_threshold=45,
            path_precision=5,
        ),
    ),
    # Icon-only (no wordmark) for spots where the text would be too tiny.
    (
        ASSETS / "brand-icon.png",
        ASSETS / "brand-icon.svg",
        dict(
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=7,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            splice_threshold=45,
            path_precision=5,
        ),
    ),
]


def main() -> int:
    for src, dst, opts in JOBS:
        if not src.is_file():
            print(f"  skip — missing {src.name}")
            continue
        print(f"  tracing {src.name} → {dst.name} …")
        vtracer.convert_image_to_svg_py(str(src), str(dst), **opts)
        size_kb = dst.stat().st_size / 1024
        print(f"    wrote {dst.relative_to(ROOT.parent)} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
