"""Typed exception hierarchy for the Adaptive AI Music Engine.

Every failure the pipeline can produce is a subclass of
:class:`AdaptiveMusicEngineError`, so the CLI can catch one base type,
print a clean message, and exit non-zero without leaking tracebacks at
the user.
"""

from __future__ import annotations


class AdaptiveMusicEngineError(Exception):
    """Base class for all expected, user-facing pipeline failures."""


class InputAudioError(AdaptiveMusicEngineError):
    """The input file is missing, unreadable, or not decodable audio."""


class StemSeparationError(AdaptiveMusicEngineError):
    """Demucs is unavailable or failed to produce the expected stems."""


class AudioAnalysisError(AdaptiveMusicEngineError):
    """Librosa could not analyse the track (load failure / empty signal)."""


class LoopSlicingError(AdaptiveMusicEngineError):
    """A stem could not be loaded, sliced, or exported with pydub."""
