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

  clearShake() {
    this.trauma = 0;
    this.shakeX = 0;
    this.shakeY = 0;
  }

  updateShake(dt, enabled) {
    if (!enabled || this.trauma <= 0) {
      this.clearShake();
      return;
    }
    this.trauma = Math.max(0, this.trauma - dt * (CAMERA.shakeDecay || 4.4));
    const mag = this.trauma * this.trauma * 12;
    this.shakeX = (Math.random() * 2 - 1) * mag;
    this.shakeY = (Math.random() * 2 - 1) * mag;
  }

  follow(target, world, dt, lock = null) {
    const lookScale = Number.isFinite(lock?.lookScale) ? lock.lookScale : 1;
    const wishLook = (target.facing || 1) * CAMERA.look * lookScale;
    this.look += (wishLook - this.look) * Math.min(1, dt * CAMERA.lookLerp);
    const maxX = Math.max(0, world.width - this.w);
    const maxY = Math.max(0, world.height - this.h);
    const air = !target.onGround;
    const focusY = air ? (CAMERA.airFocusY || 0.58) : CAMERA.focusY;
    const focusFrac = Number.isFinite(lock?.focusX) ? lock.focusX : CAMERA.focusX;
    const focusX = target.footX - this.w * focusFrac + this.look;
    let loX = 0;
    let hiX = maxX;
    if (lock && Number.isFinite(lock.left) && Number.isFinite(lock.right)) {
      loX = clamp(lock.left - 40, 0, maxX);
      hiX = clamp(lock.right - this.w + 40, loX, maxX);
    }
    const nextX = clamp(focusX, loX, hiX);
    this.x += (nextX - this.x) * Math.min(1, dt * CAMERA.followX);
    this.x = clamp(this.x, loX, hiX);

    const desiredY = clamp(target.footY - this.h * focusY, 0, maxY);
    const dead = air ? (CAMERA.deadY || 0) * 0.35 : CAMERA.deadY || 0;
    if (Math.abs(desiredY - this.y) > dead) {
      this.y += (desiredY - this.y) * Math.min(1, dt * CAMERA.followY);
    }
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
