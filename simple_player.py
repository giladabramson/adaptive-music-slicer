"""Simple stem-mix player with a seek bar.

Same audio engine as ``adaptive_player.py`` (imported from it) but a
stripped-down GUI for the producer-listener use case: no Exploration/
Combat mode buttons, just per-stem volume sliders, a "play everything
at max" reset button, and a scrubbable playhead.

Run from the project root::

    C:\\dev\\.venv311\\Scripts\\python.exe simple_player.py --library output/producer_vocals
"""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

# Reuse the adaptive player's audio engine and library loading verbatim —
# only the GUI differs between the two players.
from adaptive_player import (
    METER_REFRESH_MS,
    StemMixer,
    Track,
    load_track,
    resolve_sources,
)


SEEK_REFRESH_MS = 80   # how often to redraw the seek slider while playing


class SimplePlayerGUI:
    def __init__(self, root: tk.Tk, songs: list[tuple[str, Path]],
                 normalize: bool = True):
        self.root = root
        self.songs = list(songs)
        self.normalize = normalize
        self._guard = False
        self._seek_dragging = False     # block seek auto-updates while user drags

        track = load_track(self.songs[0][1], normalize=self.normalize)
        self.mixer = StemMixer(track)
        self.mixer.start()

        root.title("Simple Stem Player")
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

        # ---- header ----------------------------------------------------
        self.header = ttk.Label(root, font=("Segoe UI", 13, "bold"))
        self.header.grid(row=1, column=0, columnspan=4, sticky="w")
        self.subheader = ttk.Label(root, foreground="#666")
        self.subheader.grid(row=2, column=0, columnspan=4, sticky="w",
                            pady=(0, 10))

        # ---- "Play all at max" button ---------------------------------
        actions = ttk.Frame(root)
        actions.grid(row=3, column=0, columnspan=4, sticky="ew",
                     pady=(0, 12))
        ttk.Button(
            actions, text="Play all stems at 100%",
            command=self._all_max, width=24,
        ).grid(row=0, column=0)

        # ---- per-stem strip ---------------------------------------------
        self.strip = ttk.LabelFrame(root, text="  Stems  ", padding=10)
        self.strip.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.vol_vars: list[tk.DoubleVar] = []
        self.mute_vars: list[tk.BooleanVar] = []
        self.meters: list[ttk.Progressbar] = []

        # ---- seek bar --------------------------------------------------
        seek = ttk.LabelFrame(root, text="  Position  ", padding=8)
        seek.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_slider = ttk.Scale(
            seek, from_=0.0, to=1.0, length=420, variable=self.seek_var,
            command=self._on_seek_drag,
        )
        self.seek_slider.grid(row=0, column=0, padx=(0, 8))
        # ButtonPress/Release: pause auto-updates while user is scrubbing
        self.seek_slider.bind("<ButtonPress-1>",
                              lambda _e: setattr(self, "_seek_dragging", True))
        self.seek_slider.bind(
            "<ButtonRelease-1>", self._on_seek_release
        )
        self.seek_lbl = ttk.Label(seek, text="0.0 / 0.0 s", width=14)
        self.seek_lbl.grid(row=0, column=1)

        # ---- transport / fade ------------------------------------------
        trans = ttk.Frame(root)
        trans.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(14, 0))
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
        self._all_max()
        self._tick_meters()
        self._tick_seek()

    # ---- per-song UI (re)build ----------------------------------------- #
    def _build_strip(self, track: Track) -> None:
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
        dur = track.cfg.get("loop_duration_ms",
                            track.n_frames / track.sr * 1000) / 1000.0
        self.header.config(text=track.name)
        self.subheader.config(
            text=f"{bpm:.2f} BPM   ·   {dur:.2f}s loop   ·   "
                 f"{track.n_stems} stems   ·   "
                 f"{track.config_path.parent}")
        # Resize the seek slider's range to the new song's duration.
        self.seek_slider.config(from_=0.0, to=track.n_frames / track.sr)
        self.seek_var.set(0.0)

    # ---- song switching ------------------------------------------------- #
    def _switch_to(self, config_path: Path) -> None:
        try:
            track = load_track(config_path, normalize=self.normalize)
        except Exception as exc:
            self.subheader.config(text=f"load failed: {exc}")
            return
        self._build_strip(track)
        self._refresh_header(track)
        self._guard = True
        for idx in range(len(track.stem_names)):
            self.mute_vars[idx].set(False)
            self.vol_vars[idx].set(100.0)
        self._guard = False
        import numpy as np
        targets = np.ones(track.n_stems, dtype=np.float32)
        self.mixer.queue_swap(track, targets)

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
        if self._guard:
            return
        self.mixer.set_target(idx, self._effective_target(idx))

    def _all_max(self) -> None:
        """Reset every stem to 100% gain, unmuted."""
        self._guard = True
        for idx in range(len(self.mixer.track.stem_names)):
            self.mute_vars[idx].set(False)
            self.vol_vars[idx].set(100.0)
            self.mixer.set_target(idx, 1.0)
        self._guard = False

    # ---- seek bar ------------------------------------------------------ #
    def _on_seek_drag(self, _val: str) -> None:
        # While the user holds the slider down, update the label live;
        # the seek itself fires on release for fewer audio interruptions.
        if not self._seek_dragging:
            return
        sec = float(self.seek_var.get())
        total = self.mixer.track.n_frames / self.mixer.track.sr
        self.seek_lbl.config(text=f"{sec:5.1f} / {total:5.1f} s")

    def _on_seek_release(self, _event) -> None:
        sec = float(self.seek_var.get())
        self.mixer.seek_to(int(sec * self.mixer.track.sr))
        self._seek_dragging = False

    def _tick_seek(self) -> None:
        if not self._seek_dragging and self.mixer.track is not None:
            sr = self.mixer.track.sr
            sec = self.mixer.position / sr
            total = self.mixer.track.n_frames / sr
            self.seek_var.set(sec)
            self.seek_lbl.config(text=f"{sec:5.1f} / {total:5.1f} s")
        self.root.after(SEEK_REFRESH_MS, self._tick_seek)

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


def main() -> None:
    ap = argparse.ArgumentParser(description="Simple Stem Player")
    ap.add_argument("--library", default="songs",
                    help="Folder of song sub-dirs (default: ./songs).")
    ap.add_argument("--config",
                    help="Load a single song's config.json directly "
                         "(overrides --library).")
    ap.add_argument("--no-normalize", dest="normalize",
                    action="store_false",
                    help="Disable per-stem loudness normalization.")
    ap.set_defaults(normalize=True)
    args = ap.parse_args()

    songs = resolve_sources(args)
    print(f"Library: {len(songs)} song(s)   "
          f"[normalize={'on' if args.normalize else 'off'}]")
    for lbl, _ in songs:
        print(f"  - {lbl}")

    root = tk.Tk()
    gui = SimplePlayerGUI(root, songs, normalize=args.normalize)
    try:
        root.mainloop()
    finally:
        try:
            gui.mixer.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
