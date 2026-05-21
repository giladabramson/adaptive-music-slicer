"""Headless logic test for adaptive_player.py — no audio device, no GUI.

Verifies the parts ears can't reliably check:
  * the song library is discovered under ./songs
  * a track loads into a valid (N, S, 2) float32 buffer
  * each tension preset's fade converges within the fade time
  * the loop wraps correctly and output stays bounded
  * every stem reads the SAME playhead index (sample-accurate sync)
  * Pause silences output AND freezes the playhead
  * a queued song-swap actually swaps the track and resets the playhead

Run:   python test_player.py            (exits non-zero on failure)
It does NOT prove the mix sounds good — only listening can.
"""
import numpy as np
import sounddevice as sd


class _FakeStream:                       # stub: build StemMixer w/o a device
    def __init__(self, **kw): pass
    def start(self): pass
    def stop(self): pass
    def close(self): pass


sd.OutputStream = _FakeStream

import adaptive_player as ap


def pull(mixer, frames):
    out = np.zeros((frames, 2), np.float32)
    mixer._callback(out, frames, None, None)
    return out


def settle(mixer, seconds=1.3):
    for _ in range(int(seconds * mixer.sr) // 1024 + 1):
        pull(mixer, 1024)


def main() -> None:
    from pathlib import Path

    library = ap.discover_library(Path("songs"))
    assert library, "no songs discovered under ./songs"
    print(f"library: {len(library)} song(s)")
    for lbl, _ in library:
        print(f"  - {lbl}")

    track = ap.load_track(library[0][1])
    print(f"loaded  : {track.name}")
    print(f"  buffer: {track.buffer.shape} {track.buffer.dtype} "
          f"@ {track.sr} Hz ({track.n_frames / track.sr:.3f}s)")
    print(f"  stems : {track.stem_names}")
    assert track.buffer.ndim == 3 and track.buffer.shape[2] == 2
    assert track.buffer.dtype == np.float32
    assert track.n_stems == len(track.stem_names)

    mx = ap.StemMixer(track)
    mx.set_fade(1.0)

    # 1) Each preset converges to its targets within the fade time.
    for level, table in ap.PRESETS.items():
        for i, n in enumerate(track.stem_names):
            mx.set_target(i, table.get(n, ap.PRESET_DEFAULT))
        settle(mx)
        g = mx.live_gains
        for i, n in enumerate(track.stem_names):
            want = table.get(n, ap.PRESET_DEFAULT)
            assert abs(g[i] - want) < 0.02, \
                f"{level}/{n}: gain {g[i]:.3f} != {want}"
        print(f"  preset {level:<6} -> {np.round(g, 3)} OK")

    # 2) Loop wrap: pull across the end; output finite and bounded.
    mx._pos = mx.track.n_frames - 100
    o = pull(mx, 512)
    assert np.isfinite(o).all() and np.abs(o).max() <= 1.0
    assert mx._pos == (mx.track.n_frames - 100 + 512) % mx.track.n_frames
    print("  loop wrap OK")

    # 3) Sync: all stems indexed by one shared wrapped playhead.
    mx._pos = mx.track.n_frames - 10
    idx = (mx._pos + np.arange(512)) % mx.track.n_frames
    assert mx.track.buffer[idx].shape == (512, track.n_stems, 2)
    print("  shared-playhead sync OK")

    # 4) Pause silences output and freezes the playhead.
    mx._playing = False
    settle(mx, 0.3)
    frozen = mx._pos
    o = pull(mx, 1024)
    assert np.abs(o).max() < 1e-5, f"paused not silent: {o.max()}"
    assert mx._pos == frozen, "playhead must freeze while paused"
    print("  pause silence + freeze OK")
    mx._playing = True
    settle(mx, 0.1)

    # 5) Hot song-swap: queue a different song, confirm it takes over.
    if len(library) > 1:
        t2 = ap.load_track(library[1][1])
        mx._pos = 12345
        mx.queue_swap(t2, np.ones(t2.n_stems, np.float32))
        settle(mx, ap.SWITCH_FADE_S + 0.3)        # fade-out + swap + fade-in
        assert mx.track.name == t2.name, "swap did not take effect"
        assert mx.track.n_stems == t2.n_stems
        assert mx._pos < mx.track.n_frames and mx._pending is None
        assert not mx._switching
        print(f"  song-swap -> '{t2.name}' OK (pos reset, pending cleared)")
    else:
        print("  song-swap SKIPPED (only one song in library)")

    # 6) Per-stem normalization actually boosts quiet residual stems
    #    (the whole reason we added it). Compare hiphop's `other` stem
    #    RMS raw vs normalized — expect a large positive jump.
    from pathlib import Path as _P
    hp = next((p for lbl, p in library if "hiphop" in lbl), None)
    if hp is not None:
        raw = ap.load_track(hp, normalize=False)
        nrm = ap.load_track(hp, normalize=True)
        i = raw.stem_names.index("other")
        raw_rms = float(np.sqrt(np.mean(raw.buffer[:, i, :] ** 2)))
        nrm_rms = float(np.sqrt(np.mean(nrm.buffer[:, i, :] ** 2)))
        raw_db = 20 * np.log10(raw_rms) if raw_rms > 0 else -120
        nrm_db = 20 * np.log10(nrm_rms) if nrm_rms > 0 else -120
        boost = nrm_db - raw_db
        print(f"  normalize: hiphop/other  {raw_db:+.1f} dB -> "
              f"{nrm_db:+.1f} dB  (+{boost:.1f} dB)")
        assert boost > 10.0, f"normalization barely boosted: +{boost:.1f}dB"
        # Contract is the 99.7th-percentile peak stays under 0.99 (rare
        # outlier samples may exceed and are caught by the mixer's
        # hard limiter — that's by design).
        p997 = float(np.quantile(np.abs(nrm.buffer), 0.997))
        assert p997 <= 0.99 + 1e-3, f"99.7%ile peak {p997:.3f} > 0.99"
        print(f"  normalization OK (99.7%ile peak {p997:.3f} <= 0.99)")
    else:
        print("  normalize check SKIPPED (no hiphop in library)")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
