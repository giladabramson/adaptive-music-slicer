"""Step 0 — Text-to-music generation with Hugging Face MusicGen.

This is the product's *source* generator: a text prompt becomes a flat
stereo-ish musical bed, which then flows through the existing
separation -> analysis -> slicing -> metadata pipeline.

Model
-----
`facebook/musicgen-small` by default (CPU-friendly; ~2 GB weights
downloaded once to the HF cache on first use). Larger checkpoints
(`-medium`, `-large`, `-melody`) are selectable but are slow without a
GPU.

Important limitation
--------------------
MusicGen is an **instrumental** model — Meta intentionally trained it
without vocals. Expect a near-silent ``vocals`` stem from Demucs
downstream. Adding real sung vocals would require a separate model
(e.g. Bark) layered on top; that is out of scope here.

Heavy imports (``torch``/``transformers``) are done lazily inside
:func:`generate_track` so importing this module — and the package — is
cheap and does not fail when ``transformers`` is absent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .errors import TrackGenerationError

logger = logging.getLogger("adaptive_music_engine")

#: MusicGen emits audio tokens at 50 Hz; this maps seconds -> max tokens.
_TOKENS_PER_SECOND = 50
#: One-shot generation ceiling for the small model (~30 s of audio).
_MAX_DURATION_S = 30.0


def generate_track(
    prompt: str,
    out_path: Path,
    *,
    duration_s: float = 20.0,
    model_name: str = "facebook/musicgen-small",
    seed: int | None = None,
) -> Path:
    """Generate a music clip from ``prompt`` and write it to ``out_path``.

    Parameters
    ----------
    prompt:
        Free-text description, e.g. ``"upbeat funky house groove,
        sidechained bass, 120 bpm"``.
    out_path:
        Destination ``.wav``. Parent dirs are created.
    duration_s:
        Requested length in seconds. Clamped to (0, 30] — the small
        model generates in a single pass up to ~30 s. Make this long
        enough for the loop you intend to cut (e.g. >= 16 s for an
        8-bar / 120 BPM loop).
    model_name:
        Any MusicGen checkpoint on the HF Hub.
    seed:
        Optional torch manual seed for reproducible generation.

    Returns
    -------
    The written ``out_path``.

    Raises
    ------
    TrackGenerationError
        If ``transformers`` is not installed, the prompt is empty, or
        generation/IO fails.
    """
    if not prompt or not prompt.strip():
        raise TrackGenerationError("Generation prompt is empty.")

    if duration_s <= 0:
        raise TrackGenerationError("--gen-duration must be > 0.")
    if duration_s > _MAX_DURATION_S:
        logger.warning(
            "Requested %.1fs exceeds the %.0fs single-pass limit; "
            "clamping to %.0fs.",
            duration_s,
            _MAX_DURATION_S,
            _MAX_DURATION_S,
        )
        duration_s = _MAX_DURATION_S

    # --- lazy heavy imports ------------------------------------------
    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
    except ImportError as exc:
        raise TrackGenerationError(
            "MusicGen needs 'transformers' (and torch). Install with:\n"
            "  pip install -r requirements.txt"
        ) from exc

    try:
        logger.info("Loading MusicGen model '%s' (first run downloads "
                    "~2 GB to the HF cache)…", model_name)
        processor = AutoProcessor.from_pretrained(model_name)
        gen_model = MusicgenForConditionalGeneration.from_pretrained(model_name)
        gen_model.eval()

        if seed is not None:
            torch.manual_seed(seed)

        inputs = processor(
            text=[prompt], padding=True, return_tensors="pt"
        )
        max_new_tokens = int(duration_s * _TOKENS_PER_SECOND)
        logger.info(
            "Generating ~%.1fs of audio (CPU inference is slow — "
            "expect minutes)…", duration_s
        )
        with torch.no_grad():
            audio = gen_model.generate(
                **inputs, do_sample=True, max_new_tokens=max_new_tokens
            )

        sr = gen_model.config.audio_encoder.sampling_rate
        # audio shape: (batch, channels, samples) -> mono float32
        wav = audio[0, 0].cpu().numpy().astype("float32")
    except TrackGenerationError:
        raise
    except Exception as exc:  # broad: model/runtime failures are opaque
        raise TrackGenerationError(
            f"MusicGen generation failed: {exc}"
        ) from exc

    try:
        import soundfile as sf

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out_path, wav, sr)
    except Exception as exc:
        raise TrackGenerationError(
            f"Failed to write generated audio to '{out_path}': {exc}"
        ) from exc

    logger.info("  -> wrote %s (%.1fs @ %d Hz)",
                out_path.name, wav.size / float(sr), sr)
    return out_path
