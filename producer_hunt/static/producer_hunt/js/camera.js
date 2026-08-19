import { DESIGN_H, DESIGN_W } from "./config.js";
import { clamp } from "./collision.js";

export class Camera {
  constructor() {
    this.x = 0;
    this.y = 0;
    this.w = DESIGN_W;
    this.h = DESIGN_H;
    this.look = 0;
  }

  follow(target, world, dt) {
    const wishLook = target.facing * 140;
    this.look += (wishLook - this.look) * Math.min(1, dt * 4);
    const focusX = target.footX - this.w * 0.38 + this.look;
    const nextX = clamp(focusX, 0, Math.max(0, world.width - this.w));
    this.x += (nextX - this.x) * Math.min(1, dt * 10);
    this.x = clamp(this.x, 0, Math.max(0, world.width - this.w));
    const focusY = target.footY - this.h * 0.72;
    this.y = clamp(focusY, 0, Math.max(0, world.height - this.h));
  }

  worldToScreen(wx, wy) {
    return { x: wx - this.x, y: wy - this.y };
  }
}
