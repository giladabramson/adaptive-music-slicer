"""Run the full pipeline (Demucs + slicing) on every generated track
so the adaptive player can browse and A/B them.

Inputs: ``output/comparison/<backend>/<slug>.<ext>``
Outputs: ``output/player_library/<slug>__<backend>/``
          (drums.wav, bass.wav, other.wav, vocals.wav, config.json)

Folder naming is ``<slug>__<backend>`` so the player's alphabetical
dropdown groups all four backends for the same prompt next to each
other — perfect for back-to-back A/B/C/D listening.

Run from the project root::

    C:\\dev\\.venv311\\Scripts\\python.exe scripts\\process_for_player.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adaptive_music_engine.pipeline import run_pipeline
from adaptive_music_engine.errors import AdaptiveMusicEngineError


# 15-second source clips are too short for the CLI's default 16 bars at
# typical BPMs. bars=4 fits comfortably across 90-140 BPM in 15s:
#   90 BPM: 4 × 4 × (60/90) = 10.7 s
#   140 BPM: 4 × 4 × (60/140) = 6.9 s
BARS = 4


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING, format="%(message)s", stream=sys.stderr
    )
    logging.getLogger("adaptive_music_engine").setLevel(logging.INFO)

    comp_root = ROOT / "output" / "comparison"
    out_root = ROOT / "output" / "player_library"
    out_root.mkdir(parents=True, exist_ok=True)

    # Discover everything in output/comparison/<backend>/<slug>.<ext>
    inputs: list[tuple[str, str, Path]] = []
    for backend_dir in sorted(comp_root.iterdir()):
        if not backend_dir.is_dir():
            continue
        for audio in sorted(backend_dir.iterdir()):
            if audio.suffix.lower() not in {".wav", ".mp3", ".flac"}:
                continue
            slug = audio.stem
            inputs.append((slug, backend_dir.name, audio))

    if not inputs:
        print("No inputs found under output/comparison/.", file=sys.stderr)
        return 1

    total = len(inputs)
    print(f"Processing {total} tracks (Demucs CPU pass, ~30-60 s each)…",
          file=sys.stderr)

    results: list[tuple[str, bool, float, str]] = []
    for i, (slug, backend, audio) in enumerate(inputs, 1):
        # <slug>__<backend> so player groups by prompt
        out_dir = out_root / f"{slug}__{backend}"
        # Skip if already done (idempotent)
        if (out_dir / "config.json").exists():
            print(f"[{i}/{total}] SKIP {slug}__{backend} (already processed)",
                  file=sys.stderr)
            results.append((f"{slug}__{backend}", True, 0.0, "skipped"))
            continue

        print(f"\n[{i}/{total}] {slug}__{backend} <- {audio.name}",
              file=sys.stderr)
        t0 = time.time()
        try:
            run_pipeline(
                input_path=audio,
                output_dir=out_dir,
                bars=BARS,
                export_format="wav",
                analysis_source="mix",
            )
            results.append((f"{slug}__{backend}", True, time.time() - t0, ""))
        except AdaptiveMusicEngineError as e:
            err = f"{type(e).__name__}: {e}"
            print(f"  FAILED: {err[:200]}", file=sys.stderr)
            results.append(
                (f"{slug}__{backend}", False, time.time() - t0, err)
            )
        except Exception as e:
            err = f"UNEXPECTED {type(e).__name__}: {e}"
            print(f"  FAILED: {err[:200]}", file=sys.stderr)
            results.append(
                (f"{slug}__{backend}", False, time.time() - t0, err)
            )

    ok = sum(1 for _, o, *_ in results if o)
    fail = total - ok
    avg = (
        sum(t for _, o, t, _ in results if o and t > 0)
        / max(1, sum(1 for _, o, t, _ in results if o and t > 0))
    )
    print(f"\n=== Done: {ok}/{total} ok, {fail} failed, avg "
          f"{avg:.1f}s/track ===", file=sys.stderr)
    print(f"Player library: {out_root}", file=sys.stderr)
    print(f"\nLaunch the player on this library:", file=sys.stderr)
    print(f"  C:\\dev\\.venv311\\Scripts\\python.exe "
          f"adaptive_player.py --library "
          f"{out_root.relative_to(ROOT)}", file=sys.stderr)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
