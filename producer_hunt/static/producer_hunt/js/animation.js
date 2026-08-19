/**
 * Data-driven horizontal-strip animator.
 * Gameplay only calls play / update / draw — it does not know about art.
 */
export class SpriteAnimator {
  constructor(kit = null) {
    this.kit = kit;
    this.name = "idle";
    this.frame = 0;
    this.time = 0;
    this.finished = false;
    this.paused = false;
    this.flip = false;
    this.enteredFrame = -1;
    this._onFinished = null;
    this._applyClip(this._clip("idle"));
  }

  setKit(kit) {
    this.kit = kit;
    this._applyClip(this._clip(this.name));
  }

  _clip(name) {
    const anims = (this.kit && this.kit.animations) || {};
    return anims[name] || anims.idle || {
      frames: 1,
      fps: 8,
      loop: true,
      image: null,
      frameWidth: this.kit?.frameWidth || 256,
      frameHeight: this.kit?.frameHeight || 256,
      renderWidth: this.kit?.renderWidth || this.kit?.frameWidth || 256,
      renderHeight: this.kit?.renderHeight || this.kit?.frameHeight || 256,
    };
  }

  _applyClip(clip) {
    this.clip = clip;
    this.frames = Math.max(1, clip.frames || 1);
    this.fps = clip.fps || 8;
    this.loop = Boolean(clip.loop);
    this.image = clip.image || null;
    this.frameWidth = clip.frameWidth || this.kit?.frameWidth || 256;
    this.frameHeight = clip.frameHeight || this.kit?.frameHeight || 256;
    this.renderWidth = clip.renderWidth || this.kit?.renderWidth || this.frameWidth;
    this.renderHeight = clip.renderHeight || this.kit?.renderHeight || this.frameHeight;
  }

  play(name, opts = {}) {
    if (!name) return false;
    const restart = Boolean(opts.restart);
    if (this.name === name && !restart) return false;
    this.name = name;
    this.frame = 0;
    this.time = 0;
    this.finished = false;
    this.enteredFrame = 0;
    this._applyClip(this._clip(name));
    if (typeof opts.onFinished === "function") this._onFinished = opts.onFinished;
    return true;
  }

  get current() {
    return this.name;
  }

  get state() {
    return this.name;
  }

  pause() {
    this.paused = true;
  }

  resume() {
    this.paused = false;
  }

  update(dt) {
    this.enteredFrame = -1;
    if (this.paused || this.finished) return;
    const fps = Math.max(0.01, this.fps);
    this.time += dt;
    const step = 1 / fps;
    while (this.time >= step && !this.finished) {
      this.time -= step;
      this.frame += 1;
      this.enteredFrame = this.frame;
      if (this.frame >= this.frames) {
        if (this.loop) {
          this.frame = 0;
          this.enteredFrame = 0;
        } else {
          this.frame = this.frames - 1;
          this.finished = true;
          if (this._onFinished) this._onFinished(this.name);
        }
      }
    }
  }

  /**
   * Draw current frame with origin at bottom-center (x, y).
   * Source crop uses frameWidth/frameHeight; dest size uses renderWidth/renderHeight.
   */
  draw(ctx, x, y, fallback) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(this.flip ? -1 : 1, 1);
    const fw = this.frameWidth;
    const fh = this.frameHeight;
    const rw = this.renderWidth || fw;
    const rh = this.renderHeight || fh;
    if (this.image) {
      ctx.drawImage(
        this.image,
        this.frame * fw,
        0,
        fw,
        fh,
        -rw / 2,
        -rh,
        rw,
        rh
      );
    } else if (fallback) {
      fallback(ctx, rw, rh);
    }
    ctx.restore();
  }
}

export { SpriteAnimator as Animator };
