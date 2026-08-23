/** Studio 01 destructible props. Damage goes through the existing projectile/explosion pipeline. */

import { aabb, lineBlocked } from "./collision.js";
import { instantiatePickup } from "./pickups.js";
import { resolveDifficulty } from "./difficulty.js";
import { DEBUG_COMBAT, HITSTOP_LIGHT_SEC, SHAKE_HEAVY, SHAKE_LIGHT } from "./config.js";
import { syncDoorSolids } from "./progression.js";

const HP = 10;
const MISSING = new Set();
const IMPACT_GAP = 0.08;

export const EXPECTED_DESTRUCTIBLE_ASSETS = [
  "environment/studio_01/destructibles/equipment_crate.png",
  "environment/studio_01/destructibles/production_monitor.png",
  "environment/studio_01/destructibles/studio_light_stand.png",
  "environment/studio_01/destructibles/film_reel_container.png",
  "environment/studio_01/destructibles/electrical_control_box.png",
  "environment/studio_01/destructibles/compressed_air_canister.png",
  "environment/studio_01/destructibles/barber_supply_case.png",
  "environment/studio_01/destructibles/equipment_cage.png",
  "environment/studio_01/destructibles/locked_sound_booth.png",
  "environment/studio_01/destructibles/collapsed_set_debris.png",
  "environment/studio_01/destructibles/security_barrier.png",
  "effects/destruction/debris.png",
  "effects/explosions/blast.png",
];

export function warnMissingDestructibleAsset(rel) {
  if (MISSING.has(rel)) return;
  MISSING.add(rel);
  console.warn(`[Producer Hunt] Missing destructible asset: ${rel}. Using a labeled placeholder.`);
}

function visual(id, extra = {}) {
  const asset = `environment/studio_01/destructibles/${id}.png`;
  return {
    asset,
    damagedAsset: asset,
    destroyedAsset: extra.destroyedAsset || "effects/destruction/debris.png",
    hitEffect: "effects/destruction/debris.png",
    destroyEffect: extra.explosive ? "effects/explosions/blast.png" : "effects/destruction/debris.png",
    collisionSize: { w: extra.w, h: extra.h },
    collisionOffset: extra.collisionOffset || { x: 0, y: 0 },
    persistent: Boolean(extra.persistent),
    ...extra,
  };
}

export const DESTRUCTIBLE_DEFS = {
  equipment_crate: visual("equipment_crate", {
    id: "equipment_crate",
    displayName: "Equipment Crate",
    maxHealth: 4 * HP,
    w: 56,
    h: 52,
    color: "#b45309",
    damagedColor: "#7c2d12",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    hitSfx: "destruct_wood",
    destroySfx: "destruct_break",
    scoreOnBreak: 15,
    dropTable: [
      { kind: null, weight: 45 },
      { kind: "ammo", weight: 25 },
      { kind: "health", weight: 15 },
      { kind: "bonus", weight: 10 },
      { kind: "machine_gun", weight: 5 },
    ],
  }),
  production_monitor: visual("production_monitor", {
    id: "production_monitor",
    displayName: "Production Monitor",
    maxHealth: 3 * HP,
    w: 70,
    h: 78,
    color: "#1e3a5f",
    damagedColor: "#0f172a",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    hitSfx: "destruct_glass",
    destroySfx: "destruct_glass",
    scoreOnBreak: 25,
    sparks: true,
    dropTable: [{ kind: null, weight: 70 }, { kind: "bonus", weight: 30 }],
  }),
  studio_light_stand: visual("studio_light_stand", {
    id: "studio_light_stand",
    displayName: "Studio Light Stand",
    maxHealth: 3 * HP,
    w: 28,
    h: 92,
    collisionOffset: { x: 8, y: 0 },
    color: "#64748b",
    damagedColor: "#334155",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    hitSfx: "destruct_metal",
    destroySfx: "destruct_break",
    scoreOnBreak: 20,
    collapse: true,
    dropTable: [{ kind: null, weight: 100 }],
  }),
  film_reel_container: visual("film_reel_container", {
    id: "film_reel_container",
    displayName: "Film-Reel Container",
    maxHealth: 5 * HP,
    w: 72,
    h: 64,
    color: "#57534e",
    damagedColor: "#44403c",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    hitSfx: "destruct_wood",
    destroySfx: "destruct_break",
    scoreOnBreak: 20,
    dropTable: [
      { kind: null, weight: 50 },
      { kind: "ammo", weight: 30 },
      { kind: "bonus", weight: 20 },
    ],
  }),
  electrical_control_box: visual("electrical_control_box", {
    id: "electrical_control_box",
    displayName: "Electrical Control Box",
    maxHealth: 6 * HP,
    w: 48,
    h: 70,
    color: "#0e7490",
    damagedColor: "#155e75",
    explosive: true,
    explosionDamage: 3 * HP,
    explosionRadius: 90,
    explosionDelay: 0.45,
    knockback: 280,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_metal",
    destroySfx: "destruct_overload",
    warningSfx: "destruct_overload",
    scoreOnBreak: 40,
    dropTable: [{ kind: null, weight: 80 }, { kind: "ammo", weight: 20 }],
  }),
  compressed_air_canister: visual("compressed_air_canister", {
    id: "compressed_air_canister",
    displayName: "Compressed-Air Canister",
    maxHealth: 3 * HP,
    w: 32,
    h: 78,
    color: "#38bdf8",
    damagedColor: "#0369a1",
    explosive: true,
    explosionDamage: 4 * HP,
    explosionRadius: 110,
    explosionDelay: 0.65,
    knockback: 340,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_metal",
    destroySfx: "destruct_boom",
    warningSfx: "destruct_hiss",
    scoreOnBreak: 35,
    dropTable: [{ kind: null, weight: 100 }],
  }),
  barber_supply_case: visual("barber_supply_case", {
    id: "barber_supply_case",
    displayName: "Barber Supply Case",
    maxHealth: 6 * HP,
    w: 64,
    h: 52,
    color: "#e8b84a",
    damagedColor: "#a16207",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    persistent: true,
    hitSfx: "destruct_wood",
    destroySfx: "destruct_break",
    scoreOnBreak: 50,
    guaranteed: true,
    dropTable: [
      { kind: "health", weight: 55 },
      { kind: "ammo", weight: 45 },
    ],
  }),
  equipment_cage: visual("equipment_cage", {
    id: "equipment_cage",
    displayName: "Equipment Cage",
    maxHealth: 5 * HP,
    w: 88,
    h: 118,
    color: "#78716c",
    damagedColor: "#44403c",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_metal",
    destroySfx: "destruct_break",
    scoreOnBreak: 10,
    dropTable: [{ kind: null, weight: 100 }],
  }),
  locked_sound_booth: visual("locked_sound_booth", {
    id: "locked_sound_booth",
    displayName: "Locked Sound Booth",
    maxHealth: 5 * HP,
    w: 96,
    h: 112,
    color: "#1e3a5f",
    damagedColor: "#0f172a",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_wood",
    destroySfx: "destruct_break",
    scoreOnBreak: 10,
    dropTable: [{ kind: null, weight: 100 }],
  }),
  collapsed_set_debris: visual("collapsed_set_debris", {
    id: "collapsed_set_debris",
    displayName: "Collapsed Set Debris",
    maxHealth: 4 * HP,
    w: 100,
    h: 72,
    color: "#57534e",
    damagedColor: "#292524",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_wood",
    destroySfx: "destruct_break",
    scoreOnBreak: 10,
    dropTable: [{ kind: null, weight: 100 }],
  }),
  security_barrier: visual("security_barrier", {
    id: "security_barrier",
    displayName: "Security Barrier",
    maxHealth: 5 * HP,
    w: 80,
    h: 100,
    color: "#eab308",
    damagedColor: "#a16207",
    explosive: false,
    blocksMovement: true,
    enemyDamage: false,
    chain: true,
    hitSfx: "destruct_metal",
    destroySfx: "destruct_break",
    scoreOnBreak: 10,
    dropTable: [{ kind: null, weight: 100 }],
  }),
};

export function destructibleDef(kind) {
  return DESTRUCTIBLE_DEFS[kind] || DESTRUCTIBLE_DEFS.equipment_crate;
}

export function instantiateDestructible(raw, index, levelId) {
  const def = destructibleDef(raw.kind);
  const w = raw.w || def.collisionSize?.w || def.w;
  const h = raw.h || def.collisionSize?.h || def.h;
  const ox = raw.collisionOffset?.x ?? def.collisionOffset?.x ?? 0;
  const oy = raw.collisionOffset?.y ?? def.collisionOffset?.y ?? 0;
  return {
    id: raw.id || `${levelId || "lvl"}_brk_${index}`,
    kind: def.id,
    displayName: def.displayName,
    x: raw.x + ox,
    y: raw.y - h + oy,
    w,
    h,
    maxHealth: def.maxHealth,
    health: def.maxHealth,
    state: "intact",
    hitFlash: 0,
    delay: 0,
    dropped: false,
    dropKind: null,
    armed: false,
    exploded: false,
    shake: 0,
    blocksMovement: def.blocksMovement !== false,
    persistent: Boolean(def.persistent || raw.persistent),
    guaranteed: Boolean(def.guaranteed),
    enemyDamage: Boolean(def.enemyDamage || raw.enemyDamage),
    def,
  };
}

export function destructibleSolid(d) {
  if (!d || !d.blocksMovement || d.state === "gone" || d.state === "rubble") return null;
  if (d.state === "pending" || d.state === "intact" || d.state === "damaged") {
    return { x: d.x, y: d.y, w: d.w, h: d.h, destructibleId: d.id };
  }
  return null;
}

export function injectDestructibleSolids(world) {
  if (!world) return;
  world.destructibleSolids = (world.destructibles || []).map(destructibleSolid).filter(Boolean);
  syncDoorSolids(world);
}

export function snapshotDestructibles(world) {
  return (world?.destructibles || []).map((d) => {
    const pending = d.state === "pending";
    return {
      id: d.id,
      health: pending ? Math.max(1, Math.floor(d.maxHealth * 0.25)) : d.health,
      state: pending ? "damaged" : d.state,
      dropped: Boolean(d.dropped),
      dropKind: d.dropKind,
      armed: false,
      exploded: pending ? false : Boolean(d.exploded),
    };
  });
}

export function applyDestructibleSnapshot(world, rows) {
  if (!world || !rows) return;
  const map = Object.fromEntries(rows.map((r) => [r.id, r]));
  for (const d of world.destructibles || []) {
    const rec = map[d.id];
    if (!rec) {
      d.health = d.maxHealth;
      d.state = "intact";
      d.dropped = false;
      d.dropKind = null;
      d.armed = false;
      d.exploded = false;
      d.delay = 0;
      d.blocksMovement = d.def.blocksMovement !== false;
      continue;
    }
    d.health = rec.health;
    d.state = rec.state === "pending" ? "damaged" : rec.state;
    d.dropped = Boolean(rec.dropped);
    d.dropKind = rec.dropKind;
    d.armed = false;
    d.exploded = Boolean(rec.exploded) && rec.state !== "pending";
    d.delay = 0;
    d.hitFlash = 0;
    const broken = rec.state === "gone" || rec.state === "rubble" || rec.exploded;
    if (broken) {
      d.state = d.def.collapse && !d.def.explosive ? "rubble" : "gone";
      d.health = 0;
      d.blocksMovement = false;
    } else {
      d.blocksMovement = d.def.blocksMovement !== false;
    }
    if (d.dropped && d.dropKind) restoreDrop(world, d);
  }
  injectDestructibleSolids(world);
}

function restoreDrop(world, d) {
  const id = `${d.id}_drop`;
  if ((world.pickups || []).some((p) => p.id === id)) return;
  const ground = world.ground?.y ?? 960;
  const pickup = instantiatePickup({ id, kind: d.dropKind, x: d.x + d.w / 2 - 32, y: Math.min(d.y + d.h, ground) - 64 }, 0, world.id);
  pickup.respawn = false;
  pickup.persistence = "persist";
  world.pickups.push(pickup);
}

export function resetDestructibleFx(game) {
  game.debris = [];
}

function freezeBreak(game) {
  return Boolean(
    game._cinematicActive ||
      game.bossEncounter?.phase === "intro" ||
      game.bossEncounter?.phase === "dying" ||
      game.bossEncounter?.phase === "defeat_cinematic"
  );
}

function onCam(game, x, margin = 80) {
  const cam = game.camera;
  if (!cam) return true;
  return x > cam.x - margin && x < cam.x + cam.w + margin;
}

export function cancelPendingExplosions(game, opts = {}) {
  const beyond = opts.beyondX;
  for (const d of game.world?.destructibles || []) {
    if (d.state !== "pending") continue;
    if (Number.isFinite(beyond) && d.x + d.w < beyond) continue;
    d.state = "gone";
    d.armed = true;
    d.exploded = true;
    d.blocksMovement = false;
    d.delay = 0;
  }
  injectDestructibleSolids(game.world);
}

function rollDrop(def, settings) {
  const diff = resolveDifficulty(settings?.difficulty);
  const mul = diff.pickup || 1;
  const table = (def.dropTable || []).map((row) => {
    if (!row.kind) return row;
    if (row.kind === "health" || row.kind === "ammo") return { ...row, weight: row.weight * mul };
    return row;
  });
  const total = table.reduce((s, r) => s + (r.weight || 0), 0) || 1;
  let n = Math.random() * total;
  for (const row of table) {
    n -= row.weight || 0;
    if (n <= 0) return row.kind || null;
  }
  return table[table.length - 1]?.kind || null;
}

function spawnDrop(game, d, kind) {
  if (d.dropped) return;
  d.dropped = true;
  d.dropKind = kind || null;
  if (!kind) return;
  const ground = game.world.ground?.y ?? 960;
  let x = d.x + d.w / 2 - 32;
  let y = Math.min(d.y + d.h, ground) - 64;
  const box = { x, y, w: 36, h: 36 };
  const blocked = (game.world.solids || []).some((s) => !s.destructibleId && aabb(box, s) && s.y + 8 < y + 36);
  if (blocked) {
    x += 48;
    y = ground - 64;
  }
  const pickup = instantiatePickup({ id: `${d.id}_drop`, kind, x, y }, 0, game.world.id);
  pickup.respawn = false;
  pickup.persistence = "persist";
  game.world.pickups.push(pickup);
  game.sfx("destruct_drop", { x: pickup.x });
}

function spawnDebris(game, d, count = 6) {
  if (!game.debris) game.debris = [];
  game._debrisPool = game._debrisPool || [];
  const n = Math.min(10, count);
  for (let i = 0; i < n; i += 1) {
    const p = game._debrisPool.pop() || {};
    p.x = d.x + Math.random() * d.w;
    p.y = d.y + Math.random() * d.h * 0.5;
    p.vx = (Math.random() - 0.5) * 280;
    p.vy = -80 - Math.random() * 220;
    p.life = 0.45 + Math.random() * 0.35;
    p.age = 0;
    p.size = 4 + Math.random() * 6;
    p.color = d.def.damagedColor || "#78716c";
    game.debris.push(p);
  }
  game.sfx("destruct_debris", { x: d.x + d.w / 2 });
}

function throttleSfx(game, id, x) {
  const now = game._worldTime || 0;
  game._breakSfxAt = game._breakSfxAt || {};
  if (now - (game._breakSfxAt[id] || -99) < IMPACT_GAP) return;
  game._breakSfxAt[id] = now;
  game.sfx(id, { x });
}

export function damageDestructible(game, d, amount, opts = {}) {
  if (!d || d.state === "gone" || d.state === "rubble" || d.state === "pending") return 0;
  if (freezeBreak(game) && !opts.force) return 0;
  const amt = Number(amount);
  if (!Number.isFinite(amt) || amt <= 0) return 0;
  if (d.health <= 0) return 0;
  d.health = Math.max(0, d.health - amt);
  d.hitFlash = 0.09;
  const cx = d.x + d.w / 2;
  if (d.health > 0) {
    d.state = d.health <= d.maxHealth * 0.5 ? "damaged" : "intact";
    throttleSfx(game, d.def.hitSfx || "destruct_metal", cx);
    game.spawnFx?.({
      sheetKey: "effects",
      frame: 5,
      x: cx,
      y: d.y + d.h * 0.4,
      size: 40,
      life: 0.12,
    });
    return amt;
  }
  beginDestroy(game, d);
  return amt;
}

function beginDestroy(game, d) {
  if (d.armed) return;
  d.armed = true;
  d.health = 0;
  const cx = d.x + d.w / 2;
  if (d.def.explosive) {
    d.state = "pending";
    d.delay = d.def.explosionDelay || 0.45;
    d.shake = 1;
    game.sfx(d.def.warningSfx || "destruct_hiss", { x: cx });
    return;
  }
  finishDestroy(game, d);
}

function finishDestroy(game, d) {
  if (d.state === "gone" || d.state === "rubble") return;
  d.blocksMovement = false;
  d.health = 0;
  const cx = d.x + d.w / 2;
  const cy = d.y + d.h * 0.5;
  if (!d.def.explosive) game.sfx(d.def.destroySfx || "destruct_break", { x: cx });
  spawnDebris(game, d, d.kind === "film_reel_container" ? 9 : 6);
  if (d.def.scoreOnBreak) game.score += d.def.scoreOnBreak;
  const kind = d.dropKind || rollDrop(d.def, game.settings);
  spawnDrop(game, d, kind);
  if (d.def.collapse) d.state = "rubble";
  else d.state = "gone";
  injectDestructibleSolids(game.world);
  game.hud?.invalidate?.();
  game.spawnFx?.({
    sheetKey: "effects",
    frame: d.def.sparks ? 5 : 4,
    x: cx,
    y: cy,
    size: d.def.sparks ? 56 : 72,
    life: 0.22,
  });
}

export function applyExplosion(game, origin, spec) {
  if (!game || freezeBreak(game)) return;
  const radius = spec.radius || 90;
  const damage = spec.damage || 30;
  const knock = spec.knockback || 260;
  const ox = origin.x;
  const oy = origin.y;
  const seen = spec.seen || new Set();
  const solids = (game.world.solids || []).filter((s) => !s.destructibleId);
  if (game.shakeEnabled()) game.camera.addShake(SHAKE_HEAVY);
  game.beginHitStop?.(HITSTOP_LIGHT_SEC, SHAKE_LIGHT);
  game.sfx(spec.sfx || "destruct_boom", { x: ox });
  game.spawnFx?.({ sheetKey: "effects", frame: 4, x: ox, y: oy, size: Math.min(140, radius * 1.2), life: 0.28 });

  const tryHit = (id, box, fn) => {
    if (!box || seen.has(id)) return;
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    if (Math.hypot(cx - ox, cy - oy) > radius) return;
    if (lineBlocked(ox, oy, cx, cy, solids, 6)) return;
    seen.add(id);
    fn();
  };

  if (spec.hitsPlayer !== false && game.player?.alive) {
    tryHit("player", game.player.bounds(), () => {
      const dir = Math.sign(game.player.footX - ox) || 1;
      const dealt = game.player.takeDamage(damage, { knockbackX: dir * knock });
      if (dealt) {
        game._applyPlayerKnockback?.(dir * 28);
        game.sfx("player_hit");
        game.hud?.invalidate?.();
      }
    });
  }
  if (spec.hitsEnemies !== false) {
    for (const enemy of game.enemies || []) {
      if (!enemy.alive) continue;
      tryHit(enemy.spawnId || enemy, enemy.bounds(), () => {
        let dmg = damage;
        if (enemy.isBoss) dmg = Math.round(dmg * (spec.bossMul ?? 0.15));
        if (dmg <= 0) return;
        const wasAlive = enemy.alive;
        const wasDying = Boolean(enemy.deathStarted);
        game.score += enemy.takeDamage(dmg);
        if (enemy.isBoss) {
          if (enemy.deathStarted && !wasDying) game.sfx("enemy_death", { x: enemy.footX });
          else if (!enemy.deathStarted) game.sfx("enemy_hit", { x: enemy.footX });
        } else if (wasAlive && !enemy.alive) {
          game.stats.kills += 1;
          game.sfx("enemy_death", { x: enemy.footX });
        } else game.sfx("enemy_hit", { x: enemy.footX });
      });
    }
  }
  if (spec.hitsProps !== false) {
    for (const d of game.world.destructibles || []) {
      if (d.id === spec.sourceId) continue;
      if (d.state === "gone" || d.state === "rubble" || d.state === "pending") continue;
      tryHit(d.id, { x: d.x, y: d.y, w: d.w, h: d.h }, () => {
        damageDestructible(game, d, damage, { force: true });
      });
    }
  }
}

export function tickDestructibles(game, dt) {
  if (!game.world) return;
  const frozen = freezeBreak(game);
  for (const d of game.world.destructibles || []) {
    if (d.hitFlash > 0) d.hitFlash -= dt;
    if (frozen) continue;
    if (d.state === "pending") {
      d.delay -= dt;
      d.shake = 1;
      if (d.delay <= 0 && !d.exploded) {
        d.exploded = true;
        const origin = { x: d.x + d.w / 2, y: d.y + d.h * 0.5 };
        finishDestroy(game, d);
        applyExplosion(game, origin, {
          damage: d.def.explosionDamage,
          radius: d.def.explosionRadius,
          knockback: d.def.knockback,
          sourceId: d.id,
          sfx: d.def.destroySfx,
          bossMul: 0.15,
        });
      }
    }
  }
  tickDebris(game, dt);
}

function tickDebris(game, dt) {
  const next = [];
  game._debrisPool = game._debrisPool || [];
  for (const p of game.debris || []) {
    if (!onCam(game, p.x, 120) || (p.age += dt) >= p.life) {
      game._debrisPool.push(p);
      continue;
    }
    p.vy += 1400 * dt;
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    next.push(p);
  }
  game.debris = next;
}

export function tryHitDestructible(game, shot) {
  if (!shot?.alive || shot.spent || shot.hasHit) return false;
  const travel = typeof shot.travelBounds === "function" ? shot.travelBounds() : shot.bounds();
  const playerShot = shot.owner === "player";
  for (const d of game.world?.destructibles || []) {
    if (d.state === "gone" || d.state === "rubble" || d.state === "pending") continue;
    if (!playerShot && !d.enemyDamage) continue;
    if (!aabb(travel, d) && !aabb(shot.bounds(), d)) continue;
    if (!playerShot) {
      shot.hasHit = true;
      damageDestructible(game, d, shot.damage || 10);
      shot.disable();
      return true;
    }
    shot.hasHit = true;
    damageDestructible(game, d, shot.damage || 10);
    const stop = shot.hitStop;
    if (stop === "heavy") game.beginHitStop(0.085, shot.cameraShake || SHAKE_HEAVY);
    else if (stop === "light") game.beginHitStop(0.045, shot.cameraShake || SHAKE_LIGHT);
    game.spawnImpact(shot);
    game._applySplash(shot, d);
    shot.disable();
    game.hud?.invalidate?.();
    return true;
  }
  return false;
}

export function splashDestructibles(game, shot, excludeBox) {
  if (!shot || shot.owner !== "player" || !(shot.splashRadius > 0) || !(shot.splashDamage > 0)) return;
  const c = shot.center ? shot.center() : { x: shot.x + shot.w / 2, y: shot.y + shot.h / 2 };
  const seen = new Set();
  for (const d of game.world?.destructibles || []) {
    if (d.state === "gone" || d.state === "rubble" || d.state === "pending") continue;
    if (excludeBox && (excludeBox === d || excludeBox.id === d.id)) continue;
    const cx = d.x + d.w / 2;
    const cy = d.y + d.h / 2;
    const dist = Math.hypot(cx - c.x, cy - c.y);
    if (dist > shot.splashRadius) continue;
    if (seen.has(d.id)) continue;
    seen.add(d.id);
    const falloff = 1 - dist / shot.splashRadius;
    const dmg = Math.max(1, Math.round(shot.splashDamage * (0.4 + 0.6 * falloff)));
    damageDestructible(game, d, dmg);
  }
}

export function damageDestructiblesInRadius(game, x, y, radius, amount) {
  const hit = new Set();
  for (const d of game.world?.destructibles || []) {
    if (hit.has(d.id)) continue;
    const cx = d.x + d.w / 2;
    const cy = d.y + d.h / 2;
    if (Math.hypot(cx - x, cy - y) > radius) continue;
    hit.add(d.id);
    damageDestructible(game, d, amount);
  }
}

export function drawDestructibles(ctx, game) {
  for (const d of game.world?.destructibles || []) {
    if (d.state === "gone" && !d.def.collapse) continue;
    const s = game.camera.worldToScreen(d.x, d.y);
    const flash = d.hitFlash > 0;
    const pending = d.state === "pending";
    const shakeX = pending ? Math.sin((game._worldTime || 0) * 40) * 3 : 0;
    const img = game.assets?.get?.(d.def.asset) || game.assets?.images?.get(d.def.asset);
    ctx.save();
    if (d.state === "rubble") {
      ctx.globalAlpha = 0.7;
      if (img) ctx.drawImage(img, s.x, s.y + d.h * 0.35, d.w, d.h * 0.65);
      else {
        ctx.fillStyle = d.def.damagedColor;
        ctx.fillRect(s.x, s.y + d.h * 0.55, d.w, d.h * 0.45);
      }
      ctx.restore();
      continue;
    }
    ctx.translate(shakeX, 0);
    if (img) {
      ctx.globalAlpha = pending ? 0.85 : 1;
      ctx.drawImage(img, s.x, s.y, d.w, d.h);
      if (d.state === "damaged" || pending) {
        ctx.fillStyle = "rgba(15,23,42,0.28)";
        ctx.fillRect(s.x, s.y, d.w, d.h);
      }
      if (flash) {
        ctx.globalAlpha = 0.35;
        ctx.fillStyle = "#f8fafc";
        ctx.fillRect(s.x, s.y, d.w, d.h);
      }
    } else {
      ctx.fillStyle = flash ? "#f8fafc" : d.state === "damaged" || pending ? d.def.damagedColor : d.def.color;
      ctx.fillRect(s.x, s.y, d.w, d.h);
    }
    if (d.kind === "production_monitor" && (!img || d.state === "damaged")) {
      if (!img) {
        ctx.fillStyle = d.state === "damaged" ? "#67e8f9" : "#22d3ee";
        ctx.globalAlpha = pending ? 0.4 : 0.85;
        ctx.fillRect(s.x + 8, s.y + 10, d.w - 16, d.h * 0.45);
      }
      if (d.state === "damaged") {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "#e2e8f0";
        ctx.beginPath();
        ctx.moveTo(s.x + 10, s.y + 14);
        ctx.lineTo(s.x + d.w - 12, s.y + d.h * 0.4);
        ctx.stroke();
      }
    }
    if ((d.kind === "compressed_air_canister" || d.kind === "electrical_control_box") && pending) {
      ctx.fillStyle = `rgba(250,204,21,${0.4 + 0.4 * Math.sin((game._worldTime || 0) * 16)})`;
      ctx.fillRect(s.x + d.w * 0.35, s.y + 8, d.w * 0.3, 10);
    }
    if (d.kind === "barber_supply_case" && !img) {
      ctx.fillStyle = "#ef4444";
      ctx.fillRect(s.x + 6, s.y + 6, 10, d.h - 12);
      ctx.fillRect(s.x + d.w - 16, s.y + 6, 10, d.h - 12);
    }
    ctx.restore();
  }
}

export function drawDebris(ctx, game) {
  for (const p of game.debris || []) {
    const s = game.camera.worldToScreen(p.x, p.y);
    ctx.globalAlpha = Math.max(0, 1 - p.age / p.life);
    ctx.fillStyle = p.color;
    ctx.fillRect(s.x, s.y, p.size, p.size);
    ctx.globalAlpha = 1;
  }
}

export function drawDestructibleDebug(ctx, game) {
  if (!game.debug && !DEBUG_COMBAT) return;
  const cam = game.camera;
  ctx.save();
  ctx.font = "11px monospace";
  for (const d of game.world?.destructibles || []) {
    const s = cam.worldToScreen(d.x, d.y);
    ctx.strokeStyle = d.blocksMovement ? "#f97316" : "#64748b";
    ctx.strokeRect(s.x, s.y, d.w, d.h);
    if (d.def.explosive) {
      ctx.strokeStyle = "rgba(248,113,113,0.5)";
      ctx.beginPath();
      ctx.arc(s.x + d.w / 2, s.y + d.h / 2, d.def.explosionRadius, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.fillStyle = "#e2e8f0";
    ctx.fillText(`${d.id} ${d.state} hp:${Math.ceil(d.health)}`, s.x, s.y - 4);
    ctx.fillText(d.dropped ? `drop ${d.dropKind || "none"}` : "drop -", s.x, s.y - 16);
  }
  ctx.restore();
}

export { HP };
