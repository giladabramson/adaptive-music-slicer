"""Step 1 — Source separation with Demucs.

We shell out to Demucs via ``python -m demucs`` rather than importing its
Python API. Reasons:

* Demucs drags in torch/torchaudio; importing it in-process slows every
  CLI invocation (and import side effects load CUDA) even when the user
  only wants ``--help``.
* The subprocess boundary keeps Demucs' heavy global state out of our
  process and lets its native progress bar stream straight to the
  terminal — good UX for a multi-minute operation.

The default model ``htdemucs`` emits exactly the four stems this engine
expects: ``drums``, ``bass``, ``other``, ``vocals``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .errors import StemSeparationError

#: Canonical stem names produced by the 4-source htdemucs model, in a
#: stable order. Everything downstream iterates this list.
STEM_NAMES: tuple[str, ...] = ("drums", "bass", "other", "vocals")


def _demucs_is_available(python_exe: str) -> bool:
    """Return True if ``python -m demucs`` is importable and runnable."""
    try:
        proc = subprocess.run(
            [python_exe, "-m", "demucs", "-h"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def separate_stems(
    input_path: Path,
    work_dir: Path,
    *,
    model: str = "htdemucs",
    python_exe: str | None = None,
) -> dict[str, Path]:
    """Split ``input_path`` into 4 stems under ``work_dir``.

    Parameters
    ----------
    input_path:
        Source track (already validated to exist by the caller).
    work_dir:
        Scratch directory. Demucs writes to
        ``work_dir/<model>/<track_stem>/<stem>.wav``.
    model:
        Demucs model name. Must be a 4-source model for the stem names
        in :data:`STEM_NAMES` to line up.
    python_exe:
        Interpreter used to launch Demucs. Defaults to the current
        interpreter so the active virtualenv is respected.

    Returns
    -------
    dict mapping each name in :data:`STEM_NAMES` to its ``.wav`` path.

    Raises
    ------
    StemSeparationError
        If Demucs is not installed, exits non-zero, or any expected
        stem file is missing afterwards.
    """
    python_exe = python_exe or sys.executable
    work_dir.mkdir(parents=True, exist_ok=True)

    if not _demucs_is_available(python_exe):
        raise StemSeparationError(
            "Demucs is not installed in the active environment.\n"
            "  Install it with:  pip install -r requirements.txt"
        )

    cmd = [
        python_exe,
        "-m",
        "demucs",
        "-n",
        model,
        "-o",
        str(work_dir),
        str(input_path),
    ]

    # Do NOT capture output: let Demucs' progress bar stream to the
    # terminal so a multi-minute separation isn't a silent black box.
    try:
        proc = subprocess.run(cmd, check=False)
    except OSError as exc:  # pragma: no cover - environment dependent
        raise StemSeparationError(f"Failed to launch Demucs: {exc}") from exc

    if proc.returncode != 0:
        raise StemSeparationError(
            f"Demucs exited with status {proc.returncode}. "
            "See its output above for the underlying cause."
        )

    stem_dir = work_dir / model / input_path.stem
    stems: dict[str, Path] = {}
    missing: list[str] = []
    for name in STEM_NAMES:
        candidate = stem_dir / f"{name}.wav"
        if candidate.is_file():
            stems[name] = candidate
        else:
            missing.append(name)

    if missing:
        raise StemSeparationError(
            f"Demucs finished but these stems are missing under "
            f"{stem_dir}: {', '.join(missing)}. "
            f"Is '{model}' a 4-source model?"
        )

    return stems
