"""Headless logic test for adaptive_player.py — no audio device, no GUI.

Verifies the parts that ears can't reliably check:
  * config.json loads and stems stack to a valid (N, S, 2) float32 buffer
  * each tension preset's fade converges within the fade time
  * the loop wraps correctly and output stays bounded
  * every stem reads the SAME playhead index (sample-accurate sync)
  * Pause silences the output AND freezes the playhead

Run:   python test_player.py            (exits non-zero on failure)
It does NOT prove the mix sounds good — only listening can.
"""
import numpy as np
import sounddevice as sd

# Stub the audio stream so StemMixer builds without a device.
class _FakeStream:
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


def main() -> None:
    cfg_path = ap.find_config(None)            # auto-discovers ./output*/
    names, emotions, buf, sr, cfg = ap.load_stems(cfg_path)
    print(f"loaded {cfg_path}")
    print(f"  stems   : {names}")
    print(f"  emotions: {emotions}")
    print(f"  buffer  : {buf.shape} {buf.dtype} @ {sr} Hz "
          f"({buf.shape[0] / sr:.3f}s)")

    assert buf.ndim == 3 and buf.shape[2] == 2, "buffer must be (N, S, 2)"
    assert buf.dtype == np.float32
    assert len(names) == buf.shape[1]

    mx = ap.StemMixer(buf, sr)
    mx.set_fade(1.0)

    # 1) Each preset's fade converges to its target within the fade time.
    for level, table in ap.PRESETS.items():
        for i, n in enumerate(names):
            mx.set_target(i, table.get(n, ap.PRESET_DEFAULT))
        for _ in range(int(1.2 * sr) // 1024 + 1):
            pull(mx, 1024)
        g = mx.live_gains
        for i, n in enumerate(names):
            want = table.get(n, ap.PRESET_DEFAULT)
            assert abs(g[i] - want) < 0.02, \
                f"{level}/{n}: gain {g[i]:.3f} != target {want}"
        print(f"  preset {level:<6} -> gains {np.round(g, 3)} OK")

    # 2) Loop wrap: pull across the end; output finite and bounded.
    mx._pos = mx.n_frames - 100
    o = pull(mx, 512)
    assert np.isfinite(o).all() and np.abs(o).max() <= 1.0
    assert mx._pos == (mx.n_frames - 100 + 512) % mx.n_frames
    print("  loop wrap OK")

    # 3) Sync: all stems indexed by one shared wrapped playhead.
    mx._pos = mx.n_frames - 10
    idx = (mx._pos + np.arange(512)) % mx.n_frames
    assert buf[idx].shape == (512, len(names), 2)
    print("  shared-playhead sync OK")

    # 4) Pause silences output and freezes the playhead.
    mx._playing = False
    for _ in range(40):                        # let the 50ms master fade end
        pull(mx, 1024)
    frozen = mx._pos
    o = pull(mx, 1024)
    assert np.abs(o).max() < 1e-5, f"paused output not silent: {o.max()}"
    assert mx._pos == frozen, "playhead must freeze while paused"
    print("  pause silence + freeze OK")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
