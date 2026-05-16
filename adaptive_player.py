"""Adaptive Music Player Prototype
=================================

A local desktop tool that plays the 4 synchronized stems produced by the
adaptive-music-slicer pipeline and lets you reshape the mix in real time —
exactly how a game or app would drive adaptive music from a "tension"
signal.

Design rationale
----------------
* **Sample-accurate sync by construction.** Instead of playing four
  independent players (which can start a few ms apart and drift on loop),
  every stem is mixed inside ONE ``sounddevice`` output callback that
  shares a single playhead index. They are therefore phase-locked
  forever, and the infinite loop is just ``index % N`` — seamless,
  zero-drift.
* **Click-free, linear fades.** Volume changes never snap. Each stem's
  gain ramps toward its target with a per-sample linear ``np.linspace``
  ramp inside every audio block, so a Low->High tension change glides
  over ``fade`` seconds with no zipper noise.
* **Lock-free audio thread.** The GUI thread only writes target gains;
  the audio thread snapshots them with a cheap copy. No locks are held
  in the realtime callback (locks in audio callbacks cause glitches).
  A momentarily torn multi-stem preset write is inaudible and self-
  corrects on the next ~10 ms block.

Run
---
    pip install sounddevice soundfile numpy        # tkinter ships with Python
    python adaptive_player.py                       # auto-finds config.json
    python adaptive_player.py --config output_vocals/config.json

The script reads ``config.json`` for the stem file names, their emotion
tags, and the sample rate; stem paths are resolved relative to the
config file's own directory (that is how the pipeline writes them).
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import numpy as np
import sounddevice as sd
import soundfile as sf

# --------------------------------------------------------------------------- #
# Tension presets                                                             #
# --------------------------------------------------------------------------- #
# Keyed by the Demucs stem NAME (stable), value = target volume fraction.
# "Melody" is the `other` stem (its emotion tag in config.json is "melody").
# This dict is the single place to retune the adaptive behaviour.
#
#   Low    : only Melody audible.
#   Medium : Melody + Bass full, Drums ducked to 20%.
#   High   : everything at full — maximum intensity.
PRESETS: dict[str, dict[str, float]] = {
    "Low":    {"drums": 0.0, "bass": 0.0, "other": 1.0, "vocals": 0.0},
    "Medium": {"drums": 0.2, "bass": 1.0, "other": 1.0, "vocals": 0.0},
    "High":   {"drums": 1.0, "bass": 1.0, "other": 1.0, "vocals": 1.0},
}
#: Fraction used when a preset does not mention a stem (e.g. a 6-stem model).
PRESET_DEFAULT = 1.0

#: Master pause/resume fade (seconds) — short, just to kill the click.
MASTER_FADE_S = 0.05

#: GUI refresh interval for the live level meters (ms).
METER_REFRESH_MS = 50


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #
def find_config(explicit: str | None) -> Path:
    """Locate config.json: explicit arg first, then common output dirs."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            sys.exit(f"config not found: {p}")
        return p
    for cand in ("config.json", "output_vocals/config.json",
                 "output/config.json", "output_game/config.json"):
        p = Path(cand).resolve()
        if p.exists():
            return p
    sys.exit(
        "Could not find config.json. Pass one explicitly:\n"
        "  python adaptive_player.py --config path/to/config.json"
    )


def to_stereo_f32(audio: np.ndarray) -> np.ndarray:
    """Coerce any soundfile array to a contiguous (frames, 2) float32 buffer."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:                       # mono -> duplicate to L/R
        audio = np.repeat(audio[:, None], 2, axis=1)
    elif audio.shape[1] == 1:                 # (N,1) -> (N,2)
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:                  # take first two channels
        audio = audio[:, :2]
    return np.ascontiguousarray(audio)


def load_stems(config_path: Path):
    """Read config.json, load every stem, return (names, emotions, buffer, sr).

    ``buffer`` has shape (frames, n_stems, 2); all stems are truncated to
    the shortest length so a single shared playhead keeps them aligned.
    (The pipeline already exports equal-length loops — this is defensive.)
    """
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    layers = cfg.get("layers", [])
    if not layers:
        sys.exit(f"No 'layers' in {config_path}")

    names, emotions, arrays, srs = [], [], [], []
    for layer in layers:
        f = base / layer["file"]
        if not f.exists():
            print(f"  ! skipping missing stem: {f}", file=sys.stderr)
            continue
        data, sr = sf.read(f, dtype="float32", always_2d=True)
        names.append(layer["name"])
        emotions.append(layer.get("emotion", "unassigned"))
        arrays.append(to_stereo_f32(data))
        srs.append(sr)

    if not arrays:
        sys.exit("No playable stems found.")
    if len(set(srs)) != 1:
        sys.exit(f"Stems have mismatched sample rates: {srs}")
    sr = srs[0]
    cfg_sr = cfg.get("sample_rate")
    if cfg_sr and cfg_sr != sr:
        print(f"  ! config says {cfg_sr} Hz but files are {sr} Hz; "
              f"using {sr} Hz.", file=sys.stderr)

    n = min(len(a) for a in arrays)
    if len({len(a) for a in arrays}) != 1:
        print(f"  ! stems differ in length; truncating to {n} frames "
              f"({n / sr:.3f}s).", file=sys.stderr)
    buffer = np.stack([a[:n] for a in arrays], axis=1)  # (frames, stems, 2)
    return names, emotions, buffer, sr, cfg


# --------------------------------------------------------------------------- #
# Realtime mixer                                                              #
# --------------------------------------------------------------------------- #
class StemMixer:
    """Single-callback software mixer: the heart of the sync guarantee."""

    def __init__(self, buffer: np.ndarray, samplerate: int):
        self.buffer = buffer                       # (N, S, 2) float32
        self.n_frames, self.n_stems, _ = buffer.shape
        self.sr = samplerate

        # Shared state. `targets` is written by the GUI thread; everything
        # else is owned by the audio thread. Plain numpy arrays — no locks
        # in the realtime path (see module docstring).
        self.targets = np.ones(self.n_stems, dtype=np.float32)
        self._gains = np.ones(self.n_stems, dtype=np.float32)   # live, faded
        self._pos = 0
        self.fade_s = 1.5          # tension crossfade length (GUI-tunable)
        self._playing = True
        self._master = 1.0         # pause/resume click-killer

        # A fixed, generous block + 'high' latency makes the Windows
        # default host API far less prone to "output underflow" glitches.
        # Extra latency (~tens of ms) is irrelevant here — tension fades
        # already span 1-2 s. The callback handles any block size.
        self.stream = sd.OutputStream(
            samplerate=samplerate, channels=2, dtype="float32",
            blocksize=1024, latency="high",
            callback=self._callback,
        )

    # ---- GUI-thread API -------------------------------------------------- #
    def set_target(self, stem_idx: int, value: float) -> None:
        self.targets[stem_idx] = float(np.clip(value, 0.0, 1.0))

    def set_fade(self, seconds: float) -> None:
        self.fade_s = max(0.05, float(seconds))

    def toggle_play(self) -> bool:
        self._playing = not self._playing
        return self._playing

    @property
    def live_gains(self) -> np.ndarray:
        """Snapshot of the actually-audible (post-fade) gains, for meters."""
        return self._gains.copy()

    def start(self) -> None:
        self.stream.start()

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()

    # ---- realtime callback (audio thread) -------------------------------- #
    def _callback(self, outdata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)

        targets = self.targets.copy()                 # lock-free snapshot
        sr = self.sr

        # Master gain ramps to 0 on pause / back to 1 on play (50 ms),
        # so pause/resume never clicks. While fully paused we freeze the
        # playhead (resume continues exactly where it stopped).
        m_goal = 1.0 if self._playing else 0.0
        m_step = frames / (MASTER_FADE_S * sr)
        m0 = self._master
        m1 = float(np.clip(m_goal, m0 - m_step, m0 + m_step))
        master_ramp = np.linspace(m0, m1, frames, endpoint=False,
                                  dtype=np.float32)
        self._master = m1

        if not self._playing and m1 <= 1e-4:
            outdata.fill(0.0)                         # frozen + silent
            return

        # Wrapped indices into the loop — the SAME index array feeds every
        # stem, which is what makes them sample-accurate forever.
        idx = (self._pos + np.arange(frames)) % self.n_frames
        block = self.buffer[idx]                      # (frames, S, 2)

        # Per-stem linear gain ramp toward target, capped so a full
        # 0<->1 swing takes exactly `fade_s` seconds.
        max_step = frames / (self.fade_s * sr)
        g0 = self._gains
        delta = np.clip(targets - g0, -max_step, max_step)
        g1 = g0 + delta
        # ramp shape: (frames, S) -> broadcast over the 2 channels
        ramp = (g0[None, :]
                + np.linspace(0.0, 1.0, frames, endpoint=False,
                              dtype=np.float32)[:, None] * delta[None, :])
        self._gains = g1

        mixed = np.sum(block * ramp[:, :, None], axis=1)   # (frames, 2)
        mixed *= master_ramp[:, None]
        np.clip(mixed, -1.0, 1.0, out=mixed)               # hard safety limit
        outdata[:] = mixed

        self._pos = (self._pos + frames) % self.n_frames


# --------------------------------------------------------------------------- #
# GUI                                                                         #
# --------------------------------------------------------------------------- #
class PlayerGUI:
    def __init__(self, root: tk.Tk, mixer: StemMixer,
                 names, emotions, cfg):
        self.root = root
        self.mixer = mixer
        self.names = names
        self.emotions = emotions
        self._guard = False        # suppress slider callbacks during preset

        root.title("Adaptive Music Player Prototype")
        root.configure(padx=16, pady=14)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- header -----------------------------------------------------
        track = cfg.get("track_name", "?")
        bpm = cfg.get("detected_bpm", 0.0)
        dur = cfg.get("loop_duration_ms", 0) / 1000.0
        ttk.Label(root, text=track, font=("Segoe UI", 13, "bold")
                  ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(root,
                  text=f"{bpm:.2f} BPM   ·   {dur:.2f}s loop   ·   "
                       f"{len(names)} stems",
                  foreground="#666"
                  ).grid(row=1, column=0, columnspan=4, sticky="w",
                         pady=(0, 10))

        # ---- tension presets -------------------------------------------
        pres = ttk.LabelFrame(root, text="  Tension  ", padding=10)
        pres.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 12))
        self.preset_btns: dict[str, ttk.Button] = {}
        for i, level in enumerate(("Low", "Medium", "High")):
            b = ttk.Button(pres, text=level, width=12,
                           command=lambda lv=level: self.apply_preset(lv))
            b.grid(row=0, column=i, padx=6)
            self.preset_btns[level] = b
        self.preset_lbl = ttk.Label(pres, text="(custom mix)",
                                    foreground="#888")
        self.preset_lbl.grid(row=0, column=3, padx=(14, 0))

        # ---- per-stem strips -------------------------------------------
        strip = ttk.LabelFrame(root, text="  Stems  ", padding=10)
        strip.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.vol_vars: list[tk.DoubleVar] = []
        self.mute_vars: list[tk.BooleanVar] = []
        self.meters: list[ttk.Progressbar] = []

        for r, (name, emo) in enumerate(zip(names, emotions)):
            label = "Melody" if name == "other" else name.capitalize()
            ttk.Label(strip, text=f"{label}",
                      font=("Segoe UI", 10, "bold"), width=8
                      ).grid(row=r, column=0, sticky="w", pady=6)
            ttk.Label(strip, text=emo, foreground="#888", width=11
                      ).grid(row=r, column=1, sticky="w")

            vol = tk.DoubleVar(value=100.0)
            self.vol_vars.append(vol)
            scale = ttk.Scale(strip, from_=0, to=100, length=240,
                              variable=vol,
                              command=lambda _v, idx=r: self._on_slider(idx))
            scale.grid(row=r, column=2, padx=10)

            mute = tk.BooleanVar(value=False)
            self.mute_vars.append(mute)
            ttk.Checkbutton(strip, text="Mute", variable=mute,
                            command=lambda idx=r: self._on_change(idx)
                            ).grid(row=r, column=3, padx=(4, 10))

            meter = ttk.Progressbar(strip, length=120, maximum=100.0)
            meter.grid(row=r, column=4, padx=(0, 4))
            self.meters.append(meter)

        # ---- transport / fade ------------------------------------------
        trans = ttk.Frame(root)
        trans.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.play_btn = ttk.Button(trans, text="⏸  Pause",
                                   command=self._toggle_play, width=12)
        self.play_btn.grid(row=0, column=0, padx=(0, 16))

        ttk.Label(trans, text="Fade").grid(row=0, column=1)
        self.fade_var = tk.DoubleVar(value=mixer.fade_s)
        ttk.Scale(trans, from_=0.3, to=3.0, length=160,
                  variable=self.fade_var,
                  command=lambda _v: self._on_fade()
                  ).grid(row=0, column=2, padx=6)
        self.fade_lbl = ttk.Label(trans, text=f"{mixer.fade_s:.1f}s", width=5)
        self.fade_lbl.grid(row=0, column=3)

        ttk.Button(trans, text="Quit", command=self._on_close
                   ).grid(row=0, column=4, padx=(16, 0))

        self.apply_preset("High")          # sensible starting point
        self._tick_meters()                # start the live level meters

    # ---- target recomputation ------------------------------------------ #
    def _effective_target(self, idx: int) -> float:
        if self.mute_vars[idx].get():
            return 0.0
        return self.vol_vars[idx].get() / 100.0

    def _on_change(self, idx: int) -> None:
        """Push one stem's intended volume to the mixer (it fades there)."""
        self.mixer.set_target(idx, self._effective_target(idx))
        if not self._guard:
            self._mark_custom()

    def _on_slider(self, idx: int) -> None:
        self._on_change(idx)

    def _mark_custom(self) -> None:
        self.preset_lbl.config(text="(custom mix)")
        for b in self.preset_btns.values():
            b.state(["!pressed"])

    # ---- presets -------------------------------------------------------- #
    def apply_preset(self, level: str) -> None:
        """Set every stem to the preset; the audio engine fades to it."""
        table = PRESETS[level]
        self._guard = True                 # don't flag this as a custom edit
        for idx, name in enumerate(self.names):
            frac = table.get(name, PRESET_DEFAULT)
            self.mute_vars[idx].set(False)
            self.vol_vars[idx].set(frac * 100.0)
            self.mixer.set_target(idx, frac)
        self._guard = False
        self.preset_lbl.config(text=f"▶ {level}")
        for lv, b in self.preset_btns.items():
            b.state(["pressed"] if lv == level else ["!pressed"])

    # ---- transport ------------------------------------------------------ #
    def _toggle_play(self) -> None:
        playing = self.mixer.toggle_play()
        self.play_btn.config(text="⏸  Pause" if playing else "▶  Play")

    def _on_fade(self) -> None:
        self.mixer.set_fade(self.fade_var.get())
        self.fade_lbl.config(text=f"{self.fade_var.get():.1f}s")

    # ---- live meters ---------------------------------------------------- #
    def _tick_meters(self) -> None:
        gains = self.mixer.live_gains
        for i, meter in enumerate(self.meters):
            meter["value"] = float(gains[i]) * 100.0
        self.root.after(METER_REFRESH_MS, self._tick_meters)

    # ---- shutdown ------------------------------------------------------- #
    def _on_close(self) -> None:
        self.mixer.close()
        self.root.destroy()


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Adaptive Music Player Prototype")
    ap.add_argument("--config", help="Path to config.json (default: "
                    "auto-discover in ./ or ./output*/).")
    args = ap.parse_args()

    config_path = find_config(args.config)
    print(f"Loading {config_path}")
    names, emotions, buffer, sr, cfg = load_stems(config_path)
    print(f"  {len(names)} stems @ {sr} Hz, "
          f"{buffer.shape[0] / sr:.3f}s loop: {', '.join(names)}")

    mixer = StemMixer(buffer, sr)
    mixer.start()

    root = tk.Tk()
    PlayerGUI(root, mixer, names, emotions, cfg)
    try:
        root.mainloop()
    finally:
        # Belt-and-braces: ensure the audio stream is released even if the
        # window manager bypassed the close handler.
        try:
            mixer.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
