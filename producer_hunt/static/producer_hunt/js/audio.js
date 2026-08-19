const CATEGORIES = ["music", "weapon", "player", "enemy", "environment", "ui"];

/** Stub mixer. Wire real buffers later; never load copyrighted arcade samples. */
export class AudioManager {
  constructor() {
    this.enabled = false;
    this.volumes = Object.fromEntries(CATEGORIES.map((c) => [c, 1]));
    this._ctx = null;
  }

  async init() {
    if (this._ctx) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    this._ctx = new Ctx();
    this.enabled = true;
  }

  applyMix(settings) {
    const master = settings?.masterVolume ?? 1;
    const music = (settings?.musicVolume ?? 0.8) * master;
    const fx = (settings?.effectsVolume ?? 1) * master;
    this.setVolume("music", music);
    for (const cat of ["weapon", "player", "enemy", "environment", "ui"]) {
      this.setVolume(cat, fx);
    }
  }

  setVolume(category, value) {
    if (this.volumes[category] == null) return;
    this.volumes[category] = Math.max(0, Math.min(1, value));
  }

  play(_category, _id) {
    /* Placeholder: no samples in this milestone. */
  }

  stopAll() {
    /* no-op */
  }
}
