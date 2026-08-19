import { dist } from "./collision.js";

function nearbyEnemies(ctx, radius) {
  const p = ctx.player;
  const px = p.x + p.w / 2;
  const py = p.y + p.h / 2;
  return ctx.enemies.filter((e) => e.alive && dist(px, py, e.x + e.w / 2, e.y + e.h / 2) <= radius);
}

const HANDLERS = {
  cut: {
    activate(ctx) {
      for (const e of nearbyEnemies(ctx, 320)) e.freeze(ctx.player.ability.duration);
    },
  },
  turbo_sync: {
    activate(ctx) {
      ctx.player.speedMul = 1.55;
    },
    expire(ctx) {
      ctx.player.speedMul = 1;
    },
  },
  final_render: {
    activate(ctx) {
      ctx.player.renderBurst = 0.3;
      for (const e of nearbyEnemies(ctx, 180)) {
        ctx.score += e.takeDamage(ctx.player.weapon.damage * 2.2);
      }
    },
  },
  grade_shift: {
    activate(ctx) {
      ctx.player.damageMul = 1.75;
    },
    expire(ctx) {
      ctx.player.damageMul = 1;
    },
  },
};

export class SpecialAbility {
  constructor(spec) {
    this.id = spec.id;
    this.name = spec.name;
    this.duration = spec.duration;
    this.cooldown = spec.cooldown;
    this.active = 0;
    this.cool = 0;
    this.handler = HANDLERS[spec.id] || {};
  }

  get ready() {
    return this.cool <= 0 && this.active <= 0;
  }

  activate(ctx) {
    if (!this.ready) return false;
    this.active = this.duration;
    this.cool = this.cooldown;
    if (this.handler.activate) this.handler.activate(ctx);
    return true;
  }

  update(dt, ctx) {
    if (this.active > 0) {
      this.active -= dt;
      if (this.active <= 0) {
        this.active = 0;
        if (this.handler.expire) this.handler.expire(ctx);
      }
    }
    if (this.cool > 0) this.cool -= dt;
  }
}
