"""Step 1 — Source separation with a Roformer + Demucs hybrid.

Two-stage pipeline shipped through the ``audio-separator`` package:

1. **BS-Roformer-Viperx-1296** extracts the vocals stem. Roformer's
   transformer-on-mel-spectrogram architecture isolates vocals far more
   cleanly than Demucs and leaves the residual instrumental largely
   free of ghost-vocal energy.
2. **Demucs htdemucs_ft** (4-model fine-tuned ensemble) splits the
   instrumental into drums / bass / other. Its own (near-silent)
   vocals stem is discarded — we already have the Roformer one.

This combination was A/B-tested by ear across seven generated genres
and sounded consistently better than plain ``htdemucs``. The trade-off
is ~30 s of GPU compute per song (or ~200 s on CPU); see the project
``.venv-cuda`` for the CUDA torch setup.

``audio-separator`` selects CUDA automatically when ``torch.cuda`` is
available and falls back to CPU otherwise.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .errors import StemSeparationError

logger = logging.getLogger(__name__)

#: Canonical stem names produced by the hybrid, in a stable order.
#: Everything downstream iterates this list.
STEM_NAMES: tuple[str, ...] = ("drums", "bass", "other", "vocals")

#: BS-Roformer-Viperx-1296 — vocals/instrumental split, vocals SDR ≈ 12.1.
_VOCALS_MODEL = "model_bs_roformer_ep_368_sdr_12.9628.ckpt"

#: Demucs v4 htdemucs_ft — 4-stem fine-tuned ensemble. We feed it the
#: vocals-removed instrumental and take its drums / bass / other.
_REST_MODEL = "htdemucs_ft.yaml"

#: Where audio-separator caches downloaded checkpoints. Project-local
#: so it travels with the repo and is shared with scripts/compare_separators.py.
_DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".models"


def _classify_stem(path: Path) -> str | None:
    """Map an audio-separator output filename to a canonical stem name.

    ``audio-separator`` writes ``<input>_(Vocals)_<model>.wav``,
    ``<input>_(Drums)_<model>.wav``, etc. — we key off the parenthesised tag.
    """
    name = path.name.lower()
    for tag, canonical in (
        ("(vocals)", "vocals"),
        ("(drums)", "drums"),
        ("(bass)", "bass"),
        ("(other)", "other"),
        ("(instrumental)", "instrumental"),
    ):
        if tag in name:
            return canonical
    return None


def _new_separator(scratch_dir: Path, model_cache: Path):
    """Construct a Separator that writes to ``scratch_dir``."""
    from audio_separator.separator import Separator  # noqa: PLC0415

    return Separator(
        output_dir=str(scratch_dir),
        model_file_dir=str(model_cache),
        output_format="WAV",
        log_level=logging.WARNING,
    )


def _run_model(
    sep,
    model_filename: str,
    input_path: Path,
    scratch_dir: Path,
) -> list[Path]:
    """Load a model, separate ``input_path``, return the new WAVs."""
    sep.load_model(model_filename=model_filename)
    before = set(scratch_dir.glob("*.wav"))
    sep.separate(str(input_path))
    return sorted(p for p in scratch_dir.glob("*.wav") if p not in before)


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    shutil.move(str(src), str(dest))


def separate_stems(
    input_path: Path,
    work_dir: Path,
    *,
    model_cache: Path | None = None,
) -> dict[str, Path]:
    """Split ``input_path`` into 4 stems under ``work_dir`` via the hybrid.

    Returns a dict mapping each name in :data:`STEM_NAMES` to its WAV path.

    Raises
    ------
    StemSeparationError
        If ``audio-separator`` is not installed, a model run fails, or
        an expected stem is missing afterwards.
    """
    try:
        import audio_separator.separator  # noqa: F401, PLC0415
    except ImportError as exc:
        raise StemSeparationError(
            "audio-separator is not installed in the active environment.\n"
            "  Install it with:  pip install -r requirements.txt"
        ) from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    cache = (model_cache or _DEFAULT_CACHE).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    final_dir = work_dir / "stems"
    final_dir.mkdir(parents=True, exist_ok=True)
    scratch = work_dir / "_audio_sep"
    scratch.mkdir(parents=True, exist_ok=True)

    stems: dict[str, Path] = {}

    # --- Step 1: Roformer vocals split ----------------------------------
    logger.debug("Loading vocals model: %s", _VOCALS_MODEL)
    sep = _new_separator(scratch, cache)
    produced = _run_model(sep, _VOCALS_MODEL, input_path, scratch)

    vocals_src: Path | None = None
    instrumental_src: Path | None = None
    for p in produced:
        canon = _classify_stem(p)
        if canon == "vocals":
            vocals_src = p
        elif canon == "instrumental":
            instrumental_src = p
    if vocals_src is None or instrumental_src is None:
        raise StemSeparationError(
            "Roformer step did not produce both vocals and instrumental; "
            f"got {[p.name for p in produced]}"
        )

    _move(vocals_src, final_dir / "vocals.wav")
    stems["vocals"] = final_dir / "vocals.wav"

    # --- Step 2: Demucs htdemucs_ft on the instrumental -----------------
    logger.debug("Loading instrumental model: %s", _REST_MODEL)
    sep2 = _new_separator(scratch, cache)
    produced = _run_model(sep2, _REST_MODEL, instrumental_src, scratch)

    for p in produced:
        canon = _classify_stem(p)
        if canon in ("drums", "bass", "other"):
            dest = final_dir / f"{canon}.wav"
            _move(p, dest)
            stems[canon] = dest

    missing = [s for s in STEM_NAMES if s not in stems]
    if missing:
        raise StemSeparationError(
            f"Hybrid separation finished but stems are missing: {missing}"
        )

    shutil.rmtree(scratch, ignore_errors=True)
    return stems
