"""Crop the StemForge logo sheet into individual brand assets.

The current source sheet is 1705x923 with variants arranged as:
  Top-left:       large horizontal logo (no label)
  Top-right:      COMPACT horizontal (small, labelled)
  Middle-right:   ICON ONLY (labelled)
  Bottom row:     SQUARE / CIRCLE / ICON MARK / WORDMARK / FAVICON (all labelled)

The whole sheet is on a dark navy background so the brand reads on a
dark-theme landing page natively — we just need to:
  1. Crop with a top-margin to skip the variant's text label
  2. Trim tight to actual artwork (drop the surrounding navy)
  3. Make the dark navy background transparent (so brand floats on whatever
     page bg sits behind it)
  4. Save as PNG to landing/assets/.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image
import numpy as np

SRC = Path(r"C:\adaptive-music-slicer\ChatGPT Image Jun 1, 2026, 06_18_30 PM.png")
DEST = Path(__file__).resolve().parents[1] / "assets"
DEST.mkdir(parents=True, exist_ok=True)


def trim_to_content(img: Image.Image, bg_thresh: int = 50, pad: int = 8) -> Image.Image:
    """Trim away the dark background, keeping just the artwork."""
    arr = np.array(img.convert("RGB"))
    # A pixel counts as "content" if any channel is meaningfully brighter
    # than the dark navy bg.
    mask = arr.max(axis=-1) > bg_thresh
    if not mask.any():
        return img
    ys, xs = np.where(mask)
    y0, y1 = max(0, ys.min() - pad), min(arr.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(arr.shape[1], xs.max() + pad)
    return img.crop((x0, y0, x1, y1))


def make_dark_bg_transparent(img: Image.Image, dark_threshold: int = 45) -> Image.Image:
    """Drop the dark navy background to alpha 0; keep brand pixels.

    Brand whites and electric-blues are far above the threshold across
    all three channels, so they're safe. Brand outlines and shadows are
    not pure black in this sheet either, so they also survive.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    is_dark = (r < dark_threshold) & (g < dark_threshold) & (b < dark_threshold)
    arr[..., 3][is_dark] = 0
    return Image.fromarray(arr, mode="RGBA")


def crop(img: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    return img.crop(box)


def save(img: Image.Image, name: str) -> None:
    out = DEST / name
    img.save(out, "PNG")
    print(f"  wrote {out.relative_to(DEST.parent.parent)} {img.size}")


def main() -> None:
    sheet = Image.open(SRC).convert("RGB")
    W, H = sheet.size
    print(f"source: {W}x{H}")

    # Y values measured via brightness profile so each box sits strictly
    # between the variant's label and the next variant's label. X values
    # are deliberately generous; trim_to_content tightens them.
    boxes = {
        # Top half — labels at y=80 (COMPACT) and y=340 (ICON ONLY)
        "horizontal_large":   (0,    190, 1040, 345),  # no label, big top-left
        "horizontal_compact": (1050, 130, 1700, 250),  # COMPACT content
        "icon_only":          (1050, 380, 1700, 500),  # ICON ONLY content
        # Bottom row — labels at y=630, content at y=700-815
        "square_app":         (0,    700,  350, 830),
        "circle_app":         (340,  700,  700, 830),
        "icon_mark":          (680,  700, 1040, 830),
        "wordmark":           (1020, 700, 1400, 830),
        "favicon_src":        (1380, 700, 1705, 830),
    }

    # Horizontal — for sticky bar + footer.
    hor = make_dark_bg_transparent(trim_to_content(crop(sheet, boxes["horizontal_compact"]), pad=10))
    save(hor, "brand-horizontal.png")

    # Larger horizontal — used by footer if a heavier mark is wanted.
    hor_lg = make_dark_bg_transparent(trim_to_content(crop(sheet, boxes["horizontal_large"]), pad=12))
    save(hor_lg, "brand-horizontal-large.png")

    # Icon mark — for hero or any small standalone-icon spot.
    icon = make_dark_bg_transparent(trim_to_content(crop(sheet, boxes["icon_mark"]), pad=10))
    save(icon, "brand-icon.png")

    # Wordmark — pure type, for places where the icon would be redundant.
    word = make_dark_bg_transparent(trim_to_content(crop(sheet, boxes["wordmark"]), pad=8))
    save(word, "brand-wordmark.png")

    # Favicon — keep transparent bg; scale to two common sizes.
    fav = make_dark_bg_transparent(trim_to_content(crop(sheet, boxes["favicon_src"]), pad=6))
    fav_96 = fav.resize((96, 96), Image.LANCZOS)
    save(fav_96, "favicon-96.png")
    fav_180 = fav.resize((180, 180), Image.LANCZOS)
    save(fav_180, "apple-touch-icon.png")

    # Square OG image — keep the original blue/circle background and the
    # full square aspect ratio. Used as the og:image and twitter:image,
    # where a transparent PNG would render badly against unknown bg.
    sq = crop(sheet, boxes["square_app"]).resize((512, 512), Image.LANCZOS)
    save(sq, "brand-square.png")

    print("done.")


if __name__ == "__main__":
    main()
