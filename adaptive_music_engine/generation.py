"""Step 0 — Text-to-music generation (pluggable backend).

A text prompt becomes a flat musical bed, which then flows through the
existing separation -> analysis -> slicing -> metadata pipeline.

Backends
--------
``lyria`` (Google, via the ``google-genai`` SDK — *recommended*)
    Calls ``lyria-3-clip-preview`` with a single synchronous request and
    writes the returned **MP3**. Real, high-quality music; no local
    model, no GPU. Needs an API key (env var, ``--gen-api-key``, or the
    OS secret store via ``keyring``) with access to the Lyria preview
    model. Ported from the librono-app ``lyria_generate.py``.

``musicgen`` (Hugging Face, local — default, offline)
    ``facebook/musicgen-small`` via ``transformers``. ~2 GB weights
    downloaded once; CPU inference is slow. **Instrumental only** —
    Meta trained it without vocals, so the Demucs ``vocals`` stem will
    be near-silent on MusicGen tracks.

All heavy/optional imports (``torch``/``transformers`` for MusicGen,
``google-genai`` for Lyria) are lazy, so importing this module — and
the package — stays cheap and never fails on a missing optional dep.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from .errors import TrackGenerationError

logger = logging.getLogger("adaptive_music_engine")

#: Selectable backends.
BACKENDS = ("lyria", "musicgen")

#: Per-backend default model when ``model_name`` is not given.
DEFAULT_MODELS = {
    "lyria": "lyria-3-clip-preview",
    "musicgen": "facebook/musicgen-small",
}

#: File extension each backend's audio is written as.
BACKEND_SUFFIX = {"lyria": ".mp3", "musicgen": ".wav"}

#: API-key env vars tried in order for the Lyria backend. librono uses
#: GOOGLE_API_KEY; the watchdog uses GEMINI_API_KEY — same key value
#: usually works for both, so we accept either.
_LYRIA_KEY_ENV = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

#: Service name under which the key may be stored in the OS secret
#: store (Windows Credential Manager / macOS Keychain) via ``keyring``.
_KEYRING_SERVICE = "adaptive-music-slicer"

#: MusicGen emits audio tokens at 50 Hz; this maps seconds -> max tokens.
_TOKENS_PER_SECOND = 50
#: One-shot generation ceiling for the small MusicGen model (~30 s).
_MAX_DURATION_S = 30.0


def generate_track(
    prompt: str,
    out_path: Path,
    *,
    backend: str = "musicgen",
    duration_s: float = 20.0,
    model_name: str | None = None,
    seed: int | None = None,
    api_key: str | None = None,
) -> Path:
    """Generate a music clip from ``prompt`` and write it to ``out_path``.

    Parameters
    ----------
    prompt:
        Free-text description, e.g. ``"energetic synthwave, punchy
        kick, deep bassline, 120 bpm"``.
    out_path:
        Destination file. The caller is responsible for giving it the
        right suffix for ``backend`` (see :data:`BACKEND_SUFFIX`).
    backend:
        ``"lyria"`` or ``"musicgen"``.
    duration_s:
        MusicGen only — requested length, clamped to (0, 30]. Ignored
        by Lyria (the preview model returns a fixed-length clip).
    model_name:
        Override the model. Defaults per backend
        (:data:`DEFAULT_MODELS`).
    seed:
        MusicGen only — torch manual seed for reproducibility.
    api_key:
        Lyria only — explicit key; otherwise read from
        ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``.

    Returns
    -------
    The written path.

    Raises
    ------
    TrackGenerationError
        Empty prompt, unknown backend, missing optional dependency,
        missing API key, or a generation/IO failure (all typed — the
        CLI prints these cleanly without a traceback).
    """
    if not prompt or not prompt.strip():
        raise TrackGenerationError("Generation prompt is empty.")
    if backend not in BACKENDS:
        raise TrackGenerationError(
            f"Unknown --gen-backend '{backend}' (expected one of "
            f"{', '.join(BACKENDS)})."
        )

    model = model_name or DEFAULT_MODELS[backend]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if backend == "lyria":
        return _generate_lyria(prompt, out_path, model=model, api_key=api_key)
    return _generate_musicgen(
        prompt, out_path, duration_s=duration_s, model=model, seed=seed
    )


# --------------------------------------------------------------------- #
# Lyria backend (Google google-genai) — ported from librono-app          #
# --------------------------------------------------------------------- #
def _first_audio_bytes(response) -> bytes:
    """Walk a google-genai response for the first inline audio payload.

    The SDK returns raw bytes on some versions and a base64 string on
    others; handle both. (Faithfully ported from librono's
    ``first_audio_bytes``.)
    """
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                data = inline_data.data
                if isinstance(data, bytes):
                    return data
                if isinstance(data, str):
                    try:
                        return base64.b64decode(data)
                    except Exception:
                        return data.encode("utf-8", errors="ignore")
    return b""


def _resolve_lyria_key(api_key: str | None) -> str:
    """Find the Lyria API key without ever hardcoding it.

    Resolution order (first hit wins):
      1. explicit ``--gen-api-key`` / ``api_key`` argument
      2. env var (``GOOGLE_API_KEY`` then ``GEMINI_API_KEY``)
      3. OS secret store via ``keyring`` (Windows Credential Manager /
         macOS Keychain) — encrypted at rest, never on disk in clear,
         never committable. ``keyring`` is optional: if it's absent or
         has no backend, this step is silently skipped.
    """
    if api_key:
        return api_key

    for env in _LYRIA_KEY_ENV:
        val = os.getenv(env)
        if val:
            return val

    try:
        import keyring

        for username in _LYRIA_KEY_ENV:
            val = keyring.get_password(_KEYRING_SERVICE, username)
            if val:
                return val
    except Exception:
        # keyring not installed / no OS backend: fall through to error.
        pass

    raise TrackGenerationError(
        "Lyria backend needs an API key. Provide it one of these ways:\n"
        f"  • Env var ({' / '.join(_LYRIA_KEY_ENV)}) — PowerShell:\n"
        '      setx GOOGLE_API_KEY "YOUR_KEY"   (then open a new terminal)\n'
        "  • OS secret store (encrypted, recommended) — run once:\n"
        '      python -c "import keyring; keyring.set_password'
        f"('{_KEYRING_SERVICE}', 'GOOGLE_API_KEY', 'YOUR_KEY')\"\n"
        "  • --gen-api-key on the command line\n"
        "The key must have access to the Lyria preview model."
    )


def _generate_lyria(
    prompt: str, out_path: Path, *, model: str, api_key: str | None
) -> Path:
    key = _resolve_lyria_key(api_key)

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise TrackGenerationError(
            "Lyria backend needs the 'google-genai' SDK. Install with:\n"
            "  pip install -r requirements.txt"
        ) from exc

    logger.info("Generating with Google Lyria ('%s')…", model)
    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["AUDIO"]),
        )
    except Exception as exc:  # network / auth / access — opaque SDK errors
        raise TrackGenerationError(
            f"Lyria request failed: {exc}\n"
            "Common causes: key/project lacks preview-model access, "
            "billing/quota limits, or region/model availability."
        ) from exc

    audio_bytes = _first_audio_bytes(response)
    if not audio_bytes:
        raise TrackGenerationError(
            "Lyria returned no audio. Try a simpler prompt or verify "
            "the key has access to the model."
        )

    try:
        out_path.write_bytes(audio_bytes)
    except OSError as exc:
        raise TrackGenerationError(
            f"Failed to write generated audio to '{out_path}': {exc}"
        ) from exc

    logger.info("  -> wrote %s (%d bytes, MP3)",
                out_path.name, out_path.stat().st_size)
    return out_path


# --------------------------------------------------------------------- #
# MusicGen backend (Hugging Face transformers, local)                    #
# --------------------------------------------------------------------- #
def _generate_musicgen(
    prompt: str,
    out_path: Path,
    *,
    duration_s: float,
    model: str,
    seed: int | None,
) -> Path:
    if duration_s <= 0:
        raise TrackGenerationError("--gen-duration must be > 0.")
    if duration_s > _MAX_DURATION_S:
        logger.warning(
            "Requested %.1fs exceeds the %.0fs single-pass limit; "
            "clamping to %.0fs.",
            duration_s, _MAX_DURATION_S, _MAX_DURATION_S,
        )
        duration_s = _MAX_DURATION_S

    try:
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
    except ImportError as exc:
        raise TrackGenerationError(
            "MusicGen backend needs 'transformers' (and torch). "
            "Install with:\n  pip install -r requirements.txt"
        ) from exc

    try:
        logger.info("Loading MusicGen model '%s' (first run downloads "
                    "~2 GB to the HF cache)…", model)
        processor = AutoProcessor.from_pretrained(model)
        gen_model = MusicgenForConditionalGeneration.from_pretrained(model)
        gen_model.eval()

        if seed is not None:
            torch.manual_seed(seed)

        inputs = processor(text=[prompt], padding=True, return_tensors="pt")
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
        wav = audio[0, 0].cpu().numpy().astype("float32")
    except TrackGenerationError:
        raise
    except Exception as exc:  # broad: model/runtime failures are opaque
        raise TrackGenerationError(
            f"MusicGen generation failed: {exc}"
        ) from exc

    try:
        import soundfile as sf

        sf.write(out_path, wav, sr)
    except Exception as exc:
        raise TrackGenerationError(
            f"Failed to write generated audio to '{out_path}': {exc}"
        ) from exc

    logger.info("  -> wrote %s (%.1fs @ %d Hz)",
                out_path.name, wav.size / float(sr), sr)
    return out_path
