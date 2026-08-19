/**
 * Producer Hunt mixer. Optional files load through the existing static URL helper.
 * Missing samples stay silent after one warning. No competing global audio bus.
 */
import {
  AUDIO_EXTENSIONS,
  MUSIC_CROSSFADE_SEC,
  SOUND_DEFS,
  SOUND_LIST,
  WEAPON_SOUND_ID,
  soundDef,
} from "./audio-catalog.js";

const BUS = { music: 1, effects: 1, ui: 1 };

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

export class AudioManager {
  constructor(options = {}) {
    this.loader = options.loader || null;
    this.logMissing = options.logMissing !== false;
    this.enabled = false;
    this.unlocked = false;
    this._ctx = null;
    this._master = null;
    this._buses = {};
    this._buffers = new Map();
    this._missing = new Set();
    this._warned = new Set();
    this._voices = new Map();
    this._lastPlay = new Map();
    this._music = { id: "", gain: null, source: null, startedAt: 0, offset: 0, paused: false };
    this._pendingMusic = null;
    this._gameplayMuted = false;
    this._autoplayWarned = false;
    this._unlockBound = false;
    this.volumes = { music: 1, effects: 1, ui: 1, master: 1 };
    this._onUnlock = (e) => this.unlock(e);
  }

  attachUnlock(target) {
    if (this._unlockBound) return;
    this._unlockBound = true;
    const el = target || window;
    el.addEventListener("pointerdown", this._onUnlock, { capture: true });
    el.addEventListener("keydown", this._onUnlock, { capture: true });
  }

  detachUnlock(target) {
    if (!this._unlockBound) return;
    const el = target || window;
    el.removeEventListener("pointerdown", this._onUnlock, { capture: true });
    el.removeEventListener("keydown", this._onUnlock, { capture: true });
    this._unlockBound = false;
  }

  async init() {
    if (this._ctx) return this._ctx;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    this._ctx = new Ctx();
    this._master = this._ctx.createGain();
    this._master.connect(this._ctx.destination);
    for (const name of Object.keys(BUS)) {
      const g = this._ctx.createGain();
      g.connect(this._master);
      this._buses[name] = g;
    }
    this.enabled = true;
    this._applyBusGains();
    return this._ctx;
  }

  async preload() {
    await this.init();
    if (!this._ctx) return;
    await Promise.all(SOUND_LIST.map((def) => this._loadDef(def)));
  }

  applyMix(settings) {
    const master = clamp(Number(settings?.masterVolume), 0, 1);
    const music = clamp(Number(settings?.musicVolume), 0, 1);
    const fx = clamp(Number(settings?.effectsVolume), 0, 1);
    this.volumes.master = Number.isFinite(master) ? master : 1;
    this.volumes.music = Number.isFinite(music) ? music : 0.8;
    this.volumes.effects = Number.isFinite(fx) ? fx : 1;
    this.volumes.ui = this.volumes.effects;
    this._applyBusGains();
  }

  setVolume(category, value) {
    if (this.volumes[category] == null) return;
    this.volumes[category] = clamp(value, 0, 1);
    this._applyBusGains();
  }

  _applyBusGains() {
    if (!this._master) return;
    this._master.gain.value = this.volumes.master;
    if (this._buses.music) this._buses.music.gain.value = this.volumes.music;
    if (this._buses.effects) this._buses.effects.gain.value = this.volumes.effects;
    if (this._buses.ui) this._buses.ui.gain.value = this.volumes.ui;
  }

  async unlock() {
    await this.init();
    if (!this._ctx) return;
    try {
      if (this._ctx.state === "suspended") await this._ctx.resume();
      this.unlocked = this._ctx.state === "running";
    } catch (err) {
      this._warnAutoplay(err);
      this.unlocked = false;
      return;
    }
    if (this.unlocked && this._pendingMusic) {
      const pending = this._pendingMusic;
      this._pendingMusic = null;
      this.playMusic(pending.id, pending.opts);
    }
  }

  _warnAutoplay(err) {
    if (this._autoplayWarned) return;
    this._autoplayWarned = true;
    if (err && err.name === "NotAllowedError") {
      this._warnOnce("[Producer Hunt Audio] Autoplay was blocked. Audio will unlock after the next click or key press.");
    }
  }

  _warnOnce(message) {
    if (this._warned.has(message)) return;
    this._warned.add(message);
    if (this.logMissing) console.warn(message);
  }

  _urlCandidates(def) {
    if (!this.loader || typeof this.loader.url !== "function") return [];
    const urls = [];
    for (const ext of AUDIO_EXTENSIONS) {
      const rel = `${def.path}${ext}`;
      const url = this.loader.url(rel);
      if (url) urls.push({ ext, url, rel });
    }
    return urls;
  }

  async _loadDef(def) {
    if (this._buffers.has(def.id) || this._missing.has(def.id)) return this._buffers.get(def.id) || null;
    const candidates = this._urlCandidates(def);
    for (const cand of candidates) {
      try {
        const res = await fetch(cand.url, { credentials: "same-origin" });
        if (!res.ok) continue;
        const type = res.headers.get("content-type") || "";
        if (type.includes("text/html")) continue;
        const raw = await res.arrayBuffer();
        if (!raw || raw.byteLength < 32) continue;
        const ctx = await this.init();
        if (!ctx) return null;
        const copy = raw.slice(0);
        const buffer = await ctx.decodeAudioData(copy);
        this._buffers.set(def.id, buffer);
        return buffer;
      } catch {
        continue;
      }
    }
    this._missing.add(def.id);
    this._warnOnce(`[Producer Hunt Audio] Missing optional sound:\n${def.path}.ogg`);
    return null;
  }

  outputVolume(def) {
    const cat = def.category === "music" ? "music" : def.category === "ui" ? "ui" : "effects";
    return clamp(this.volumes.master * this.volumes[cat] * def.volume, 0, 1);
  }

  _spatial(def, opts) {
    if (!def.spatial || opts?.x == null || !opts.camera) {
      return { pan: 0, atten: 1 };
    }
    const cam = opts.camera;
    const cx = cam.x + cam.w * 0.5;
    const pan = clamp((opts.x - cx) / (cam.w * 0.55), -0.55, 0.55);
    const dist = Math.abs(opts.x - cx);
    const atten = clamp(1 - dist / (cam.w * 1.35), 0.42, 1);
    return { pan, atten };
  }

  play(idOrCategory, idOrOpts, maybeOpts) {
    if (SOUND_DEFS[idOrCategory]) return this.playSound(idOrCategory, idOrOpts || {});
    const mapped = WEAPON_SOUND_ID[idOrOpts] || this._legacyId(idOrOpts);
    return this.playSound(mapped, maybeOpts || {});
  }

  _legacyId(id) {
    return (
      {
        checkpoint: "checkpoint_activate",
        door: "door_open",
        pickup: "pickup_collect",
        hit: "player_hit",
      }[id] || id
    );
  }

  playSound(id, opts = {}) {
    const def = soundDef(id);
    if (!def || def.category === "music") return false;
    if (this._gameplayMuted && def.category === "effects" && !opts.force) return false;
    if (this._missing.has(id)) return false;
    const now = performance.now() / 1000;
    const last = this._lastPlay.get(id) || 0;
    if (def.cooldown && now - last < def.cooldown) return false;
    const voices = this._voices.get(id) || [];
    const live = voices.filter((v) => v.alive);
    if (live.length >= def.maxInstances) {
      const oldest = live[0];
      if (oldest) this._stopVoice(oldest);
    }
    if (!this._buffers.has(id)) {
      if (!this._missing.has(id)) {
        this._loadDef(def).then((buf) => {
          if (buf && opts.allowDeferred) this.playSound(id, opts);
        });
      }
      return false;
    }
    if (!this.unlocked) return false;
    const started = this._startVoice(def, opts);
    if (started) this._lastPlay.set(id, now);
    return started;
  }

  _startVoice(def, opts) {
    if (!this._ctx || !this._buses[def.category === "ui" ? "ui" : "effects"]) return false;
    const buffer = this._buffers.get(def.id);
    if (!buffer) return false;
    try {
      const src = this._ctx.createBufferSource();
      src.buffer = buffer;
      src.loop = Boolean(def.loop);
      const gain = this._ctx.createGain();
      const { pan, atten } = this._spatial(def, opts);
      gain.gain.value = clamp(def.volume * atten, 0, 1);
      const panner = this._ctx.createStereoPanner();
      panner.pan.value = pan;
      const bus = this._buses[def.category === "ui" ? "ui" : "effects"];
      src.connect(gain);
      gain.connect(panner);
      panner.connect(bus);
      const voice = { id: def.id, src, gain, alive: true };
      src.onended = () => {
        voice.alive = false;
      };
      src.start();
      const list = this._voices.get(def.id) || [];
      list.push(voice);
      this._voices.set(
        def.id,
        list.filter((v) => v.alive)
      );
      return true;
    } catch (err) {
      this._warnAutoplay(err);
      return false;
    }
  }

  _stopVoice(voice) {
    voice.alive = false;
    try {
      voice.src.stop();
    } catch {
      /* already stopped */
    }
  }

  stopGameplayVoices() {
    for (const [id, list] of this._voices) {
      const def = soundDef(id);
      if (!def || def.category !== "effects") continue;
      for (const voice of list) this._stopVoice(voice);
      this._voices.set(id, []);
    }
  }

  setGameplayMuted(muted) {
    this._gameplayMuted = Boolean(muted);
    if (this._gameplayMuted) this.stopGameplayVoices();
  }

  playMusic(id, opts = {}) {
    const def = soundDef(id);
    if (!def || def.category !== "music") return;
    if (!this.unlocked) {
      this._pendingMusic = { id, opts };
      return;
    }
    if (this._music.id === id && this._music.source && !this._music.paused && !opts.restart) return;
    this._pendingMusic = null;
    if (!this._buffers.has(id)) {
      this._loadDef(def).then((buf) => {
        if (buf) this.playMusic(id, opts);
      });
      if (this._missing.has(id)) this._stopMusic(0.2);
      return;
    }
    this._crossfadeTo(def, opts);
  }

  _crossfadeTo(def, opts) {
    if (!this._ctx || !this._buses.music) return;
    const fade = MUSIC_CROSSFADE_SEC;
    const prev = this._music;
    if (prev.source && prev.id === def.id && !opts.restart && !prev.paused) return;
    const nextGain = this._ctx.createGain();
    nextGain.gain.value = 0;
    const src = this._ctx.createBufferSource();
    src.buffer = this._buffers.get(def.id);
    src.loop = opts.loop != null ? Boolean(opts.loop) : Boolean(def.loop);
    src.connect(nextGain);
    nextGain.connect(this._buses.music);
    const offset = opts.restart ? 0 : 0;
    try {
      src.start(0, offset);
    } catch (err) {
      this._warnAutoplay(err);
      return;
    }
    const now = this._ctx.currentTime;
    nextGain.gain.linearRampToValueAtTime(def.volume, now + fade);
    if (prev.source && prev.gain) {
      prev.gain.gain.cancelScheduledValues(now);
      prev.gain.gain.setValueAtTime(prev.gain.gain.value, now);
      prev.gain.gain.linearRampToValueAtTime(0, now + fade);
      const dying = prev.source;
      window.setTimeout(() => {
        try {
          dying.stop();
        } catch {
          /* noop */
        }
      }, fade * 1000 + 40);
    }
    src.onended = () => {
      if (this._music.source === src) {
        this._music.source = null;
        this._music.id = this._music.id === def.id ? "" : this._music.id;
      }
    };
    this._music = {
      id: def.id,
      gain: nextGain,
      source: src,
      startedAt: now,
      offset: 0,
      paused: false,
      volume: def.volume,
    };
  }

  pauseMusic() {
    const m = this._music;
    if (!m.source || m.paused || !this._ctx) return;
    m.offset = Math.max(0, this._ctx.currentTime - m.startedAt);
    m.paused = true;
    try {
      m.source.stop();
    } catch {
      /* noop */
    }
    m.source = null;
  }

  resumeMusic() {
    if (!this._music.id) return;
    if (!this._music.paused) {
      if (!this._music.source) this.playMusic(this._music.id, { restart: false });
      return;
    }
    const def = soundDef(this._music.id);
    if (!def || !this._buffers.has(def.id) || !this._ctx) return;
    const src = this._ctx.createBufferSource();
    src.buffer = this._buffers.get(def.id);
    src.loop = Boolean(def.loop);
    const gain = this._ctx.createGain();
    gain.gain.value = def.volume;
    src.connect(gain);
    gain.connect(this._buses.music);
    const dur = src.buffer.duration || 1;
    const offset = def.loop ? this._music.offset % dur : Math.min(this._music.offset, Math.max(0, dur - 0.05));
    try {
      src.start(0, offset);
    } catch (err) {
      this._warnAutoplay(err);
      return;
    }
    this._music.source = src;
    this._music.gain = gain;
    this._music.startedAt = this._ctx.currentTime - offset;
    this._music.paused = false;
  }

  _stopMusic(fade = 0.2) {
    const m = this._music;
    if (!m.source || !this._ctx) {
      this._music = { id: "", gain: null, source: null, startedAt: 0, offset: 0, paused: false };
      return;
    }
    const now = this._ctx.currentTime;
    try {
      m.gain.gain.cancelScheduledValues(now);
      m.gain.gain.setValueAtTime(m.gain.gain.value, now);
      m.gain.gain.linearRampToValueAtTime(0, now + fade);
    } catch {
      /* noop */
    }
    const dying = m.source;
    window.setTimeout(() => {
      try {
        dying.stop();
      } catch {
        /* noop */
      }
    }, fade * 1000 + 40);
    this._music = { id: "", gain: null, source: null, startedAt: 0, offset: 0, paused: false };
  }

  stopAll() {
    this.stopGameplayVoices();
    this._stopMusic(0.12);
    this._pendingMusic = null;
  }

  dispose() {
    this.detachUnlock();
    this.stopAll();
    if (this._ctx && this._ctx.state !== "closed") {
      this._ctx.suspend?.();
    }
  }
}

export { SOUND_DEFS, WEAPON_SOUND_ID };
