export function aabb(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

export function dist(ax, ay, bx, by) {
  const dx = ax - bx;
  const dy = ay - by;
  return Math.hypot(dx, dy);
}

export function resolveSolids(actor, solids, dt) {
  actor.onGround = false;
  actor.y += actor.vy * dt;
  for (const s of solids) {
    if (!aabb(actor, s)) continue;
    if (actor.vy >= 0 && actor.y + actor.h > s.y && actor.y + actor.h - actor.vy * dt <= s.y + 4) {
      actor.y = s.y - actor.h;
      actor.vy = 0;
      actor.onGround = true;
    } else if (actor.vy < 0 && actor.y < s.y + s.h) {
      actor.y = s.y + s.h;
      actor.vy = 0;
    }
  }

  actor.x += actor.vx * dt;
  for (const s of solids) {
    if (!aabb(actor, s)) continue;
    if (actor.vx > 0) actor.x = s.x - actor.w;
    else if (actor.vx < 0) actor.x = s.x + s.w;
    actor.vx = 0;
  }
}

export function keepInWorld(actor, world) {
  actor.x = clamp(actor.x, 0, world.width - actor.w);
  if (actor.y + actor.h > world.height) {
    actor.y = world.height - actor.h;
    actor.vy = 0;
    actor.onGround = true;
  }
  if (actor.y < 0) {
    actor.y = 0;
    actor.vy = 0;
  }
}

export function hitsSolid(box, solids) {
  return solids.some((s) => aabb(box, s));
}
