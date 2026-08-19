import { PROJECTILE_FRAMES, drawSheetFrame } from "./asset-catalog.js";

export class Projectile {
  constructor({ x, y, vx, damage, owner, type, sheet = null }) {
    this.x = x;
    this.y = y;
    this.w = 22;
    this.h = 16;
    this.vx = vx;
    this.vy = 0;
    this.damage = damage;
    this.owner = owner;
    this.type = type || "shot";
    this.sheet = sheet;
    this.direction = Math.sign(vx) || 1;
    this.alive = true;
    this.age = 0;
    this.lifetime = 1.15;
    this.maxDistance = 900;
    this.traveled = 0;
    this.vis = 56;
  }

  bounds() {
    return { x: this.x, y: this.y, w: this.w, h: this.h };
  }

  update(dt) {
    const dx = this.vx * dt;
    this.x += dx;
    this.traveled += Math.abs(dx);
    this.age += dt;
    if (this.age >= this.lifetime || this.traveled >= this.maxDistance) this.alive = false;
  }

  draw(ctx, camera) {
    const vis = this.vis;
    const cx = this.x + this.w / 2;
    const cy = this.y + this.h / 2;
    const s = camera.worldToScreen(cx, cy);
    const frame = PROJECTILE_FRAMES[this.type] ?? 0;
    const flip = this.vx < 0;
    if (!drawSheetFrame(ctx, this.sheet, frame, s.x - vis / 2, s.y - vis / 2, vis, vis, flip)) {
      ctx.fillStyle = "#fde68a";
      ctx.fillRect(s.x - this.w / 2, s.y - this.h / 2, this.w, this.h);
    }
  }
}
