"""Compare two source-separation pipelines on the project's existing songs.

Pipeline A (baseline) — Demucs htdemucs, the current default in separation.py.
Pipeline B (Roformer hybrid) — BS-Roformer-Viperx-1296 extracts vocals; the
remaining instrumental is then split into drums/bass/other by Demucs htdemucs_ft
(fine-tuned variant). This is the modern "best of both architectures" recipe
that commercial tools (LALAL/Moises/RipX) ensemble.

Both pipelines emit the same four stems (drums, bass, other, vocals), written
side-by-side under ``comparison/<song>/{demucs,roformer_hybrid}/`` so you can
A/B by ear. A per-song ``stats.json`` and a top-level ``comparison/REPORT.md``
report RMS dBFS per stem and a cross-stem bleed proxy (Pearson correlation of
RMS envelopes between drums↔bass and other↔vocals).

Usage::

    python scripts/compare_separators.py              # run all songs/*
    python scripts/compare_separators.py synthwave    # one song
    python scripts/compare_separators.py --dry-run synthwave   # one song, log only
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SONGS_DIR = ROOT / "songs"
OUT_DIR = ROOT / "comparison"
MODEL_CACHE = ROOT / ".models"

STEM_NAMES = ("drums", "bass", "other", "vocals")

BASELINE_MODEL = "htdemucs.yaml"
HYBRID_VOCALS_MODEL = "model_bs_roformer_ep_368_sdr_12.9628.ckpt"
HYBRID_REST_MODEL = "htdemucs_ft.yaml"

log = logging.getLogger("compare")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if verbose else logging.INFO,
    )
    # audio-separator is chatty at INFO; quiet it unless -v
    logging.getLogger("audio_separator").setLevel(
        logging.DEBUG if verbose else logging.WARNING
    )


def _new_separator(output_dir: Path):
    """Return a fresh Separator instance bound to ``output_dir``.

    audio-separator caches model state on the instance; using one instance
    across different models is supported but switching models reloads weights.
    We make a fresh instance per pipeline for clean logging.
    """
    from audio_separator.separator import Separator

    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return Separator(
        output_dir=str(output_dir),
        model_file_dir=str(MODEL_CACHE),
        output_format="WAV",
    )


def _move_stem(produced_path: Path, dest: Path) -> None:
    """audio-separator names outputs ``<input>_(<stem>)_<model>.wav`` etc.
    We just shutil.move to a canonical name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    shutil.move(str(produced_path), str(dest))


def _collect_produced(out_dir: Path, before: set[Path]) -> list[Path]:
    """Return WAVs in ``out_dir`` that weren't there before the run."""
    return sorted(p for p in out_dir.glob("*.wav") if p not in before)


def _classify_stem(path: Path) -> str | None:
    """Map a produced filename to one of our canonical stem names.

    audio-separator emits names like ``input_(Vocals)_modelname.wav`` or
    ``input_(Drums)_modelname.wav``. We look for the tag in parentheses.
    """
    name = path.name.lower()
    for tag, canonical in (
        ("(vocals)", "vocals"),
        ("(drums)", "drums"),
        ("(bass)", "bass"),
        ("(other)", "other"),
        ("(instrumental)", "instrumental"),
        ("_vocals_", "vocals"),
        ("_drums_", "drums"),
        ("_bass_", "bass"),
        ("_other_", "other"),
        ("_instrumental_", "instrumental"),
    ):
        if tag in name:
            return canonical
    return None


def run_baseline(input_path: Path, out_root: Path) -> dict[str, Path]:
    """Pipeline A — plain Demucs htdemucs → 4 stems."""
    work = out_root / "_work_demucs"
    work.mkdir(parents=True, exist_ok=True)
    final = out_root / "demucs"
    final.mkdir(parents=True, exist_ok=True)

    log.info("[baseline] Loading %s", BASELINE_MODEL)
    sep = _new_separator(work)
    sep.load_model(model_filename=BASELINE_MODEL)

    log.info("[baseline] Separating %s", input_path.name)
    before = set(work.glob("*.wav"))
    sep.separate(str(input_path))
    produced = _collect_produced(work, before)

    stems: dict[str, Path] = {}
    for p in produced:
        canon = _classify_stem(p)
        if canon in STEM_NAMES:
            dest = final / f"{canon}.wav"
            _move_stem(p, dest)
            stems[canon] = dest

    missing = [s for s in STEM_NAMES if s not in stems]
    if missing:
        raise RuntimeError(
            f"baseline produced {sorted(p.name for p in produced)} but missing canonical stems: {missing}"
        )
    shutil.rmtree(work, ignore_errors=True)
    return stems


def run_roformer_hybrid(input_path: Path, out_root: Path) -> dict[str, Path]:
    """Pipeline B — BS-Roformer (vocals) → Demucs htdemucs_ft (drums/bass/other).

    Step 1: Roformer splits input into vocals + instrumental.
    Step 2: Demucs htdemucs_ft splits the instrumental into 4 stems; we discard
            its (near-silent) vocals stem and keep its drums/bass/other.
    """
    work = out_root / "_work_hybrid"
    work.mkdir(parents=True, exist_ok=True)
    final = out_root / "roformer_hybrid"
    final.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Roformer vocals split ----------------------------------
    log.info("[hybrid:1] Loading %s", HYBRID_VOCALS_MODEL)
    sep = _new_separator(work)
    sep.load_model(model_filename=HYBRID_VOCALS_MODEL)

    log.info("[hybrid:1] Separating vocals from %s", input_path.name)
    before = set(work.glob("*.wav"))
    sep.separate(str(input_path))
    produced = _collect_produced(work, before)

    vocals_src: Path | None = None
    instrumental_src: Path | None = None
    for p in produced:
        canon = _classify_stem(p)
        if canon == "vocals":
            vocals_src = p
        elif canon == "instrumental":
            instrumental_src = p
    if vocals_src is None or instrumental_src is None:
        raise RuntimeError(
            f"Roformer step did not produce both vocals+instrumental; got {[p.name for p in produced]}"
        )

    # Keep vocals as the final vocals stem
    _move_stem(vocals_src, final / "vocals.wav")

    # --- Step 2: Demucs htdemucs_ft on the instrumental -----------------
    log.info("[hybrid:2] Loading %s", HYBRID_REST_MODEL)
    sep2 = _new_separator(work)
    sep2.load_model(model_filename=HYBRID_REST_MODEL)

    log.info("[hybrid:2] Splitting instrumental into drums/bass/other")
    before = set(work.glob("*.wav"))
    sep2.separate(str(instrumental_src))
    produced = _collect_produced(work, before)

    stems: dict[str, Path] = {"vocals": final / "vocals.wav"}
    for p in produced:
        canon = _classify_stem(p)
        if canon in ("drums", "bass", "other"):
            dest = final / f"{canon}.wav"
            _move_stem(p, dest)
            stems[canon] = dest
        # ignore the htdemucs_ft "vocals" stem — should be near-silent and
        # we already have the Roformer one.

    missing = [s for s in STEM_NAMES if s not in stems]
    if missing:
        raise RuntimeError(
            f"hybrid step 2 produced {sorted(p.name for p in produced)} but missing: {missing}"
        )
    shutil.rmtree(work, ignore_errors=True)
    return stems


# --- Measurement -------------------------------------------------------------

def _to_mono(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 2:
        return samples.mean(axis=1)
    return samples


def _rms_dbfs(samples: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2) + 1e-12))
    return 20.0 * np.log10(max(rms, 1e-12))


def _peak_dbfs(samples: np.ndarray) -> float:
    peak = float(np.max(np.abs(samples)) + 1e-12)
    return 20.0 * np.log10(max(peak, 1e-12))


def _rms_envelope(samples: np.ndarray, sr: int, window_ms: int = 50) -> np.ndarray:
    """Short-window RMS envelope, used for cross-stem correlation."""
    win = max(1, int(sr * window_ms / 1000))
    n_windows = len(samples) // win
    if n_windows == 0:
        return np.array([0.0])
    trimmed = samples[: n_windows * win]
    return np.sqrt((trimmed.reshape(n_windows, win) ** 2).mean(axis=1) + 1e-12)


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a = a[:n] - a[:n].mean()
    b = b[:n] - b[:n].mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()) + 1e-12)
    return float((a * b).sum() / denom)


def measure(stems: dict[str, Path]) -> dict:
    """Per-stem RMS/peak + cross-stem bleed proxy.

    Bleed pairs:
      drums↔bass — kick leaking into bass (the EDM problem)
      other↔vocals — backing-vocals/synth bleed into the melodic stem
    Lower magnitude = cleaner separation.
    """
    samples_by_stem: dict[str, tuple[np.ndarray, int]] = {}
    out: dict = {"stems": {}}
    for name in STEM_NAMES:
        data, sr = sf.read(stems[name])
        mono = _to_mono(np.asarray(data, dtype=np.float32))
        samples_by_stem[name] = (mono, sr)
        rms = float(_rms_dbfs(mono))
        out["stems"][name] = {
            "rms_dbfs": round(rms, 2),
            "peak_dbfs": round(float(_peak_dbfs(mono)), 2),
            "duration_s": round(len(mono) / sr, 2),
            "near_silent": bool(rms < -40.0),
        }

    envelopes = {
        name: _rms_envelope(samples, sr)
        for name, (samples, sr) in samples_by_stem.items()
    }
    out["bleed"] = {
        "drums_x_bass": round(_correlation(envelopes["drums"], envelopes["bass"]), 3),
        "other_x_vocals": round(_correlation(envelopes["other"], envelopes["vocals"]), 3),
        "drums_x_other": round(_correlation(envelopes["drums"], envelopes["other"]), 3),
        "bass_x_other": round(_correlation(envelopes["bass"], envelopes["other"]), 3),
    }
    return out


# --- Reporting ---------------------------------------------------------------

def _fmt_db(v: float) -> str:
    return f"{v:+6.1f} dB"


def write_report(all_stats: dict, out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Separator comparison")
    lines.append("")
    lines.append("Baseline: **Demucs htdemucs** (current default in `separation.py`).")
    lines.append("")
    lines.append(
        "Hybrid: **BS-Roformer-Viperx-1296** for vocals, then **Demucs htdemucs_ft** "
        "for drums/bass/other on the residual instrumental."
    )
    lines.append("")
    lines.append(
        "Per-stem RMS in dBFS (higher = louder content present; "
        "values < -40 dB are near-silent — Demucs routed that frequency band "
        "to a different stem). Bleed = Pearson correlation of RMS envelopes "
        "between two stems; closer to 0 = cleaner separation."
    )
    lines.append("")

    for song, songdata in all_stats.items():
        lines.append(f"## {song}")
        lines.append("")
        lines.append("| stem | Demucs RMS | Hybrid RMS | Δ (hybrid−demucs) |")
        lines.append("|---|---:|---:|---:|")
        for stem in STEM_NAMES:
            d_rms = songdata["demucs"]["stems"][stem]["rms_dbfs"]
            h_rms = songdata["roformer_hybrid"]["stems"][stem]["rms_dbfs"]
            lines.append(
                f"| {stem} | {_fmt_db(d_rms)} | {_fmt_db(h_rms)} | "
                f"{_fmt_db(h_rms - d_rms)} |"
            )
        lines.append("")
        lines.append("**Bleed (lower magnitude = cleaner):**")
        lines.append("")
        lines.append("| pair | Demucs | Hybrid |")
        lines.append("|---|---:|---:|")
        for pair in ("drums_x_bass", "other_x_vocals", "drums_x_other", "bass_x_other"):
            d_corr = songdata["demucs"]["bleed"][pair]
            h_corr = songdata["roformer_hybrid"]["bleed"][pair]
            lines.append(f"| {pair} | {d_corr:+.3f} | {h_corr:+.3f} |")
        lines.append("")
        lines.append(f"**Runtime:** baseline {songdata['timing']['demucs_s']:.1f} s, "
                     f"hybrid {songdata['timing']['hybrid_s']:.1f} s")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# --- Main --------------------------------------------------------------------

def discover_songs(filter_names: list[str]) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    if not SONGS_DIR.is_dir():
        log.error("No songs/ directory at %s", SONGS_DIR)
        return []
    for sub in sorted(SONGS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if filter_names and sub.name not in filter_names:
            continue
        # Prefer the generated mp3, fall back to any input-like file
        candidates = [sub / "generated_input.mp3", sub / "generated_input.wav"]
        src = next((c for c in candidates if c.is_file()), None)
        if src is None:
            log.warning("Skipping %s — no generated_input.{mp3,wav}", sub.name)
            continue
        found.append((sub.name, src))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="*", help="Specific song names; default = all")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list what would run; do not separate or measure")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip a song if both its output dirs already exist")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    songs = discover_songs(args.songs)
    if not songs:
        log.error("No songs to process.")
        return 1

    log.info("Songs queued: %s", ", ".join(name for name, _ in songs))
    if args.dry_run:
        for name, path in songs:
            log.info("  %s → %s", name, path)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_stats: dict[str, dict] = {}

    for name, src in songs:
        log.info("=== %s ===", name)
        song_out = OUT_DIR / name
        demucs_dir = song_out / "demucs"
        hybrid_dir = song_out / "roformer_hybrid"
        already_done = (
            args.skip_existing
            and all((demucs_dir / f"{s}.wav").is_file() for s in STEM_NAMES)
            and all((hybrid_dir / f"{s}.wav").is_file() for s in STEM_NAMES)
        )
        if already_done:
            log.info("[%s] Skipping (--skip-existing) — both pipelines already present", name)

        try:
            t0 = time.time()
            if not already_done:
                demucs_stems = run_baseline(src, song_out)
            else:
                demucs_stems = {s: demucs_dir / f"{s}.wav" for s in STEM_NAMES}
            t1 = time.time()

            if not already_done:
                hybrid_stems = run_roformer_hybrid(src, song_out)
            else:
                hybrid_stems = {s: hybrid_dir / f"{s}.wav" for s in STEM_NAMES}
            t2 = time.time()

            log.info("[%s] Measuring", name)
            stats = {
                "demucs": measure(demucs_stems),
                "roformer_hybrid": measure(hybrid_stems),
                "timing": {
                    "demucs_s": round(t1 - t0, 1),
                    "hybrid_s": round(t2 - t1, 1),
                },
                "models": {
                    "demucs": BASELINE_MODEL,
                    "roformer_hybrid": {
                        "vocals": HYBRID_VOCALS_MODEL,
                        "rest": HYBRID_REST_MODEL,
                    },
                },
                "source": str(src),
            }
            (song_out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
            all_stats[name] = stats
            log.info("[%s] Done in %.1fs total", name, t2 - t0)
        except Exception:  # noqa: BLE001 - we want to keep going on a single failure
            log.exception("[%s] FAILED — continuing with remaining songs", name)

    if all_stats:
        report_path = OUT_DIR / "REPORT.md"
        write_report(all_stats, report_path)
        log.info("Wrote %s", report_path)
    else:
        log.error("No successful runs — nothing to report.")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
