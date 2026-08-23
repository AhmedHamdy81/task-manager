import { dist } from "./collision.js";
import { damageDestructiblesInRadius } from "./destructibles.js";
import { BOSS_01 } from "./combat.js";

export const SPECIAL_POWER_ALIASES = {
  cut: "timeline_freeze",
  turbo_sync: "production_rush",
  grade_shift: "color_blast",
  final_render: "particle_storm",
};

export function resolveSpecialPowerId(id) {
  const raw = String(id || "");
  return SPECIAL_POWER_ALIASES[raw] || raw;
}

function nearbyEnemies(ctx, radius) {
  const p = ctx.player;
  if (!p) return [];
  const px = p.footX;
  const py = p.footY - (p.h || p.standH || 170) * 0.5;
  return (ctx.enemies || []).filter((e) => {
    if (!e.alive) return false;
    const ex = e.footX ?? e.x + (e.w || 0) / 2;
    const ey = (e.footY ?? e.y + (e.h || 0)) - (e.h || 0) * 0.5;
    return dist(px, py, ex, ey) <= radius;
  });
}

function applyEnemyDamage(ctx, enemy, amount) {
  if (!enemy?.alive || typeof enemy.takeDamage !== "function") return 0;
  let dmg = amount;
  if (enemy.isBoss) dmg = Math.min(dmg, BOSS_01.specialBossCap || 80);
  const wasAlive = enemy.alive;
  const wasDying = Boolean(enemy.deathStarted);
  const dealt = enemy.takeDamage(dmg);
  const n = Number(dealt) || 0;
  if (wasAlive && !enemy.alive && !enemy.isBoss) {
    ctx.scoreboard?.awardEnemyDefeat(enemy, { weaponId: "special" });
    ctx.scoreboard?.sync(ctx);
  } else if (n > 0 && !enemy.isBoss) {
    /* hit only */
  }
  if (n > 0) ctx.beginHitStop?.(0.07, 0.18);
  if (enemy.isBoss) {
    ctx.audio?.playSound?.(enemy.deathStarted ? "enemy_death" : "enemy_hit", { x: enemy.footX, camera: ctx.camera });
  } else {
    ctx.audio?.playSound?.(enemy.alive ? "enemy_hit" : "enemy_death", { x: enemy.footX, camera: ctx.camera });
  }
  ctx.hud?.invalidate?.();
  return n;
}

function restoreRush(player) {
  if (!player) return;
  player.speedMul = 1;
  player.airControlMul = player.baseAirControl || 1;
  if (player.weapon && player._fireCooldownBase != null) {
    player.weapon.cooldownSec = player._fireCooldownBase;
  }
}

function clearCombatSlow(ctx) {
  if (!ctx) return;
  ctx.enemyTimeScale = 1;
  ctx.bossTimeScale = 1;
  ctx.hostileTimeScale = 1;
}

export const SPECIAL_POWERS = {
  timeline_freeze: {
    id: "timeline_freeze",
    displayName: "TIMELINE FREEZE",
    description: "Slows enemies and hostile shots. You keep moving at full speed.",
    image: "abilities/editor_timeline_freeze.png",
    cooldown: 14,
    energyCost: 50,
    duration: 4,
    canActivate(ctx) {
      return Boolean(ctx?.player?.alive);
    },
    activate(ctx) {
      ctx.enemyTimeScale = 0.35;
      ctx.bossTimeScale = 0.7;
      ctx.hostileTimeScale = 0.35;
    },
    update() {},
    cancel(ctx) {
      clearCombatSlow(ctx);
    },
  },
  production_rush: {
    id: "production_rush",
    displayName: "PRODUCTION RUSH",
    description: "Boosts movement, jump control, and fire rate.",
    image: "abilities/assistant_production_rush.png",
    cooldown: 15,
    energyCost: 45,
    duration: 6,
    canActivate(ctx) {
      return Boolean(ctx?.player?.alive);
    },
    activate(ctx) {
      const p = ctx.player;
      p.speedMul = 1.25;
      p.airControlMul = (p.baseAirControl || 1) * 1.15;
      if (p.weapon) p.weapon.cooldownSec = (p._fireCooldownBase ?? p.weapon.cooldownSec) * 0.6;
    },
    update() {},
    cancel(ctx) {
      restoreRush(ctx?.player);
    },
  },
  color_blast: {
    id: "color_blast",
    displayName: "COLOR BLAST",
    description: "Releases a color-energy burst that damages nearby enemies once.",
    image: "abilities/colorist_color_blast.png",
    cooldown: 12,
    energyCost: 55,
    duration: 0.45,
    radius: 260,
    canActivate(ctx) {
      return Boolean(ctx?.player?.alive);
    },
    activate(ctx, ability) {
      const p = ctx.player;
      const radius = this.radius;
      const damage = Math.max(1, Math.round((p.weapon?.damage || 10) * 2.8));
      ability.runtime.blast = { age: 0, life: this.duration, radius };
      p.powerFx = { kind: "blast", age: 0, life: this.duration, radius };
      const hit = new Set();
      for (const enemy of nearbyEnemies(ctx, radius)) {
        if (hit.has(enemy)) continue;
        hit.add(enemy);
        applyEnemyDamage(ctx, enemy, damage);
      }
      damageDestructiblesInRadius(ctx, p.footX, p.footY - (p.h || 170) * 0.5, radius, damage);
    },
    update(ctx, dt, ability) {
      const blast = ability.runtime.blast;
      if (!blast) return;
      blast.age += dt;
      if (ctx.player?.powerFx?.kind === "blast") ctx.player.powerFx.age = blast.age;
    },
    cancel(ctx) {
      if (ctx?.player?.powerFx?.kind === "blast") ctx.player.powerFx = null;
    },
  },
  particle_storm: {
    id: "particle_storm",
    displayName: "PARTICLE STORM",
    description: "A controlled storm around you that ticks damage on nearby enemies.",
    image: "abilities/vfx_supervisor_particle_storm.png",
    cooldown: 16,
    energyCost: 60,
    duration: 5,
    radius: 210,
    tickSec: 0.6,
    canActivate(ctx) {
      return Boolean(ctx?.player?.alive);
    },
    activate(ctx, ability) {
      ability.runtime.storm = { t: 0, tickAcc: this.tickSec, radius: this.radius };
      ctx.player.powerFx = { kind: "storm", age: 0, life: this.duration, radius: this.radius, particles: [] };
    },
    update(ctx, dt, ability) {
      const storm = ability.runtime.storm;
      const p = ctx.player;
      if (!storm || !p?.alive) return;
      storm.t += dt;
      storm.tickAcc += dt;
      const fx = p.powerFx?.kind === "storm" ? p.powerFx : null;
      if (fx) {
        fx.age += dt;
        const parts = fx.particles || [];
        while (parts.length < 18) {
          parts.push({
            a: Math.random() * Math.PI * 2,
            r: 40 + Math.random() * storm.radius * 0.7,
            s: 0.6 + Math.random() * 1.4,
          });
        }
        for (const part of parts) part.a += dt * part.s;
        fx.particles = parts;
      }
      if (storm.tickAcc >= this.tickSec) {
        storm.tickAcc -= this.tickSec;
        const damage = Math.max(1, Math.round((p.weapon?.damage || 10) * 0.85));
        const hit = new Set();
        for (const enemy of nearbyEnemies(ctx, storm.radius)) {
          if (hit.has(enemy)) continue;
          hit.add(enemy);
          applyEnemyDamage(ctx, enemy, damage);
        }
      }
    },
    cancel(ctx) {
      if (ctx?.player?.powerFx?.kind === "storm") ctx.player.powerFx = null;
    },
  },
};

export function getSpecialPower(id) {
  return SPECIAL_POWERS[resolveSpecialPowerId(id)] || null;
}

export function specialPowerSpec(id) {
  const power = getSpecialPower(id);
  if (!power) {
    return {
      id: resolveSpecialPowerId(id) || "none",
      name: "COMING SOON",
      duration: 0,
      cooldown: 0,
      energyCost: 0,
      image: "",
    };
  }
  return {
    id: power.id,
    name: power.displayName,
    duration: power.duration,
    cooldown: power.cooldown,
    energyCost: power.energyCost,
    image: power.image,
  };
}

export function abilityImplemented(id) {
  return Boolean(getSpecialPower(id));
}

export function abilityMenuInfo(spec) {
  const id = resolveSpecialPowerId(spec?.id || spec);
  const power = getSpecialPower(id);
  if (!power) {
    return {
      id: id || "none",
      name: "COMING SOON",
      description: "This special power is not available yet.",
      resource: "",
      implemented: false,
      image: id ? `abilities/${id}.png` : "",
    };
  }
  return {
    id: power.id,
    name: power.displayName,
    description: power.description,
    resource: `Energy ${power.energyCost}  ·  CD ${power.cooldown}s`,
    cooldown: power.cooldown,
    duration: power.duration,
    energyCost: power.energyCost,
    implemented: true,
    image: power.image,
  };
}

export class SpecialAbility {
  constructor(spec) {
    const resolved = resolveSpecialPowerId(spec?.id);
    this.def = getSpecialPower(resolved);
    this.id = this.def?.id || resolved || spec?.id;
    this.name = this.def?.displayName || spec?.name || this.id;
    this.duration = this.def?.duration ?? spec?.duration ?? 0;
    this.cooldown = this.def?.cooldown ?? spec?.cooldown ?? 0;
    this.energyCost = this.def?.energyCost ?? spec?.energyCost ?? 0;
    this.image = this.def?.image || spec?.image || "";
    this.active = 0;
    this.cool = 0;
    this.runtime = {};
  }

  get ready() {
    return this.cool <= 0 && this.active <= 0;
  }

  canActivate(ctx) {
    if (!ctx?.player?.alive) return { ok: false, reason: "busy" };
    if (!this.def) return { ok: false, reason: "missing", id: this.id };
    if (!this.ready) return { ok: false, reason: "cooldown", remain: Math.max(0, this.cool) };
    const cost = this.energyCost || 0;
    if ((ctx.player.energy || 0) < cost) return { ok: false, reason: "energy" };
    if (this.def.canActivate && !this.def.canActivate(ctx)) return { ok: false, reason: "busy" };
    return { ok: true };
  }

  activate(ctx) {
    const check = this.canActivate(ctx);
    if (!check.ok) return check;
    ctx.player.spendEnergy(this.energyCost || 0);
    this.runtime = {};
    this.active = this.duration || 0.05;
    this.cool = this.cooldown;
    this.def.activate(ctx, this);
    ctx.scoreboard?.noteAbilityUse(this.id);
    ctx.hud?.invalidate?.();
    return { ok: true };
  }

  update(dt, ctx) {
    if (this.active > 0 && this.def?.update) this.def.update(ctx, dt, this);
    if (this.active > 0) {
      this.active -= dt;
      if (this.active <= 0) {
        this.active = 0;
        this.def?.cancel?.(ctx, this);
        this.runtime = {};
      }
    }
    if (this.cool > 0) this.cool -= dt;
  }

  cancel(ctx) {
    if (this.def?.cancel) this.def.cancel(ctx, this);
    this.active = 0;
    this.runtime = {};
  }
}
