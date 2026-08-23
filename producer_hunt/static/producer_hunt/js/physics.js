import { GRAVITY, MAX_FALL } from "./config.js";

export function applyGravity(body, dt, gravity = GRAVITY, maxFall = MAX_FALL) {
  body.vy = Math.min(maxFall, body.vy + gravity * dt);
}

export function jumpApexHeight(launchSpeed, gravity = GRAVITY) {
  const v = Math.abs(Number(launchSpeed) || 0);
  const g = Number(gravity) || GRAVITY;
  if (g <= 0) return 0;
  return (v * v) / (2 * g);
}

export function arcadeAxis(body, wish, dt, { accel, decel, maxSpeed, reverse = 0 }) {
  if (wish !== 0) {
    if (body.vx !== 0 && Math.sign(body.vx) !== wish) {
      const rev = reverse > 0 ? reverse : accel * 2.4;
      body.vx += wish * rev * dt;
    }
    body.vx += wish * accel * dt;
    if (body.vx > maxSpeed) body.vx = maxSpeed;
    if (body.vx < -maxSpeed) body.vx = -maxSpeed;
    return;
  }
  if (body.vx === 0) return;
  const sign = Math.sign(body.vx);
  body.vx -= sign * decel * dt;
  if (Math.sign(body.vx) !== sign) body.vx = 0;
}
