"""Adaptive Music Player Prototype
=================================

A local desktop tool that plays the synchronized stems produced by the
adaptive-music-slicer pipeline and lets you reshape the mix in real time
(as a game/app would drive adaptive music from a "tension" signal) — and
now lets you **switch between songs live**, without restarting.

Library model
-------------
Songs live as sub-folders of a single ``songs/`` directory, each holding
its stems + ``config.json``::

    songs/
      synthwave/   drums.wav bass.wav other.wav vocals.wav config.json
      hiphop/      ...
      reggae/      ...

The player scans that folder, lists every song in a dropdown, and you can
hop between them mid-playback — the swap happens on the audio thread with
a short master fade so it never clicks. A "Load…" button also lets you
browse to any ``config.json`` outside the library.

Design rationale
----------------
* **Sample-accurate sync by construction.** Every stem of the current
  song is mixed inside ONE ``sounddevice`` callback sharing a single
  playhead index, so they are phase-locked forever and the infinite loop
  is just ``index % N``.
* **Click-free, linear fades.** Tension changes ramp each stem's gain
  with a per-sample ``np.linspace`` ramp; a separate master gain handles
  pause/resume and song-switch fades.
* **Lock-free, audio-thread-owned swaps.** The GUI prepares the next
  track + its target gains and hands them over as one atomic package;
  the realtime callback applies the swap itself once the master has
  faded out. No locks are ever held in the audio callback.

Run
---
    pip install sounddevice soundfile numpy        # tkinter ships with Python
    python adaptive_player.py                       # scans ./songs/
    python adaptive_player.py --library path/to/songs
    python adaptive_player.py --config songs/reggae/config.json   # one song
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, ttk

import numpy as np
import sounddevice as sd
import soundfile as sf

# --------------------------------------------------------------------------- #
# Tension presets                                                             #
# --------------------------------------------------------------------------- #
# Keyed by Demucs stem NAME. "Melody" is the `other` stem (its config.json
# emotion tag is "melody"). This dict is the one place to retune behaviour.
PRESETS: dict[str, dict[str, float]] = {
    "Low":    {"drums": 0.0, "bass": 0.0, "other": 1.0, "vocals": 0.0},
    "Medium": {"drums": 0.2, "bass": 1.0, "other": 1.0, "vocals": 0.0},
    "High":   {"drums": 1.0, "bass": 1.0, "other": 1.0, "vocals": 1.0},
}
PRESET_DEFAULT = 1.0          # used for stems a preset doesn't mention
MASTER_FADE_S = 0.05          # pause/resume anti-click ramp
SWITCH_FADE_S = 0.25          # song-to-song crossfade dip
METER_REFRESH_MS = 50         # GUI level-meter refresh


# --------------------------------------------------------------------------- #
# Track loading / library discovery                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Track:
    """One fully-loaded song: audio buffer + metadata."""
    name: str                 # display name
    config_path: Path
    buffer: np.ndarray        # (frames, n_stems, 2) float32
    sr: int
    stem_names: list[str]
    emotions: list[str]
    cfg: dict

    @property
    def n_frames(self) -> int:
        return self.buffer.shape[0]

    @property
    def n_stems(self) -> int:
        return self.buffer.shape[1]


def _to_stereo_f32(audio: np.ndarray) -> np.ndarray:
    """Coerce any soundfile array to a contiguous (frames, 2) float32 buffer."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = np.repeat(audio[:, None], 2, axis=1)
    elif audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    return np.ascontiguousarray(audio)


#: Per-stem loudness target (RMS dBFS) when normalization is on. The
#: `other` (melody) stem is a Demucs *residual* and is often 15-20 dB
#: quieter than drums/bass/vocals on dense mixes — boosting toward a
#: shared target makes the tension presets (esp. Low = melody only)
#: perceptually balanced across songs.
_NORMALIZE_TARGET_DB = -20.0
#: Hard cap on how much a quiet stem may be boosted, to avoid
#: amplifying noise on near-silent stems into something hissy.
_NORMALIZE_MAX_BOOST_DB = 18.0


def normalize_stems(buffer: np.ndarray,
                    target_db: float = _NORMALIZE_TARGET_DB,
                    max_boost_db: float = _NORMALIZE_MAX_BOOST_DB,
                    ) -> np.ndarray:
    """Boost-only per-stem loudness match. Mutates and returns ``buffer``.

    Each stem is multiplied by a gain that brings its RMS up toward
    ``target_db``, never **down** (loud stems are left alone — we don't
    want to weaken a punchy drum stem to match a quiet residual). Two
    safety caps: max +``max_boost_db`` total boost, and the resulting
    per-stem peak is held below 0.99 to keep stems individually clean.
    Returns the same array (mutated in place) for convenience.
    """
    target_rms = 10.0 ** (target_db / 20.0)
    max_gain = 10.0 ** (max_boost_db / 20.0)
    for i in range(buffer.shape[1]):
        stem = buffer[:, i, :]
        rms = float(np.sqrt(np.mean(stem.astype(np.float64) ** 2)))
        if rms < 1e-6:
            continue                                  # truly silent: skip
        gain = min(target_rms / rms, max_gain)
        gain = max(gain, 1.0)                         # boost-only
        # 99.7th-percentile "peak" — a single Demucs artifact spike
        # would otherwise cap the boost to a few dB on quiet stems.
        # The mixer's hard limiter catches the rare outliers that go
        # above 1.0 after the boost.
        peak = float(np.quantile(np.abs(stem), 0.997))
        if peak * gain > 0.99:
            gain = max(0.99 / max(peak, 1e-9), 1.0)
        if gain != 1.0:
            buffer[:, i, :] = (stem * gain).astype(np.float32)
    return buffer


def load_track(config_path: Path, normalize: bool = True) -> Track:
    """Read a config.json and load every stem into one aligned buffer.

    Stems are truncated to the shortest length so a single playhead keeps
    them sample-aligned (the pipeline already exports equal-length loops —
    this is defensive).
    """
    config_path = Path(config_path)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    layers = cfg.get("layers", [])
    if not layers:
        raise ValueError(f"No 'layers' in {config_path}")

    names, emotions, arrays, srs = [], [], [], []
    for layer in layers:
        f = base / layer["file"]
        if not f.exists():
            print(f"  ! skipping missing stem: {f}", file=sys.stderr)
            continue
        data, sr = sf.read(f, dtype="float32", always_2d=True)
        names.append(layer["name"])
        emotions.append(layer.get("emotion", "unassigned"))
        arrays.append(_to_stereo_f32(data))
        srs.append(sr)

    if not arrays:
        raise ValueError(f"No playable stems for {config_path}")
    if len(set(srs)) != 1:
        raise ValueError(f"Mismatched sample rates in {config_path}: {srs}")

    n = min(len(a) for a in arrays)
    buffer = np.stack([a[:n] for a in arrays], axis=1)  # (frames, stems, 2)
    if normalize:
        normalize_stems(buffer)
    name = cfg.get("track_name") or base.name
    return Track(name, config_path, buffer, srs[0], names, emotions, cfg)


def discover_library(root: Path) -> list[tuple[str, Path]]:
    """Return [(display_name, config_path)] for every song under ``root``.

    A "song" is any sub-directory containing a config.json. Cheap — only
    the JSON is read here; audio is loaded lazily on selection.
    """
    songs: list[tuple[str, Path]] = []
    if not root.is_dir():
        return songs
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        cfg_path = sub / "config.json"
        if not cfg_path.is_file():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            track_name = cfg.get("track_name") or sub.name
        except Exception:
            track_name = sub.name
        songs.append((f"{sub.name}  ·  {track_name}", cfg_path))
    return songs


def resolve_sources(args) -> list[tuple[str, Path]]:
    """Build the song list from --config (single) or --library (folder)."""
    if args.config:
        p = Path(args.config).expanduser().resolve()
        if not p.is_file():
            sys.exit(f"config not found: {p}")
        return [(p.parent.name, p)]

    root = Path(args.library).expanduser().resolve()
    songs = discover_library(root)
    if songs:
        return songs

    # Fallbacks so a bare `python adaptive_player.py` still works.
    for cand in ("songs", "output_vocals", "output"):
        songs = discover_library(Path(cand).resolve())
        if songs:
            return songs
        p = Path(cand) / "config.json"
        if p.is_file():
            return [(p.parent.name, p.resolve())]
    sys.exit(
        f"No songs found under '{root}'. Generate some, or pass\n"
        "  --library <folder>   or   --config <path/to/config.json>"
    )


# --------------------------------------------------------------------------- #
# Realtime mixer                                                              #
# --------------------------------------------------------------------------- #
class StemMixer:
    """Single-callback software mixer with hot song-swap support."""

    def __init__(self, track: Track):
        self.track = track
        self.sr = track.sr
        self.targets = np.ones(track.n_stems, dtype=np.float32)
        self._gains = np.zeros(track.n_stems, dtype=np.float32)  # fade in
        self._pos = 0
        self.fade_s = 1.5
        self._playing = True
        self._master = 0.0                 # start silent -> fade in
        self._pending: tuple[Track, np.ndarray] | None = None
        self._switching = False

        # Fixed, generous block + 'high' latency: far less prone to
        # "output underflow" on the Windows default host API. The
        # callback handles any block size; channels are always stereo.
        self.stream = sd.OutputStream(
            samplerate=track.sr, channels=2, dtype="float32",
            blocksize=1024, latency="high",
            callback=self._callback,
        )

    # ---- GUI-thread API -------------------------------------------------- #
    def set_target(self, stem_idx: int, value: float) -> None:
        if 0 <= stem_idx < self.targets.shape[0]:
            self.targets[stem_idx] = float(np.clip(value, 0.0, 1.0))

    def set_fade(self, seconds: float) -> None:
        self.fade_s = max(0.05, float(seconds))

    def toggle_play(self) -> bool:
        self._playing = not self._playing
        return self._playing

    def queue_swap(self, track: Track, targets: np.ndarray) -> None:
        """Hand the next song + its start gains to the audio thread.

        One atomic package — the callback fades the master out, applies
        the swap itself, then fades the new song in. Lock-free.
        """
        self._pending = (track, np.asarray(targets, dtype=np.float32))
        self._switching = True

    @property
    def live_gains(self) -> np.ndarray:
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

        switching = self._switching
        # Master fades to 0 while switching or paused, else up to 1.
        m_goal = 0.0 if (switching or not self._playing) else 1.0
        fade = SWITCH_FADE_S if switching else MASTER_FADE_S
        m_step = frames / (fade * self.sr)
        m0 = self._master
        m1 = float(np.clip(m_goal, m0 - m_step, m0 + m_step))
        self._master = m1

        # Apply a queued swap once the old song has faded out.
        if switching and m1 <= 1e-3 and self._pending is not None:
            new_track, new_targets = self._pending
            self.track = new_track
            self.sr = new_track.sr
            self.targets = new_targets
            self._gains = np.zeros(new_track.n_stems, dtype=np.float32)
            self._pos = 0
            self._pending = None
            self._switching = False
            outdata.fill(0.0)                # silent seam frame
            return

        # Fully silent + paused (not mid-switch): freeze and output zeros.
        if not self._playing and not switching and m1 <= 1e-4:
            outdata.fill(0.0)
            return

        track = self.track
        n_frames = track.n_frames
        targets = self.targets.copy()                  # lock-free snapshot
        master_ramp = np.linspace(m0, m1, frames, endpoint=False,
                                  dtype=np.float32)

        # Same wrapped index feeds every stem -> sample-accurate sync.
        idx = (self._pos + np.arange(frames)) % n_frames
        block = track.buffer[idx]                      # (frames, S, 2)

        # Per-stem linear gain ramp toward target, capped so a full
        # 0<->1 swing lasts exactly `fade_s` seconds.
        max_step = frames / (self.fade_s * self.sr)
        g0 = self._gains
        delta = np.clip(targets - g0, -max_step, max_step)
        ramp = (g0[None, :]
                + np.linspace(0.0, 1.0, frames, endpoint=False,
                              dtype=np.float32)[:, None] * delta[None, :])
        self._gains = g0 + delta

        mixed = np.sum(block * ramp[:, :, None], axis=1)   # (frames, 2)
        mixed *= master_ramp[:, None]
        np.clip(mixed, -1.0, 1.0, out=mixed)               # safety limiter
        outdata[:] = mixed
        self._pos = (self._pos + frames) % n_frames


# --------------------------------------------------------------------------- #
# GUI                                                                         #
# --------------------------------------------------------------------------- #
class PlayerGUI:
    def __init__(self, root: tk.Tk, songs: list[tuple[str, Path]],
                 normalize: bool = True):
        self.root = root
        self.songs = list(songs)               # [(label, config_path)]
        self.normalize = normalize             # boost-only stem loudness match
        self.current_level = "High"
        self._guard = False                    # suppress slider callbacks

        track = load_track(self.songs[0][1], normalize=self.normalize)
        self.mixer = StemMixer(track)
        self.mixer.start()

        root.title("Adaptive Music Player Prototype")
        root.configure(padx=16, pady=14)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- song chooser ----------------------------------------------
        chooser = ttk.Frame(root)
        chooser.grid(row=0, column=0, columnspan=4, sticky="ew",
                     pady=(0, 12))
        ttk.Label(chooser, text="Song",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0)
        self.song_var = tk.StringVar(value=self.songs[0][0])
        self.song_box = ttk.Combobox(
            chooser, textvariable=self.song_var, state="readonly",
            width=42, values=[lbl for lbl, _ in self.songs])
        self.song_box.grid(row=0, column=1, padx=8)
        self.song_box.bind("<<ComboboxSelected>>",
                           lambda _e: self._on_pick())
        ttk.Button(chooser, text="Load…",
                   command=self._on_browse).grid(row=0, column=2)

        # ---- header (updated per song) ---------------------------------
        self.header = ttk.Label(root, font=("Segoe UI", 13, "bold"))
        self.header.grid(row=1, column=0, columnspan=4, sticky="w")
        self.subheader = ttk.Label(root, foreground="#666")
        self.subheader.grid(row=2, column=0, columnspan=4, sticky="w",
                            pady=(0, 10))

        # ---- tension presets -------------------------------------------
        pres = ttk.LabelFrame(root, text="  Tension  ", padding=10)
        pres.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 12))
        self.preset_btns: dict[str, ttk.Button] = {}
        for i, level in enumerate(("Low", "Medium", "High")):
            b = ttk.Button(pres, text=level, width=12,
                           command=lambda lv=level: self.apply_preset(lv))
            b.grid(row=0, column=i, padx=6)
            self.preset_btns[level] = b
        self.preset_lbl = ttk.Label(pres, text="", foreground="#888")
        self.preset_lbl.grid(row=0, column=3, padx=(14, 0))

        # ---- per-stem strip (rebuilt on song switch) -------------------
        self.strip = ttk.LabelFrame(root, text="  Stems  ", padding=10)
        self.strip.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.vol_vars: list[tk.DoubleVar] = []
        self.mute_vars: list[tk.BooleanVar] = []
        self.meters: list[ttk.Progressbar] = []

        # ---- transport / fade ------------------------------------------
        trans = ttk.Frame(root)
        trans.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.play_btn = ttk.Button(trans, text="⏸  Pause",
                                   command=self._toggle_play, width=12)
        self.play_btn.grid(row=0, column=0, padx=(0, 16))
        ttk.Label(trans, text="Fade").grid(row=0, column=1)
        self.fade_var = tk.DoubleVar(value=self.mixer.fade_s)
        ttk.Scale(trans, from_=0.3, to=3.0, length=160,
                  variable=self.fade_var,
                  command=lambda _v: self._on_fade()
                  ).grid(row=0, column=2, padx=6)
        self.fade_lbl = ttk.Label(trans, text=f"{self.mixer.fade_s:.1f}s",
                                  width=5)
        self.fade_lbl.grid(row=0, column=3)
        ttk.Button(trans, text="Quit", command=self._on_close
                   ).grid(row=0, column=4, padx=(16, 0))

        self._build_strip(track)
        self._refresh_header(track)
        self.apply_preset(self.current_level, fade_into_mixer=True)
        self._tick_meters()

    # ---- per-song UI (re)build ------------------------------------------ #
    def _build_strip(self, track: Track) -> None:
        """Recreate the stem rows to match the current song's stems."""
        for child in self.strip.winfo_children():
            child.destroy()
        self.vol_vars, self.mute_vars, self.meters = [], [], []

        for r, (name, emo) in enumerate(zip(track.stem_names,
                                            track.emotions)):
            label = "Melody" if name == "other" else name.capitalize()
            ttk.Label(self.strip, text=label,
                      font=("Segoe UI", 10, "bold"), width=8
                      ).grid(row=r, column=0, sticky="w", pady=6)
            ttk.Label(self.strip, text=emo, foreground="#888", width=11
                      ).grid(row=r, column=1, sticky="w")

            vol = tk.DoubleVar(value=100.0)
            self.vol_vars.append(vol)
            ttk.Scale(self.strip, from_=0, to=100, length=240,
                      variable=vol,
                      command=lambda _v, idx=r: self._on_change(idx)
                      ).grid(row=r, column=2, padx=10)

            mute = tk.BooleanVar(value=False)
            self.mute_vars.append(mute)
            ttk.Checkbutton(self.strip, text="Mute", variable=mute,
                            command=lambda idx=r: self._on_change(idx)
                            ).grid(row=r, column=3, padx=(4, 10))

            meter = ttk.Progressbar(self.strip, length=120, maximum=100.0)
            meter.grid(row=r, column=4, padx=(0, 4))
            self.meters.append(meter)

    def _refresh_header(self, track: Track) -> None:
        bpm = track.cfg.get("detected_bpm", 0.0)
        dur = track.cfg.get("loop_duration_ms", track.n_frames
                             / track.sr * 1000) / 1000.0
        self.header.config(text=track.name)
        self.subheader.config(
            text=f"{bpm:.2f} BPM   ·   {dur:.2f}s loop   ·   "
                 f"{track.n_stems} stems   ·   "
                 f"{track.config_path.parent}")

    # ---- song switching ------------------------------------------------- #
    def _targets_for(self, track: Track) -> np.ndarray:
        table = PRESETS[self.current_level]
        return np.array([table.get(n, PRESET_DEFAULT)
                         for n in track.stem_names], dtype=np.float32)

    def _switch_to(self, config_path: Path) -> None:
        try:
            track = load_track(config_path, normalize=self.normalize)
        except Exception as exc:
            self.subheader.config(text=f"load failed: {exc}")
            return
        self._build_strip(track)
        self._refresh_header(track)
        self._guard = True
        for idx, n in enumerate(track.stem_names):
            self.mute_vars[idx].set(False)
            self.vol_vars[idx].set(
                PRESETS[self.current_level].get(n, PRESET_DEFAULT) * 100.0)
        self._guard = False
        # Hand the whole package to the audio thread (it fades + swaps).
        self.mixer.queue_swap(track, self._targets_for(track))
        self._mark_preset(self.current_level)

    def _on_pick(self) -> None:
        label = self.song_var.get()
        for lbl, path in self.songs:
            if lbl == label:
                self._switch_to(path)
                return

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a config.json",
            filetypes=[("Song config", "config.json"),
                       ("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        p = Path(path)
        label = f"{p.parent.name}  ·  (loaded)"
        if all(lbl != label for lbl, _ in self.songs):
            self.songs.append((label, p))
            self.song_box["values"] = [lbl for lbl, _ in self.songs]
        self.song_var.set(label)
        self._switch_to(p)

    # ---- mix controls --------------------------------------------------- #
    def _effective_target(self, idx: int) -> float:
        if self.mute_vars[idx].get():
            return 0.0
        return self.vol_vars[idx].get() / 100.0

    def _on_change(self, idx: int) -> None:
        self.mixer.set_target(idx, self._effective_target(idx))
        if not self._guard:
            self.preset_lbl.config(text="(custom mix)")
            for b in self.preset_btns.values():
                b.state(["!pressed"])

    def apply_preset(self, level: str, fade_into_mixer: bool = True) -> None:
        self.current_level = level
        table = PRESETS[level]
        self._guard = True
        for idx, name in enumerate(self.mixer.track.stem_names):
            frac = table.get(name, PRESET_DEFAULT)
            self.mute_vars[idx].set(False)
            self.vol_vars[idx].set(frac * 100.0)
            if fade_into_mixer:
                self.mixer.set_target(idx, frac)
        self._guard = False
        self._mark_preset(level)

    def _mark_preset(self, level: str) -> None:
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

    # ---- meters / shutdown --------------------------------------------- #
    def _tick_meters(self) -> None:
        g = self.mixer.live_gains
        for i, meter in enumerate(self.meters):
            meter["value"] = float(g[i]) * 100.0 if i < len(g) else 0.0
        self.root.after(METER_REFRESH_MS, self._tick_meters)

    def _on_close(self) -> None:
        self.mixer.close()
        self.root.destroy()


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Adaptive Music Player Prototype")
    ap.add_argument("--library", default="songs",
                    help="Folder of song sub-dirs (default: ./songs).")
    ap.add_argument("--config",
                    help="Load a single song's config.json directly "
                         "(overrides --library).")
    ap.add_argument("--no-normalize", dest="normalize", action="store_false",
                    help="Disable per-stem loudness normalization (raw "
                         "stems straight from disk). Default: normalize on.")
    ap.set_defaults(normalize=True)
    args = ap.parse_args()

    songs = resolve_sources(args)
    print(f"Library: {len(songs)} song(s)   "
          f"[normalize={'on' if args.normalize else 'off'}]")
    for lbl, _ in songs:
        print(f"  - {lbl}")

    root = tk.Tk()
    gui = PlayerGUI(root, songs, normalize=args.normalize)
    try:
        root.mainloop()
    finally:
        try:
            gui.mixer.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
