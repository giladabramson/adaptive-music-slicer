# Separator comparison

Baseline: **Demucs htdemucs** (current default in `separation.py`).

Hybrid: **BS-Roformer-Viperx-1296** for vocals, then **Demucs htdemucs_ft** for drums/bass/other on the residual instrumental.

Per-stem RMS in dBFS (higher = louder content present; values < -40 dB are near-silent — Demucs routed that frequency band to a different stem). Bleed = Pearson correlation of RMS envelopes between two stems; closer to 0 = cleaner separation.

## reggae

| stem | Demucs RMS | Hybrid RMS | Δ (hybrid−demucs) |
|---|---:|---:|---:|
| drums |  -25.6 dB |  -25.6 dB |   +0.1 dB |
| bass |  -18.2 dB |  -19.6 dB |   -1.4 dB |
| other |  -29.8 dB |  -29.8 dB |   +0.0 dB |
| vocals |  -18.0 dB |  -19.2 dB |   -1.2 dB |

**Bleed (lower magnitude = cleaner):**

| pair | Demucs | Hybrid |
|---|---:|---:|
| drums_x_bass | -0.078 | -0.071 |
| other_x_vocals | -0.015 | +0.040 |
| drums_x_other | -0.121 | -0.109 |
| bass_x_other | +0.059 | +0.089 |

**Runtime:** baseline 45.2 s, hybrid 32.6 s
