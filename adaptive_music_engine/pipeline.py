"""End-to-end orchestration: file -> stems -> loop plan -> config.

This is the single entry point library consumers should call. The CLI
is a thin wrapper around :func:`run_pipeline`.
"""

from __future__ import annotations

import dataclasses
import logging
import shutil
from pathlib import Path

from .analysis import LoopPlan, analyze_loop
from .errors import AdaptiveMusicEngineError, InputAudioError
from .metadata import build_config, write_config
from .separation import separate_stems
from .slicing import slice_all_stems

logger = logging.getLogger("adaptive_music_engine")

# Extensions we accept as input. Anything ffmpeg can decode also works,
# but these are the formats we explicitly document/support.
_SUPPORTED_INPUT_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}


@dataclasses.dataclass
class PipelineResult:
    """Everything a caller needs after a successful run."""

    track_name: str
    plan: LoopPlan
    exported_layers: dict[str, Path]
    config_path: Path
    output_dir: Path


def _validate_input(input_path: Path) -> None:
    """Fail fast with a clear message before doing any heavy work."""
    if not input_path.exists():
        raise InputAudioError(f"Input file not found: {input_path}")
    if not input_path.is_file():
        raise InputAudioError(f"Input path is not a file: {input_path}")
    if input_path.stat().st_size == 0:
        raise InputAudioError(f"Input file is empty: {input_path}")
    if input_path.suffix.lower() not in _SUPPORTED_INPUT_SUFFIXES:
        logger.warning(
            "Input suffix '%s' is unusual; attempting to process anyway "
            "(decoding may require ffmpeg).",
            input_path.suffix,
        )


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    *,
    bars: int = 16,
    beats_per_bar: int = 4,
    model: str = "htdemucs",
    export_format: str = "wav",
    mp3_bitrate: str = "320k",
    manual_bpm: float | None = None,
    analysis_source: str = "mix",
    start_on_beat: bool = True,
    start_ms_override: int | None = None,
    emotion_overrides: dict[str, str] | None = None,
    keep_temp: bool = False,
) -> PipelineResult:
    """Run Steps 1-4 and return a :class:`PipelineResult`.

    Parameters
    ----------
    input_path:
        Flat stereo source track.
    output_dir:
        Where sliced loops and ``config.json`` are written.
    bars / beats_per_bar:
        Loop geometry (see :func:`~.analysis.analyze_loop`).
    model:
        Demucs model (must be 4-source).
    export_format:
        ``"wav"`` or ``"mp3"``.
    manual_bpm:
        Lock tempo instead of detecting it.
    analysis_source:
        ``"mix"`` to analyse the original track, or a stem name
        (e.g. ``"drums"``) to analyse that separated stem instead —
        ``drums`` often gives the cleanest beat tracking.
    start_on_beat / start_ms_override:
        Loop-start strategy (see :func:`~.analysis.analyze_loop`).
    keep_temp:
        Keep the intermediate Demucs output directory for debugging.

    Raises
    ------
    AdaptiveMusicEngineError
        Any expected failure in steps 1-4 (already typed/messaged).
    """
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    _validate_input(input_path)

    track_name = input_path.stem
    work_dir = output_dir / "_work"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # --- Step 1: source separation -------------------------------
        logger.info("Step 1/4 — Separating stems with Demucs (%s)…", model)
        stems = separate_stems(input_path, work_dir, model=model)
        logger.info("  -> %d stems: %s", len(stems), ", ".join(stems))

        # --- Step 2: MIR / loop plan ---------------------------------
        if analysis_source == "mix":
            analysis_path = input_path
        elif analysis_source in stems:
            analysis_path = stems[analysis_source]
        else:
            raise AdaptiveMusicEngineError(
                f"--analysis-source '{analysis_source}' is not 'mix' or "
                f"one of the available stems: {', '.join(stems)}"
            )
        logger.info(
            "Step 2/4 — Analysing %s for BPM & beat grid…", analysis_source
        )
        plan = analyze_loop(
            analysis_path,
            bars=bars,
            beats_per_bar=beats_per_bar,
            manual_bpm=manual_bpm,
            start_on_beat=start_on_beat,
            start_ms_override=start_ms_override,
        )
        logger.info(
            "  -> BPM=%.2f  loop=[%d, %d]ms  (%d bars / %d beats, %d ms)",
            plan.detected_bpm,
            plan.loop_start_ms,
            plan.loop_end_ms,
            plan.bars,
            plan.total_beats,
            plan.loop_duration_ms,
        )

        # --- Step 3: slice & export ----------------------------------
        logger.info("Step 3/4 — Slicing %d stems to the loop window…", len(stems))
        exported = slice_all_stems(
            stems,
            plan,
            output_dir,
            export_format=export_format,
            mp3_bitrate=mp3_bitrate,
        )

        # --- Step 4: metadata ----------------------------------------
        logger.info("Step 4/4 — Writing config.json…")
        config = build_config(
            track_name,
            plan,
            exported,
            output_dir,
            emotion_overrides=emotion_overrides,
        )
        config_path = write_config(config, output_dir)
        logger.info("Done. Output: %s", output_dir)

    finally:
        if not keep_temp and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.debug("Removed temp dir %s", work_dir)

    return PipelineResult(
        track_name=track_name,
        plan=plan,
        exported_layers=exported,
        config_path=config_path,
        output_dir=output_dir,
    )
