"""Step 4 — Metadata generation (config.json).

The config is the contract the runtime adaptive-music player consumes:
it tells the player where the loop boundaries are and which emotional
"layer" each stem represents so it can cross-fade them in/out.

Emotion tags are placeholders for the Wizard-of-Oz MVP — a human (or a
later model) tunes them per track.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .analysis import LoopPlan

CONFIG_FILENAME = "config.json"

#: Placeholder emotion tag per stem. Override via ``emotion_overrides``.
DEFAULT_EMOTION_TAGS: dict[str, str] = {
    "drums": "high_energy",
    "bass": "suspense",
    "other": "melody",
    "vocals": "lead",
}


def build_config(
    track_name: str,
    plan: LoopPlan,
    exported_layers: dict[str, Path],
    output_dir: Path,
    *,
    emotion_overrides: dict[str, str] | None = None,
) -> dict:
    """Assemble the config dict (paths stored relative to output_dir)."""
    tags = dict(DEFAULT_EMOTION_TAGS)
    if emotion_overrides:
        tags.update(emotion_overrides)

    layers = []
    for name, path in exported_layers.items():
        layers.append(
            {
                "name": name,
                "file": path.name,  # relative to the config's own dir
                "emotion": tags.get(name, "unassigned"),
            }
        )

    return {
        "track_name": track_name,
        "detected_bpm": plan.detected_bpm,
        "loop_start_ms": plan.loop_start_ms,
        "loop_end_ms": plan.loop_end_ms,
        "loop_duration_ms": plan.loop_duration_ms,
        "bars": plan.bars,
        "beats_per_bar": plan.beats_per_bar,
        "total_beats": plan.total_beats,
        "sample_rate": plan.sample_rate,
        "loop_start_sample": plan.loop_start_sample,
        "loop_end_sample": plan.loop_end_sample,
        "beat_count": plan.beat_count,
        "beat_times_ms": plan.beat_times_ms,
        "layers": layers,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": _engine_version(),
    }


def write_config(config: dict, output_dir: Path) -> Path:
    """Write ``config.json`` into ``output_dir`` and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / CONFIG_FILENAME
    with config_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return config_path


def _engine_version() -> str:
    from . import __version__

    return __version__
