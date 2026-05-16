"""Step 3 — Precise slicing & export with pydub.

Every stem is cut at the *identical* ``[loop_start_ms, loop_end_ms)``
window from the shared :class:`~.analysis.LoopPlan`, so the exported
loops stay perfectly phase-aligned and loop seamlessly.
"""

from __future__ import annotations

from pathlib import Path

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError, CouldntEncodeError

from .analysis import LoopPlan
from .errors import LoopSlicingError

#: Supported export containers and their pydub format string.
_VALID_FORMATS = {"wav", "mp3"}


def slice_stem(
    stem_path: Path,
    plan: LoopPlan,
    out_path: Path,
    *,
    export_format: str = "wav",
    mp3_bitrate: str = "320k",
) -> Path:
    """Slice one stem to the loop window and export it.

    Parameters
    ----------
    stem_path:
        Source stem (a Demucs ``.wav``).
    plan:
        Shared loop plan — its ms boundaries are applied verbatim.
    out_path:
        Destination file. Its suffix should match ``export_format``.
    export_format:
        ``"wav"`` (lossless, no ffmpeg needed) or ``"mp3"`` (needs
        ffmpeg installed).
    mp3_bitrate:
        CBR bitrate used only when ``export_format == "mp3"``.

    Returns
    -------
    The written ``out_path``.

    Raises
    ------
    LoopSlicingError
        On unsupported format, unreadable stem, too-short stem, or an
        encode failure (typically missing ffmpeg for MP3).
    """
    if export_format not in _VALID_FORMATS:
        raise LoopSlicingError(
            f"Unsupported export format '{export_format}' "
            f"(expected one of {sorted(_VALID_FORMATS)})."
        )

    try:
        segment = AudioSegment.from_file(stem_path)
    except (CouldntDecodeError, FileNotFoundError, OSError) as exc:
        raise LoopSlicingError(
            f"Could not load stem '{stem_path}': {exc}"
        ) from exc

    if plan.loop_end_ms > len(segment):
        raise LoopSlicingError(
            f"Loop end {plan.loop_end_ms}ms exceeds stem length "
            f"{len(segment)}ms for '{stem_path.name}'. The analysis "
            f"track and the stems are not the same length."
        )

    # Half-open slice [start, end): pydub end index is exclusive, which
    # is exactly what we want so the loop length is precise.
    loop = segment[plan.loop_start_ms : plan.loop_end_ms]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_kwargs: dict = {"format": export_format}
    if export_format == "mp3":
        export_kwargs["bitrate"] = mp3_bitrate

    try:
        loop.export(out_path, **export_kwargs)
    except (CouldntEncodeError, FileNotFoundError) as exc:
        hint = (
            " MP3 export needs ffmpeg on PATH "
            "(Windows: `winget install Gyan.FFmpeg`)."
            if export_format == "mp3"
            else ""
        )
        raise LoopSlicingError(
            f"Failed to export '{out_path}': {exc}.{hint}"
        ) from exc

    return out_path


def slice_all_stems(
    stems: dict[str, Path],
    plan: LoopPlan,
    output_dir: Path,
    *,
    export_format: str = "wav",
    mp3_bitrate: str = "320k",
) -> dict[str, Path]:
    """Slice every stem with the shared plan; return name -> output path."""
    exported: dict[str, Path] = {}
    for name, src in stems.items():
        dest = output_dir / f"{name}.{export_format}"
        exported[name] = slice_stem(
            src,
            plan,
            dest,
            export_format=export_format,
            mp3_bitrate=mp3_bitrate,
        )
    return exported
