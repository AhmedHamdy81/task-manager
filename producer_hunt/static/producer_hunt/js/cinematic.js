/**
 * One-shot HTML video overlay for Producer Hunt cinematics.
 * Completes exactly once from ended, skip, error, timeout, or cancel.
 */
import { BOSS_DEFEAT_SRC, BOSS_INTRO_SRC } from "./config.js";

const SKIP_GUARD_SEC = 0.5;
const DEFAULT_TIMEOUT_SEC = 14;
const VIDEO_VOLUME = 0.8;

export class CinematicPlayer {
  constructor(game, elements = {}) {
    this.game = game;
    this.root = elements.root || null;
    this.video = elements.video || null;
    this.skipBtn = elements.skipBtn || null;
    this._playing = false;
    this._completed = false;
    this._allowSkip = true;
    this._onComplete = null;
    this._failMessage = "";
    this._skipReadyAt = 0;
    this._timeout = 0;
    this._onEnded = () => this.complete("ended");
    this._onError = () => this.complete("error");
    this._onSkipClick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.trySkip();
    };
  }

  get active() {
    return this._playing;
  }

  bindDom(elements = {}) {
    this.root = elements.root || this.root;
    this.video = elements.video || this.video;
    this.skipBtn = elements.skipBtn || this.skipBtn;
  }

  assetSrc(rel) {
    const path = rel || "";
    return this.game.assets?.url?.(path) || `${this.game.assets?.baseUrl || ""}/${path}`;
  }

  introSrc() {
    return this.assetSrc(BOSS_INTRO_SRC);
  }

  defeatSrc() {
    return this.assetSrc(BOSS_DEFEAT_SRC);
  }

  applyMix() {
    const video = this.video;
    if (!video) return;
    const muted = Boolean(this.game.audio?.muted || this.game.settings?.muted);
    const master = Number(this.game.audio?.volumes?.master);
    const voice = Number(this.game.audio?.volumes?.voice);
    const vol =
      (Number.isFinite(master) ? master : 1) * (Number.isFinite(voice) ? voice : VIDEO_VOLUME);
    video.muted = muted;
    video.volume = muted ? 0 : Math.max(0, Math.min(1, vol));
  }

  playBossIntro(options = {}) {
    return this.playCinematic({
      src: this.introSrc(),
      timeoutSec: 14,
      failMessage: "[Producer Hunt] Boss intro playback failed. Starting the encounter.",
      ...options,
    });
  }

  playBossDefeat(options = {}) {
    return this.playCinematic({
      src: this.defeatSrc(),
      timeoutSec: 20,
      failMessage: "[Producer Hunt] Boss defeat video failed. Continuing to results.",
      ...options,
    });
  }

  async playCinematic({
    src,
    allowSkip = true,
    timeoutSec = DEFAULT_TIMEOUT_SEC,
    onComplete,
    failMessage,
  } = {}) {
    if (this._playing) return;
    this.bindDom({
      root: this.root || document.querySelector(".ph-boss-intro"),
      video: this.video || document.querySelector(".ph-boss-intro__video"),
      skipBtn: this.skipBtn || document.querySelector(".ph-boss-intro__skip"),
    });
    this._playing = true;
    this._completed = false;
    this._allowSkip = allowSkip !== false;
    this._onComplete = typeof onComplete === "function" ? onComplete : null;
    this._failMessage = failMessage || "[Producer Hunt] Cinematic playback failed.";
    this._skipReadyAt = performance.now() + SKIP_GUARD_SEC * 1000;

    this.game.beginCinematic?.();
    this.game.audio?.stopGameplayVoices?.();
    this.game.audio?.setGameplayMuted?.(true);
    this.game.audio?.stopMusic?.(0.55);

    if (!this.root || !this.video) {
      this.complete("missing-dom");
      return;
    }

    const url = src || this.introSrc();
    this.root.hidden = false;
    this.root.classList.add("is-visible");
    this.root.setAttribute("aria-hidden", "false");
    if (this.skipBtn) this.skipBtn.hidden = !this._allowSkip;
    this.video.setAttribute("playsinline", "");
    this.video.setAttribute("preload", "auto");
    this.video.playsInline = true;
    this.video.src = url;
    this.video.currentTime = 0;
    this.applyMix();

    this.video.addEventListener("ended", this._onEnded);
    this.video.addEventListener("error", this._onError);
    if (this._allowSkip) this.skipBtn?.addEventListener("click", this._onSkipClick);

    const ms = Math.max(3000, (Number(timeoutSec) || DEFAULT_TIMEOUT_SEC) * 1000);
    this._timeout = window.setTimeout(() => this.complete("timeout"), ms);

    try {
      this.video.load();
      await this.video.play();
    } catch {
      this.complete("rejected");
    }
  }

  trySkip() {
    if (!this._playing || !this._allowSkip) return false;
    if (performance.now() < this._skipReadyAt) return false;
    this.complete("skip");
    return true;
  }

  pause() {
    if (!this.video || this._completed) return;
    try {
      this.video.pause();
    } catch {
      /* ignore */
    }
  }

  resume() {
    if (!this._playing || this._completed || !this.video) return;
    this.applyMix();
    this.video.play().catch(() => this.complete("rejected"));
  }

  cancel() {
    this.complete("cancel");
  }

  complete(reason = "ended") {
    if (this._completed) return;
    this._completed = true;
    this._playing = false;
    if (this._timeout) {
      window.clearTimeout(this._timeout);
      this._timeout = 0;
    }
    const video = this.video;
    if (video) {
      video.removeEventListener("ended", this._onEnded);
      video.removeEventListener("error", this._onError);
      try {
        video.pause();
      } catch {
        /* ignore */
      }
      video.removeAttribute("src");
      video.src = "";
      try {
        video.load();
      } catch {
        /* ignore */
      }
    }
    this.skipBtn?.removeEventListener("click", this._onSkipClick);
    if (this.root) {
      this.root.classList.remove("is-visible");
      this.root.hidden = true;
      this.root.setAttribute("aria-hidden", "true");
    }
    this.game.endCinematic?.();
    this.game.input?.clearTransient?.();
    const done = this._onComplete;
    this._onComplete = null;
    if (reason === "error" || reason === "rejected" || reason === "missing-dom" || reason === "timeout") {
      console.warn(this._failMessage);
    }
    if (reason === "cancel") return;
    const finish = () => {
      if (typeof done === "function") done(reason);
    };
    const resume = this.game.audio?.unlock?.();
    if (resume && typeof resume.then === "function") {
      resume.then(finish, finish);
      return;
    }
    finish();
  }
}
