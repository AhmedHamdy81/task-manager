import { applyGravity } from "./physics.js";
import { keepInWorld, resolveSolids } from "./collision.js";
import { Enemy } from "./enemy.js";
import { BOSS_01, projectileDef } from "./combat.js";
import { Projectile } from "./projectile.js";
import { DESIGN_H, DEBUG_REPLAY_BOSS_INTRO } from "./config.js";

export const BOSS_STATES = {
  spawning: "spawning",
  idle: "idle",
  approach: "approach",
  throw_prepare: "throw_prepare",
  throw_attack: "throw_attack",
  melee_attack: "melee_attack",
  charge_prepare: "charge_prepare",
  charge: "charge",
  charge_recovery: "charge_recovery",
  hit: "hit",
  phase_transition: "phase_transition",
  death: "death",
  complete: "complete",
};

const ENCOUNTER = {
  idle: "idle",
  pending: "pending",
  intro: "intro",
  spawn: "spawn",
  combat: "combat",
  dying: "dying",
  complete: "complete",
};

const ATTACK_LOCK = new Set([
  BOSS_STATES.spawning,
  BOSS_STATES.hit,
  BOSS_STATES.phase_transition,
  BOSS_STATES.death,
  BOSS_STATES.complete,
]);

const UNINTERRUPTIBLE = new Set([
  BOSS_STATES.throw_attack,
  BOSS_STATES.melee_attack,
  BOSS_STATES.charge_prepare,
  BOSS_STATES.charge,
  BOSS_STATES.phase_transition,
  BOSS_STATES.spawning,
]);

const ANIM_FOR_STATE = {
  spawning: "idle",
  idle: "idle",
  approach: "walk",
  throw_prepare: "idle",
  throw_attack: "throw",
  melee_attack: "melee",
  charge_prepare: "charge",
  charge: "charge",
  charge_recovery: "idle",
  hit: "hit",
  phase_transition: "phase_transition",
  death: "death",
  complete: "idle",
};

const _animWarned = new Set();

function warnAnim(id, wanted, used) {
  const key = `${id}:${wanted}:${used}`;
  if (_animWarned.has(key)) return;
  _animWarned.add(key);
  console.warn(`[Producer Hunt] Missing ${id} animation "${wanted}", using "${used}".`);
}

function clipExists(kit, name) {
  return Boolean(kit?.animations?.[name]?.image);
}

function pickAnim(kit, wanted) {
  if (clipExists(kit, wanted)) return wanted;
  const fallbacks =
    wanted === "death"
      ? ["death", "hit", "idle"]
      : wanted === "hit"
        ? ["hit", "idle"]
        : wanted === "throw"
          ? ["throw", "melee", "walk", "idle"]
          : wanted === "melee"
            ? ["melee", "throw", "walk", "idle"]
            : wanted === "phase_transition"
              ? ["phase_transition", "hit", "idle"]
              : wanted === "charge"
                ? ["charge", "walk", "idle"]
                : ["walk", "idle", "throw"];
  for (const name of fallbacks) {
    if (clipExists(kit, name) && name !== wanted) {
      warnAnim("boss_01", wanted, name);
      return name;
    }
  }
  if (wanted !== "idle") warnAnim("boss_01", wanted, "idle");
  return "idle";
}

export function hostileShotCount(game) {
  return (game.hostileProjectiles || []).filter((p) => p.alive).length;
}

export class HostileProjectilePool {
  constructor() {
    this._free = [];
  }

  acquire(opts) {
    const shot = this._free.pop() || new Projectile();
    return shot.reset({ ...opts, owner: "enemy", faction: "boss" });
  }

  release(shot) {
    if (!shot) return;
    shot.recycle();
    this._free.push(shot);
  }

  clear(list) {
    for (const shot of list || []) {
      shot.disable();
      this.release(shot);
    }
    return [];
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
    this.spec = { ...this.spec, health: cfg.maxHealth, contactDamage: cfg.contactDamage, damage: cfg.projectileDamage };
    this.phase = 1;
    this.phaseShifted = false;
    this.scoreAwarded = false;
    this.deathStarted = false;
    this.state = BOSS_STATES.spawning;
    this.stateTime = 0;
    this.attackTimer = cfg.attackCooldown * 0.35;
    this.chargeTimer = cfg.chargeCooldown * 0.45;
    this.throwKind = "razor";
    this.chargeDir = -1;
    this.walkSpeed = cfg.walkSpeed;
    this.chargeSpeed = cfg.chargeSpeed;
    this.attackCooldown = cfg.attackCooldown;
    this.chargeCooldown = cfg.chargeCooldown;
    this.phaseFx = 0;
    this.arena = spawn.arena || null;
    this.meleeActive = false;
    this.meleeHitOnce = false;
    this._thrown = false;
    this._playBossAnim(BOSS_STATES.spawning, { restart: true });
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
    this.state = BOSS_STATES.death;
    this.stateTime = 0;
    this._playBossAnim(BOSS_STATES.death, { restart: true });
  }

  clearMelee() {
    this.meleeActive = false;
    this.meleeHitOnce = false;
  }

  meleeBounds() {
    const reach = 78;
    const x = this.direction >= 0 ? this.x : this.x - reach;
    return { x, y: this.y + 28, w: this.w + reach, h: this.h - 36 };
  }

  _playBossAnim(state, opts = {}) {
    const wanted = ANIM_FOR_STATE[state] || "idle";
    const name = pickAnim(this.anim.kit, wanted);
    return this.anim.play(name, opts);
  }

  _timersPaused() {
    return ATTACK_LOCK.has(this.state) || !this.combatEnabled;
  }

  _facePlayer(player) {
    if (!player) return;
    this.direction = player.footX >= this.footX ? 1 : -1;
    this._applyFacingFlip();
  }

  _clampArena() {
    if (!this.arena) return;
    const pad = 40;
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

  _setState(next) {
    if (this.state === next) return;
    if (this.state === BOSS_STATES.melee_attack) this.clearMelee();
    this.state = next;
    this.stateTime = 0;
    this._playBossAnim(next, { restart: true });
  }

  tryPhaseTwo() {
    if (this.phaseShifted || this.deathStarted) return false;
    const ratio = this.cfg.phaseTwoHealthRatio;
    if (this.health > this.cfg.maxHealth * ratio) return false;
    this.phaseShifted = true;
    this.phase = 2;
    this.invuln = this.cfg.phaseTransitionSec;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.vx = 0;
    this.clearMelee();
    this.walkSpeed = this.cfg.walkSpeed * this.cfg.phase2.walkSpeedMul;
    this.chargeSpeed = this.cfg.chargeSpeed * this.cfg.phase2.chargeSpeedMul;
    this.attackCooldown = this.cfg.attackCooldown * this.cfg.phase2.attackCooldownMul;
    this.chargeCooldown = this.cfg.chargeCooldown * this.cfg.phase2.attackCooldownMul;
    this._phaseFxDone = false;
    this._setState(BOSS_STATES.phase_transition);
    return true;
  }

  update(dt, player, world, projectiles, game) {
    if (this.contactCool > 0) this.contactCool -= dt;
    if (this.invuln > 0) this.invuln -= dt;
    if (this.hitFlash > 0) this.hitFlash -= dt;
    this.phaseFx = Math.max(0, this.phaseFx - dt);
    this.stateTime += dt;

    if (this.state === BOSS_STATES.death || this.state === BOSS_STATES.complete) {
      this.vx = 0;
      this.hitboxEnabled = false;
      this.combatEnabled = false;
      this.clearMelee();
      this.deadTimer += dt;
      this.anim.update(dt);
      if (this.anim.finished && this.state === BOSS_STATES.death) this.state = BOSS_STATES.complete;
      this._applyFacingFlip();
      return;
    }

    if (this.frozen > 0) {
      this.frozen -= dt;
      this.vx = 0;
      applyGravity(this, dt);
      resolveSolids(this, world.solids, dt);
      keepInWorld(this, world);
      this._syncFeet();
      this._clampArena();
      this.anim.update(dt);
      return;
    }

    if (!this._timersPaused() && player?.alive) {
      this.attackTimer -= dt;
      this.chargeTimer -= dt;
    }

    if (this.state === BOSS_STATES.spawning) {
      this.hitboxEnabled = false;
      this.combatEnabled = false;
      this.vx = 0;
      if (this.stateTime >= this.cfg.spawnSec) {
        this.hitboxEnabled = true;
        this.combatEnabled = true;
        this._setState(BOSS_STATES.idle);
      }
    } else if (this.state === BOSS_STATES.hit) {
      this.vx = 0;
      this._facePlayer(player);
      if (this.anim.finished || this.stateTime > (this.cfg.hitInvuln || 0.18)) {
        this.tryPhaseTwo() || this._setState(BOSS_STATES.idle);
      }
    } else if (this.state === BOSS_STATES.phase_transition) {
      this.vx = 0;
      this.hitboxEnabled = false;
      this.combatEnabled = false;
      this.phaseFx = 0.2;
      if (!this._movedPhase && this.arena) {
        this._movedPhase = true;
        const mid = (this.arena.left + this.arena.right) / 2;
        this.footX += (mid - this.footX) * 0.35;
        this._syncBox();
      }
      if (!this._phaseFxDone && game) {
        this._phaseFxDone = true;
        game.spawnFx?.({
          sheetKey: "effects",
          frame: 7,
          x: this.footX,
          y: this.footY - 110,
          size: 88,
          life: 0.45,
        });
      }
      if (this.anim.finished || this.stateTime >= this.cfg.phaseTransitionSec) {
        this.hitboxEnabled = true;
        this.combatEnabled = true;
        this.invuln = 0.12;
        this._setState(BOSS_STATES.idle);
      }
    } else if (this.state === BOSS_STATES.throw_prepare) {
      this.vx = 0;
      this._facePlayer(player);
      if (this.stateTime >= this.cfg.throwPrepareSec) {
        this._thrown = false;
        this._setState(BOSS_STATES.throw_attack);
      }
    } else if (this.state === BOSS_STATES.throw_attack) {
      this.vx = 0;
      this._tickThrow(player, game);
    } else if (this.state === BOSS_STATES.melee_attack) {
      this.vx = 0;
      this._tickMelee();
    } else if (this.state === BOSS_STATES.charge_prepare) {
      this.vx = 0;
      if (this.stateTime >= this.cfg.chargePrepareSec) this._setState(BOSS_STATES.charge);
    } else if (this.state === BOSS_STATES.charge) {
      this.vx = this.chargeDir * this.chargeSpeed;
      const hitWall = this._chargeHitBound();
      if (hitWall || this.stateTime > 1.15) this._setState(BOSS_STATES.charge_recovery);
    } else if (this.state === BOSS_STATES.charge_recovery) {
      this.vx = 0;
      if (this.stateTime >= this.cfg.recoverySec) this._setState(BOSS_STATES.idle);
    } else {
      this._tickApproach(player, world);
    }

    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();
    this._clampArena();
    if (this.state !== BOSS_STATES.hit && this.state !== BOSS_STATES.throw_attack && this.state !== BOSS_STATES.melee_attack) {
      this._playBossAnim(this.state);
    }
    this._applyFacingFlip();
    this.anim.update(dt);
  }

  _chargeHitBound() {
    if (!this.arena) return false;
    const pad = 36;
    if (this.chargeDir > 0 && this.footX >= this.arena.right - pad - this.w / 2) return true;
    if (this.chargeDir < 0 && this.footX <= this.arena.left + pad + this.w / 2) return true;
    return false;
  }

  _tickApproach(player, world) {
    if (!player?.alive || !this.combatEnabled) {
      this.vx = 0;
      this._setState(BOSS_STATES.idle);
      return;
    }
    this._facePlayer(player);
    const dx = player.footX - this.footX;
    const dist = Math.abs(dx);
    const preferred = this.spec.preferredRange;
    const band = this.spec.rangeBand || 48;

    if (dist <= this.cfg.meleeRange && this.attackTimer <= 0) {
      this.attackTimer = this.attackCooldown;
      this.meleeHitOnce = false;
      this._setState(BOSS_STATES.melee_attack);
      return;
    }
    if (this.chargeTimer <= 0 && dist > 160) {
      this.chargeDir = dx >= 0 ? 1 : -1;
      this.chargeTimer = this.chargeCooldown;
      this._setState(BOSS_STATES.charge_prepare);
      return;
    }
    if (this.attackTimer <= 0) {
      this.throwKind = this._pickThrow();
      this.attackTimer = this.attackCooldown;
      this._setState(BOSS_STATES.throw_prepare);
      return;
    }

    if (dist < this.cfg.meleeRange + 36 && this._canStep(world, -this.direction)) {
      this._setState(BOSS_STATES.approach);
      this.vx = -this.direction * this.walkSpeed;
      return;
    }
    if (dist > preferred + band && this._canStep(world, this.direction)) {
      this._setState(BOSS_STATES.approach);
      this.vx = this.direction * this.walkSpeed;
    } else if (dist < preferred - band && this._canStep(world, -this.direction)) {
      this._setState(BOSS_STATES.approach);
      this.vx = -this.direction * this.walkSpeed;
    } else {
      this._setState(BOSS_STATES.idle);
      this.vx = 0;
    }
  }

  _pickThrow() {
    if (this.phase < 2) return "razor";
    const roll = Math.random();
    if (roll < 0.34) return "scissors";
    if (roll < 0.67) return "clippers";
    return "razor";
  }

  _tickThrow(player, game) {
    const release = this.cfg.throwReleaseFrame;
    if (!this._thrown && (this.anim.frame >= release || this.anim.finished)) {
      this._fireTool(player, game, this.throwKind);
      this._thrown = true;
    }
    if (this.anim.finished) this._setState(BOSS_STATES.charge_recovery);
  }

  _tickMelee() {
    const start = this.cfg.meleeHitStartFrame;
    const end = this.cfg.meleeHitEndFrame;
    this.meleeActive = this.anim.frame >= start && this.anim.frame <= end && !this.anim.finished;
    if (this.anim.finished) {
      this.clearMelee();
      this._setState(BOSS_STATES.charge_recovery);
    }
  }

  _handMuzzle() {
    const off = this.weapon.muzzle || { x: 58, y: -128 };
    return {
      x: this.footX + this.direction * off.x,
      y: this.footY + off.y,
    };
  }

  _fireTool(player, game, kind) {
    if (!game || !player?.alive) return;
    const id =
      kind === "scissors" ? "boss_01_scissors" : kind === "clippers" ? "boss_01_clippers" : "boss_01_razor";
    const def = projectileDef(id);
    const muzzle = this._handMuzzle();
    const aimX = player.footX;
    const aimY = player.footY - 90 + (kind === "scissors" ? (Math.random() * 48 - 24) : 0);
    const dx = aimX - muzzle.x;
    const dy = aimY - muzzle.y;
    const len = Math.max(1, Math.hypot(dx, dy));
    const speed =
      kind === "scissors"
        ? this.cfg.projectileSpeedScissors
        : kind === "clippers"
          ? this.cfg.projectileSpeedClippers
          : this.cfg.projectileSpeedRazor;
    const gravity = kind === "razor" ? this.cfg.razorGravity : 0;
    game.acquireHostileShot({
      x: muzzle.x - (def.hitW || 32) / 2,
      y: muzzle.y - (def.hitH || 20) / 2,
      vx: (dx / len) * speed,
      vy: (dy / len) * speed * (kind === "razor" ? 0.35 : 1),
      damage: this.cfg.projectileDamage,
      type: def.id,
      frame: 0,
      w: def.hitW,
      h: def.hitH,
      vis: def.vis,
      flip: false,
      lifetime: def.lifetime || 2.4,
      sheet: game.assets?.sheet(def.sheetKey) || null,
      impactFx: this.weapon.impactFx,
      animFrames: def.frames || 4,
      animFps: def.fps || 16,
      spin: def.spin || 0,
      gravity,
      interruptMove: Boolean(def.interruptMove),
      tint: def.tint || "",
    });
  }

  takeDamage(amount) {
    if (this.deathStarted || this.state === BOSS_STATES.death || this.state === BOSS_STATES.complete) return 0;
    if (this.state === BOSS_STATES.spawning || this.state === BOSS_STATES.phase_transition) return 0;
    if (this.hitboxEnabled === false) return 0;
    if (this.invuln > 0) return 0;
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    this.health -= amt;
    this.invuln = this.cfg.hitInvuln;
    this.hitFlash = 0.16;
    if (this.health <= 0) {
      this.health = 0;
      this.beginDeath();
      return 0;
    }
    if (this.tryPhaseTwo()) return 0;
    if (UNINTERRUPTIBLE.has(this.state)) return 0;
    this.clearMelee();
    this._setState(BOSS_STATES.hit);
    return 0;
  }

  draw(ctx, camera) {
    super.draw(ctx, camera);
    if (this.phase === 2 && this.alive && this.state !== BOSS_STATES.death) {
      const origin = camera.worldToScreen(this.footX, this.footY);
      ctx.save();
      ctx.globalAlpha = 0.35 + (this.phaseFx > 0 ? 0.35 : 0);
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 3;
      ctx.strokeRect(origin.x - this.w / 2 - 3, origin.y - this.h - 3, this.w + 6, this.h + 6);
      ctx.restore();
    }
  }
}

export class BossEncounter {
  constructor(game) {
    this.game = game;
    this.reset();
  }

  reset() {
    this.phase = ENCOUNTER.idle;
    this.timer = 0;
    this.boss = null;
    this.warningOnce = false;
    this.spawnedOnce = false;
    this.hudVisible = false;
    this.scoreAwarded = false;
    this.arenaLocked = false;
    this.arenaSolids = [];
    this.cfg = BOSS_01;
    this.introPlayed = false;
    this.clearBanner = false;
    this._phaseClear = false;
  }

  destroy() {
    this.game.cinematic?.cancel();
    this.unlockArena();
    this.clearHostile();
    if (this.boss) {
      this.game.enemies = (this.game.enemies || []).filter((e) => e !== this.boss);
    }
    this.reset();
  }

  get active() {
    return this.phase !== ENCOUNTER.idle && this.phase !== ENCOUNTER.complete;
  }

  get blocksInput() {
    if (this.phase === ENCOUNTER.intro || this.phase === ENCOUNTER.spawn) return true;
    return Boolean(this.boss && this.boss.state === BOSS_STATES.spawning);
  }

  hudView() {
    if (!this.hudVisible || !this.boss) return null;
    if (this.phase === ENCOUNTER.complete) return null;
    if (this.boss.state === BOSS_STATES.complete) return null;
    return {
      name: this.cfg.displayName,
      title: this.cfg.title,
      health: Math.max(0, this.boss.health),
      maxHealth: this.cfg.maxHealth,
      phase: this.boss.phase,
      transitioning: this.boss.state === BOSS_STATES.phase_transition,
    };
  }

  begin() {
    if (this.phase !== ENCOUNTER.idle && this.phase !== ENCOUNTER.complete) return;
    this._removeBosses();
    this.clearHostile();
    this.phase = ENCOUNTER.pending;
    this.timer = 0;
  }

  start(opts = {}) {
    if (this.phase === ENCOUNTER.intro || this.phase === ENCOUNTER.spawn || this.phase === ENCOUNTER.combat) {
      return;
    }
    this.clearHostile();
    this._removeBosses();
    this.timer = 0;
    this.warningOnce = false;
    this.spawnedOnce = false;
    this.hudVisible = false;
    this.scoreAwarded = false;
    this.clearBanner = false;
    this.cfg = this.game.world?.boss || BOSS_01;
    const enc = (this.game.world?.encounters || []).find((e) => e.boss);
    if (enc) enc.activated = true;
    this.lockArena();
    this.captureArenaCheckpoint();
    if (this.game.waves) this.game.waves.banner = null;
    this.game.hud?.invalidate();
    const skipIntro = Boolean(opts.skipIntro) && !DEBUG_REPLAY_BOSS_INTRO;
    if (skipIntro) {
      this.afterIntro("skipped-run");
      return;
    }
    this.phase = ENCOUNTER.intro;
    this.game.playBossIntro({
      onComplete: () => this.afterIntro("intro"),
    });
  }

  afterIntro() {
    if (this.phase === ENCOUNTER.spawn || this.phase === ENCOUNTER.combat) return;
    this.introPlayed = true;
    if (this.game.checkpoint) this.game.checkpoint.bossIntroWatched = true;
    this.game.audio?.setGameplayMuted?.(false);
    // Let playBossMusic mark the flag only after the post-video audio context
    // is unlocked and a real (or level fallback) track has been selected.
    this.game._bossMusic = false;
    this.game._bossWarned.add("enc_final");
    this.placePlayerCombatStart();
    this.phase = ENCOUNTER.spawn;
    this.timer = 0;
    this.spawnBoss();
    this.hudVisible = true;
    this.game.playBossMusic();
    if (this.game.waves) {
      this.game.waves.banner = { title: this.cfg.displayName, subtitle: this.cfg.title };
    }
    this.captureArenaCheckpoint();
    this.game.hud?.invalidate();
  }

  restartCombat() {
    this.unlockArena();
    this.clearHostile();
    this._removeBosses();
    this.game.cinematic?.cancel();
    this.phase = ENCOUNTER.idle;
    this.begin();
    const watched = Boolean(this.game.checkpoint?.bossIntroWatched);
    this.start({ skipIntro: watched && !DEBUG_REPLAY_BOSS_INTRO });
  }

  onPlayerDied() {
    if (this.boss) {
      this.boss.combatEnabled = false;
      this.boss.hitboxEnabled = false;
      this.boss.vx = 0;
      this.boss.clearMelee();
      if (this.boss.state !== BOSS_STATES.death && this.boss.state !== BOSS_STATES.complete) {
        this.boss.state = BOSS_STATES.idle;
      }
    }
    this.clearHostile();
  }

  lockArena() {
    if (this.arenaLocked || !this.game.world) return;
    const arena = this.arenaBox();
    const h = this.game.world.height || DESIGN_H;
    this.arenaSolids = [
      { x: arena.left - 24, y: 0, w: 24, h, bossArena: true },
      { x: arena.right, y: 0, w: 24, h, bossArena: true },
    ];
    this.game.world.solids = [...(this.game.world.solids || []), ...this.arenaSolids];
    this.arenaLocked = true;
  }

  unlockArena() {
    if (!this.arenaLocked || !this.game.world) {
      this.arenaLocked = false;
      this.arenaSolids = [];
      return;
    }
    const drop = new Set(this.arenaSolids);
    this.game.world.solids = (this.game.world.solids || []).filter((s) => !drop.has(s) && !s.bossArena);
    this.arenaLocked = false;
    this.arenaSolids = [];
  }

  arenaBox() {
    const world = this.game.world;
    if (world?.bossArena) return { ...world.bossArena };
    const zones = world?.zones || [];
    const wrap = zones.find((z) => String(z.label || "").toUpperCase().includes("WRAP"));
    if (wrap) return { left: wrap.x, right: wrap.x + wrap.w, groundY: world.ground?.y ?? 960 };
    const w = world?.width || 2000;
    return { left: Math.max(0, w - 1400), right: w - 64, groundY: world.ground?.y ?? 960 };
  }

  playerInArena(opts = {}) {
    const player = this.game.player;
    const arena = this.arenaBox();
    if (!player || !arena) return false;
    const pad = opts.pad ?? 48;
    return player.footX >= arena.left - pad && player.footX <= arena.right + pad;
  }

  placePlayerCombatStart() {
    const player = this.game.player;
    const arena = this.arenaBox();
    if (!player || !arena) return;
    player.footX = arena.left + 150;
    player.footY = arena.groundY ?? player.footY;
    player.vx = 0;
    player.vy = 0;
    player.direction = 1;
    player.facing = 1;
    player._syncBox?.();
  }

  _removeBosses() {
    this.game.enemies = (this.game.enemies || []).filter((e) => !e.isBoss);
    this.boss = null;
    this.hudVisible = false;
  }

  clearHostile() {
    const game = this.game;
    if (!game.hostilePool) game.hostilePool = new HostileProjectilePool();
    game.hostileProjectiles = game.hostilePool.clear(game.hostileProjectiles || []);
    for (const shot of game.projectiles || []) {
      if (shot.owner === "enemy" || shot.faction === "boss") shot.disable();
    }
    game.projectiles = (game.projectiles || []).filter((p) => p.alive);
    this.boss?.clearMelee?.();
  }

  spawnBoss() {
    if (this.spawnedOnce && this.boss) return this.boss;
    this._removeBosses();
    const arena = this.arenaBox();
    const kit = this.game.assets.enemyKit("boss_01");
    const spawn = {
      id: "boss_01",
      x: arena.right - 180,
      y: arena.groundY ?? this.game.world.ground?.y ?? 960,
      activated: true,
      activateRange: 4000,
      arena,
    };
    const boss = new BossEnemy(spawn, kit, this.cfg);
    boss.health = this.cfg.maxHealth;
    boss.phase = 1;
    boss.phaseShifted = false;
    boss.direction = -1;
    boss._applyFacingFlip();
    boss.spawnId = spawn.id;
    this.game.enemies.push(boss);
    this.boss = boss;
    this.spawnedOnce = true;
    this.hudVisible = true;
    return boss;
  }

  captureArenaCheckpoint() {
    const cp = (this.game.world?.checkpoints || []).find((c) => c.id === "studio_01_boss");
    if (cp) {
      cp.activated = true;
      this.game.captureCheckpoint(cp, { silent: true });
    } else {
      this.game.captureCheckpoint(null, { silent: true });
    }
    if (this.game.checkpoint) {
      this.game.checkpoint.bossArena = true;
      this.game.checkpoint.bossIntroWatched = Boolean(this.game.checkpoint.bossIntroWatched || this.introPlayed);
      this.game.checkpoint.waves = this.game.waves?.snapshot?.() || this.game.checkpoint.waves;
    }
  }

  update(dt) {
    if (this.phase === ENCOUNTER.idle || this.phase === ENCOUNTER.complete) return;
    this.timer += dt;

    if (this.phase === ENCOUNTER.pending) {
      const living = (this.game.enemies || []).some((e) => e.alive && !e.isBoss);
      const shots = (this.game.projectiles || []).some((p) => p.alive && p.owner === "enemy");
      if (living || shots) return;
      if (!this.playerInArena()) return;
      this.start();
      return;
    }

    if (this.phase === ENCOUNTER.intro) return;

    if (this.phase === ENCOUNTER.spawn) {
      if (!this.boss) this.spawnBoss();
      if (this.timer > 2.4 && this.game.waves?.banner?.title === this.cfg.displayName) {
        this.game.waves.banner = null;
      }
      if (this.boss && this.boss.state !== BOSS_STATES.spawning) {
        this.phase = ENCOUNTER.combat;
        this.hudVisible = true;
        this.game.hud?.invalidate();
      }
      return;
    }

    if (this.phase === ENCOUNTER.combat) {
      if (this.boss?.state === BOSS_STATES.phase_transition) {
        if (!this._phaseClear) {
          this._phaseClear = true;
          this.boss.clearMelee();
          this.clearHostile();
        }
        this.game.hud?.invalidate();
      }
      if (this.boss && (this.boss.deathStarted || this.boss.state === BOSS_STATES.death)) {
        this.phase = ENCOUNTER.dying;
        this.timer = 0;
        this.boss.hitboxEnabled = false;
        this.boss.combatEnabled = false;
        this.boss.clearMelee();
        this.clearHostile();
      }
      return;
    }

    if (this.phase === ENCOUNTER.dying) {
      if (this.boss && this.boss.state === BOSS_STATES.complete) {
        if (!this.clearBanner) {
          this.clearBanner = true;
          this.timer = 0;
          this._prepareClear();
        } else if (this.timer >= 1.35) {
          this._finishDeath();
        }
      }
    }
  }

  _prepareClear() {
    this.hudVisible = false;
    this.clearHostile();
    this.unlockArena();
    if (!this.scoreAwarded && this.boss) {
      this.scoreAwarded = true;
      this.game.score += this.cfg.scoreValue;
      this.game.stats.kills += 1;
    }
    this.game._bossMusic = false;
    this.game.audio.stopMusic(0.45);
    if (this.game.waves) this.game.waves.banner = { title: "BOSS DEFEATED", subtitle: this.cfg.displayName };
    this.game.waves?.completeStudio?.();
    const enc = (this.game.world?.encounters || []).find((e) => e.boss || e.id === "enc_final");
    if (enc) {
      enc.activated = true;
      enc.cleared = true;
    }
    this.game.hud?.invalidate();
  }

  _finishDeath() {
    if (this.phase === ENCOUNTER.complete) return;
    this.phase = ENCOUNTER.complete;
    this.game.awardStudioClear?.();
  }
}
