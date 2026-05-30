/**
 * AdaptivePlayer — Web Audio port of adaptive_player.py.
 *
 * Plays four stems (drums/bass/other/vocals) in sample-accurate sync by
 * starting every AudioBufferSourceNode at the same context.currentTime
 * and letting Web Audio's built-in looping wrap each one identically.
 * Per-stem GainNodes hold the tension/volume; a master GainNode handles
 * play/pause and song-switch fades, mirroring the desktop player's
 * lock-free swap design.
 *
 * Browsers refuse to start an AudioContext until a user gesture
 * (autoplay policy), so the host page must call play() from a click
 * handler — not on load.
 */

const STEM_KEYS = ["drums", "bass", "other", "vocals"];

const PRESETS = {
    Low:    { drums: 0.0, bass: 0.0, other: 1.0, vocals: 0.0 },
    Medium: { drums: 0.2, bass: 1.0, other: 1.0, vocals: 0.0 },
    High:   { drums: 1.0, bass: 1.0, other: 1.0, vocals: 1.0 },
};

const MASTER_FADE_S = 0.08;
const SWITCH_FADE_S = 0.25;

class AdaptivePlayer {
    constructor() {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();
        this.master = this.ctx.createGain();
        this.master.gain.value = 0;
        this.master.connect(this.ctx.destination);

        this.stemGains = {};
        this.stemSources = {};
        this.targetGains = {};
        this.currentSong = null;
        this.playing = false;
        this.fadeSec = 1.5;
        this._bufferCache = new Map();
    }

    /** Pre-warm the AudioContext from a user gesture. iOS Safari needs this. */
    unlock() {
        if (this.ctx.state === "suspended") {
            return this.ctx.resume();
        }
        return Promise.resolve();
    }

    async loadSong(songMeta, baseUrl, { onProgress } = {}) {
        await this.unlock();

        const buffers = {};
        await Promise.all(STEM_KEYS.map(async (stem, i) => {
            const file = songMeta.stems.find(s => s.startsWith(stem));
            if (!file) throw new Error(`song ${songMeta.name} missing ${stem}`);
            const url = `${baseUrl}/${songMeta.name}/${file}`;
            const buf = await this._fetchBuffer(url);
            buffers[stem] = buf;
            if (onProgress) onProgress(stem, i + 1, STEM_KEYS.length);
        }));

        // Dip the master while we swap so the cut is silent, then ramp
        // back to wherever the player was before the swap.
        const wasPlaying = this.playing;
        this._rampMaster(0.0, SWITCH_FADE_S);
        await this._wait(SWITCH_FADE_S * 1000);

        this._stopAllSources();
        this.currentSong = songMeta;

        for (const stem of STEM_KEYS) {
            const gain = this.ctx.createGain();
            gain.gain.value = this.targetGains[stem] ?? 1.0;
            gain.connect(this.master);

            const src = this.ctx.createBufferSource();
            src.buffer = buffers[stem];
            src.loop = true;
            src.connect(gain);

            this.stemGains[stem] = gain;
            this.stemSources[stem] = src;
        }

        // Start every source at the exact same context time — that's
        // what guarantees sample-accurate sync across the four stems.
        const startAt = this.ctx.currentTime + 0.05;
        for (const stem of STEM_KEYS) this.stemSources[stem].start(startAt);

        if (wasPlaying) this._rampMaster(1.0, SWITCH_FADE_S);
    }

    play() {
        this.ctx.resume();
        this.playing = true;
        this._rampMaster(1.0, MASTER_FADE_S);
    }

    pause() {
        this.playing = false;
        this._rampMaster(0.0, MASTER_FADE_S);
    }

    toggle() {
        if (this.playing) this.pause();
        else this.play();
        return this.playing;
    }

    /** Per-stem linear gain ramp toward `value`. */
    setStemTarget(stem, value, fadeSec = this.fadeSec) {
        this.targetGains[stem] = value;
        const node = this.stemGains[stem];
        if (!node) return;
        const now = this.ctx.currentTime;
        const g = node.gain;
        g.cancelScheduledValues(now);
        g.setValueAtTime(g.value, now);
        g.linearRampToValueAtTime(value, now + fadeSec);
    }

    applyPreset(name) {
        const table = PRESETS[name];
        if (!table) return;
        for (const stem of STEM_KEYS) this.setStemTarget(stem, table[stem]);
    }

    setFadeSeconds(s) {
        this.fadeSec = Math.max(0.05, s);
    }

    /** Live read of where each stem's gain ramp currently is — for meters. */
    liveGains() {
        const out = {};
        for (const stem of STEM_KEYS) {
            out[stem] = this.stemGains[stem]?.gain.value ?? 0;
        }
        return out;
    }

    // -- internals --------------------------------------------------------

    async _fetchBuffer(url) {
        if (this._bufferCache.has(url)) return this._bufferCache.get(url);
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`fetch ${url} → ${resp.status}`);
        const bytes = await resp.arrayBuffer();
        const buf = await this.ctx.decodeAudioData(bytes);
        this._bufferCache.set(url, buf);
        return buf;
    }

    _rampMaster(target, seconds) {
        const now = this.ctx.currentTime;
        const g = this.master.gain;
        g.cancelScheduledValues(now);
        g.setValueAtTime(g.value, now);
        g.linearRampToValueAtTime(target, now + seconds);
    }

    _stopAllSources() {
        for (const src of Object.values(this.stemSources)) {
            try { src.stop(); } catch (_) { /* already stopped */ }
        }
        this.stemSources = {};
        this.stemGains = {};
    }

    _wait(ms) {
        return new Promise(r => setTimeout(r, ms));
    }
}

window.AdaptivePlayer = AdaptivePlayer;
window.PRESETS = PRESETS;
window.STEM_KEYS = STEM_KEYS;
