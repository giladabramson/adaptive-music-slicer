"""Command-line interface for the Adaptive AI Music Engine.

Usage:
    python -m adaptive_music_engine -i input_track.mp3 -o ./output --bars 16
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .errors import AdaptiveMusicEngineError
from .pipeline import run_pipeline


def _parse_emotion_overrides(values: list[str] | None) -> dict[str, str]:
    """Parse repeated ``--emotion stem=tag`` flags into a dict."""
    overrides: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"--emotion expects 'stem=tag', got '{item}'"
            )
        stem, _, tag = item.partition("=")
        stem, tag = stem.strip(), tag.strip()
        if not stem or not tag:
            raise argparse.ArgumentTypeError(
                f"--emotion expects 'stem=tag', got '{item}'"
            )
        overrides[stem] = tag
    return overrides


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adaptive_music_engine",
        description=(
            "Turn a flat stereo track into adaptive, loop-ready instrument "
            "stems plus a config.json (Wizard-of-Oz MVP)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input", type=Path, default=None,
        help="Path to the input audio file (e.g. input_track.mp3). "
             "Omit when using --generate.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("./output"),
        help="Directory for sliced loops and config.json.",
    )
    gen = parser.add_argument_group("generation (Hugging Face MusicGen)")
    gen.add_argument(
        "--generate", metavar="PROMPT", default=None,
        help="Generate the source track from this text prompt instead "
             "of supplying --input. NOTE: MusicGen is instrumental — "
             "the vocals stem will be near-silent.",
    )
    gen.add_argument(
        "--gen-duration", type=float, default=20.0,
        help="Generated length in seconds (clamped to 30; make it long "
             "enough for the loop, e.g. >=16s for 8 bars @120 BPM).",
    )
    gen.add_argument(
        "--gen-model", default="facebook/musicgen-small",
        help="MusicGen checkpoint (small is CPU-friendly).",
    )
    gen.add_argument(
        "--gen-seed", type=int, default=None,
        help="Torch seed for reproducible generation.",
    )
    parser.add_argument(
        "--bars", type=int, default=16, choices=(8, 16, 32, 64),
        help="Loop length in bars.",
    )
    parser.add_argument(
        "--beats-per-bar", type=int, default=4,
        help="Time-signature numerator (4 = common time).",
    )
    parser.add_argument(
        "--format", dest="export_format", default="wav",
        choices=("wav", "mp3"),
        help="Export container. mp3 requires ffmpeg on PATH.",
    )
    parser.add_argument(
        "--mp3-bitrate", default="320k",
        help="CBR bitrate when --format mp3.",
    )
    parser.add_argument(
        "--model", default="htdemucs",
        help="Demucs model name (must be a 4-source model).",
    )
    parser.add_argument(
        "--manual-bpm", type=float, default=None,
        help="Lock tempo to this BPM instead of detecting it.",
    )
    parser.add_argument(
        "--analysis-source", default="mix",
        help="What to analyse for tempo: 'mix' (original) or a stem "
             "name like 'drums' (often cleanest for beat tracking).",
    )
    parser.add_argument(
        "--start-ms", type=int, default=None,
        help="Force loop start (ms), ignoring beat snapping.",
    )
    parser.add_argument(
        "--no-beat-snap", action="store_true",
        help="Start the loop at 0s instead of the first detected beat.",
    )
    parser.add_argument(
        "--emotion", action="append", metavar="STEM=TAG",
        help="Override an emotion tag, e.g. --emotion drums=climax "
             "(repeatable).",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Keep the intermediate Demucs working directory.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Keep the root logger (and chatty third-party libs like numba's JIT
    # tracer and pydub's ffmpeg subprocess logger) quiet; only elevate
    # our own package logger so -v shows pipeline progress, not spam.
    logging.basicConfig(
        level=logging.WARNING, format="%(message)s", stream=sys.stderr
    )
    logging.getLogger("adaptive_music_engine").setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )
    logging.getLogger("numba").setLevel(logging.WARNING)

    if not args.input and not args.generate:
        parser.error("provide an input file (-i) or a --generate prompt.")
    if args.input and args.generate:
        parser.error("--input and --generate are mutually exclusive.")

    try:
        emotion_overrides = _parse_emotion_overrides(args.emotion)
        result = run_pipeline(
            input_path=args.input,
            output_dir=args.output,
            generate_prompt=args.generate,
            gen_duration=args.gen_duration,
            gen_model=args.gen_model,
            gen_seed=args.gen_seed,
            bars=args.bars,
            beats_per_bar=args.beats_per_bar,
            model=args.model,
            export_format=args.export_format,
            mp3_bitrate=args.mp3_bitrate,
            manual_bpm=args.manual_bpm,
            analysis_source=args.analysis_source,
            start_on_beat=not args.no_beat_snap,
            start_ms_override=args.start_ms,
            emotion_overrides=emotion_overrides,
            keep_temp=args.keep_temp,
        )
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        return 2  # parser.error exits, but keep type-checkers happy
    except AdaptiveMusicEngineError as exc:
        # Expected, typed failure — clean message, no traceback.
        logging.error("\nERROR: %s", exc)
        return 1
    except KeyboardInterrupt:
        logging.error("\nInterrupted.")
        return 130

    print()
    print(f"  Track     : {result.track_name}")
    print(f"  BPM       : {result.plan.detected_bpm}")
    print(
        f"  Loop      : {result.plan.loop_start_ms}–"
        f"{result.plan.loop_end_ms} ms "
        f"({result.plan.loop_duration_ms} ms / "
        f"{result.plan.bars} bars)"
    )
    print(f"  Layers    : {', '.join(result.exported_layers)}")
    print(f"  Config    : {result.config_path}")
    print(f"  Output dir: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
