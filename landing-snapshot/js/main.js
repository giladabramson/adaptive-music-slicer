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
    viz:         document.getElementById("viz"),
    vizWrap:     document.getElementById("viz-wrap"),
    seekbar:     document.getElementById("seekbar"),
    progress:    document.getElementById("seekbar-progress"),
    thumb:       document.getElementById("seekbar-thumb"),
    timeCurrent: document.getElementById("time-current"),
    timeTotal:   document.getElementById("time-total"),
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
            // Mute and Solo are mutually exclusive per stem — toggling
            // one clears the other so the row never lies about its state.
            if (stemState[stem].muted) stemState[stem].soloed = false;
            syncStemUI(stem);
            pushStems(0.15);
            markCustomMix();
            track("stem_mute", { stem, muted: stemState[stem].muted });
        });

        els.soloBtns[stem].addEventListener("click", () => {
            stemState[stem].soloed = !stemState[stem].soloed;
            if (stemState[stem].soloed) stemState[stem].muted = false;
            syncStemUI(stem);
            pushStems(0.15);
            markCustomMix();
            track("stem_solo", { stem, soloed: stemState[stem].soloed });
        });
    }
}

function tickMeters() {
    const gains = player.liveGains();
    for (const stem of STEMS) {
        const bar = els.meters[stem];
        if (!bar) continue;
        bar.style.setProperty("--level", `${(gains[stem] || 0) * 100}%`);
    }
    drawSpectrum();
    updateSeekbar();
    requestAnimationFrame(tickMeters);
}

// --- seekbar --------------------------------------------------------------

let seekbarDragging = false;

function fmtTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

function updateSeekbar() {
    if (!els.seekbar) return;
    const dur = player.loopDurationSec;
    const pos = seekbarDragging ? seekbarDraggingPos : player.positionSec;
    const pct = dur > 0 ? (pos / dur) * 100 : 0;
    els.progress.style.width = `${pct}%`;
    els.thumb.style.left = `${pct}%`;
    els.timeCurrent.textContent = fmtTime(pos);
    els.timeTotal.textContent = fmtTime(dur);
    els.seekbar.setAttribute("aria-valuenow", Math.round(pct));
}

let seekbarDraggingPos = 0;

function seekFromEvent(ev) {
    const rect = els.seekbar.getBoundingClientRect();
    const clientX = ev.touches ? ev.touches[0].clientX : ev.clientX;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return ratio * player.loopDurationSec;
}

function wireSeekbar() {
    if (!els.seekbar) return;

    const onMove = (ev) => {
        if (!seekbarDragging) return;
        seekbarDraggingPos = seekFromEvent(ev);
        updateSeekbar();
    };
    const onUp = (ev) => {
        if (!seekbarDragging) return;
        seekbarDragging = false;
        const target = seekFromEvent(ev);
        player.seek(target);
        track("seek", { position_sec: Math.round(target * 10) / 10 });
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
    };

    els.seekbar.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        if (!player.currentSong) return;
        seekbarDragging = true;
        seekbarDraggingPos = seekFromEvent(ev);
        updateSeekbar();
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
    });

    // Keyboard accessibility — left/right arrows nudge by 5%, home/end jump.
    els.seekbar.addEventListener("keydown", (ev) => {
        const dur = player.loopDurationSec;
        if (!dur) return;
        const step = dur * 0.05;
        let target = null;
        if (ev.key === "ArrowLeft")       target = player.positionSec - step;
        else if (ev.key === "ArrowRight") target = player.positionSec + step;
        else if (ev.key === "Home")       target = 0;
        else if (ev.key === "End")        target = dur - 0.1;
        if (target !== null) {
            ev.preventDefault();
            player.seek(Math.max(0, Math.min(dur, target)));
        }
    });
}

// --- audio visualizer ----------------------------------------------------

const VIZ_BARS = 56;
let vizCtx = null;

function resizeViz() {
    const canvas = els.viz;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width  = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    vizCtx = canvas.getContext("2d");
    vizCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawSpectrum() {
    if (!els.viz || !vizCtx) return;
    const canvas = els.viz;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    vizCtx.clearRect(0, 0, w, h);

    const spec = player.readSpectrum();
    // Pull only the low-mid range — the high bins are mostly empty on
    // game music and would visually flatline. ~first 60% of the bins.
    const usable = Math.floor(spec.length * 0.6);
    const step = Math.max(1, Math.floor(usable / VIZ_BARS));
    const gap = 3;
    const barW = (w - gap * (VIZ_BARS - 1)) / VIZ_BARS;

    // Soft underlying gradient — kept dim until there's signal so the
    // visualizer fades in with the music instead of glowing on idle.
    const grad = vizCtx.createLinearGradient(0, h, 0, 0);
    grad.addColorStop(0, "rgba(167, 139, 250, 0.55)");
    grad.addColorStop(0.6, "rgba(103, 232, 249, 0.85)");
    grad.addColorStop(1, "rgba(245, 184, 90, 0.95)");

    let totalSignal = 0;
    for (let i = 0; i < VIZ_BARS; i++) {
        let peak = 0;
        for (let j = 0; j < step; j++) {
            const v = spec[i * step + j];
            if (v > peak) peak = v;
        }
        totalSignal += peak;
        // Logarithmic feel for nicer dynamics; floor at 2px so the
        // baseline doesn't disappear entirely between hits.
        const norm = peak / 255;
        const barH = Math.max(2, Math.pow(norm, 1.4) * (h - 6));
        const x = i * (barW + gap);
        const y = h - barH;
        vizCtx.fillStyle = grad;
        vizCtx.fillRect(x, y, barW, barH);
    }

    // Toggle "playing" class so the placeholder text fades.
    if (els.vizWrap) {
        const isLive = totalSignal > 50;
        els.vizWrap.classList.toggle("playing", isLive && player.playing);
    }
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

    resizeViz();
    window.addEventListener("resize", resizeViz);

    wireScrollReveal();
    wireStickyBar();
    wireSeekbar();
    wireSampleCards();

    renderMeta(songByName(els.songPicker.value));
    setStatus("Press play to start", "info");
    requestAnimationFrame(tickMeters);
}

/** Fade-in + lift sections as they scroll into view. One-shot per element. */
function wireScrollReveal() {
    const targets = document.querySelectorAll("[data-reveal]");
    if (!("IntersectionObserver" in window) || targets.length === 0) {
        // Older browsers: just show everything.
        targets.forEach(el => el.classList.add("is-visible"));
        return;
    }
    const obs = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                obs.unobserve(entry.target);
            }
        }
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    targets.forEach(el => obs.observe(el));
}

/** Sample-track cards: clicking one loads that song into the main player
 * and scrolls to it. Reuses the main player rather than spawning a second.
 */
function wireSampleCards() {
    const cards = document.querySelectorAll(".sample-card[data-song]");
    cards.forEach(card => {
        card.addEventListener("click", async () => {
            const name = card.dataset.song;
            if (!name) return;
            track("sample_card_click", { song: name });
            els.songPicker.value = name;
            await pickSong(name);
            document.getElementById("player").scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
            await player.unlock();
            if (!player.playing) {
                player.play();
                els.playBtn.textContent = "Pause";
                els.playBtn.classList.add("playing");
            }
        });
    });
}

/** Show the sticky condensed header once the hero scrolls out of view. */
function wireStickyBar() {
    const bar = document.getElementById("sticky-bar");
    const hero = document.querySelector(".hero");
    if (!bar || !hero || !("IntersectionObserver" in window)) return;
    const obs = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            bar.dataset.visible = entry.isIntersecting ? "false" : "true";
        }
    }, { rootMargin: "-40% 0px 0px 0px", threshold: 0 });
    obs.observe(hero);
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
