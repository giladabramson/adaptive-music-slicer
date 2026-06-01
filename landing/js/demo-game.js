/**
 * Use case 02 — Adaptive game music.
 *
 * One generated track (combat scene, 4 stems). Two "game state" buttons
 * (Exploration / Combat) crossfade the stem gains over ~1 s to reshape
 * the mix without restarting playback. The per-stem meters dance with
 * actual audio energy thanks to the per-stem analysers on StemMixer.
 *
 * Cooperates with other demos via the StemForgePlay event coordinator.
 */

(function () {
    const FADE_SEC = 1.0;
    const STEMS = ["drums", "bass", "other", "vocals"];

    // Defaults mirror what the desktop player ships with — they appear
    // before the manifest finishes loading so the bars never start
    // blank.
    const DEFAULT_PRESETS = {
        Exploration: { drums: 0.0, bass: 0.2, other: 1.0, vocals: 0.3 },
        Combat:      { drums: 1.0, bass: 1.0, other: 0.7, vocals: 0.5 },
    };

    let mixer = null;
    let manifestEntry = null;
    let currentMode = "Exploration";

    const els = {
        section:   document.getElementById("demo-game"),
        playBtn:   document.getElementById("dg-play"),
        modeBtns:  document.querySelectorAll(".dg-mode"),
        status:    document.getElementById("dg-status"),
        intensity: document.getElementById("dg-intensity"),
        meters:    {},
    };
    for (const stem of STEMS) {
        els.meters[stem] = document.getElementById(`dg-meter-${stem}`);
    }

    function track(name, props = {}) {
        try { window.va?.("event", { name, ...props }); } catch (_) {}
    }

    function setStatus(text, kind = "info") {
        if (!els.status) return;
        els.status.textContent = text;
        els.status.dataset.kind = kind;
    }

    function presetFor(mode) {
        return (manifestEntry && manifestEntry.modes && manifestEntry.modes[mode])
            || DEFAULT_PRESETS[mode]
            || {};
    }

    function paintMeters(preset) {
        // The bars show each stem's *participation* in the current
        // mode — same idea as the desktop GUI's per-stem sliders.
        // CSS supplies the smooth crossfade transition so the visual
        // slide matches the audio crossfade.
        for (const stem of STEMS) {
            const m = els.meters[stem];
            if (!m) continue;
            const v = Math.max(0, Math.min(1, preset[stem] ?? 0));
            m.style.setProperty("--level", `${(v * 100).toFixed(1)}%`);
        }
    }

    function markActiveMode(mode) {
        currentMode = mode;
        for (const btn of els.modeBtns) {
            const active = btn.dataset.mode === mode;
            btn.classList.toggle("active", active);
            btn.setAttribute("aria-pressed", active);
        }
        if (els.intensity) els.intensity.dataset.mode = mode.toLowerCase();
        paintMeters(presetFor(mode));
    }

    async function loadManifest() {
        const resp = await fetch("audio/manifest.json");
        if (!resp.ok) { setStatus("Couldn't load manifest.json", "error"); return null; }
        return resp.json();
    }

    async function ensureLoaded() {
        if (mixer && mixer.loaded) return mixer;
        if (!manifestEntry) {
            const m = await loadManifest();
            if (!m) return null;
            manifestEntry = m.adaptive_combat;
        }
        if (!mixer) mixer = new StemMixer(STEMS);
        const files = {};
        for (const s of manifestEntry.stems) files[s.name] = s.file;
        setStatus("Loading stems…", "info");
        await mixer.load(`audio/${manifestEntry.base}`, files,
            (stem, done, total) => setStatus(`Loading ${stem} (${done}/${total})…`, "info"));
        mixer.applyPreset(manifestEntry.modes?.Exploration ||
            { drums: 0, bass: 0.2, other: 1.0, vocals: 0.3 }, 0.05);
        markActiveMode("Exploration");
        setStatus("Ready · press play", "info");
        return mixer;
    }

    async function onPlay() {
        const m = await ensureLoaded();
        if (!m) return;
        const playing = m.toggle();
        if (els.playBtn) {
            els.playBtn.textContent = playing ? "Pause" : "Play";
            els.playBtn.classList.toggle("playing", playing);
        }
        track(playing ? "demo_g_play" : "demo_g_pause", { mode: currentMode });
        if (playing) {
            window.StemForgePlay?.notifyPlay("demo-game");
        }
    }

    function onMode(mode) {
        const preset = presetFor(mode);
        if (mixer) mixer.applyPreset(preset, FADE_SEC);
        markActiveMode(mode);
        track("demo_g_mode", { mode });
    }

    function wire() {
        if (!els.section) return;
        els.playBtn?.addEventListener("click", onPlay);
        for (const btn of els.modeBtns) {
            btn.addEventListener("click", () => onMode(btn.dataset.mode));
        }
        markActiveMode("Exploration");
        setStatus("Press play to start", "info");

        window.StemForgePlay?.onOtherPlayed("demo-game", () => {
            if (!mixer || !mixer.playing) return;
            mixer.pause();
            if (els.playBtn) {
                els.playBtn.textContent = "Play";
                els.playBtn.classList.remove("playing");
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", wire);
    } else {
        wire();
    }
})();
