import { drawSheetFrame } from "./asset-catalog.js";

export class Projectile {
  constructor(opts = {}) {
    this.reset(opts);
  }

  reset({
    x = 0,
    y = 0,
    vx = 0,
    vy = 0,
    damage = 0,
    owner = "player",
    faction = "",
    type,
    frame = 0,
    w = 32,
    h = 20,
    vis = 48,
    flip = true,
    lifetime = 2,
    sheet = null,
    impactFx = null,
    animFrames = 1,
    animFps = 0,
    spin = 0,
    gravity = 0,
    interruptMove = false,
    tint = "",
  } = {}) {
    this.x = x;
    this.y = y;
    this.w = w;
    this.h = h;
    this.vx = vx;
    this.vy = vy || 0;
    this.damage = damage;
    this.owner = owner;
    this.faction = faction || owner;
    this.type = type || "shot";
    this.frame = frame;
    this.sheet = sheet;
    this.flipArt = Boolean(flip);
    this.direction = Math.sign(vx) || 1;
    this.alive = true;
    this.spent = false;
    this.hasHit = false;
    this.age = 0;
    this.lifetime = lifetime;
    this.vis = vis;
    this.impactFx = impactFx;
    this.prevX = x;
    this.prevY = y;
    this.animFrames = Math.max(1, animFrames || 1);
    this.animFps = Number(animFps) || 0;
    this.animTime = 0;
    this.spin = Number(spin) || 0;
    this.angle = 0;
    this.gravity = Number(gravity) || 0;
    this.interruptMove = Boolean(interruptMove);
    this.tint = tint || "";
    return this;
  }

  bounds() {
    return { x: this.x, y: this.y, w: this.w, h: this.h };
  }

  center() {
    return { x: this.x + this.w / 2, y: this.y + this.h / 2 };
  }

  disable() {
    this.alive = false;
    this.spent = true;
    this.hasHit = true;
  }

  recycle() {
    this.disable();
    this.x = 0;
    this.y = 0;
    this.vx = 0;
    this.vy = 0;
    this.sheet = null;
  }

  update(dt) {
    if (!this.alive) return;
    this.prevX = this.x;
    this.prevY = this.y;
    this.x += this.vx * dt;
    this.y += this.vy * dt;
    if (this.gravity) this.vy += this.gravity * dt;
    if (this.spin) this.angle += this.spin * dt;
    if (this.animFps > 0) {
      this.animTime += dt;
      const step = 1 / this.animFps;
      while (this.animTime >= step) {
        this.animTime -= step;
        this.frame = (this.frame + 1) % this.animFrames;
      }
    }
    this.age += dt;
    if (this.age >= this.lifetime) this.disable();
  }

  travelBounds() {
    const x = this.prevX == null ? this.x : Math.min(this.prevX, this.x);
    const y = this.prevY == null ? this.y : Math.min(this.prevY, this.y);
    const w = this.w + Math.abs(this.x - (this.prevX ?? this.x));
    const h = this.h + Math.abs(this.y - (this.prevY ?? this.y));
    return { x, y, w, h };
  }

  draw(ctx, camera) {
    const vis = this.vis;
    const c = this.center();
    const s = camera.worldToScreen(c.x, c.y);
    const flip = this.flipArt && this.vx < 0;
    ctx.save();
    ctx.translate(s.x, s.y);
    if (this.angle) ctx.rotate(this.angle);
    if (this.tint) ctx.filter = `drop-shadow(0 0 6px ${this.tint})`;
    const drawn = drawSheetFrame(ctx, this.sheet, this.frame, -vis / 2, -vis / 2, vis, vis, flip);
    ctx.restore();
    if (!drawn) {
      ctx.fillStyle = this.tint || (this.owner === "enemy" ? "#f87171" : "#fde68a");
      ctx.fillRect(s.x - this.w / 2, s.y - this.h / 2, this.w, this.h);
    }
  }
}
