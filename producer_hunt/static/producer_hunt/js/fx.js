/** One-shot world-space (or screen-space) visual effects. Non-collidable. Pooled. */

import { DESIGN_H, DESIGN_W } from "./config.js";
import { fxCap } from "./presentation.js";

export class FxSprite {
  constructor({
    sheet,
    frame = 0,
    frames = 1,
    fps = 0,
    x,
    y,
    size = 64,
    life = 0.22,
    loop = false,
    screenSpace = false,
    flipX = false,
  }) {
    this.sheet = sheet;
    this.frame = frame;
    this.frames = Math.max(1, frames || 1);
    this.fps = fps || 0;
    this.x = x;
    this.y = y;
    this.size = size;
    this.life = life;
    this.loop = loop;
    this.screenSpace = screenSpace;
    this.flipX = flipX;
    this.age = 0;
    this.alive = true;
    this.kind = "";
  }

  reset(opts) {
    Object.assign(this, {
      sheet: opts.sheet || null,
      frame: opts.frame || 0,
      frames: Math.max(1, opts.frames || 1),
      fps: opts.fps || 0,
      x: opts.x,
      y: opts.y,
      size: opts.size || 64,
      life: opts.life || 0.22,
      loop: Boolean(opts.loop),
      screenSpace: Boolean(opts.screenSpace),
      flipX: Boolean(opts.flipX),
      age: 0,
      alive: true,
      kind: opts.kind || "",
    });
    return this;
  }

  update(dt) {
    this.age += dt;
    if (this.fps > 0 && this.frames > 1) {
      const i = Math.floor(this.age * this.fps);
      if (!this.loop && i >= this.frames) {
        this.alive = false;
        return;
      }
      this.frame = this.loop ? i % this.frames : Math.min(this.frames - 1, i);
      return;
    }
    if (!this.loop && this.age >= this.life) this.alive = false;
  }

  draw(ctx, camera, drawSheetFrame) {
    if (!this.alive) return;
    const pos = this.screenSpace
      ? { x: this.x, y: this.y }
      : camera.worldToScreen(this.x, this.y);
    const fade = this.fps > 0 && this.frames > 1 ? 1 : this.loop ? 1 : Math.max(0, 1 - this.age / this.life);
    ctx.save();
    ctx.globalAlpha = fade;
    drawSheetFrame(
      ctx,
      this.sheet,
      this.frame,
      pos.x - this.size / 2,
      pos.y - this.size / 2,
      this.size,
      this.size,
      this.flipX
    );
    ctx.restore();
  }

  onScreen(camera, pad = 80) {
    if (this.screenSpace) return true;
    if (!camera) return true;
    const x = this.x - camera.x;
    const y = this.y - camera.y;
    return x > -pad && x < DESIGN_W + pad && y > -pad && y < DESIGN_H + pad;
  }
}

export class FxPool {
  constructor() {
    this.live = [];
    this.dead = [];
  }

  get length() {
    return this.live.length;
  }

  clear() {
    for (const fx of this.live) {
      fx.alive = false;
      this.dead.push(fx);
    }
    this.live.length = 0;
  }

  spawn(opts, settings) {
    const cap = fxCap(settings);
    while (this.live.length >= cap) {
      const oldest = this.live.shift();
      if (oldest) {
        oldest.alive = false;
        this.dead.push(oldest);
      }
    }
    const fx = this.dead.pop() || new FxSprite({ x: 0, y: 0 });
    fx.reset(opts);
    this.live.push(fx);
    return fx;
  }

  update(dt, camera) {
    const next = [];
    for (const fx of this.live) {
      fx.update(dt);
      if (!fx.alive) {
        this.dead.push(fx);
        continue;
      }
      if (camera && !fx.onScreen(camera, 120)) {
        fx.alive = false;
        this.dead.push(fx);
        continue;
      }
      next.push(fx);
    }
    this.live = next;
    if (this.dead.length > 64) this.dead.length = 64;
  }

  draw(ctx, camera, drawSheetFrame) {
    for (const fx of this.live) fx.draw(ctx, camera, drawSheetFrame);
  }
}

