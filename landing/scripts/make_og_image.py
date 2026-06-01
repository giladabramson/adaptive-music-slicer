"""Compose a 1200x630 Open Graph / Twitter share image.

Social platforms render the og:image at this aspect ratio when a URL is
posted; using a square (512x512) made our previews look squashed and
text-light. This script lays the horizontal logo centered on a dark
gradient and stamps a tagline below it.

Run after any logo change::

    python landing/scripts/make_og_image.py
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "assets" / "brand-horizontal-large.png"
OUT = ROOT / "assets" / "og-image.png"

CANVAS_W, CANVAS_H = 1200, 630
TAGLINE = "AI music — with the stems you control"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",  # Segoe UI Bold
        "C:/Windows/Fonts/seguisb.ttf",   # Segoe UI Semibold
        "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _gradient_bg(w: int, h: int) -> Image.Image:
    """A subtle radial-feeling gradient on dark navy. Approximated with
    a vertical fade plus a top-right violet glow.
    """
    base = Image.new("RGB", (w, h), (7, 8, 15))  # var(--bg)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Violet glow in the upper-right corner
    cx, cy = int(w * 0.78), int(h * -0.08)
    for r in range(int(w * 0.55), 20, -16):
        alpha = int(34 * (1 - r / (w * 0.55)) ** 2)
        if alpha < 1:
            continue
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=(139, 92, 246, alpha))

    # Cyan glow in the lower-left
    cx, cy = int(w * -0.05), int(h * 1.05)
    for r in range(int(w * 0.45), 20, -14):
        alpha = int(22 * (1 - r / (w * 0.45)) ** 2)
        if alpha < 1:
            continue
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=(103, 232, 249, alpha))

    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def main() -> int:
    if not LOGO.is_file():
        print(f"ERROR: logo not found at {LOGO}")
        print("Run landing/scripts/crop_logo.py first.")
        return 1

    canvas = _gradient_bg(CANVAS_W, CANVAS_H)

    # Scale logo to ~55% of canvas width, preserve aspect ratio
    logo = Image.open(LOGO).convert("RGBA")
    target_w = int(CANVAS_W * 0.55)
    scale = target_w / logo.width
    target_h = int(logo.height * scale)
    logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

    # Compose: logo slightly above center, tagline beneath
    canvas_rgba = canvas.convert("RGBA")
    logo_x = (CANVAS_W - target_w) // 2
    logo_y = int(CANVAS_H * 0.34) - target_h // 2
    canvas_rgba.paste(logo_resized, (logo_x, logo_y), logo_resized)

    # Tagline
    draw = ImageDraw.Draw(canvas_rgba)
    font = _load_font(34)
    bbox = draw.textbbox((0, 0), TAGLINE, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = (CANVAS_W - text_w) // 2
    ty = logo_y + target_h + 36
    draw.text((tx, ty), TAGLINE, fill=(164, 173, 193), font=font)

    # Subtle bottom hairline
    draw.line([(CANVAS_W * 0.42, CANVAS_H - 60),
               (CANVAS_W * 0.58, CANVAS_H - 60)],
              fill=(167, 139, 250, 100), width=1)

    # Bottom small text (URL or sub-claim)
    sub_font = _load_font(20)
    sub_text = "Open source · MIT · runs locally"
    sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sx = (CANVAS_W - sub_w) // 2
    sy = CANVAS_H - 44
    draw.text((sx, sy), sub_text, fill=(94, 102, 120), font=sub_font)

    final = canvas_rgba.convert("RGB")
    final.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT.relative_to(ROOT.parent)} ({final.size[0]}x{final.size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
