import { GRAVITY, MAX_FALL } from "./config.js";

export function applyGravity(body, dt, gravity = GRAVITY, maxFall = MAX_FALL) {
  body.vy = Math.min(maxFall, body.vy + gravity * dt);
}

export function arcadeAxis(body, wish, dt, { accel, decel, maxSpeed }) {
  if (wish !== 0) {
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
