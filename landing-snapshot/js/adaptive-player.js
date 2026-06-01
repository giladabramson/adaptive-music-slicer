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

        // AnalyserNode tap on the master bus, so the visualizer reads the
        // exact post-mix, post-fade signal the user is hearing. Smoothing
        // tuned for a calm spectrum on slow game-music tempos.
        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 512;
        this.analyser.smoothingTimeConstant = 0.78;
        this.master.connect(this.analyser);
        this.analyser.connect(this.ctx.destination);
        this._freqBuf = new Uint8Array(this.analyser.frequencyBinCount);

        this.stemGains = {};
        this.stemSources = {};
        this.stemBuffers = {};       // decoded buffer per stem, kept across seek
        this.targetGains = {};
        this.currentSong = null;
        this.playing = false;
        this.fadeSec = 1.5;
        this._bufferCache = new Map();
        this._sourceStartTime = 0;   // ctx.currentTime when current sources began
        this._sourceStartOffset = 0; // buffer position they began at (seconds)
        // Snapshot of the playhead at the moment we paused. While this
        // is non-null we consider the player paused and freeze
        // positionSec at this value; play() resumes from here.
        this._pausedPosition = null;
    }

    /** Loop duration in seconds (all stems share length by construction). */
    get loopDurationSec() {
        const buf = Object.values(this.stemBuffers)[0];
        return buf ? buf.duration : 0;
    }

    /** Current playhead position within the loop, in seconds. */
    get positionSec() {
        if (this._pausedPosition !== null) return this._pausedPosition;
        const dur = this.loopDurationSec;
        if (!dur) return 0;
        const elapsed = this.ctx.currentTime - this._sourceStartTime;
        // Clamp negative offsets (during the brief swap window) to 0.
        return ((Math.max(0, this._sourceStartOffset + elapsed)) % dur);
    }

    /** Snapshot the analyser's frequency bins (Uint8 0-255 per bin). */
    readSpectrum() {
        this.analyser.getByteFrequencyData(this._freqBuf);
        return this._freqBuf;
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
        this.stemBuffers = buffers;

        if (wasPlaying) {
            // Continue playback into the new song from its start.
            this._pausedPosition = null;
            this._spawnSources(0);
            this._rampMaster(1.0, SWITCH_FADE_S);
        } else {
            // Not playing — don't spawn sources yet. positionSec returns 0
            // (frozen) so the seekbar doesn't drift while the user is
            // still deciding whether to hit play.
            this._pausedPosition = 0;
        }
    }

    /** Seek to ``positionSec`` within the loop without re-fetching audio.
     * Works whether playing or paused: while paused, this just updates
     * the saved position so the next play() resumes from there.
     */
    seek(positionSec) {
        if (!this.currentSong || !this.stemBuffers.drums) return;
        const dur = this.loopDurationSec;
        if (!dur) return;
        const offset = Math.max(0, Math.min(positionSec, dur - 0.05));
        if (this._pausedPosition !== null) {
            this._pausedPosition = offset;
            return;
        }
        this._stopAllSources();
        this._spawnSources(offset);
    }

    /** Internal: create + start the four source nodes at ``offset`` seconds.
     * Caller is responsible for having stopped the previous sources first.
     */
    _spawnSources(offset) {
        const startAt = this.ctx.currentTime + 0.04;
        for (const stem of STEM_KEYS) {
            const buffer = this.stemBuffers[stem];
            if (!buffer) continue;

            const gain = this.ctx.createGain();
            gain.gain.value = this.targetGains[stem] ?? 1.0;
            gain.connect(this.master);

            const src = this.ctx.createBufferSource();
            src.buffer = buffer;
            src.loop = true;
            src.connect(gain);
            // Starting every source at the same context time with the same
            // offset is what gives us sample-accurate sync across the four
            // stems for the rest of the loop.
            src.start(startAt, offset);

            this.stemGains[stem] = gain;
            this.stemSources[stem] = src;
        }
        this._sourceStartTime = startAt;
        this._sourceStartOffset = offset;
    }

    play() {
        this.ctx.resume();
        if (this.playing) return;
        this.playing = true;
        // If we're resuming from pause, sources were stopped — respawn
        // them at the saved position so playback continues from there.
        if (!this.stemSources.drums && this.currentSong) {
            this._spawnSources(this._pausedPosition ?? 0);
        }
        this._pausedPosition = null;
        this._rampMaster(1.0, MASTER_FADE_S);
    }

    pause() {
        if (!this.playing) return;
        // Snapshot before flipping state so positionSec still computes live.
        this._pausedPosition = this.positionSec;
        this.playing = false;
        this._rampMaster(0.0, MASTER_FADE_S);
        // The master fade covers the audible cut; stopping the sources is
        // what makes the playhead actually stop advancing.
        this._stopAllSources();
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
