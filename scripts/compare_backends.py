"""Compare every generation backend against every test prompt.

Generates the source audio only (no Demucs / loop slicing), so the run
is fast and cheap. Outputs go to ``output/comparison/<backend>/<slug>.<ext>``
and a CSV summary at ``output/comparison/_results.csv``.

Run from the project root:

    C:\\dev\\.venv311\\Scripts\\python.exe scripts\\compare_backends.py

API keys are resolved by generation.py itself (env var or keyring),
so set them once with::

    python -c "import keyring; keyring.set_password('adaptive-music-slicer','REPLICATE_API_TOKEN','...')"
    python -c "import keyring; keyring.set_password('adaptive-music-slicer','FAL_KEY','...')"

(``GOOGLE_API_KEY`` for Lyria is read from env or keyring the same way.)
"""

from __future__ import annotations

import csv
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adaptive_music_engine.generation import (
    BACKEND_SUFFIX,
    generate_track,
)
from adaptive_music_engine.errors import TrackGenerationError


# Raw prompts. The stem-friendly suffix gets appended by generate_track()
# automatically — we keep these short and intent-focused.
PROMPTS: list[tuple[str, str]] = [
    (
        "rpg_loop",
        "warm fantasy folk, gentle acoustic fingerpicked guitar, "
        "soft pad strings, melancholic but hopeful, 90 bpm",
    ),
    (
        "youtube_intro",
        "upbeat modern indie pop, bright synth lead, energetic and "
        "friendly, 110 bpm",
    ),
    (
        "funk_soul",
        "funky 90s soul groove, wah guitar riffs, smooth rhodes "
        "electric piano, 95 bpm",
    ),
    (
        "deep_house",
        "driving deep house, hypnotic synth arpeggio, sustained "
        "energy, 124 bpm",
    ),
    (
        "boss_battle",
        "epic hybrid orchestral-electronic, soaring brass with "
        "saw-wave lead, dark cinematic, building tension, 140 bpm",
    ),
]

# Beatoven is excluded today (fal-side queue stuck on the model).
BACKENDS: list[str] = ["lyria", "stable-audio", "audioldm", "musicgen"]

# Per-backend duration request (Lyria ignores it).
DURATION_S = 15.0

# Defensive sleep between Replicate calls. Replicate throttles accounts
# to 6 req/min (burst 1) while credit is under $5, and we've seen 429s
# in practice. 12s spacing keeps us safely under the threshold even at
# the throttled rate.
REPLICATE_SLEEP_S = 12.0
_REPLICATE_BACKENDS = {"stable-audio", "audioldm"}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(message)s", stream=sys.stderr
    )
    logging.getLogger("adaptive_music_engine").setLevel(logging.INFO)

    out_root = ROOT / "output" / "comparison"
    out_root.mkdir(parents=True, exist_ok=True)
    results_csv = out_root / "_results.csv"

    rows: list[dict[str, str]] = []
    total = len(PROMPTS) * len(BACKENDS)
    n = 0

    for backend in BACKENDS:
        backend_dir = out_root / backend
        backend_dir.mkdir(parents=True, exist_ok=True)
        suffix = BACKEND_SUFFIX[backend]

        for slug, prompt in PROMPTS:
            n += 1
            out_path = backend_dir / f"{slug}{suffix}"

            # Idempotent: skip cells we already have. Lets the script
            # double as "fill in the missing cells" after a partial run.
            if out_path.exists() and out_path.stat().st_size > 0:
                print(
                    f"\n[{n}/{total}] {backend} <- {slug} "
                    f"SKIP (already have {out_path.stat().st_size} bytes)",
                    file=sys.stderr,
                )
                rows.append({
                    "backend": backend,
                    "prompt_slug": slug,
                    "ok": "1",
                    "elapsed_s": "0.0",
                    "bytes": str(out_path.stat().st_size),
                    "path": str(out_path.relative_to(ROOT)),
                    "error": "(skipped — pre-existing output)",
                })
                continue

            # Defensive throttle for Replicate-hosted backends.
            if backend in _REPLICATE_BACKENDS:
                print(
                    f"  (sleeping {REPLICATE_SLEEP_S:.0f}s to respect "
                    "Replicate's 6 req/min throttle)",
                    file=sys.stderr,
                )
                time.sleep(REPLICATE_SLEEP_S)

            print(
                f"\n[{n}/{total}] {backend} <- {slug} "
                f"(out: {out_path.relative_to(ROOT)})",
                file=sys.stderr,
            )

            t0 = time.time()
            err = ""
            size_b = 0
            ok = False
            try:
                generate_track(
                    prompt,
                    out_path,
                    backend=backend,
                    duration_s=DURATION_S,
                )
                size_b = out_path.stat().st_size
                ok = True
            except TrackGenerationError as e:
                err = f"{type(e).__name__}: {e}"
                print(f"  FAILED: {err[:200]}", file=sys.stderr)
            except Exception as e:  # unexpected
                err = f"UNEXPECTED {type(e).__name__}: {e}"
                print(f"  FAILED: {err[:200]}", file=sys.stderr)

            elapsed = time.time() - t0
            rows.append({
                "backend": backend,
                "prompt_slug": slug,
                "ok": "1" if ok else "0",
                "elapsed_s": f"{elapsed:.1f}",
                "bytes": str(size_b),
                "path": str(out_path.relative_to(ROOT)) if ok else "",
                "error": err,
            })

    with results_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "backend", "prompt_slug", "ok", "elapsed_s",
                "bytes", "path", "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n=== Summary (results CSV: {results_csv}) ===")
    by_backend: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_backend.setdefault(r["backend"], []).append(r)
    for backend, br in by_backend.items():
        ok_n = sum(int(r["ok"]) for r in br)
        avg_t = sum(float(r["elapsed_s"]) for r in br) / max(1, len(br))
        total_b = sum(int(r["bytes"]) for r in br)
        print(
            f"  {backend:14s}  {ok_n}/{len(br)} ok   "
            f"avg {avg_t:5.1f}s   total {total_b/1024:7.0f} KB"
        )

    failed = [r for r in rows if r["ok"] == "0"]
    if failed:
        print(f"\n{len(failed)} failures (see CSV for details):")
        for r in failed:
            print(
                f"  - {r['backend']}/{r['prompt_slug']}: {r['error'][:160]}"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
