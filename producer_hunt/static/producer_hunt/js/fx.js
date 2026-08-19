/** One-shot world-space (or screen-space) visual effects. Non-collidable. */

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
}
