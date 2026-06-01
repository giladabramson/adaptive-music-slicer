"""Generate a naive-prompt bass line via Lyria — the "what you'd get
without isolation prompting" comparison audio for Use case 03.

One Lyria call. No Demucs, no slicing. The result is what someone gets
when they ask Lyria for "bass" without the solo/dry/recording trick.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the adaptive_music_engine package importable when run from anywhere.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adaptive_music_engine.generation import generate_track  # noqa: E402

OUT = ROOT / "output" / "naive_bass__lyria"
OUT.mkdir(parents=True, exist_ok=True)
out_path = OUT / "generated_input.mp3"

PROMPT = "bass line, 130 BPM, E minor, electric bass"


def main() -> int:
    print(f"Naive bass prompt → Lyria")
    print(f"  prompt: {PROMPT!r}")
    print(f"  output: {out_path}")
    generate_track(prompt=PROMPT, out_path=out_path, backend="lyria")
    size = out_path.stat().st_size
    print(f"  wrote {size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
