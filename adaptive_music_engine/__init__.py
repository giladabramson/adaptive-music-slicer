"""Adaptive AI Music Engine — local CLI prototype (Wizard-of-Oz MVP).

Pipeline:
  1. Source separation  (Demucs)   -> 4 stems
  2. Music info retrieval (Librosa) -> BPM + beat grid -> LoopPlan
  3. Precise slicing     (pydub)    -> phase-locked loop stems
  4. Metadata            (json)     -> config.json
"""

from __future__ import annotations

__version__ = "0.1.0"

from .analysis import LoopPlan, analyze_loop
from .errors import (
    AdaptiveMusicEngineError,
    AudioAnalysisError,
    InputAudioError,
    LoopSlicingError,
    StemSeparationError,
    TrackGenerationError,
)
from .generation import generate_track
from .pipeline import PipelineResult, run_pipeline

__all__ = [
    "__version__",
    "run_pipeline",
    "PipelineResult",
    "generate_track",
    "analyze_loop",
    "LoopPlan",
    "AdaptiveMusicEngineError",
    "InputAudioError",
    "TrackGenerationError",
    "StemSeparationError",
    "AudioAnalysisError",
    "LoopSlicingError",
]
