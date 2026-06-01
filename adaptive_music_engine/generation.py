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

``stable-audio`` (Stability AI, via Replicate)
    ``stability-ai/stable-audio-2.5``. High-quality instrumental,
    long-form (up to ~190 s in one call). Needs ``REPLICATE_API_TOKEN``.

``audioldm`` (haoheliu/audio-ldm, via Replicate)
    Latent-diffusion model with a distinctly *ambient/atmospheric*
    aesthetic. Cheap, good for textural background. Needs
    ``REPLICATE_API_TOKEN`` (same as ``stable-audio``).

``beatoven`` (Beatoven.ai, via fal.ai)
    Purpose-built for background music (video/podcast/game beds).
    Flat per-request pricing, up to ~150 s. Needs ``FAL_KEY``.

All heavy/optional imports (``torch``/``transformers`` for MusicGen,
``google-genai`` for Lyria, ``replicate`` / ``fal-client`` for the
hosted backends) are lazy, so importing this module — and the package
— stays cheap and never fails on a missing optional dep.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

from .errors import TrackGenerationError

logger = logging.getLogger("adaptive_music_engine")

#: Selectable backends.
BACKENDS = ("lyria", "musicgen", "stable-audio", "audioldm", "beatoven")

#: Replicate / fal endpoint slugs (also used as the default model name
#: for each hosted backend). The AudioLDM slug is version-pinned because
#: it's a community model: bare ``owner/name`` returns 404 from
#: Replicate's `models/.../predictions` endpoint (which is reserved for
#: featured models). Pinning to ``owner/name:hash`` makes the SDK use
#: the versioned `/v1/predictions` endpoint instead. Refresh the hash
#: by re-running ``replicate.models.get('haoheliu/audio-ldm').latest_version.id``.
_REPLICATE_STABLE_AUDIO_SLUG = "stability-ai/stable-audio-2.5"
_REPLICATE_AUDIOLDM_SLUG = (
    "haoheliu/audio-ldm:"
    "b61392adecdd660326fc9cfc5398182437dbe5e97b5decfb36e1a36de68b5b95"
)
_FAL_BEATOVEN_SLUG = "beatoven/music-generation"

#: Per-backend default model when ``model_name`` is not given.
DEFAULT_MODELS = {
    "lyria": "lyria-3-clip-preview",
    "musicgen": "facebook/musicgen-small",
    "stable-audio": _REPLICATE_STABLE_AUDIO_SLUG,
    "audioldm": _REPLICATE_AUDIOLDM_SLUG,
    "beatoven": _FAL_BEATOVEN_SLUG,
}

#: File extension each backend's audio is written as.
BACKEND_SUFFIX = {
    "lyria": ".mp3",
    "musicgen": ".wav",
    "stable-audio": ".wav",
    "audioldm": ".wav",
    "beatoven": ".mp3",
}

#: API-key env vars tried in order for the Lyria backend. librono uses
#: GOOGLE_API_KEY; the watchdog uses GEMINI_API_KEY — same key value
#: usually works for both, so we accept either.
_LYRIA_KEY_ENV = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

#: API-key env vars for the hosted backends.
_REPLICATE_KEY_ENV = ("REPLICATE_API_TOKEN",)
_FAL_KEY_ENV = ("FAL_KEY",)

#: Service name under which the key may be stored in the OS secret
#: store (Windows Credential Manager / macOS Keychain) via ``keyring``.
_KEYRING_SERVICE = "adaptive-music-slicer"

#: MusicGen emits audio tokens at 50 Hz; this maps seconds -> max tokens.
_TOKENS_PER_SECOND = 50
#: One-shot generation ceiling for the small MusicGen model (~30 s).
_MAX_DURATION_S = 30.0

#: Max duration (seconds) accepted by each hosted backend, used for a
#: clamp + warning. Lyria ignores duration (fixed clip); MusicGen has
#: its own constant above.
_BACKEND_MAX_DURATION = {
    "stable-audio": 190.0,
    "audioldm": 20.0,
    "beatoven": 150.0,
}

#: AudioLDM's `duration` is a string-enum (discrete values), not a free
#: number. We snap to the closest allowed step and send as string.
_AUDIOLDM_DURATIONS = (2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0)

#: Suffix automatically appended to every prompt to maximise stem
#: separability. The product's value is clean drums/bass/other stems
#: that Demucs can split — wash-y ambient prompts give muddy stems and
#: defeat the point. These five tags steer the generator toward a
#: present drum kit, a distinct rhythmic bass, low reverb, and no
#: vocals (vocals stem stays clean-silent). Users can opt out per-call
#: with ``apply_stem_suffix=False`` for genuinely ambient experiments.
_STEM_FRIENDLY_SUFFIX = (
    "prominent drum kit, isolated punchy bassline, minimal reverb, "
    "clean instrument separation, instrumental"
)


def generate_track(
    prompt: str,
    out_path: Path,
    *,
    backend: str = "musicgen",
    duration_s: float = 20.0,
    model_name: str | None = None,
    seed: int | None = None,
    api_key: str | None = None,
    apply_stem_suffix: bool = True,
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
        ``"lyria"``, ``"musicgen"``, ``"stable-audio"``, ``"audioldm"``,
        or ``"beatoven"``.
    duration_s:
        Requested length in seconds. Honored by ``musicgen``,
        ``stable-audio``, ``audioldm``, and ``beatoven`` (each with its
        own max, clamped with a warning). Ignored by ``lyria`` (the
        preview model returns a fixed-length clip).
    model_name:
        Override the model / Replicate slug / fal endpoint. Defaults
        per backend (:data:`DEFAULT_MODELS`).
    seed:
        Forwarded to ``musicgen`` (torch) and the Replicate-hosted
        backends. Ignored by ``lyria`` and ``beatoven``.
    api_key:
        Lyria only — explicit key; otherwise read from
        ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``. The hosted backends
        read their tokens from env / keyring directly
        (``REPLICATE_API_TOKEN``, ``FAL_KEY``).
    apply_stem_suffix:
        Append :data:`_STEM_FRIENDLY_SUFFIX` to the prompt before
        sending it to the backend. Default ``True`` — this is the
        product's "secret sauce" that keeps stems separable. Set
        ``False`` only for ambient / sound-design experiments.

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

    sent_prompt = (
        f"{prompt.strip()}, {_STEM_FRIENDLY_SUFFIX}"
        if apply_stem_suffix
        else prompt
    )
    if apply_stem_suffix:
        logger.debug("Augmented prompt: %s", sent_prompt)

    if backend == "lyria":
        return _generate_lyria(sent_prompt, out_path, model=model, api_key=api_key)
    if backend == "musicgen":
        return _generate_musicgen(
            sent_prompt, out_path, duration_s=duration_s, model=model, seed=seed
        )
    if backend in ("stable-audio", "audioldm"):
        return _generate_replicate(
            sent_prompt, out_path, backend=backend, model=model,
            duration_s=duration_s, seed=seed,
        )
    # backend == "beatoven" (BACKENDS check above prevents other values)
    return _generate_beatoven(
        sent_prompt, out_path, model=model, duration_s=duration_s
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


def _first_text(response) -> str:
    """First text part of a response (for diagnostics on no-audio)."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            txt = getattr(part, "text", None)
            if txt:
                return txt.strip()
    return ""


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

    # lyria-3-clip-preview is non-deterministic: it intermittently
    # returns a text-only ("<instrumental>") response with no audio
    # part for the very same prompt. Retry a few times before failing.
    attempts = 3
    audio_bytes = b""
    last_text = ""
    for attempt in range(1, attempts + 1):
        logger.info(
            "Generating with Google Lyria ('%s')%s…",
            model,
            "" if attempt == 1 else f" — retry {attempt}/{attempts}",
        )
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"]
                ),
            )
        except Exception as exc:  # network / auth / access
            raise TrackGenerationError(
                f"Lyria request failed: {exc}\n"
                "Common causes: key/project lacks preview-model access, "
                "billing/quota limits, or region/model availability."
            ) from exc

        audio_bytes = _first_audio_bytes(response)
        if audio_bytes:
            break
        last_text = _first_text(response)
        logger.warning(
            "Lyria returned no audio (attempt %d/%d)%s.",
            attempt, attempts,
            f"; model said {last_text!r}" if last_text else "",
        )
        if attempt < attempts:
            time.sleep(2 * attempt)

    if not audio_bytes:
        raise TrackGenerationError(
            f"Lyria returned no audio after {attempts} attempts. The "
            "preview model intermittently responds text-only"
            + (f" (last: {last_text!r})" if last_text else "")
            + ". Re-run, or try a simpler prompt."
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


# --------------------------------------------------------------------- #
# Shared helpers for the hosted (Replicate / fal.ai) backends            #
# --------------------------------------------------------------------- #
def _resolve_hosted_key(
    env_vars: tuple[str, ...],
    *,
    backend_label: str,
    setx_example: str,
    where_to_get: str,
) -> str:
    """Generic env-var + keyring resolver for a hosted-backend token.

    Same resolution order as :func:`_resolve_lyria_key`: explicit arg
    is handled by the caller; here we try env vars then ``keyring``.
    """
    for env in env_vars:
        val = os.getenv(env)
        if val:
            return val
    try:
        import keyring

        for username in env_vars:
            val = keyring.get_password(_KEYRING_SERVICE, username)
            if val:
                return val
    except Exception:
        pass

    primary = env_vars[0]
    raise TrackGenerationError(
        f"{backend_label} backend needs an API token. Provide it:\n"
        f"  • Env var {primary}:\n"
        f"      {setx_example}   (then open a new terminal)\n"
        "  • OS secret store (encrypted, recommended) — run once:\n"
        '      python -c "import keyring; keyring.set_password'
        f"('{_KEYRING_SERVICE}', '{primary}', 'YOUR_TOKEN')\"\n"
        f"Get a token at {where_to_get}"
    )


def _download_url(url: str, *, timeout: float = 120.0) -> bytes:
    """Fetch a URL with stdlib so we don't take a hard dep on requests."""
    from urllib.request import urlopen

    with urlopen(url, timeout=timeout) as resp:
        return resp.read()


# --------------------------------------------------------------------- #
# Replicate backends (Stable Audio 2.5, AudioLDM)                        #
# --------------------------------------------------------------------- #
def _replicate_inputs(backend: str, prompt: str, duration_s: float,
                      seed: int | None) -> dict:
    """Build the input dict for the right Replicate slug.

    The two Replicate models use different parameter names; pin each
    explicitly so we don't send unknown keys.
    """
    inputs: dict = {}
    if backend == "stable-audio":
        # Stability's Replicate model uses `prompt` + `seconds_total`.
        inputs["prompt"] = prompt
        inputs["seconds_total"] = int(duration_s)
        if seed is not None:
            inputs["seed"] = int(seed)
    elif backend == "audioldm":
        # haoheliu/audio-ldm uses `text` + `duration` + `random_seed`
        # (NOT `seed`). `duration` is a STRING enum, not a number — see
        # _AUDIOLDM_DURATIONS. Snap to the closest valid step.
        snapped = min(_AUDIOLDM_DURATIONS,
                      key=lambda v: abs(v - duration_s))
        inputs["text"] = prompt
        inputs["duration"] = f"{snapped:.1f}"
        if seed is not None:
            inputs["random_seed"] = int(seed)
    else:
        inputs["prompt"] = prompt
        if seed is not None:
            inputs["seed"] = int(seed)
    return inputs


def _replicate_first_file_bytes(output) -> bytes:
    """Tolerantly extract audio bytes from a ``replicate.run()`` return.

    Replicate models return either a single ``FileOutput`` object, an
    iterable of them, a single URL string, or an iterable of URL
    strings — handle all four shapes without committing to one.
    """
    if hasattr(output, "read") and callable(getattr(output, "read")):
        try:
            return output.read()
        except Exception:
            pass

    if isinstance(output, str):
        if output.startswith(("http://", "https://")):
            return _download_url(output)
        return b""

    try:
        for item in output:
            if hasattr(item, "read") and callable(getattr(item, "read")):
                try:
                    return item.read()
                except Exception:
                    continue
            if isinstance(item, (bytes, bytearray)):
                return bytes(item)
            if isinstance(item, str) and item.startswith(
                ("http://", "https://")
            ):
                return _download_url(item)
    except TypeError:
        pass
    return b""


def _generate_replicate(
    prompt: str,
    out_path: Path,
    *,
    backend: str,
    model: str,
    duration_s: float,
    seed: int | None,
) -> Path:
    token = _resolve_hosted_key(
        _REPLICATE_KEY_ENV,
        backend_label="Replicate",
        setx_example='setx REPLICATE_API_TOKEN "r8_..."',
        where_to_get="https://replicate.com/account/api-tokens",
    )

    try:
        import replicate
    except ImportError as exc:
        raise TrackGenerationError(
            "Replicate backend needs the 'replicate' package. Install "
            "with:\n  pip install -r requirements.txt"
        ) from exc

    max_s = _BACKEND_MAX_DURATION.get(backend, 30.0)
    if duration_s <= 0:
        raise TrackGenerationError("--gen-duration must be > 0.")
    if duration_s > max_s:
        logger.warning(
            "Requested %.1fs exceeds %s's %.0fs limit; clamping to %.0fs.",
            duration_s, backend, max_s, max_s,
        )
        duration_s = max_s

    # The replicate SDK reads REPLICATE_API_TOKEN from the env; make
    # sure it's set if the user stored the token only in keyring.
    os.environ.setdefault("REPLICATE_API_TOKEN", token)

    inputs = _replicate_inputs(backend, prompt, duration_s, seed)
    logger.info(
        "Generating with Replicate '%s' (~%.0fs)…", model, duration_s
    )
    try:
        output = replicate.run(model, input=inputs)
    except Exception as exc:
        raise TrackGenerationError(
            f"Replicate request failed for '{model}': {exc}\n"
            "Common causes: invalid token, model version moved, or "
            "quota/credit exhausted."
        ) from exc

    audio_bytes = _replicate_first_file_bytes(output)
    if not audio_bytes:
        raise TrackGenerationError(
            f"Replicate model '{model}' returned no audio (response "
            f"shape: {type(output).__name__}). Try a different prompt "
            "or check the model's recent input-schema updates."
        )

    try:
        out_path.write_bytes(audio_bytes)
    except OSError as exc:
        raise TrackGenerationError(
            f"Failed to write generated audio to '{out_path}': {exc}"
        ) from exc

    logger.info("  -> wrote %s (%d bytes)",
                out_path.name, out_path.stat().st_size)
    return out_path


# --------------------------------------------------------------------- #
# Beatoven backend (fal.ai)                                              #
# --------------------------------------------------------------------- #
def _beatoven_audio_url(result) -> str:
    """Tolerantly pull the audio URL from a ``fal_client.run()`` return.

    fal endpoints return a dict; the key naming isn't stable across
    models, so try the handful of shapes that show up in practice.
    """
    if not isinstance(result, dict):
        return ""
    for key in ("audio", "audio_file", "output", "result"):
        val = result.get(key)
        if isinstance(val, dict) and isinstance(val.get("url"), str):
            return val["url"]
    for key in ("audio_url", "url"):
        val = result.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            return val
    return ""


def _generate_beatoven(
    prompt: str,
    out_path: Path,
    *,
    model: str,
    duration_s: float,
) -> Path:
    key = _resolve_hosted_key(
        _FAL_KEY_ENV,
        backend_label="Beatoven (fal.ai)",
        setx_example='setx FAL_KEY "..."',
        where_to_get="https://fal.ai/dashboard/keys",
    )

    try:
        import fal_client
    except ImportError as exc:
        raise TrackGenerationError(
            "Beatoven backend needs the 'fal-client' package. Install "
            "with:\n  pip install -r requirements.txt"
        ) from exc

    max_s = _BACKEND_MAX_DURATION["beatoven"]
    if duration_s <= 0:
        raise TrackGenerationError("--gen-duration must be > 0.")
    if duration_s > max_s:
        logger.warning(
            "Requested %.1fs exceeds Beatoven's %.0fs limit; clamping.",
            duration_s, max_s,
        )
        duration_s = max_s

    os.environ.setdefault("FAL_KEY", key)

    arguments = {"prompt": prompt, "duration": int(duration_s)}
    logger.info(
        "Generating with Beatoven (fal.ai) '%s' (~%.0fs)…", model, duration_s
    )
    try:
        result = fal_client.run(model, arguments=arguments)
    except Exception as exc:
        raise TrackGenerationError(
            f"Beatoven (fal.ai) request failed: {exc}\n"
            "Common causes: invalid FAL_KEY, quota exhausted, or the "
            "endpoint slug moved."
        ) from exc

    audio_url = _beatoven_audio_url(result)
    if not audio_url:
        shape = (
            list(result.keys()) if isinstance(result, dict)
            else type(result).__name__
        )
        raise TrackGenerationError(
            f"Beatoven returned no audio URL. Response shape: {shape}"
        )

    try:
        audio_bytes = _download_url(audio_url)
        out_path.write_bytes(audio_bytes)
    except Exception as exc:
        raise TrackGenerationError(
            f"Failed to download/write Beatoven audio: {exc}"
        ) from exc

    logger.info("  -> wrote %s (%d bytes)",
                out_path.name, out_path.stat().st_size)
    return out_path
