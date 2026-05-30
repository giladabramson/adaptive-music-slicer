/**
 * Page wiring: load the manifest, populate the song picker, hook up
 * the play/pause + tension preset buttons, and drive the level meters.
 *
 * Also fires custom analytics events through Vercel Analytics' `window.va`.
 * The wrapper is a no-op when VA isn't present (local dev, other hosts),
 * so the same code works in every environment.
 */

const SONGS_BASE = "songs";

function track(name, props = {}) {
    try {
        window.va?.("event", { name, ...props });
    } catch (_) { /* never let analytics break the UX */ }
}

const STEMS = ["drums", "bass", "other", "vocals"];

const els = {
    songPicker:  document.getElementById("song-picker"),
    songMeta:    document.getElementById("song-meta"),
    playBtn:     document.getElementById("play-btn"),
    presetBtns:  document.querySelectorAll("[data-preset]"),
    fadeRange:   document.getElementById("fade-range"),
    fadeValue:   document.getElementById("fade-value"),
    status:      document.getElementById("status"),
    stemRows:    {},
    volSliders:  {},
    muteBtns:    {},
    soloBtns:    {},
    meters:      {},
};
for (const stem of STEMS) {
    els.stemRows[stem]   = document.querySelector(`.stem[data-stem="${stem}"]`);
    els.volSliders[stem] = document.querySelector(`.stem-vol[data-stem="${stem}"]`);
    els.muteBtns[stem]   = document.querySelector(`.stem-mute[data-stem="${stem}"]`);
    els.soloBtns[stem]   = document.querySelector(`.stem-solo[data-stem="${stem}"]`);
    els.meters[stem]     = document.getElementById(`meter-${stem}`);
}

const player = new AdaptivePlayer();
let manifest = null;
let currentPreset = "Medium";

// Per-stem state — the manual controls drive this; the preset buttons
// just snap it to known values. The effective gain we send to the audio
// engine is computed from this struct (see effectiveGain).
const stemState = Object.fromEntries(
    STEMS.map(s => [s, { volume: 1.0, muted: false, soloed: false }])
);

function setStatus(text, kind = "info") {
    els.status.textContent = text;
    els.status.dataset.kind = kind;
}

function bpmLabel(bpm) {
    return bpm ? `${bpm.toFixed(1)} BPM` : "—";
}

function songLabel(meta) {
    return `${meta.name}  ·  ${meta.track_name || meta.name}`;
}

async function loadManifest() {
    const resp = await fetch(`${SONGS_BASE}/manifest.json`);
    if (!resp.ok) {
        setStatus(`Couldn't load manifest.json (${resp.status}). ` +
                  `Run landing/build_assets.py first.`, "error");
        return null;
    }
    return resp.json();
}

function populatePicker(m) {
    els.songPicker.innerHTML = "";
    for (const song of m.songs) {
        const opt = document.createElement("option");
        opt.value = song.name;
        opt.textContent = songLabel(song);
        els.songPicker.appendChild(opt);
    }
    els.songPicker.value = m.featured || m.songs[0].name;
}

function songByName(name) {
    return manifest.songs.find(s => s.name === name);
}

function renderMeta(meta) {
    const bars = meta.bars ? `${meta.bars} bars` : "";
    const loop = meta.loop_duration_ms
        ? `${(meta.loop_duration_ms / 1000).toFixed(2)}s loop`
        : "";
    els.songMeta.textContent = [bpmLabel(meta.bpm), bars, loop]
        .filter(Boolean)
        .join("  ·  ");
}

async function pickSong(name) {
    const meta = songByName(name);
    if (!meta) return;
    renderMeta(meta);
    setStatus(`Loading ${meta.name}…`, "info");
    try {
        await player.loadSong(meta, SONGS_BASE, {
            onProgress: (_stem, done, total) => {
                setStatus(`Loading ${meta.name} (${done}/${total})…`, "info");
            },
        });
        applyPreset(currentPreset);
        setStatus(`Ready · press play`, "info");
    } catch (err) {
        console.error(err);
        setStatus(`Load failed: ${err.message}`, "error");
    }
}

function effectiveGain(stem) {
    const s = stemState[stem];
    if (s.muted) return 0;
    const anySoloed = STEMS.some(k => stemState[k].soloed);
    if (anySoloed && !s.soloed) return 0;
    return s.volume;
}

/** Push every stem's current effective gain to the audio engine. */
function pushStems(fadeSec) {
    for (const stem of STEMS) {
        player.setStemTarget(stem, effectiveGain(stem), fadeSec);
    }
}

/** A manual control was touched — strip the preset highlight. */
function markCustomMix() {
    currentPreset = null;
    for (const btn of els.presetBtns) btn.classList.remove("active");
}

function syncStemUI(stem) {
    const s = stemState[stem];
    els.volSliders[stem].value = Math.round(s.volume * 100);
    els.muteBtns[stem].setAttribute("aria-pressed", s.muted);
    els.soloBtns[stem].setAttribute("aria-pressed", s.soloed);
    els.stemRows[stem].classList.toggle("muted", s.muted);
    els.stemRows[stem].classList.toggle("soloed", s.soloed);
}

function applyPreset(name) {
    const table = PRESETS[name];
    if (!table) return;
    currentPreset = name;
    for (const stem of STEMS) {
        stemState[stem].volume = table[stem];
        stemState[stem].muted = false;
        stemState[stem].soloed = false;
        syncStemUI(stem);
    }
    pushStems(player.fadeSec);
    for (const btn of els.presetBtns) {
        btn.classList.toggle("active", btn.dataset.preset === name);
    }
}

function wireStemControls() {
    for (const stem of STEMS) {
        els.volSliders[stem].addEventListener("input", () => {
            stemState[stem].volume = els.volSliders[stem].value / 100;
            // If we were muted, dragging the volume should imply un-mute.
            stemState[stem].muted = false;
            syncStemUI(stem);
            // Short ramp while dragging so it feels live but not glitchy.
            pushStems(0.08);
            markCustomMix();
        });
        els.volSliders[stem].addEventListener("change", () => {
            track("stem_volume", { stem, volume: stemState[stem].volume });
        });

        els.muteBtns[stem].addEventListener("click", () => {
            stemState[stem].muted = !stemState[stem].muted;
            syncStemUI(stem);
            pushStems(0.15);
            markCustomMix();
            track("stem_mute", { stem, muted: stemState[stem].muted });
        });

        els.soloBtns[stem].addEventListener("click", () => {
            stemState[stem].soloed = !stemState[stem].soloed;
            syncStemUI(stem);
            pushStems(0.15);
            markCustomMix();
            track("stem_solo", { stem, soloed: stemState[stem].soloed });
        });
    }
}

function tickMeters() {
    const gains = player.liveGains();
    for (const stem of ["drums", "bass", "other", "vocals"]) {
        const bar = els.meters[stem];
        if (!bar) continue;
        bar.style.setProperty("--level", `${(gains[stem] || 0) * 100}%`);
    }
    requestAnimationFrame(tickMeters);
}

async function main() {
    manifest = await loadManifest();
    if (!manifest) return;
    populatePicker(manifest);

    els.songPicker.addEventListener("change", () => {
        track("song_change", { song: els.songPicker.value });
        pickSong(els.songPicker.value);
    });

    els.playBtn.addEventListener("click", async () => {
        await player.unlock();
        if (!player.currentSong) {
            await pickSong(els.songPicker.value);
        }
        const playing = player.toggle();
        els.playBtn.textContent = playing ? "Pause" : "Play";
        els.playBtn.classList.toggle("playing", playing);
        track(playing ? "play" : "pause", {
            song: player.currentSong?.name,
        });
    });

    for (const btn of els.presetBtns) {
        btn.addEventListener("click", () => {
            applyPreset(btn.dataset.preset);
            track("preset", {
                preset: btn.dataset.preset,
                song: player.currentSong?.name,
            });
        });
    }

    wireStemControls();

    els.fadeRange.addEventListener("input", () => {
        const v = parseFloat(els.fadeRange.value);
        player.setFadeSeconds(v);
        els.fadeValue.textContent = `${v.toFixed(1)}s`;
    });

    wireInterestForm();

    renderMeta(songByName(els.songPicker.value));
    setStatus("Press play to start", "info");
    requestAnimationFrame(tickMeters);
}

function wireInterestForm() {
    const form = document.getElementById("interest-form");
    const status = document.getElementById("interest-status");
    if (!form || !status) return;

    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const email = form.email.value.trim();
        if (!email) return;

        // If the form ID is still the placeholder, surface that loud and
        // clear — better than silently swallowing the click.
        if (form.action.includes("YOUR_FORM_ID")) {
            status.hidden = false;
            status.textContent =
                "Form not wired yet — set up a Formspree form and replace " +
                "YOUR_FORM_ID in index.html.";
            status.dataset.kind = "error";
            return;
        }

        status.hidden = false;
        status.textContent = "Sending…";
        status.dataset.kind = "info";

        try {
            const resp = await fetch(form.action, {
                method: "POST",
                headers: { Accept: "application/json" },
                body: new FormData(form),
            });
            if (resp.ok) {
                form.reset();
                status.textContent = "Got it — I'll be in touch when there's something to try.";
                status.dataset.kind = "ok";
                track("signup");
            } else {
                status.textContent = `Couldn't submit (HTTP ${resp.status}). Try again later.`;
                status.dataset.kind = "error";
            }
        } catch (err) {
            status.textContent = `Network error: ${err.message}`;
            status.dataset.kind = "error";
        }
    });
}

main();
