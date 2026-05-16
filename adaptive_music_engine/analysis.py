"""Step 2 — Music Information Retrieval with Librosa.

This module turns a flat audio file into a :class:`LoopPlan`: the exact
sample/millisecond boundaries of a musically perfect N-bar loop.

Why the loop length is *computed*, not *measured*
-------------------------------------------------
Beat-tracking output is slightly noisy — consecutive detected beats are
not perfectly equidistant. If we sliced from "detected beat 0" to
"detected beat 64" the loop length would inherit that jitter and the
seam would click and drift over repeats.

Instead we:

1. Detect a single global tempo (BPM) and the beat grid.
2. Snap the loop **start** to a detected beat (skips silent lead-in /
   anacrusis so the downbeat lands on sample 0 of the loop).
3. Derive the loop **length** purely from the tempo:

       seconds_per_beat = 60 / BPM
       loop_seconds     = bars * beats_per_bar * seconds_per_beat

   This makes the loop an exact whole number of beats, so the end
   sample lines up with where the start sample "wants" to be — the
   defining condition for a click-free, drift-free loop.

4. Quantise to integer milliseconds **once**, and reuse the *same*
   ``loop_start_ms`` / ``loop_end_ms`` for every stem. Per-stem drift is
   therefore impossible (all stems share identical boundaries), and the
   single rounding step bounds the seam error to < 0.5 ms — well below
   the audible / phase-relevant threshold.

A 4/4 time signature is assumed (``beats_per_bar=4``); override it for
3/4, 6/8, etc.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import librosa
import numpy as np

from .errors import AudioAnalysisError


@dataclasses.dataclass(frozen=True)
class LoopPlan:
    """Immutable, sample-accurate description of the target loop.

    The same instance is applied to all four stems, guaranteeing they
    stay phase-locked.
    """

    detected_bpm: float
    bars: int
    beats_per_bar: int
    sample_rate: int
    loop_start_ms: int
    loop_end_ms: int
    loop_duration_ms: int
    loop_start_sample: int
    loop_end_sample: int
    beat_count: int
    beat_times_ms: list[int]

    @property
    def total_beats(self) -> int:
        return self.bars * self.beats_per_bar


def _coerce_bpm(tempo) -> float:
    """librosa>=0.10 returns tempo as an ndarray; normalise to a float."""
    arr = np.atleast_1d(tempo).astype(float)
    if arr.size == 0 or not np.isfinite(arr[0]) or arr[0] <= 0:
        raise AudioAnalysisError(
            "Tempo detection failed (no finite positive BPM). "
            "Pass --manual-bpm to override."
        )
    return float(arr[0])


def analyze_loop(
    audio_path: Path,
    *,
    bars: int = 16,
    beats_per_bar: int = 4,
    manual_bpm: float | None = None,
    start_on_beat: bool = True,
    start_ms_override: int | None = None,
) -> LoopPlan:
    """Analyse ``audio_path`` and return a :class:`LoopPlan`.

    Parameters
    ----------
    audio_path:
        Track to analyse — typically the original mix (richest beat
        information) or the ``drums`` stem.
    bars:
        Loop length in bars (16 or 32 are typical for adaptive layers).
    beats_per_bar:
        Time-signature numerator. 4 for common time.
    manual_bpm:
        If given, locks the tempo to this value instead of estimating
        it (useful when you already know the track's BPM).
    start_on_beat:
        Snap the loop start to the first detected beat (trims lead-in).
    start_ms_override:
        Force an explicit loop start in ms, ignoring beat snapping.

    Raises
    ------
    AudioAnalysisError
        If the file cannot be loaded or yields an empty signal.
    """
    try:
        # sr=None preserves the file's native sample rate so reported
        # sample offsets match the actual audio.
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    except Exception as exc:  # librosa raises a grab-bag of types
        raise AudioAnalysisError(
            f"Librosa could not load '{audio_path}': {exc}. "
            "For MP3/M4A input make sure ffmpeg is installed."
        ) from exc

    if y is None or y.size == 0:
        raise AudioAnalysisError(
            f"'{audio_path}' decoded to an empty signal — corrupt or silent file."
        )

    # Lock or estimate tempo. Passing bpm= to beat_track pins the grid
    # to a known tempo while still returning a beat sequence.
    if manual_bpm is not None:
        if manual_bpm <= 0:
            raise AudioAnalysisError("--manual-bpm must be > 0.")
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, bpm=manual_bpm)
        bpm = float(manual_bpm)
    else:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        bpm = _coerce_bpm(tempo)

    beat_times = librosa.frames_to_time(beat_frames, sr=sr)  # seconds
    beat_times_ms = [int(round(t * 1000.0)) for t in beat_times.tolist()]

    # --- Loop START ---------------------------------------------------
    if start_ms_override is not None:
        start_sec = max(0.0, start_ms_override / 1000.0)
    elif start_on_beat and beat_times.size > 0:
        start_sec = float(beat_times[0])
    else:
        start_sec = 0.0

    # --- Loop LENGTH (tempo-derived, not measured) --------------------
    seconds_per_beat = 60.0 / bpm
    total_beats = bars * beats_per_bar
    loop_seconds = total_beats * seconds_per_beat

    track_seconds = y.size / float(sr)
    if start_sec + loop_seconds > track_seconds + 1e-6:
        need = start_sec + loop_seconds
        raise AudioAnalysisError(
            f"Requested {bars}-bar loop needs {need:.2f}s from start "
            f"{start_sec:.2f}s, but '{audio_path}' is only "
            f"{track_seconds:.2f}s long. Use fewer --bars, set "
            f"--start-ms 0, or supply a longer track."
        )

    # Quantise once to integer ms (pydub's slicing unit) and to samples
    # (for the metadata / any sample-accurate consumer).
    loop_start_ms = int(round(start_sec * 1000.0))
    loop_duration_ms = int(round(loop_seconds * 1000.0))
    loop_end_ms = loop_start_ms + loop_duration_ms

    loop_start_sample = int(round(start_sec * sr))
    loop_end_sample = loop_start_sample + int(round(loop_seconds * sr))

    return LoopPlan(
        detected_bpm=round(bpm, 4),
        bars=bars,
        beats_per_bar=beats_per_bar,
        sample_rate=int(sr),
        loop_start_ms=loop_start_ms,
        loop_end_ms=loop_end_ms,
        loop_duration_ms=loop_duration_ms,
        loop_start_sample=loop_start_sample,
        loop_end_sample=loop_end_sample,
        beat_count=int(beat_times.size),
        beat_times_ms=beat_times_ms,
    )
