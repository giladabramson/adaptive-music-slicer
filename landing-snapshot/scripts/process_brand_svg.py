"""Process the Recraft-generated SVG into three standalone brand SVGs.

The Recraft sheet stacks three logo variants vertically on the same
canvas:

  • top band      → icon-only mark (large)
  • middle band   → horizontal lockup (icon + StemForge wordmark)
  • bottom band   → favicon

We:
  1. Strip the full-canvas background path
  2. Group every remaining path by Y-band (gap analysis)
  3. Emit one tight SVG per band, with its own viewBox flush to content

Output:
  landing/assets/brand-icon.svg          — top band
  landing/assets/brand-horizontal.svg    — middle band (the main one)
  landing/assets/brand-favicon.svg       — bottom band
"""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "modern-ai-native-logo-for--stemforge---an-adaptive.svg"
ASSETS = ROOT / "landing" / "assets"


def _path_bbox(d_attr: str) -> tuple[float, float, float, float] | None:
    nums = [float(n) for n in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", d_attr)]
    if len(nums) < 2:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _path_mid_y(d_attr: str) -> float | None:
    bbox = _path_bbox(d_attr)
    if bbox is None:
        return None
    return (bbox[1] + bbox[3]) / 2


def main() -> int:
    if not SRC.is_file():
        print(f"ERROR: {SRC} not found.")
        return 1

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    tree = ET.parse(SRC)
    root = tree.getroot()
    ns = "{http://www.w3.org/2000/svg}"

    width = float(root.get("width", 1024))
    height = float(root.get("height", 1024))

    # 1. Strip the canvas-bg path(s)
    all_paths = list(root.findall(f"{ns}path"))
    paths: list[ET.Element] = []
    for p in all_paths:
        bbox = _path_bbox(p.get("d", ""))
        if bbox is None:
            continue
        if (bbox[2] - bbox[0]) >= width * 0.95 and (bbox[3] - bbox[1]) >= height * 0.95:
            continue  # full-canvas bg
        paths.append(p)

    # 2. Group by Y-bands. Sort by mid-Y, then walk the gap distribution
    # to find natural cluster boundaries.
    paths.sort(key=lambda p: _path_mid_y(p.get("d", "")) or 0)
    mid_ys = [_path_mid_y(p.get("d", "")) or 0 for p in paths]

    # A "band break" is a gap between consecutive mid-Y values that is
    # at least 5% of the canvas height. Tuned: the variants are at
    # y≈190, y≈530, y≈880 — gaps of 300+ between them, vs ~10-50 within
    # a band.
    gap_threshold = height * 0.05
    bands: list[list[ET.Element]] = [[]]
    for i, p in enumerate(paths):
        if i > 0 and (mid_ys[i] - mid_ys[i - 1]) > gap_threshold:
            bands.append([])
        bands[-1].append(p)

    print(f"  detected {len(bands)} band(s)")

    # Determine which band is which: top = icon, middle = horizontal,
    # bottom = favicon. We assume the user generated a sheet with all
    # three. If only one band, that's the horizontal lockup.
    band_names = {
        1: ["brand-horizontal.svg"],
        2: ["brand-icon.svg", "brand-horizontal.svg"],
        3: ["brand-icon.svg", "brand-horizontal.svg", "brand-favicon.svg"],
    }
    names = band_names.get(len(bands), [f"brand-band-{i+1}.svg" for i in range(len(bands))])

    # 2.5 Within each band, fold dark "cutout" paths into their parent
    # letter shapes as evenodd subpaths. The Recraft export draws each
    # letter as a light outer path with a dark inner path layered on top
    # to fake a transparent hole — that works when the SVG sits on the
    # exact original canvas color but creates visible dark blobs on any
    # other background.
    def _is_cutout(p: ET.Element) -> bool:
        fill = (p.get("fill") or "").lower()
        return fill in ("#0a0511", "#030209")

    def _contains(outer: tuple, inner: tuple) -> bool:
        return (outer[0] <= inner[0] and outer[1] <= inner[1] and
                outer[2] >= inner[2] and outer[3] >= inner[3])

    for band in bands:
        outers = [p for p in band if not _is_cutout(p)]
        cutouts = [p for p in band if _is_cutout(p)]
        merged_count = 0
        for cut in cutouts:
            cb = _path_bbox(cut.get("d", ""))
            if cb is None:
                continue
            # Smallest outer whose bbox contains this cutout's bbox.
            best, best_area = None, float("inf")
            for o in outers:
                ob = _path_bbox(o.get("d", ""))
                if ob is None or not _contains(ob, cb):
                    continue
                area = (ob[2] - ob[0]) * (ob[3] - ob[1])
                if area < best_area:
                    best, best_area = o, area
            if best is not None:
                best.set("d", best.get("d", "") + " " + cut.get("d", ""))
                best.set("fill-rule", "evenodd")
                band.remove(cut)
                merged_count += 1
        if merged_count:
            print(f"    folded {merged_count} cutout(s) into letter subpaths")

    # 3. Emit one SVG per band
    for i, band in enumerate(bands):
        # Compute tight bbox for this band's paths
        minx = miny = float("inf")
        maxx = maxy = float("-inf")
        for p in band:
            bbox = _path_bbox(p.get("d", ""))
            if bbox is None:
                continue
            minx = min(minx, bbox[0])
            miny = min(miny, bbox[1])
            maxx = max(maxx, bbox[2])
            maxy = max(maxy, bbox[3])
        pad = 4
        minx, miny = max(0, minx - pad), max(0, miny - pad)
        maxx, maxy = maxx + pad, maxy + pad
        w, h = maxx - minx, maxy - miny

        # ET adds xmlns automatically from the registered namespace —
        # we must NOT also pass xmlns as an attribute, or we'd get a
        # duplicate-attribute XML error that browsers refuse to render.
        new_root = ET.Element(
            f"{ns}svg",
            {
                "viewBox": f"{minx:.2f} {miny:.2f} {w:.2f} {h:.2f}",
                "fill": "none",
            },
        )
        for defs in root.findall(f"{ns}defs"):
            new_root.append(defs)
        for p in band:
            new_root.append(p)

        out = ASSETS / names[i]
        ASSETS.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(new_root).write(out, encoding="utf-8", xml_declaration=True)
        size_kb = out.stat().st_size / 1024
        print(f"  band {i+1}: {len(band):2d} paths · {w:.0f}x{h:.0f} · "
              f"{size_kb:.1f} KB → {out.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
