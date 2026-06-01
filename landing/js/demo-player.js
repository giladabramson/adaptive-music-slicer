/**
 * Shared Web Audio mixer for the two landing demos.
 *
 * Both Demo A (adaptive game music) and Demo B (stem generator) need
 * the same underlying behavior:
 *   • Load N stem files
 *   • Start every source at the exact same context.currentTime so they
 *     stay sample-locked through the entire loop
 *   • Expose per-stem gain ramps (smooth linearRampToValueAtTime)
 *   • Expose a master gain for play/pause
 *   • Tap an AnalyserNode on master for spectrum visualization
 *
 * Differences between the two demos are entirely in the UI on top —
 * preset buttons (Demo A) vs per-stem channel strips (Demo B). Both UI
 * controllers call the same StemMixer methods.
 */

const FADE_MASTER_S = 0.08;

class StemMixer {
    constructor(stemNames) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();

        this.master = this.ctx.createGain();
        this.master.gain.value = 0;

        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 512;
        this.analyser.smoothingTimeConstant = 0.78;
        this.master.connect(this.analyser);
        this.analyser.connect(this.ctx.destination);
        this._freqBuf = new Uint8Array(this.analyser.frequencyBinCount);

        this.stemNames = stemNames.slice();
        this.stemGains = {};
        this.stemSources = {};
        this.stemBuffers = {};
        this.stemAnalysers = {};   // per-stem AnalyserNode for real meters
        this._stemBufs = {};       // pre-allocated Uint8Arrays per stem
        this.targetGains = {};
        for (const name of stemNames) this.targetGains[name] = 0;

        this.playing = false;
        this.loaded = false;
        this._bufferCache = new Map();
    }

    /** Mean of the per-stem analyser's byte-frequency bins, normalized
     * to roughly [0, 1]. Returns 0 when no signal (paused, muted, or
     * before the first play). Useful for animating per-stem meters.
     */
    stemEnergy(stemName) {
        const an = this.stemAnalysers[stemName];
        const buf = this._stemBufs[stemName];
        if (!an || !buf) return 0;
        an.getByteFrequencyData(buf);
        // Cheap RMS-ish: mean of frequency bin magnitudes. Divide by 128
        // (rather than 255) so typical music maps to ~0.4–0.8 range,
        // leaving headroom for transient peaks to reach 1.0.
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i];
        return Math.min(1, (sum / buf.length) / 128);
    }

    /** Return N normalized [0..1] band magnitudes for the stem's current
     * spectrum, log-spaced so the visualizer reads naturally to a human
     * eye (low bands wider than high bands). Used for the classical
     * dancing-bars meter per channel strip. */
    stemBars(stemName, n) {
        const out = new Float32Array(n);
        const an = this.stemAnalysers[stemName];
        const buf = this._stemBufs[stemName];
        if (!an || !buf) return out;
        an.getByteFrequencyData(buf);
        // Skip the top 1/4 — for music, those bins are mostly noise or
        // empty, and including them would make the right side of the
        // visualizer feel dead.
        const usefulBins = Math.max(n, Math.floor(buf.length * 0.75));
        for (let i = 0; i < n; i++) {
            const lo = Math.floor(Math.pow(i / n, 1.5) * usefulBins);
            const hi = Math.max(lo + 1,
                Math.floor(Math.pow((i + 1) / n, 1.5) * usefulBins));
            let sum = 0;
            for (let j = lo; j < hi; j++) sum += buf[j];
            // Divide by 180 (not 255) so most music peaks reach the
            // top of the visualizer instead of sitting at half height.
            out[i] = Math.min(1, (sum / (hi - lo)) / 180);
        }
        return out;
    }

    async unlock() {
        if (this.ctx.state === "suspended") return this.ctx.resume();
    }

    /** Fetch + decode every stem at `${baseUrl}/${name}.mp3`. */
    async load(baseUrl, files, onProgress) {
        await this.unlock();
        const buffers = {};
        let done = 0;
        await Promise.all(this.stemNames.map(async (name) => {
            const file = files[name];
            if (!file) throw new Error(`missing file for stem "${name}"`);
            const url = `${baseUrl}/${file}`;
            buffers[name] = await this._fetchBuffer(url);
            done++;
            if (onProgress) onProgress(name, done, this.stemNames.length);
        }));
        this.stemBuffers = buffers;
        this.loaded = true;
    }

    /** Start playback from the loop's beginning. Idempotent. */
    play() {
        if (!this.loaded || this.playing) return;
        this.unlock();
        // Reset master to 0 synchronously in case a previous fade-out
        // is still in flight — keeps the upcoming fade-in starting
        // from a known floor.
        const now = this.ctx.currentTime;
        this.master.gain.cancelScheduledValues(now);
        this.master.gain.setValueAtTime(0, now);
        this._spawnSources(0);
        this.playing = true;
        this._ramp(this.master.gain, 1.0, FADE_MASTER_S);
    }

    pause() {
        if (!this.playing) return;
        this.playing = false;
        this._ramp(this.master.gain, 0.0, FADE_MASTER_S);
        // Schedule each source's stop AT THE AUDIO CLOCK, bound to the
        // specific src object — NOT via setTimeout that looks up
        // stemSources later. If a new play() runs in the meantime, the
        // global stemSources refs get overwritten and a setTimeout
        // callback would stop the wrong (new) sources, leaving the old
        // ones playing under the new song.
        const stopAt = this.ctx.currentTime + FADE_MASTER_S + 0.02;
        for (const src of Object.values(this.stemSources)) {
            try { src.stop(stopAt); } catch (_) {}
        }
        // Clear refs synchronously so a fresh _spawnSources doesn't see
        // them. Each src's scheduled .stop() is still in effect at the
        // audio layer.
        this.stemSources = {};
        this.stemGains = {};
        this.stemAnalysers = {};
        this._stemBufs = {};
    }

    /** Immediate stop — for explicit cuts like song-tab switches.
     * Sources are guaranteed stopped at the audio layer within ~25 ms,
     * and JS refs are cleared synchronously, so the caller can
     * reload + replay without any chance of race overlap. */
    hardStop() {
        this.playing = false;
        const now = this.ctx.currentTime;
        // Tiny ramp to 0 to avoid a click on instant cut.
        this.master.gain.cancelScheduledValues(now);
        this.master.gain.setValueAtTime(this.master.gain.value, now);
        this.master.gain.linearRampToValueAtTime(0, now + 0.015);
        const stopAt = now + 0.025;
        for (const src of Object.values(this.stemSources)) {
            try { src.stop(stopAt); } catch (_) {}
        }
        this.stemSources = {};
        this.stemGains = {};
        this.stemAnalysers = {};
        this._stemBufs = {};
    }

    toggle() {
        if (this.playing) this.pause();
        else this.play();
        return this.playing;
    }

    /** Smooth per-stem gain ramp. `value` in [0, 1], fadeSec >= 0.05. */
    setStemTarget(stemName, value, fadeSec = 1.0) {
        this.targetGains[stemName] = value;
        const node = this.stemGains[stemName];
        if (!node) return;
        this._ramp(node.gain, value, Math.max(0.05, fadeSec));
    }

    /** Apply a preset object (stemName → 0..1) with one ramp duration. */
    applyPreset(preset, fadeSec = 1.0) {
        for (const stem of this.stemNames) {
            const v = preset[stem];
            if (v !== undefined) this.setStemTarget(stem, v, fadeSec);
        }
    }

    liveGains() {
        const out = {};
        for (const stem of this.stemNames) {
            out[stem] = this.stemGains[stem]?.gain.value ?? 0;
        }
        return out;
    }

    readSpectrum() {
        this.analyser.getByteFrequencyData(this._freqBuf);
        return this._freqBuf;
    }

    get loopDurationSec() {
        const buf = Object.values(this.stemBuffers)[0];
        return buf ? buf.duration : 0;
    }

    // -- internals --------------------------------------------------------

    _ramp(audioParam, target, seconds) {
        const now = this.ctx.currentTime;
        audioParam.cancelScheduledValues(now);
        audioParam.setValueAtTime(audioParam.value, now);
        audioParam.linearRampToValueAtTime(target, now + seconds);
    }

    async _fetchBuffer(url) {
        if (this._bufferCache.has(url)) return this._bufferCache.get(url);
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`fetch ${url} → ${resp.status}`);
        const bytes = await resp.arrayBuffer();
        const buf = await this.ctx.decodeAudioData(bytes);
        this._bufferCache.set(url, buf);
        return buf;
    }

    _spawnSources(offset) {
        const startAt = this.ctx.currentTime + 0.04;
        for (const name of this.stemNames) {
            const buf = this.stemBuffers[name];
            if (!buf) continue;
            const gain = this.ctx.createGain();
            // Start gain at whatever target we already have set (so a
            // preset applied while paused is honored on first play).
            gain.gain.value = this.targetGains[name] ?? 0;

            // Per-stem analyser sits between gain and master so we can
            // read the post-fader signal energy for live meter dancing.
            const analyser = this.ctx.createAnalyser();
            analyser.fftSize = 256;
            analyser.smoothingTimeConstant = 0.65;
            gain.connect(analyser);
            analyser.connect(this.master);

            const src = this.ctx.createBufferSource();
            src.buffer = buf;
            src.loop = true;
            src.connect(gain);
            src.start(startAt, offset);
            this.stemGains[name] = gain;
            this.stemSources[name] = src;
            this.stemAnalysers[name] = analyser;
            this._stemBufs[name] = new Uint8Array(analyser.frequencyBinCount);
        }
    }

    _stopAllSources() {
        for (const src of Object.values(this.stemSources)) {
            try { src.stop(); } catch (_) { /* already stopped */ }
        }
        this.stemSources = {};
        this.stemGains = {};
    }
}

window.StemMixer = StemMixer;

/* ------------------------------------------------------------------------ *
 * Global "only one demo plays at a time" coordinator.
 *
 * When any demo starts playing it calls `notifyPlay(myId)`. Other demos
 * register via `onOtherPlayed(myId, callback)`. The callback fires when
 * a *different* demo's notifyPlay arrives — typical handler is to pause
 * its own mixer and revert its play button.
 * ------------------------------------------------------------------------ */
window.StemForgePlay = (() => {
    const EVENT = "stemforge:play-started";
    function notifyPlay(sourceId) {
        document.dispatchEvent(new CustomEvent(EVENT, { detail: { source: sourceId } }));
    }
    function onOtherPlayed(myId, cb) {
        document.addEventListener(EVENT, (e) => {
            if (e.detail && e.detail.source !== myId) cb(e.detail.source);
        });
    }
    return { notifyPlay, onOtherPlayed };
})();
