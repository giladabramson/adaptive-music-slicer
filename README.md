# Adaptive AI Music Engine — local CLI prototype

Takes a flat track — supplied **or generated from a text prompt** — and
produces **adaptive, loop-ready instrument stems** + a `config.json`
the runtime player consumes.

```
 text prompt ──0. MusicGen (Hugging Face) ──┐   (optional source)
                                            ▼
       input_track.mp3 / generated_input.wav
                     │
   ├─ 1. Demucs   ── drums / bass / other / vocals  (4 stems)
   ├─ 2. Librosa  ── BPM + beat grid ── exact N-bar LoopPlan
   ├─ 3. pydub    ── slice every stem at the SAME loop window
   └─ 4. JSON     ── config.json (bpm, loop points, layers+emotions)
```

> **MusicGen is instrumental.** Meta trained it without vocals, so the
> separated `vocals` stem will be near-silent on generated tracks. Real
> sung vocals would need a separate model (e.g. Bark) layered on — not
> included here.

## Install

```powershell
# from c:\dev — reuse the workspace virtualenv
.\.venv\Scripts\Activate.ps1
cd adaptive_music_engine
pip install -r requirements.txt
```

`pip install -r requirements.txt` resolves to:

```
pip install "demucs>=4.0.0" "librosa>=0.10.1" "pydub>=0.25.1" "soundfile>=0.12.1" "numpy>=1.24"
```

`demucs` automatically pulls in `torch` / `torchaudio` (CPU build is
fine for an MVP — separation just runs slower).

### ffmpeg (system dependency — not pip-installable)

**Required** — not optional. Demucs writes its intermediate stems as
MP3 (see note below), and pydub needs ffmpeg to read them back for
slicing. It's also used for MP3 input decoding and MP3 export.

```powershell
winget install Gyan.FFmpeg     # then restart the shell
ffmpeg -version                # verify it's on PATH
```

> If `winget` is unavailable, drop a static `ffmpeg.exe` / `ffprobe.exe`
> onto PATH (e.g. into your venv's `Scripts/`, which is on PATH while
> the venv is activated).

### Note: why Demucs stems are MP3

On `torch`/`torchaudio` ≥ 2.9, Demucs' WAV writer (`torchaudio.save`)
requires the optional, FFmpeg-linked `torchcodec` package (poor Windows
support). Its MP3 writer uses the bundled `lameenc` and has no such
dependency, so the engine separates to 320 kbps MP3 (near-transparent)
by default. This is purely the *intermediate* format — the final loop
is re-exported to whatever `--format` you choose (WAV by default, so
your delivered loops are still lossless from that point on).

## Generate the source track (MusicGen)

Skip `--input` and pass `--generate` to synthesise the source with
Hugging Face MusicGen, then run the same pipeline on it. The generated
audio is kept at `output/generated_input.wav`.

```powershell
python -m adaptive_music_engine `
    --generate "energetic synthwave, punchy kick, deep bassline, 120 bpm" `
    --gen-duration 30 --gen-seed 42 -o .\output --bars 8 -v
```

First `--generate` run downloads ~2 GB of weights to the HF cache;
CPU inference takes minutes (a GPU is far faster). Keep
`--gen-duration` long enough for the loop you cut (≥16 s for 8 bars
@120 BPM). `--input` and `--generate` are mutually exclusive.

## Run

```powershell
# Default: 16-bar loop, analyse the original mix, export WAV
python -m adaptive_music_engine -i input_track.mp3 -o .\output

# 32-bar loop, analyse the drums stem (cleanest beat tracking), MP3 out
python -m adaptive_music_engine -i song.wav -o .\out --bars 32 `
    --analysis-source drums --format mp3

# Lock a known tempo, custom emotion tags, keep Demucs temp files
python -m adaptive_music_engine -i song.wav --manual-bpm 128 `
    --emotion drums=climax --emotion other=ambient --keep-temp
```

`python -m adaptive_music_engine --help` lists every flag.

## Output

```
output/
├── drums.wav
├── bass.wav
├── other.wav
├── vocals.wav
└── config.json
```

Example `config.json`:

```json
{
  "track_name": "input_track",
  "detected_bpm": 120.0,
  "loop_start_ms": 512,
  "loop_end_ms": 32512,
  "loop_duration_ms": 32000,
  "bars": 16,
  "beats_per_bar": 4,
  "total_beats": 64,
  "sample_rate": 44100,
  "layers": [
    { "name": "drums",  "file": "drums.wav",  "emotion": "high_energy" },
    { "name": "bass",   "file": "bass.wav",   "emotion": "suspense" },
    { "name": "other",  "file": "other.wav",  "emotion": "melody" },
    { "name": "vocals", "file": "vocals.wav", "emotion": "lead" }
  ]
}
```

## Why the loops don't click or drift

The loop **length** is computed from the detected tempo
(`bars × beats_per_bar × 60 / BPM`), **not** measured between two noisy
detected beats — so it's an exact whole number of beats. All four stems
are sliced with the *same* `loop_start_ms`/`loop_end_ms`, quantised to
integer ms exactly once, so they stay phase-locked and the seam error
stays sub-millisecond (inaudible). Full reasoning is documented in
[adaptive_music_engine/analysis.py](adaptive_music_engine/analysis.py).

Loop length follows the *detected* BPM, so a track you know is exactly
120 BPM may estimate as e.g. 120.19 and yield a 31.95 s (not 32.00 s)
16-bar loop. Pass `--manual-bpm 120` to pin the tempo and get the exact
mathematical loop length.

## Use as a library

```python
from pathlib import Path
from adaptive_music_engine import run_pipeline

result = run_pipeline(Path("song.wav"), Path("./output"), bars=32)
print(result.plan.detected_bpm, result.config_path)
```

## Layout

| File | Step | Responsibility |
|---|---|---|
| `generation.py` | 0 | MusicGen text→music (optional source) |
| `separation.py` | 1 | Demucs subprocess → 4 stems |
| `analysis.py`   | 2 | Librosa BPM/beats → `LoopPlan` |
| `slicing.py`    | 3 | pydub slice + export |
| `metadata.py`   | 4 | build/write `config.json` |
| `pipeline.py`   | — | orchestrates 0–4, temp cleanup |
| `cli.py`        | — | argparse front-end |
| `errors.py`     | — | typed exception hierarchy |
