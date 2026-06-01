/**
 * Use case 01 — Stem mixer.
 *
 * Three example tracks (Tech house, Lo-fi, Synth pop), each generated
 * from a single Lyria prompt. Visitor picks a track via the tab row,
 * then mixes its four stems (drums, bass, melody, vocals) with
 * mute / solo / volume controls. One master play/pause.
 *
 * Mute and solo are mutually exclusive per stem.
 */

(function () {
    const STEMS = ["drums", "bass", "other", "vocals"];
    const N_BARS = 14;

    let mixer = null;
    let mixerEntry = null;
    let currentSongId = null;
    let rafHandle = 0;

    const state = Object.fromEntries(
        STEMS.map(s => [s, { volume: 1.0, muted: false, soloed: false }])
    );

    const els = {
        section:    document.getElementById("demo-adaptive"),
        tabs:       document.querySelectorAll(".dm-tab"),
        playBtn:    document.getElementById("dm-play"),
        status:     document.getElementById("dm-status"),
        stemEls:    {},
        volSliders: {},
        muteBtns:   {},
        soloBtns:   {},
        barSpans:   {},   // per-stem array of <span> elements (the bars)
    };
    for (const stem of STEMS) {
        els.stemEls[stem]    = document.querySelector(`.dm-stem[data-stem="${stem}"]`);
        els.volSliders[stem] = document.querySelector(`.dm-vol[data-stem="${stem}"]`);
        els.muteBtns[stem]   = document.querySelector(`.dm-mute[data-stem="${stem}"]`);
        els.soloBtns[stem]   = document.querySelector(`.dm-solo[data-stem="${stem}"]`);
        const barsRow = document.querySelector(`.dm-bars[data-stem="${stem}"]`);
        els.barSpans[stem] = barsRow ? Array.from(barsRow.querySelectorAll("span")) : [];
    }

    function track(name, props = {}) {
        try { window.va?.("event", { name, ...props }); } catch (_) {}
    }

    function setStatus(text, kind = "info") {
        if (!els.status) return;
        els.status.textContent = text;
        els.status.dataset.kind = kind;
    }

    function effectiveGain(stem) {
        const s = state[stem];
        if (s.muted) return 0;
        const anySoloed = STEMS.some(k => state[k].soloed);
        if (anySoloed && !s.soloed) return 0;
        return s.volume;
    }

    function pushGains(fadeSec = 0.15) {
        if (!mixer) return;
        for (const stem of STEMS) {
            mixer.setStemTarget(stem, effectiveGain(stem), fadeSec);
        }
    }

    function syncStemUI(stem) {
        const s = state[stem];
        const row = els.stemEls[stem];
        if (row) {
            row.classList.toggle("muted", s.muted);
            row.classList.toggle("soloed", s.soloed);
        }
        els.volSliders[stem].value = Math.round(s.volume * 100);
        els.muteBtns[stem].setAttribute("aria-pressed", s.muted);
        els.soloBtns[stem].setAttribute("aria-pressed", s.soloed);
    }

    function markActiveTab(songId) {
        currentSongId = songId;
        for (const tab of els.tabs) {
            const active = tab.dataset.song === songId;
            tab.classList.toggle("active", active);
            tab.setAttribute("aria-selected", active);
        }
    }

    async function loadManifest() {
        const resp = await fetch("audio/manifest.json");
        if (!resp.ok) {
            setStatus("Couldn't load manifest.json", "error");
            return null;
        }
        return resp.json();
    }

    async function loadSong(songId) {
        if (!mixerEntry) {
            const m = await loadManifest();
            if (!m) return;
            mixerEntry = m.mixer;
        }
        const song = mixerEntry.songs.find(s => s.id === songId);
        if (!song) return;

        markActiveTab(songId);

        if (!mixer) mixer = new StemMixer(STEMS);

        // Hard-stop the previous song's sources before loading new
        // buffers. hardStop schedules each src.stop() at the audio
        // clock, bound to that specific src — so no setTimeout race
        // can leave the old song playing under the new one.
        const wasPlaying = mixer.playing;
        if (wasPlaying) mixer.hardStop();

        const files = {};
        for (const spec of mixerEntry.stems) files[spec.name] = spec.file;

        setStatus(`Loading ${song.label}…`, "info");
        try {
            await mixer.load(`audio/${song.base}`, files,
                (stem, done, total) => setStatus(`Loading ${stem} (${done}/${total})…`, "info"));
            pushGains(0.05);
            setStatus(`${song.label}  ·  ready`, "info");
            track("demo_a_song", { song: songId });

            if (wasPlaying) {
                mixer.play();
                if (els.playBtn) {
                    els.playBtn.textContent = "Pause";
                    els.playBtn.classList.add("playing");
                }
                if (!rafHandle) loop();
            }
        } catch (err) {
            console.error(err);
            setStatus(`Load failed: ${err.message}`, "error");
        }
    }

    async function onPlay() {
        // Lazy-load the default song the first time play is pressed.
        if (!mixer || !mixer.loaded) {
            await loadSong(currentSongId || mixerEntry?.default_song || "tech-house");
            if (!mixer || !mixer.loaded) return;
        }
        const playing = mixer.toggle();
        if (els.playBtn) {
            els.playBtn.textContent = playing ? "Pause" : "Play";
            els.playBtn.classList.toggle("playing", playing);
        }
        track(playing ? "demo_a_play" : "demo_a_pause", { song: currentSongId });
        if (playing) {
            window.StemForgePlay?.notifyPlay("demo-mixer");
            if (!rafHandle) loop();
        }
    }

    // If any *other* demo starts playing, pause this one.
    window.StemForgePlay?.onOtherPlayed("demo-mixer", () => {
        if (!mixer || !mixer.playing) return;
        mixer.pause();
        if (els.playBtn) {
            els.playBtn.textContent = "Play";
            els.playBtn.classList.remove("playing");
        }
    });

    function clearBars() {
        for (const stem of STEMS) {
            const spans = els.barSpans[stem];
            if (!spans) continue;
            for (const span of spans) span.style.setProperty("--h", "0");
        }
    }

    function loop() {
        if (!mixer || !mixer.playing) {
            cancelAnimationFrame(rafHandle);
            rafHandle = 0;
            clearBars();
            return;
        }
        // Classical multi-bar spectrum per stem. We grab N log-spaced
        // band magnitudes and drive each <span>'s --h. The volume
        // slider is intentionally NOT touched — it shows what the user
        // set, the bars show what's actually playing.
        for (const stem of STEMS) {
            const spans = els.barSpans[stem];
            if (!spans || !spans.length) continue;
            const bars = mixer.stemBars(stem, N_BARS);
            for (let i = 0; i < spans.length && i < bars.length; i++) {
                spans[i].style.setProperty("--h", bars[i].toFixed(3));
            }
        }
        rafHandle = requestAnimationFrame(loop);
    }

    function wire() {
        if (!els.section) return;

        els.playBtn?.addEventListener("click", onPlay);

        for (const tab of els.tabs) {
            tab.addEventListener("click", () => {
                const songId = tab.dataset.song;
                if (songId && songId !== currentSongId) loadSong(songId);
            });
        }

        for (const stem of STEMS) {
            els.volSliders[stem].addEventListener("input", () => {
                state[stem].volume = els.volSliders[stem].value / 100;
                state[stem].muted = false;
                syncStemUI(stem);
                pushGains(0.08);
            });
            els.volSliders[stem].addEventListener("change", () => {
                track("demo_a_volume", { stem, value: state[stem].volume });
            });
            els.muteBtns[stem].addEventListener("click", () => {
                state[stem].muted = !state[stem].muted;
                if (state[stem].muted) state[stem].soloed = false;
                syncStemUI(stem);
                pushGains();
                track("demo_a_mute", { stem, muted: state[stem].muted });
            });
            els.soloBtns[stem].addEventListener("click", () => {
                state[stem].soloed = !state[stem].soloed;
                if (state[stem].soloed) state[stem].muted = false;
                syncStemUI(stem);
                pushGains();
                track("demo_a_solo", { stem, soloed: state[stem].soloed });
            });
            syncStemUI(stem);
        }

        // Default-active tab seeds currentSongId so the first Play knows
        // which song to load.
        const active = document.querySelector(".dm-tab.active");
        if (active) currentSongId = active.dataset.song;

        setStatus("Press play to start", "info");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", wire);
    } else {
        wire();
    }
})();
