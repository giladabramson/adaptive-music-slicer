"""Launch the adaptive player against the comparison output.

For every ``comparison/<song>/<variant>/`` directory that contains the four
stems, write a ``config.json`` and feed the player a flat list so you can
A/B Demucs vs Roformer-hybrid from the dropdown without restarting.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adaptive_player import PlayerGUI  # noqa: E402

COMPARISON_DIR = ROOT / "comparison"
SONGS_DIR = ROOT / "songs"

STEM_NAMES = ("drums", "bass", "other", "vocals")
STEM_EMOTIONS = {
    "drums": "high_energy",
    "bass": "suspense",
    "other": "melody",
    "vocals": "lead",
}
VARIANTS = ("demucs", "roformer_hybrid")


def _audio_duration_ms(path: Path) -> int:
    info = sf.info(str(path))
    return int(info.duration * 1000)


def write_variant_config(song: str, variant: str) -> Path | None:
    """Drop a config.json into comparison/<song>/<variant>/ so the player
    can load it. Returns the config path, or None if the dir is incomplete.
    """
    variant_dir = COMPARISON_DIR / song / variant
    if not variant_dir.is_dir():
        return None
    stems = [variant_dir / f"{name}.wav" for name in STEM_NAMES]
    if not all(p.is_file() for p in stems):
        return None

    # Reuse BPM from the original slicer output if it's around — purely
    # informational; the player uses the actual buffer length for playback.
    original = SONGS_DIR / song / "config.json"
    bpm = 120.0
    if original.is_file():
        try:
            bpm = float(json.loads(original.read_text())["detected_bpm"])
        except Exception:
            pass

    cfg = {
        "track_name": f"{song} [{variant}]",
        "detected_bpm": bpm,
        "loop_duration_ms": _audio_duration_ms(stems[0]),
        "sample_rate": sf.info(str(stems[0])).samplerate,
        "layers": [
            {"name": n, "file": f"{n}.wav", "emotion": STEM_EMOTIONS[n]}
            for n in STEM_NAMES
        ],
    }
    cfg_path = variant_dir / "config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg_path


def discover_comparison_library() -> list[tuple[str, Path]]:
    """Return the player's [(label, config_path)] list, interleaving each
    song's two variants so they sit next to each other in the dropdown."""
    library: list[tuple[str, Path]] = []
    if not COMPARISON_DIR.is_dir():
        return library
    for song_dir in sorted(p for p in COMPARISON_DIR.iterdir() if p.is_dir()):
        if song_dir.name.startswith("_"):
            continue
        for variant in VARIANTS:
            cfg = write_variant_config(song_dir.name, variant)
            if cfg is not None:
                library.append((f"{song_dir.name}  [{variant}]", cfg))
    return library


def main() -> None:
    library = discover_comparison_library()
    if not library:
        print("No complete comparison outputs yet — wait for separation to finish.")
        sys.exit(1)

    print(f"Comparison library: {len(library)} entries")
    for lbl, _ in library:
        print(f"  - {lbl}")

    root = tk.Tk()
    gui = PlayerGUI(root, library, normalize=True)
    try:
        root.mainloop()
    finally:
        try:
            gui.mixer.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
