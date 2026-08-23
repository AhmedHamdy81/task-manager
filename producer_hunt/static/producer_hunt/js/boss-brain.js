/** Boss 1 combat brain. Encounter flow stays in boss.js. */

import { applyGravity } from "./physics.js";
import { aabb, keepInWorld, resolveSolids } from "./collision.js";
import { Enemy } from "./enemy.js";
import { BOSS_01, playerTorsoAim, projectileDef } from "./combat.js";
import { resolveDifficulty } from "./difficulty.js";
import { DEBUG_COMBAT } from "./config.js";
import { BOSS_01_ANIMATIONS } from "./sprite-spec.js";

export const BOSS_STATES = {
  inactive: "inactive",
  intro: "intro",
  ready: "ready",
  spawning: "ready",
  choose_attack: "choose_attack",
  idle: "choose_attack",
  move: "move",
  approach: "move",
  telegraph: "telegraph",
  throw_prepare: "telegraph",
  charge_prepare: "telegraph",
  attack: "attack",
  throw_attack: "attack",
  melee_attack: "attack",
  charge: "attack",
  recover: "recover",
  charge_recovery: "recover",
  hit: "hit",
  phase_transition: "phase_transition",
  stagger: "stagger",
  death: "death",
  completed: "completed",
  complete: "completed",
};

const BUSY = new Set([
  BOSS_STATES.telegraph,
  BOSS_STATES.attack,
  BOSS_STATES.phase_transition,
  BOSS_STATES.ready,
  BOSS_STATES.death,
  BOSS_STATES.completed,
]);

const ANIM_FOR = {
  inactive: "idle",
  intro: "idle",
  ready: "idle",
  choose_attack: "idle",
  move: "walk",
  telegraph: "idle",
  attack: "throw",
  recover: "idle",
  hit: "hit",
  phase_transition: "phase_transition",
  stagger: "hit",
  death: "death",
  completed: "death",
};

const ATTACK_ANIM = {
  razor_throw: "throw",
  scissor_spread: "throw",
  brush_melee: "melee",
  clipper_burst: "throw",
  barber_charge: "charge",
  falling_tools: "idle",
  double_charge: "charge",
  tool_storm: "throw",
  ground_slam: "melee",
};

const STATE_TIMEOUT = {
  ready: 1.4,
  choose_attack: 1.6,
  move: 2.5,
  telegraph: 2.2,
  attack: 4.2,
  recover: 1.8,
  hit: 0.4,
  phase_transition: 1.6,
  stagger: 1.6,
  death: 5,
};

const _animWarned = new Set();
const _sheetWarned = new Set();

function warnAnim(wanted, used) {
  const key = `${wanted}:${used}`;
  if (_animWarned.has(key)) return;
  _animWarned.add(key);
  console.warn(`[Producer Hunt] Missing boss_01 animation "${wanted}", using "${used}".`);
}

function clipExists(kit, name) {
  return Boolean(kit?.animations?.[name]?.image);
}

function gameReducedFlash(game) {
  return Boolean(game?.settings?.reducedFlashes || game?.settings?.reducedMotion);
}

function pickAnim(kit, wanted) {
  if (clipExists(kit, wanted)) return wanted;
  const order = [wanted, "idle", "walk", "hit", "throw", "melee"];
  for (const name of order) {
    if (clipExists(kit, name) && name !== wanted) {
      warnAnim(wanted, name);
      return name;
    }
  }
  if (wanted !== "idle") warnAnim(wanted, "idle");
  return "idle";
}

export function scaleBossConfig(base, difficultyId) {
  const d = resolveDifficulty(difficultyId);
  const healthMul = d.id === "easy" ? 0.85 : d.id === "hard" ? 1.15 : 1;
  const tel = d.id === "easy" ? 1.22 : d.id === "hard" ? 0.88 : 1;
  const rec = d.id === "easy" ? 1.16 : d.id === "hard" ? 0.88 : 1;
  const stag = d.id === "easy" ? 1.2 : d.id === "hard" ? 0.9 : 1;
  return {
    ...base,
    maxHealth: Math.round(base.maxHealth * healthMul),
    throwPrepareSec: base.throwPrepareSec * tel,
    chargePrepareSec: base.chargePrepareSec * tel,
    meleeTelegraphSec: base.meleeTelegraphSec * tel,
    slamTelegraphSec: base.slamTelegraphSec * tel,
    fallingWarnSec: Math.max(0.9, base.fallingWarnSec * tel),
    recoverySec: base.recoverySec * rec,
    meleeRecoverSec: base.meleeRecoverSec * rec,
    chargeStaggerSec: base.chargeStaggerSec * stag,
    thinkDelay: base.thinkDelay * tel,
    projectileSpeedRazor: base.projectileSpeedRazor * d.projSpeed,
    projectileSpeedScissors: base.projectileSpeedScissors * d.projSpeed,
    projectileSpeedClippers: base.projectileSpeedClippers * d.projSpeed,
  };
}

export function validateBossSheets(kit) {
  for (const [name, spec] of Object.entries(BOSS_01_ANIMATIONS)) {
    const clip = kit?.animations?.[name];
    const img = clip?.image;
    if (!img) {
      if (!_sheetWarned.has(name)) {
        _sheetWarned.add(name);
        console.warn(`[Producer Hunt] Boss 1 sheet "${name}" missing. Using a safe placeholder.`);
      }
      continue;
    }
    const expectW = 256 * spec.frames;
    if (img.width !== expectW || img.height !== 256) {
      if (!_sheetWarned.has(`${name}:size`)) {
        _sheetWarned.add(`${name}:size`);
        console.warn(
          `[Producer Hunt] Boss 1 sheet "${name}" is ${img.width}x${img.height}, expected ${expectW}x256.`
        );
      }
    }
  }
}

export class BossEnemy extends Enemy {
  constructor(spawn, spriteKit, cfg = BOSS_01) {
    super("boss_01", spawn, spriteKit);
    this.cfg = cfg;
    this.isBoss = true;
    this.waveTracked = false;
    this.activated = true;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.health = cfg.maxHealth;
    this.spec = {
      ...this.spec,
      health: cfg.maxHealth,
      contactDamage: cfg.contactDamage,
      damage: cfg.meleeDamage || cfg.projectileDamage,
      chargeDamage: cfg.chargeDamage,
    };
    this.phase = 1;
    this.phaseShifted = false;
    this.phaseThreeShifted = false;
    this.scoreAwarded = false;
    this.deathStarted = false;
    this.state = BOSS_STATES.ready;
    this.stateTime = 0;
    this.attackName = "";
    this.attackTimer = cfg.thinkDelay;
    this.walkSpeed = cfg.walkSpeed;
    this.chargeSpeed = cfg.chargeSpeed;
    this.attackCooldown = cfg.attackCooldown;
    this.phaseFx = 0;
    this.arena = spawn.arena || null;
    this.meleeActive = false;
    this.meleeHitOnce = false;
    this.chargeHitOnce = false;
    this._recent = [];
    this._pendingPhase = 0;
    this._burstLeft = 0;
    this._burstAcc = 0;
    this._chargeLeft = 0;
    this._storm = null;
    this._slam = null;
    this._sgAcc = 0;
    this._sgTtl = 0;
    this._playBossAnim("idle", { restart: true });
    validateBossSheets(this.anim.kit);
  }

  beginDeath() {
    if (this.deathStarted) return;
    this.deathStarted = true;
    this.alive = true;
    this.health = 0;
    this.vx = 0;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.clearMelee();
    this.cancelTimers();
    this._setState(BOSS_STATES.death, "death");
  }

  cancelTimers() {
    this._burstLeft = 0;
    this._storm = null;
    this._slam = null;
    this._chargeLeft = 0;
    this.attackName = "";
    this.clearMelee();
  }

  clearMelee() {
    this.meleeActive = false;
    this.meleeHitOnce = false;
    this.chargeHitOnce = false;
  }

  hurtbox() {
    return { x: this.x + 10, y: this.y + 18, w: this.w - 20, h: this.h - 28 };
  }

  meleeBounds() {
    if (this.attackName === "barber_charge" || this.attackName === "double_charge") return this.chargeBounds();
    const reach = 86;
    const x = this.direction >= 0 ? this.x + this.w * 0.35 : this.x - reach;
    return { x, y: this.y + 36, w: this.w * 0.7 + reach, h: this.h - 48 };
  }

  chargeBounds() {
    return { x: this.x - 8, y: this.footY - 92, w: this.w + 16, h: 92 };
  }

  _playBossAnim(wanted, opts = {}) {
    const name = pickAnim(this.anim.kit, wanted);
    return this.anim.play(name, opts);
  }

  _facePlayer(player) {
    if (!player) return;
    this.direction = player.footX >= this.footX ? 1 : -1;
    this._applyFacingFlip();
  }

  _clampArena() {
    if (!this.arena) return;
    const pad = 36;
    const minX = this.arena.left + pad + this.w / 2;
    const maxX = this.arena.right - pad - this.w / 2;
    if (this.footX < minX) {
      this.footX = minX;
      this.vx = 0;
    }
    if (this.footX > maxX) {
      this.footX = maxX;
      this.vx = 0;
    }
    this._syncBox();
  }

  chargeSpace() {
    if (!this.arena) return 0;
    return this.direction >= 0
      ? this.arena.right - 36 - this.w / 2 - this.footX
      : this.footX - (this.arena.left + 36 + this.w / 2);
  }

  _setState(next, anim) {
    this.state = next;
    this.stateTime = 0;
    const wanted = anim || ATTACK_ANIM[this.attackName] || ANIM_FOR[next] || "idle";
    if (next === BOSS_STATES.telegraph && (this.attackName === "barber_charge" || this.attackName === "double_charge")) {
      this._playBossAnim("charge", { restart: true });
    } else if (next === BOSS_STATES.telegraph && this.attackName === "brush_melee") {
      this._playBossAnim("melee", { restart: true });
    } else if (next === BOSS_STATES.telegraph && this.attackName === "ground_slam") {
      this._playBossAnim("melee", { restart: true });
    } else {
      this._playBossAnim(wanted, { restart: true });
    }
  }

  wantedPhase() {
    const ratio = this.health / Math.max(1, this.cfg.maxHealth);
    if (ratio <= (this.cfg.phaseThreeHealthRatio || 0.32)) return 3;
    if (ratio <= (this.cfg.phaseTwoHealthRatio || 0.65)) return 2;
    return 1;
  }

  applyPhaseStats(phase) {
    const mul = phase === 3 ? this.cfg.phase3 : phase === 2 ? this.cfg.phase2 : null;
    this.walkSpeed = this.cfg.walkSpeed * (mul?.walkSpeedMul || 1);
    this.chargeSpeed = this.cfg.chargeSpeed * (mul?.chargeSpeedMul || 1);
    this.attackCooldown = this.cfg.attackCooldown * (mul?.attackCooldownMul || 1);
  }

  tryPhaseShift(game) {
    if (this.deathStarted) return false;
    const want = this.wantedPhase();
    if (want <= this.phase) return false;
    if (BUSY.has(this.state) && this.state !== BOSS_STATES.choose_attack && this.state !== BOSS_STATES.move) {
      this._pendingPhase = want;
      return false;
    }
    this.phase = want;
    if (want === 2) this.phaseShifted = true;
    if (want === 3) this.phaseThreeShifted = true;
    this.applyPhaseStats(want);
    this.invuln = want === 3 ? this.cfg.phaseThreeTransitionSec : this.cfg.phaseTransitionSec;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.vx = 0;
    this.cancelTimers();
    this._pendingPhase = 0;
    this._phaseFxDone = false;
    this._movedPhase = false;
    game?.bossEncounter?.clearHostile?.();
    game?.sfx?.("boss_warning", { force: true, x: this.footX });
    if (game) {
      game.combatHint = {
        text: want === 3 ? "MASTER BARBER RAGE" : "ANGRY BARBER",
        until: (game._worldTime || 0) + 1.6,
      };
    }
    this._setState(BOSS_STATES.phase_transition, "phase_transition");
    return true;
  }

  update(dt, player, world, projectiles, game) {
    this._game = game;
    const scale =
      this.state === BOSS_STATES.death || this.state === BOSS_STATES.completed ? 1 : game?.bossTimeScale ?? 1;
    const sdt = dt * scale;
    if (this.contactCool > 0) this.contactCool -= sdt;
    if (this.invuln > 0) this.invuln -= sdt;
    if (this.hitFlash > 0) this.hitFlash -= sdt;
    if (this._sgTtl > 0) this._sgTtl -= sdt;
    this.phaseFx = Math.max(0, this.phaseFx - sdt);
    this.stateTime += sdt;

    if (this.state === BOSS_STATES.death || this.state === BOSS_STATES.completed) {
      this.vx = 0;
      this.hitboxEnabled = false;
      this.combatEnabled = false;
      this.clearMelee();
      this.deadTimer += dt;
      this.anim.update(dt);
      if (this.anim.finished && this.state === BOSS_STATES.death) this.state = BOSS_STATES.completed;
      if (this.stateTime > STATE_TIMEOUT.death && this.state === BOSS_STATES.death) this.state = BOSS_STATES.completed;
      this._applyFacingFlip();
      return;
    }

    if (this.frozen > 0) {
      this.frozen -= sdt;
      this.vx = 0;
      this._physics(world, sdt);
      this.anim.update(sdt);
      return;
    }

    const timeout = STATE_TIMEOUT[this.state] || 3;
    if (
      this.stateTime > timeout &&
      this.state !== BOSS_STATES.phase_transition &&
      this.state !== BOSS_STATES.ready
    ) {
      this.cancelTimers();
      this.combatEnabled = true;
      this.hitboxEnabled = true;
      this._setState(BOSS_STATES.choose_attack, "idle");
    }

    this._dt = sdt;
    if (this.state === BOSS_STATES.ready) this._tickReady();
    else if (this.state === BOSS_STATES.hit) this._tickHit(player, game);
    else if (this.state === BOSS_STATES.phase_transition) this._tickPhase(game);
    else if (this.state === BOSS_STATES.stagger) this._tickStagger();
    else if (this.state === BOSS_STATES.choose_attack) this._tickChoose(player, world, game);
    else if (this.state === BOSS_STATES.move) this._tickMove(player, world, game);
    else if (this.state === BOSS_STATES.telegraph) this._tickTelegraph(player, game);
    else if (this.state === BOSS_STATES.attack) this._tickAttack(player, game);
    else if (this.state === BOSS_STATES.recover) this._tickRecover(game);
    else this._setState(BOSS_STATES.choose_attack, "idle");

    this._physics(world, sdt);
    this._separatePlayer(player, world);
    if (this.state === BOSS_STATES.move) this._playBossAnim("walk");
    this._applyFacingFlip();
    this.anim.update(sdt);
  }

  _physics(world, sdt) {
    applyGravity(this, sdt);
    resolveSolids(this, world.solids, sdt);
    keepInWorld(this, world);
    this._syncFeet();
    this._clampArena();
  }

  _separatePlayer(player, world) {
    if (!player?.alive || this.state === BOSS_STATES.death) return;
    if (!aabb(this, player.bounds())) return;
    const dir = Math.sign(player.footX - this.footX) || 1;
    player.footX += dir * 6;
    player._syncBox?.();
    const max = (world?.width || 8000) - 40;
    player.footX = Math.max(40, Math.min(max, player.footX));
    player._syncBox?.();
  }

  _tickReady() {
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.vx = 0;
    if (this.stateTime >= this.cfg.spawnSec) {
      this.hitboxEnabled = true;
      this.combatEnabled = true;
      this._setState(BOSS_STATES.choose_attack, "idle");
    }
  }

  _tickHit(player, game) {
    this.vx = 0;
    this._facePlayer(player);
    if (this.anim.finished || this.stateTime > 0.28) this.tryPhaseShift(game) || this._setState(BOSS_STATES.choose_attack, "idle");
  }

  _tickPhase(game) {
    this.vx = 0;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.phaseFx = 0.25;
    if (!this._movedPhase && this.arena) {
      this._movedPhase = true;
      const mid = (this.arena.left + this.arena.right) / 2;
      this.footX += (mid - this.footX) * 0.4;
      this._syncBox();
    }
    if (!this._phaseFxDone && game) {
      this._phaseFxDone = true;
      game.spawnFx?.({ sheetKey: "effects", frame: 7, x: this.footX, y: this.footY - 110, size: 110, life: 0.5 });
    }
    const hold = this.phase === 3 ? this.cfg.phaseThreeTransitionSec : this.cfg.phaseTransitionSec;
    if (this.anim.finished || this.stateTime >= hold) {
      this.hitboxEnabled = true;
      this.combatEnabled = true;
      this.invuln = 0.08;
      this._setState(BOSS_STATES.choose_attack, "idle");
    }
  }

  _tickStagger() {
    this.vx = 0;
    this.combatEnabled = true;
    this.hitboxEnabled = true;
    if (this.stateTime >= this.cfg.chargeStaggerSec) this._setState(BOSS_STATES.choose_attack, "idle");
  }

  _tickChoose(player, world, game) {
    this.vx = 0;
    this._facePlayer(player);
    if (this.tryPhaseShift(game)) return;
    if (!player?.alive || !this.combatEnabled) return;
    if (this.stateTime < this.cfg.thinkDelay) return;
    const attack = this._pickAttack(player);
    if (!attack) {
      this._setState(BOSS_STATES.move, "walk");
      return;
    }
    this._beginAttack(attack, player, game);
  }

  _tickMove(player, world, game) {
    if (this.tryPhaseShift(game)) return;
    if (!player?.alive) {
      this._setState(BOSS_STATES.choose_attack, "idle");
      return;
    }
    this._facePlayer(player);
    const dist = Math.abs(player.footX - this.footX);
    const preferred = this.spec.preferredRange;
    if (this.stateTime > 0.35 && dist <= this.cfg.meleeRange && this._canUse("brush_melee")) {
      this._beginAttack("brush_melee", player, game);
      return;
    }
    if (dist > preferred + 40 && this._canStep(world, this.direction)) this.vx = this.direction * this.walkSpeed;
    else if (dist < preferred - 40 && this._canStep(world, -this.direction)) this.vx = -this.direction * this.walkSpeed;
    else {
      this.vx = 0;
      this._setState(BOSS_STATES.choose_attack, "idle");
    }
  }

  _telegraphTime() {
    const n = this.attackName;
    if (n === "barber_charge" || n === "double_charge") return this.cfg.chargePrepareSec;
    if (n === "brush_melee") return this.cfg.meleeTelegraphSec;
    if (n === "ground_slam") return this.cfg.slamTelegraphSec;
    if (n === "falling_tools") return this.cfg.fallingWarnSec;
    return this.cfg.throwPrepareSec;
  }

  _recoverTime() {
    const n = this.attackName;
    if (n === "brush_melee") return this.cfg.meleeRecoverSec;
    if (n === "double_charge" || n === "ground_slam") return 1.05;
    if (n === "barber_charge") return 0.35;
    return this.cfg.recoverySec;
  }

  _tickTelegraph(player, game) {
    this.vx = 0;
    if (this.attackName !== "barber_charge" && this.attackName !== "double_charge") this._facePlayer(player);
    if (this.attackName === "falling_tools" && !this._marked) this._markFalls(game);
    if (this.stateTime >= this._telegraphTime()) {
      this._setState(BOSS_STATES.attack, ATTACK_ANIM[this.attackName] || "throw");
      this._onAttackEnter(player, game);
    }
  }

  _onAttackEnter(player, game) {
    this._thrown = false;
    this.meleeHitOnce = false;
    this.chargeHitOnce = false;
    if (this.attackName === "clipper_burst") {
      this._burstLeft = 3;
      this._burstAcc = 0;
    }
    if (this.attackName === "barber_charge") {
      this._chargeLeft = 1;
      this.chargeDir = this.direction;
    }
    if (this.attackName === "double_charge") {
      this._chargeLeft = 2;
      this.chargeDir = this.direction;
      this._pauseCharge = 0;
    }
    if (this.attackName === "tool_storm") this._storm = { i: 0, acc: 0 };
    if (this.attackName === "ground_slam") this._slam = { hopped: false, slammed: false };
    if (this.attackName === "falling_tools") this._dropFalls(game);
  }

  _tickAttack(player, game) {
    const n = this.attackName;
    if (n === "razor_throw" || n === "scissor_spread") this._tickThrowOnce(player, game);
    else if (n === "brush_melee") this._tickMelee();
    else if (n === "clipper_burst") this._tickClippers(player, game);
    else if (n === "barber_charge" || n === "double_charge") this._tickCharge(game, this._dt);
    else if (n === "tool_storm") this._tickStorm(player, game, this._dt);
    else if (n === "ground_slam") this._tickSlam(game);
    else if (n === "falling_tools") {
      if (this.stateTime > 0.35) this._finishAttack("recover");
    } else this._finishAttack("recover");
  }

  _tickRecover(game) {
    this.vx = 0;
    this.clearMelee();
    if (this.tryPhaseShift(game)) return;
    if (this.stateTime >= this._recoverTime()) this._setState(BOSS_STATES.choose_attack, "idle");
  }

  _finishAttack(next) {
    if (next === "stagger") this._setState(BOSS_STATES.stagger, "hit");
    else this._setState(BOSS_STATES.recover, "idle");
  }

  _canUse(name) {
    const phaseNeed = {
      razor_throw: 1,
      scissor_spread: 1,
      brush_melee: 1,
      clipper_burst: 2,
      barber_charge: 2,
      falling_tools: 2,
      double_charge: 3,
      tool_storm: 3,
      ground_slam: 3,
    };
    if (this.phase < (phaseNeed[name] || 1)) return false;
    const needAnim = ATTACK_ANIM[name];
    if (needAnim && needAnim !== "idle" && !clipExists(this.anim?.kit, needAnim) && !clipExists(this.anim?.kit, "idle")) {
      return false;
    }
    return true;
  }

  _pickAttack(player) {
    const dist = Math.abs((player?.footX || 0) - this.footX);
    const space = this.chargeSpace();
    const pool = [];
    const push = (id, w) => {
      if (!this._canUse(id)) return;
      if (this._recent.length >= 2 && this._recent[0] === id && this._recent[1] === id) return;
      pool.push({ id, w });
    };
    push("razor_throw", 3);
    push("scissor_spread", 2);
    if (dist <= this.cfg.meleeRange + 24) push("brush_melee", 3);
    if (this.phase >= 2) {
      push("clipper_burst", 2);
      if (dist > 200 && space > 180) push("barber_charge", 2);
      push("falling_tools", 2);
    }
    if (this.phase >= 3) {
      if (dist > 180 && space > 180) push("double_charge", 2);
      if (this._recent[0] !== "ground_slam") push("tool_storm", 2);
      if (this._recent[0] !== "tool_storm") push("ground_slam", 2);
    }
    if (!pool.length) return dist <= this.cfg.meleeRange ? "brush_melee" : "razor_throw";
    const total = pool.reduce((s, p) => s + p.w, 0);
    let roll = Math.random() * total;
    for (const p of pool) {
      roll -= p.w;
      if (roll <= 0) return p.id;
    }
    return pool[0].id;
  }

  _beginAttack(name, player, game) {
    this.attackName = name;
    this._recent = [name, this._recent[0]].filter(Boolean).slice(0, 2);
    this._marked = false;
    this._facePlayer(player);
    const caption = {
      razor_throw: "RAZOR THROW",
      scissor_spread: "SCISSOR SPREAD",
      brush_melee: "BRUSH SWING",
      clipper_burst: "CLIPPER BURST",
      barber_charge: "BARBER CHARGE",
      falling_tools: "FALLING TOOLS",
      double_charge: "DOUBLE CHARGE",
      tool_storm: "TOOL STORM",
      ground_slam: "GROUND SLAM",
    }[name];
    if (game?.settings?.captions !== false && caption) {
      game.combatHint = { text: caption, until: (game._worldTime || 0) + 1.1 };
    }
    if (name === "barber_charge" || name === "double_charge") {
      game?.sfx?.("boss_warning", { x: this.footX });
      this.chargeDir = this.direction;
    }
    this._setState(BOSS_STATES.telegraph);
  }

  _handMuzzle() {
    const off = this.weapon.muzzle || { x: 58, y: -128 };
    return { x: this.footX + this.direction * off.x, y: this.footY + off.y };
  }

  _sheet(game, key, fallback) {
    return game.assets?.sheet(key) || game.assets?.sheet(fallback) || null;
  }

  _fire(game, id, opts) {
    const def = projectileDef(id);
    const muzzle = this._handMuzzle();
    const w = def.hitW || 32;
    const h = def.hitH || 20;
    game.acquireHostileShot({
      x: (opts.x ?? muzzle.x) - w / 2,
      y: (opts.y ?? muzzle.y) - h / 2,
      vx: opts.vx || 0,
      vy: opts.vy || 0,
      damage: opts.damage ?? this.cfg.projectileDamage,
      type: def.id,
      weaponId: id,
      frame: 0,
      w,
      h,
      vis: def.vis,
      flip: Boolean(def.flip),
      lifetime: def.lifetime || 2.4,
      sheet: this._sheet(game, def.sheetKey, opts.fallbackSheet),
      impactFx: this.weapon.impactFx,
      animFrames: def.frames || 4,
      animFps: def.fps || 16,
      spin: def.spin || 0,
      gravity: opts.gravity != null ? opts.gravity : def.gravity || 0,
      interruptMove: Boolean(def.interruptMove),
      tint: def.tint || "",
      hitGroup: opts.hitGroup || "",
    });
  }

  _tickThrowOnce(player, game) {
    this.vx = 0;
    const release = this.cfg.throwReleaseFrame;
    if (!this._thrown && (this.anim.frame >= release || this.anim.finished || this.stateTime > 0.28)) {
      if (this.attackName === "scissor_spread") this._fireSpread(player, game);
      else this._fireRazor(player, game);
      this._thrown = true;
    }
    if (this.anim.finished || this.stateTime > 0.7) this._finishAttack("recover");
  }

  _fireRazor(player, game) {
    const muzzle = this._handMuzzle();
    const y = player?.footY ? player.footY - 118 : muzzle.y;
    this._fire(game, "straight_razor", {
      x: muzzle.x,
      y,
      vx: this.direction * this.cfg.projectileSpeedRazor,
      vy: 0,
      fallbackSheet: "boss_01_razor",
    });
    game?.spawnFx?.({ sheetKey: "effects", frame: 5, x: muzzle.x, y, size: 40, life: 0.12 });
  }

  _fireSpread(player, game) {
    const muzzle = this._handMuzzle();
    const speed = this.cfg.projectileSpeedScissors;
    for (const deg of [-12, 0, 12]) {
      const rad = (deg * Math.PI) / 180;
      this._fire(game, "barber_scissors", {
        x: muzzle.x,
        y: muzzle.y,
        vx: this.direction * Math.cos(rad) * speed,
        vy: Math.sin(rad) * speed,
        fallbackSheet: "boss_01_scissors",
        hitGroup: "scissor_spread",
      });
    }
  }

  _tickClippers(player, game) {
    this.vx = 0;
    const fired = 3 - this._burstLeft;
    if (this._burstLeft > 0 && this.stateTime >= fired * 0.14) {
      this._burstLeft -= 1;
      const muzzle = this._handMuzzle();
      const torso = playerTorsoAim(player);
      const dx = torso.x - muzzle.x;
      const dy = torso.y - muzzle.y;
      const len = Math.max(1, Math.hypot(dx, dy));
      const speed = this.cfg.projectileSpeedClippers;
      this._fire(game, "electric_clipper_energy", {
        x: muzzle.x,
        y: muzzle.y,
        vx: (dx / len) * speed,
        vy: (dy / len) * speed,
        fallbackSheet: "boss_01_clippers",
      });
    }
    if (this._burstLeft <= 0 && this.stateTime > 0.55) this._finishAttack("recover");
  }

  _tickMelee() {
    this.vx = 0;
    const start = this.cfg.meleeHitStartFrame ?? 2;
    const end = this.cfg.meleeHitEndFrame ?? 4;
    this.meleeActive = this.anim.frame >= start && this.anim.frame <= end;
    this.spec.damage = this.cfg.meleeDamage;
    if (this.anim.finished || this.stateTime > this.cfg.meleeActiveSec + 0.35) {
      this.clearMelee();
      this._finishAttack("recover");
    }
  }

  _chargeHitBound() {
    if (!this.arena) return false;
    const pad = 36;
    if (this.chargeDir > 0 && this.footX >= this.arena.right - pad - this.w / 2) return true;
    if (this.chargeDir < 0 && this.footX <= this.arena.left + pad + this.w / 2) return true;
    return false;
  }

  _tickCharge(game, dt = 1 / 60) {
    if (this._pauseCharge > 0) {
      this.vx = 0;
      this._pauseCharge -= dt;
      if (this._pauseCharge <= 0) {
        this.chargeDir = this.direction;
        this.meleeHitOnce = false;
        this.chargeHitOnce = false;
        this._playBossAnim("charge", { restart: true });
      }
      return;
    }
    this.vx = (this.chargeDir || this.direction) * this.chargeSpeed;
    this.meleeActive = true;
    this.spec.damage = this.cfg.chargeDamage;
    const blocked = this._chargeHitBound() || (!this._canStep(game.world, this.chargeDir) && this.stateTime > 0.12);
    if (blocked || this.stateTime > 1.2) {
      this.vx = 0;
      this.clearMelee();
      this._chargeLeft -= 1;
      if (this.attackName === "double_charge" && this._chargeLeft > 0) {
        this._pauseCharge = 0.38;
        this.stateTime = 0;
        this._facePlayer(game.player);
        return;
      }
      this._finishAttack("stagger");
    }
  }

  _markFalls(game) {
    this._marked = true;
    const arena = this.arena;
    if (!arena || !game) return;
    const ground = arena.groundY ?? game.world?.ground?.y ?? 960;
    const span = arena.right - arena.left;
    const xs = [arena.left + span * 0.28, arena.left + span * 0.5, arena.left + span * 0.72];
    this._fallXs = xs;
    for (const x of xs) {
      game.spawnDangerZone({
        x: x - 28,
        y: ground - 16,
        w: 56,
        h: 18,
        life: this.cfg.fallingWarnSec + 0.2,
        delay: 0,
        damage: 0,
        owner: "boss",
        kind: "fall_mark",
        outline: true,
        symbol: "!",
      });
    }
  }

  _dropFalls(game) {
    const ground = this.arena?.groundY ?? game.world?.ground?.y ?? 960;
    for (const x of this._fallXs || []) {
      this._fire(game, "falling_barber_tool", {
        x,
        y: 80,
        vx: 0,
        vy: 220,
        gravity: 980,
        fallbackSheet: "boss_01_brush",
      });
    }
  }

  _tickStorm(player, game, dt = 1 / 60) {
    this.vx = 0;
    const pattern = [
      { high: false },
      { high: true },
      { high: false },
      { high: true },
    ];
    this._storm = this._storm || { i: 0, acc: 0 };
    this._storm.acc += dt;
    const live = (game.hostileProjectiles || []).filter((p) => p.alive).length;
    if (this._storm.i < pattern.length && this._storm.acc > 0.22 && live < 5) {
      this._storm.acc = 0;
      const high = pattern[this._storm.i].high;
      this._storm.i += 1;
      const muzzle = this._handMuzzle();
      const y = high ? muzzle.y - 36 : (player?.footY || muzzle.y) - 48;
      const id = this._storm.i % 2 ? "straight_razor" : "barber_scissors";
      this._fire(game, id, {
        x: muzzle.x,
        y,
        vx: this.direction * this.cfg.projectileSpeedRazor * 0.92,
        vy: 0,
        fallbackSheet: id === "straight_razor" ? "boss_01_razor" : "boss_01_scissors",
      });
    }
    if (this._storm.i >= pattern.length && this.stateTime > 1.15) this._finishAttack("recover");
  }

  _tickSlam(game) {
    if (!this._slam.hopped) {
      this._slam.hopped = true;
      this.vy = -420;
      this.onGround = false;
    }
    this.meleeActive = this.onGround && this.stateTime > 0.28 && this.stateTime < 0.48;
    this.spec.damage = this.cfg.slamDamage;
    if (this.onGround && !this._slam.slammed && this.stateTime > 0.3) {
      this._slam.slammed = true;
      if (game.shakeEnabled?.()) game.camera.addShake(game.settings?.reducedMotion ? 0.08 : 0.42);
      const y = this.footY - 18;
      this._fire(game, "ground_wave", {
        x: this.footX,
        y,
        vx: -280,
        vy: 0,
        damage: this.cfg.waveDamage,
      });
      this._fire(game, "ground_wave", {
        x: this.footX,
        y,
        vx: 280,
        vy: 0,
        damage: this.cfg.waveDamage,
      });
    }
    if (this._slam.slammed && this.stateTime > 0.7) {
      this.clearMelee();
      this._finishAttack("recover");
    }
  }

  takeDamage(amount, source) {
    if (this.deathStarted || this.state === BOSS_STATES.death || this.state === BOSS_STATES.completed) return 0;
    if (this.state === BOSS_STATES.ready || this.state === BOSS_STATES.phase_transition) return 0;
    if (this.hitboxEnabled === false) return 0;
    if (this.invuln > 0) return 0;
    let amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    if (source?.weaponId === "shotgun") {
      if (this._sgTtl <= 0) this._sgAcc = 0;
      this._sgTtl = 0.09;
      const room = Math.max(0, (this.cfg.shotgunBossCap || 12) - this._sgAcc);
      amt = Math.min(amt, room);
      this._sgAcc += amt;
      if (amt <= 0) return 0;
    }
    if (this.state === BOSS_STATES.attack && (this.attackName === "barber_charge" || this.attackName === "double_charge")) {
      amt = Math.max(1, Math.round(amt * (this.cfg.chargeArmor || 0.55)));
    }
    this.health = Math.max(0, this.health - amt);
    this.invuln = this.cfg.hitInvuln;
    this.hitFlash = gameReducedFlash(this._game) ? 0.04 : 0.12;
    if (this.health <= 0) {
      this.health = 0;
      this.beginDeath();
      return amt;
    }
    const want = this.wantedPhase();
    if (want > this.phase && !BUSY.has(this.state)) this.tryPhaseShift(this._game);
    else if (this.state === BOSS_STATES.stagger) {
      this._playBossAnim("hit", { restart: true });
    } else if (this.state === BOSS_STATES.choose_attack || this.state === BOSS_STATES.move) {
      this._setState(BOSS_STATES.hit, "hit");
    }
    return amt;
  }

  draw(ctx, camera) {
    super.draw(ctx, camera);
    if (this.phase >= 2 && this.alive && this.state !== BOSS_STATES.death) {
      const origin = camera.worldToScreen(this.footX, this.footY);
      ctx.save();
      ctx.globalAlpha = 0.28 + (this.phaseFx > 0 ? 0.35 : 0);
      ctx.strokeStyle = this.phase >= 3 ? "#fb7185" : "#22d3ee";
      ctx.lineWidth = 3;
      ctx.setLineDash(gameReducedFlash(this._game) ? [8, 6] : []);
      ctx.strokeRect(origin.x - this.w / 2 - 3, origin.y - this.h - 3, this.w + 6, this.h + 6);
      ctx.restore();
    }
  }
}

export function drawBossDebug(ctx, game) {
  if (!(game.debug || DEBUG_COMBAT)) return;
  const boss = game.bossEncounter?.boss;
  const arena = game.bossEncounter?.arenaBox?.();
  ctx.save();
  ctx.font = "12px monospace";
  ctx.fillStyle = "#86efac";
  ctx.textAlign = "left";
  const music = game._bossMusic ? "boss" : "other";
  const video = game.cinematic?._playing ? "playing" : "off";
  ctx.fillText(
    `boss ${boss?.state || "none"} ph ${boss?.phase || 0} atk ${boss?.attackName || "-"} t ${(boss?.stateTime || 0).toFixed(2)} hp ${Math.ceil(boss?.health || 0)} mus ${music} vid ${video}`,
    24,
    80
  );
  const drawBox = (box, color) => {
    if (!box) return;
    const s = game.camera.worldToScreen(box.x, box.y);
    ctx.strokeStyle = color;
    ctx.strokeRect(s.x, s.y, box.w, box.h);
  };
  if (arena) {
    const s = game.camera.worldToScreen(arena.left, 40);
    ctx.strokeStyle = "rgba(251,113,133,0.85)";
    ctx.strokeRect(s.x, 40, arena.right - arena.left, 980);
  }
  if (boss) {
    drawBox(boss, "#38bdf8");
    drawBox(boss.hurtbox(), "#f472b6");
    if (boss.meleeActive) drawBox(boss.meleeBounds(), "#facc15");
    if (boss.attackName === "barber_charge" || boss.attackName === "double_charge") drawBox(boss.chargeBounds(), "#fb923c");
    const m = boss._handMuzzle();
    const ms = game.camera.worldToScreen(m.x, m.y);
    ctx.fillStyle = "#fde047";
    ctx.beginPath();
    ctx.arc(ms.x, ms.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#86efac";
    ctx.fillText(`chargeSpace ${Math.round(boss.chargeSpace())}`, 24, 98);
  }
  ctx.restore();
}
