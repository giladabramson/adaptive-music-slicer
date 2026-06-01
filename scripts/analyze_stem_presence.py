"""Report which stems are actually present (musical) vs silent in each
sliced track under ``output/player_library/``.

A stem is "present" iff BOTH:
  * its RMS is above an absolute floor (``ABS_FLOOR_DBFS``), so it's not
    just digital silence / noise, AND
  * its RMS is within ``REL_GAP_DB`` of the loudest stem in the same
    track, so we ignore tiny bleed-through that's musically irrelevant.

The output is a Markdown-style table grouped by prompt, plus a
per-backend summary showing how often each backend produced each stem.

Run from the project root::

    C:\\dev\\.venv311\\Scripts\\python.exe scripts\\analyze_stem_presence.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "output" / "player_library"

STEMS = ("drums", "bass", "other", "vocals")

# A stem quieter than this absolute RMS is digital silence / noise floor.
ABS_FLOOR_DBFS = -45.0
# A stem more than this many dB below the loudest stem in the same track
# is bleed-through, not a musically intentional layer.
REL_GAP_DB = 25.0


def rms_dbfs(wav_path: Path) -> float:
    """Integrated RMS of a WAV/MP3 file in dBFS, mono-summed."""
    audio, _ = sf.read(str(wav_path), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)  # downmix
    rms = float(np.sqrt(np.mean(audio * audio)))
    return 20.0 * math.log10(rms) if rms > 0 else -math.inf


def main() -> int:
    if not LIBRARY.exists():
        print(f"Library not found: {LIBRARY}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for track_dir in sorted(LIBRARY.iterdir()):
        if not track_dir.is_dir():
            continue
        cfg = track_dir / "config.json"
        if not cfg.exists():
            continue

        # Measure each stem.
        measurements: dict[str, float] = {}
        for stem in STEMS:
            stem_path = track_dir / f"{stem}.wav"
            measurements[stem] = (
                rms_dbfs(stem_path) if stem_path.exists() else -math.inf
            )

        loudest = max(measurements.values())
        present: dict[str, bool] = {}
        for stem, db in measurements.items():
            is_present = (
                db >= ABS_FLOOR_DBFS and (loudest - db) <= REL_GAP_DB
            )
            present[stem] = is_present

        # Split track folder name back into (prompt, backend) for grouping.
        name = track_dir.name
        if "__" in name:
            prompt, backend = name.split("__", 1)
        else:
            prompt, backend = name, "?"

        rows.append({
            "prompt": prompt,
            "backend": backend,
            "loudness": measurements,
            "present": present,
        })

    if not rows:
        print(f"No tracks found under {LIBRARY}.", file=sys.stderr)
        return 1

    # --- Per-track table, grouped by prompt -------------------------------
    print(f"# Stem presence — {len(rows)} tracks under "
          f"{LIBRARY.relative_to(ROOT)}\n")
    print(f"Threshold: a stem counts as PRESENT if RMS >= "
          f"{ABS_FLOOR_DBFS:.0f} dBFS *and* within {REL_GAP_DB:.0f} dB "
          "of the loudest stem in that track.\n")
    header = (
        f"{'track':40s}  "
        f"{'drums':>13s}  {'bass':>13s}  {'other':>13s}  {'vocals':>13s}"
    )
    print(header)
    print("-" * len(header))

    last_prompt: str | None = None
    for r in rows:
        if r["prompt"] != last_prompt:
            if last_prompt is not None:
                print()
            last_prompt = r["prompt"]
        cells = []
        for stem in STEMS:
            db = r["loudness"][stem]
            mark = "OK " if r["present"][stem] else "-- "
            db_str = f"{db:6.1f}dB" if math.isfinite(db) else "  -inf "
            cells.append(f"{mark}{db_str}")
        track = f"{r['prompt']}__{r['backend']}"
        print(f"{track:40s}  " + "  ".join(f"{c:>13s}" for c in cells))

    # --- Per-backend summary ---------------------------------------------
    backends = sorted({r["backend"] for r in rows})
    print(f"\n\n# Backend coverage (how many of N prompts produced each "
          "stem)\n")
    summary_header = (
        f"{'backend':16s}  "
        + "  ".join(f"{s:>10s}" for s in STEMS)
    )
    print(summary_header)
    print("-" * len(summary_header))
    for backend in backends:
        b_rows = [r for r in rows if r["backend"] == backend]
        n = len(b_rows)
        cells = []
        for stem in STEMS:
            ok = sum(1 for r in b_rows if r["present"][stem])
            cells.append(f"{ok}/{n}")
        print(f"{backend:16s}  " + "  ".join(f"{c:>10s}" for c in cells))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
