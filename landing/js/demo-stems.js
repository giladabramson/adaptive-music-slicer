/**
 * Demo B — Stem-generator A/B.
 *
 * Each row (drums / bass / atmosphere) offers the same instrument two
 * ways: Demucs-separated from a full mix, or generated directly by an
 * isolation prompt. The visitor clicks one button to play, clicks
 * another (or the same one) to switch or pause. Only one stem plays at
 * any time, so direct ear-comparison is easy.
 *
 * Web Audio under the hood for clean stop/start; buffers cached per URL.
 */

(function () {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    let ctx = null;
    let master = null;
    const buffers = new Map();   // url → AudioBuffer

    let currentSource = null;
    let currentButton = null;
    let currentUrl = null;
    // Track when (in ctx time) the current source started and what
    // buffer offset we started from. Together they let us compute the
    // playhead position so A↔B switches keep the listener in the
    // same musical place — they hear the same instant, just cleaned
    // or dirty.
    let startCtxTime = 0;
    let startOffset = 0;
    // Every play() call captures its own seq number; after awaits, it
    // checks the global to see if a newer click superseded it. Stops
    // rapid A↔B clicks from spawning orphan sources that play forever.
    let playSeq = 0;
    // Belt-and-suspenders: every BufferSource we create goes in here,
    // so stopAllSources() can clean up anything that slipped past
    // currentSource (e.g. if a race condition still occurs).
    const activeSources = new Set();

    const statusEl = document.getElementById("sc-status");

    function setStatus(text, kind = "info") {
        if (!statusEl) return;
        statusEl.textContent = text;
        statusEl.dataset.kind = kind;
    }

    function track(name, props = {}) {
        try { window.va?.("event", { name, ...props }); } catch (_) {}
    }

    function ensureCtx() {
        if (ctx) return ctx;
        ctx = new Ctx();
        master = ctx.createGain();
        master.gain.value = 1;
        master.connect(ctx.destination);
        return ctx;
    }

    async function fetchBuffer(url) {
        if (buffers.has(url)) return buffers.get(url);
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`fetch ${url} → ${resp.status}`);
        const bytes = await resp.arrayBuffer();
        const buf = await ctx.decodeAudioData(bytes);
        buffers.set(url, buf);
        return buf;
    }

    function stopAllSources() {
        for (const src of activeSources) {
            try { src.stop(); } catch (_) {}
            try { src.disconnect(); } catch (_) {}
        }
        activeSources.clear();
        currentSource = null;
    }

    function stop() {
        // Invalidate any in-flight play() promises so they don't
        // create a new source after we've torn everything down.
        playSeq++;
        stopAllSources();
        if (currentButton) currentButton.classList.remove("playing");
        currentButton = null;
        currentUrl = null;
        startCtxTime = 0;
        startOffset = 0;
    }

    /** Current playhead position in seconds within the current buffer. */
    function elapsedInBuffer() {
        if (!currentSource || !ctx) return 0;
        const buf = currentSource.buffer;
        if (!buf) return 0;
        const t = ctx.currentTime - startCtxTime + startOffset;
        return buf.duration > 0 ? (t % buf.duration) : 0;
    }

    async function play(button) {
        const url = button.dataset.audio;
        if (!url) return;

        // Toggle off if it's the same one currently playing.
        if (currentUrl === url) {
            stop();
            setStatus("Paused. Click any tile to play again.");
            track("demo_b_pause", { audio: url });
            return;
        }

        // Stamp this call so we can detect being superseded by a
        // newer click during the buffer-fetch await.
        const mySeq = ++playSeq;

        window.StemForgePlay?.notifyPlay("demo-stems");

        ensureCtx();
        if (ctx.state === "suspended") await ctx.resume();
        if (mySeq !== playSeq) return;

        // Look up the instrument from any ancestor that carries the
        // attribute — supports both the legacy .sc-row layout and the
        // hero A/B layout used in use case 03a.
        const ctxEl = button.closest("[data-instrument]");
        const instrument = ctxEl?.dataset.instrument || "?";
        const method = button.dataset.method || "?";

        // Capture the playhead BEFORE tearing down the current source —
        // that's how A↔B switches stay in the same musical place.
        const wasPlaying = currentSource !== null;
        const seekTo = wasPlaying ? elapsedInBuffer() : 0;

        stopAllSources();
        if (currentButton) currentButton.classList.remove("playing");

        setStatus(wasPlaying
            ? `Switching to ${method}…`
            : `Loading ${instrument} (${method})…`);

        try {
            const buf = await fetchBuffer(url);
            if (mySeq !== playSeq) return;

            // Clamp to the new buffer's length — A and B may differ in
            // duration by a fraction of a second after independent MP3
            // encodes.
            const offset = buf.duration > 0 ? (seekTo % buf.duration) : 0;

            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.loop = true;
            src.connect(master);
            const startAt = ctx.currentTime + 0.02;
            src.start(startAt, offset);
            activeSources.add(src);
            // If the buffer naturally ends (shouldn't with loop=true,
            // but defensive), remove ourselves from the active set so
            // we don't leak.
            src.onended = () => { activeSources.delete(src); };

            currentSource = src;
            currentButton = button;
            currentUrl = url;
            startCtxTime = startAt;
            startOffset = offset;

            button.classList.add("playing");
            setStatus(wasPlaying
                ? `Playing ${instrument} — ${method}. Same instant, ${method === "demucs" ? "cleaned" : "raw"}.`
                : `Playing ${instrument} — ${method}. Click the other tile to A/B at the same position.`);
            track("demo_b_play", { instrument, method, seek_s: offset.toFixed(2) });
        } catch (err) {
            console.error(err);
            setStatus(`Load failed: ${err.message}`, "error");
        }
    }

    function wire() {
        const buttons = document.querySelectorAll(".sc-play");
        if (!buttons.length) return;
        buttons.forEach(btn => btn.addEventListener("click", () => play(btn)));
        if (statusEl && !statusEl.textContent.trim()) {
            setStatus("Click any tile to play. Click again to pause.");
        }

        // If any other demo on the page starts playing, stop ours so the
        // visitor only ever hears one player at a time.
        window.StemForgePlay?.onOtherPlayed("demo-stems", () => {
            if (currentSource) {
                stop();
                setStatus("Paused — another demo started.");
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", wire);
    } else {
        wire();
    }
})();
