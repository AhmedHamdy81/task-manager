import { CAMERA, DESIGN_H, DESIGN_W } from "./config.js";
import { clamp } from "./collision.js";

export class Camera {
  constructor() {
    this.x = 0;
    this.y = 0;
    this.w = DESIGN_W;
    this.h = DESIGN_H;
    this.look = 0;
    this.shakeX = 0;
    this.shakeY = 0;
    this.trauma = 0;
  }

  addShake(amount) {
    this.trauma = Math.min(1, this.trauma + Math.max(0, amount));
  }

  updateShake(dt, enabled) {
    if (!enabled || this.trauma <= 0) {
      this.trauma = 0;
      this.shakeX = 0;
      this.shakeY = 0;
      return;
    }
    this.trauma = Math.max(0, this.trauma - dt * 2.4);
    const mag = this.trauma * this.trauma * 14;
    this.shakeX = (Math.random() * 2 - 1) * mag;
    this.shakeY = (Math.random() * 2 - 1) * mag;
  }

  follow(target, world, dt) {
    const wishLook = target.facing * CAMERA.look;
    this.look += (wishLook - this.look) * Math.min(1, dt * CAMERA.lookLerp);
    const maxX = Math.max(0, world.width - this.w);
    const maxY = Math.max(0, world.height - this.h);
    const focusX = target.footX - this.w * CAMERA.focusX + this.look;
    const focusY = target.footY - this.h * CAMERA.focusY;
    const nextX = clamp(focusX, 0, maxX);
    const nextY = clamp(focusY, 0, maxY);
    this.x += (nextX - this.x) * Math.min(1, dt * CAMERA.followX);
    this.y += (nextY - this.y) * Math.min(1, dt * CAMERA.followY);
    this.x = clamp(this.x, 0, maxX);
    this.y = clamp(this.y, 0, maxY);
  }

  snap(x, y, world) {
    const maxX = Math.max(0, (world?.width || this.w) - this.w);
    const maxY = Math.max(0, (world?.height || this.h) - this.h);
    this.x = clamp(x, 0, maxX);
    this.y = clamp(y, 0, maxY);
  }

  worldToScreen(wx, wy) {
    return { x: wx - this.x + this.shakeX, y: wy - this.y + this.shakeY };
  }
}
