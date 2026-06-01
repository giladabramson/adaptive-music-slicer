"""Build the landing-page audio assets from songs/.

For every song directory under ``../songs/`` that has the four stems
(drums/bass/other/vocals) plus ``config.json``, this script:

1. Transcodes each ``<stem>.wav`` to a smaller-bandwidth ``<stem>.mp3``
   (default 128 kbps stereo — transparent enough for melody/drum loops
   and ~10× smaller than WAV).
2. Copies the existing ``config.json`` next to the MP3s, rewriting each
   layer's ``file`` to point at the .mp3.
3. Writes a top-level ``landing/songs/manifest.json`` so the page JS
   can enumerate songs without needing a directory listing
   (browsers can't read filesystem directories).

Run from the repo root with the project venv active::

    python landing/build_assets.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from pydub import AudioSegment

ROOT = Path(__file__).resolve().parents[1]
SONGS_SRC = ROOT / "songs"
SONGS_DST = ROOT / "landing" / "songs"
MANIFEST_PATH = SONGS_DST / "manifest.json"

STEM_NAMES = ("drums", "bass", "other", "vocals")
MP3_BITRATE = "128k"

# Featured first so the page autoloads it. Anything not listed is
# appended alphabetically.
FEATURED_ORDER = (
    "ominous_test_lyria",
    "synthwave",
    "reggae",
    "vocals",
    "poprock",
    "house",
    "hiphop",
    "game",
    "ominous_test",
)


def _discover_songs() -> list[Path]:
    found: list[Path] = []
    if not SONGS_SRC.is_dir():
        sys.exit(f"No songs/ at {SONGS_SRC}")
    for sub in sorted(SONGS_SRC.iterdir()):
        if not sub.is_dir():
            continue
        if not (sub / "config.json").is_file():
            continue
        if not all((sub / f"{s}.wav").is_file() for s in STEM_NAMES):
            continue
        found.append(sub)
    return found


def _transcode(src: Path, dst: Path) -> None:
    if dst.is_file() and dst.stat().st_mtime > src.stat().st_mtime:
        return
    audio = AudioSegment.from_wav(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio.export(dst, format="mp3", bitrate=MP3_BITRATE)


def _build_one(song_dir: Path) -> dict:
    name = song_dir.name
    out = SONGS_DST / name
    out.mkdir(parents=True, exist_ok=True)

    for stem in STEM_NAMES:
        _transcode(song_dir / f"{stem}.wav", out / f"{stem}.mp3")

    cfg = json.loads((song_dir / "config.json").read_text(encoding="utf-8"))
    for layer in cfg.get("layers", []):
        if layer.get("file", "").endswith(".wav"):
            layer["file"] = layer["file"].replace(".wav", ".mp3")
    (out / "config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )

    sizes = {
        stem: (out / f"{stem}.mp3").stat().st_size for stem in STEM_NAMES
    }
    print(
        f"  {name:24} "
        + ", ".join(f"{s}={sizes[s]//1024}KB" for s in STEM_NAMES)
    )
    return {
        "name": name,
        "track_name": cfg.get("track_name", name),
        "bpm": cfg.get("detected_bpm", 0.0),
        "loop_duration_ms": cfg.get("loop_duration_ms", 0),
        "bars": cfg.get("bars", 0),
        "stems": [f"{s}.mp3" for s in STEM_NAMES],
        "total_bytes": sum(sizes.values()),
    }


def _sort_key(name: str) -> tuple[int, str]:
    try:
        return (FEATURED_ORDER.index(name), name)
    except ValueError:
        return (len(FEATURED_ORDER), name)


def main() -> int:
    SONGS_DST.mkdir(parents=True, exist_ok=True)
    songs = _discover_songs()
    if not songs:
        sys.exit("No complete songs found under songs/.")
    print(f"Building {len(songs)} song(s) for the landing page:")

    entries = [_build_one(s) for s in songs]
    entries.sort(key=lambda e: _sort_key(e["name"]))

    manifest = {
        "version": 1,
        "featured": entries[0]["name"] if entries else None,
        "songs": entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    total_mb = sum(e["total_bytes"] for e in entries) / 1024 / 1024
    print(f"\nWrote {MANIFEST_PATH.relative_to(ROOT)}  "
          f"({len(entries)} songs, {total_mb:.1f} MB total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
