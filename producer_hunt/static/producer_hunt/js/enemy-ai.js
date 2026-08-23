import { aabb, lineBlocked } from "./collision.js";
import { playerTorsoAim } from "./combat.js";
import { resolveDifficulty } from "./difficulty.js";

export const AI_STATES = [
  "spawn",
  "idle",
  "patrol",
  "alert",
  "chase",
  "position",
  "telegraph",
  "attack",
  "recover",
  "hit",
  "retreat",
  "death",
];

const STATE_TIMEOUT = {
  spawn: 0.7,
  alert: 1.2,
  telegraph: 1.1,
  attack: 1.6,
  recover: 1.4,
  hit: 0.55,
  charge: 0.7,
};

export class AttackCoordinator {
  constructor() {
    this.ranged = new Set();
    this.close = new Set();
    this.lastGroupAt = -99;
    this.minDelay = 0.3;
  }

  configure(diff) {
    this.maxRanged = diff.maxRanged ?? 2;
    this.maxClose = diff.maxClose ?? 1;
    this.minDelay = 0.3;
  }

  prune() {
    for (const set of [this.ranged, this.close]) {
      for (const e of [...set]) {
        if (!e?.alive || e.state === "death") set.delete(e);
      }
    }
  }

  release(enemy) {
    this.ranged.delete(enemy);
    this.close.delete(enemy);
  }

  canAttack(enemy, kind, now) {
    this.prune();
    if (now - this.lastGroupAt < this.minDelay) return false;
    if (kind === "close") return this.close.size < this.maxClose;
    return this.ranged.size < this.maxRanged;
  }

  begin(enemy, kind, now) {
    this.lastGroupAt = now;
    if (kind === "close") this.close.add(enemy);
    else this.ranged.add(enemy);
  }
}

export function onCamera(game, enemy, margin = 80) {
  const cam = game?.camera;
  if (!cam) return true;
  const x = enemy.footX;
  return x > cam.x - margin && x < cam.x + cam.w + margin;
}

export function enterState(enemy, name) {
  if (enemy.state === name) return;
  enemy.state = name;
  enemy.stateAge = 0;
  enemy._firedClip = name === "attack" ? enemy._firedClip : false;
  if (name !== "attack" && name !== "telegraph") enemy._attackArmed = false;
}

export function tickTimeout(enemy, dt) {
  enemy.stateAge = (enemy.stateAge || 0) + dt;
  const cap = STATE_TIMEOUT[enemy.state];
  if (cap && enemy.stateAge > cap) {
    if (enemy.state === "hit") enterState(enemy, "idle");
    else if (enemy.state === "spawn") enterState(enemy, enemy.spec.behavior === "close" ? "chase" : "patrol");
    else if (enemy.state === "telegraph" || enemy.state === "attack" || enemy.state === "recover" || enemy.state === "charge") {
      enemy._game?.attackCoord?.release(enemy);
      enemy.meleeActive = false;
      enterState(enemy, "idle");
    }
  }
}

export function rememberPlayer(enemy, player) {
  enemy.lastKnown = { x: player.footX, y: player.footY };
}

export function detected(enemy, player, world) {
  if (!player?.alive) return false;
  const dx = Math.abs(player.footX - enemy.footX);
  const dy = Math.abs(player.footY - enemy.footY);
  const rangeX = enemy.spec.detectionRange || 520;
  const rangeY = enemy.spec.detectionY || 220;
  if (dx > rangeX || dy > rangeY) return false;
  if (enemy.spec.needsLos) {
    const muzzle = enemy.muzzleWorld();
    const aim = playerTorsoAim(player);
    if (lineBlocked(muzzle.x, muzzle.y, aim.x, aim.y, world.solids)) return false;
  }
  return true;
}

export function aimAtTorso(enemy, player, spread = 0.08) {
  const muzzle = enemy.muzzleWorld();
  const aim = playerTorsoAim(player);
  const dx = aim.x - muzzle.x;
  const dy = aim.y - muzzle.y;
  const len = Math.hypot(dx, dy) || 1;
  const base = Math.atan2(dy, dx);
  const jitter = (Math.random() * 2 - 1) * spread;
  const a = base + jitter;
  return { muzzle, vx: Math.cos(a), vy: Math.sin(a), len };
}

export function applyDifficultyToEnemy(enemy, settings) {
  const diff = resolveDifficulty(settings?.difficulty);
  if (enemy._diffApplied === diff.id) return diff;
  const prev = enemy._diffId ? resolveDifficulty(enemy._diffId) : { health: 1, interval: 1, projSpeed: 1 };
  const healthRatio = diff.health / (prev.health || 1);
  enemy.health *= healthRatio;
  enemy.spec.health *= healthRatio;
  if (enemy.weapon) {
    enemy.weapon.cooldownSec = (enemy.weapon.cooldownSec / (prev.interval || 1)) * diff.interval;
    enemy.weapon.projectileSpeed = (enemy.weapon.projectileSpeed / (prev.projSpeed || 1)) * diff.projSpeed;
  }
  enemy._diffApplied = diff.id;
  enemy._diffId = diff.id;
  enemy.reactionMul = diff.reaction;
  enemy.aimSpread = diff.aimSpread;
  return diff;
}

export function shouldDropPickup(settings, kindChance = 0.22) {
  const diff = resolveDifficulty(settings?.difficulty);
  return Math.random() < kindChance * (diff.pickup || 1);
}
