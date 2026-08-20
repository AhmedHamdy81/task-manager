import { applyGravity } from "./physics.js";
import { keepInWorld, resolveSolids } from "./collision.js";
import { Enemy } from "./enemy.js";
import { EXECUTIVE_PRODUCER_BOSS, projectileDef } from "./combat.js";
import { Projectile } from "./projectile.js";
import { DESIGN_H } from "./config.js";

export const BOSS_STATES = {
  entrance: "entrance",
  idle: "idle",
  move: "move",
  ranged_attack: "ranged_attack",
  charge_prepare: "charge_prepare",
  charge: "charge",
  recovery: "recovery",
  hit: "hit",
  phase_transition: "phase_transition",
  death: "death",
  complete: "complete",
};

const ENCOUNTER = {
  idle: "idle",
  pending: "pending",
  warning: "warning",
  spawn: "spawn",
  combat: "combat",
  dying: "dying",
  complete: "complete",
};

const ATTACK_LOCK = new Set([
  BOSS_STATES.entrance,
  BOSS_STATES.hit,
  BOSS_STATES.phase_transition,
  BOSS_STATES.death,
  BOSS_STATES.complete,
]);

const ANIM_FOR_STATE = {
  entrance: "walk",
  idle: "idle",
  move: "walk",
  ranged_attack: "attack",
  charge_prepare: "attack",
  charge: "walk",
  recovery: "idle",
  hit: "hit",
  phase_transition: "hit",
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
  const fallbacks = wanted === "death" ? ["death", "hit", "idle"] : wanted === "hit" ? ["hit", "idle"] : ["walk", "idle", "attack"];
  for (const name of fallbacks) {
    if (clipExists(kit, name) && name !== wanted) {
      warnAnim("executive_producer", wanted, name);
      return name;
    }
  }
  if (wanted !== "idle") warnAnim("executive_producer", wanted, "idle");
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
  constructor(spawn, spriteKit, cfg = EXECUTIVE_PRODUCER_BOSS) {
    super("executive_producer", spawn, spriteKit);
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
    this.state = BOSS_STATES.entrance;
    this.stateTime = 0;
    this.attackTimer = cfg.attackCooldown * 0.4;
    this.chargeTimer = cfg.chargeCooldown * 0.5;
    this.burstLeft = 0;
    this.burstGap = 0;
    this.chargeDir = 1;
    this.moveSpeed = cfg.moveSpeed;
    this.chargeSpeed = cfg.chargeSpeed;
    this.attackCooldown = cfg.attackCooldown;
    this.chargeCooldown = cfg.chargeCooldown;
    this.rangedBonus = 0;
    this.phaseFx = 0;
    this.resumeState = BOSS_STATES.idle;
    this.arena = spawn.arena || null;
    this._playBossAnim(BOSS_STATES.entrance, { restart: true });
  }

  beginDeath() {
    if (this.deathStarted) return;
    this.deathStarted = true;
    this.alive = true;
    this.health = 0;
    this.vx = 0;
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.state = BOSS_STATES.death;
    this.stateTime = 0;
    this._playBossAnim(BOSS_STATES.death, { restart: true });
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
    this.vx = 0;
    this.burstLeft = 0;
    this.moveSpeed = this.cfg.moveSpeed * this.cfg.phase2.moveSpeedMul;
    this.chargeSpeed = this.cfg.chargeSpeed * this.cfg.phase2.chargeSpeedMul;
    this.attackCooldown = this.cfg.attackCooldown * this.cfg.phase2.attackCooldownMul;
    this.chargeCooldown = this.cfg.chargeCooldown * this.cfg.phase2.attackCooldownMul;
    this.rangedBonus = this.cfg.phase2.rangedProjectileAdd;
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

    if (this.state === BOSS_STATES.hit) {
      this.vx = 0;
      this._facePlayer(player);
      if (this.anim.finished || this.stateTime > (this.cfg.hitInvuln || 0.22)) {
        this.tryPhaseTwo() || this._setState(BOSS_STATES.idle);
      }
    } else if (this.state === BOSS_STATES.entrance) {
      this.hitboxEnabled = false;
      this.combatEnabled = false;
      this.vx = this.direction * this.cfg.moveSpeed * 0.55;
      if (this.stateTime >= this.cfg.entranceSec) {
        this.hitboxEnabled = true;
        this.combatEnabled = true;
        this._setState(BOSS_STATES.idle);
      }
    } else     if (this.state === BOSS_STATES.phase_transition) {
      this.vx = 0;
      this.hitboxEnabled = false;
      this.phaseFx = 0.2;
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
      if (this.stateTime >= this.cfg.phaseTransitionSec) {
        this.hitboxEnabled = true;
        this.combatEnabled = true;
        this.invuln = 0.12;
        this._setState(BOSS_STATES.idle);
      }
    } else if (this.state === BOSS_STATES.ranged_attack) {
      this.vx = 0;
      this._facePlayer(player);
      this._tickRanged(dt, player, world, game);
    } else if (this.state === BOSS_STATES.charge_prepare) {
      this.vx = 0;
      if (this.stateTime >= this.cfg.chargePrepareSec) this._setState(BOSS_STATES.charge);
    } else if (this.state === BOSS_STATES.charge) {
      this.vx = this.chargeDir * this.chargeSpeed;
      const hitWall = this._chargeHitBound();
      if (hitWall || this.stateTime > 1.15) this._setState(BOSS_STATES.recovery);
    } else if (this.state === BOSS_STATES.recovery) {
      this.vx = 0;
      if (this.stateTime >= this.cfg.recoverySec) this._setState(BOSS_STATES.idle);
    } else {
      this._tickIdleMove(dt, player, world, game);
    }

    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();
    this._clampArena();
    if (this.state !== BOSS_STATES.hit && this.state !== BOSS_STATES.ranged_attack) this._playBossAnim(this.state);
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

  _tickIdleMove(dt, player, world, game) {
    if (!player?.alive || !this.combatEnabled) {
      this.vx = 0;
      this._setState(BOSS_STATES.idle);
      return;
    }
    this._facePlayer(player);
    const dx = player.footX - this.footX;
    const dist = Math.abs(dx);
    const preferred = this.spec.preferredRange;
    const band = this.spec.rangeBand || 52;

    if (this.chargeTimer <= 0 && dist > 90) {
      this.chargeDir = dx >= 0 ? 1 : -1;
      this.chargeTimer = this.chargeCooldown;
      this._setState(BOSS_STATES.charge_prepare);
      return;
    }
    if (this.attackTimer <= 0) {
      this._beginRanged(player);
      return;
    }

    if (dist > preferred + band && this._canStep(world, this.direction)) {
      this._setState(BOSS_STATES.move);
      this.vx = this.direction * this.moveSpeed;
    } else if (dist < preferred - band && this._canStep(world, -this.direction)) {
      this._setState(BOSS_STATES.move);
      this.vx = -this.direction * this.moveSpeed;
    } else {
      this._setState(BOSS_STATES.idle);
      this.vx = 0;
    }
  }

  _beginRanged(player) {
    const min = this.cfg.rangedBurstMin;
    const max = this.cfg.rangedBurstMax + this.rangedBonus;
    const n = min + Math.floor(Math.random() * (max - min + 1));
    this.burstLeft = Math.max(1, n);
    this.burstGap = 0;
    this.attackTimer = this.attackCooldown;
    this._firedClip = false;
    this._setState(BOSS_STATES.ranged_attack);
  }

  _tickRanged(dt, player, world, game) {
    if (this.burstLeft <= 0) {
      this._setState(BOSS_STATES.idle);
      return;
    }
    this.burstGap -= dt;
    const release = this.weapon.spawnFrame ?? 2;
    const ready = this.anim.name === "attack" ? this.anim.frame >= release || this.anim.finished : true;
    if (this.burstGap > 0 || !ready || this._firedClip) {
      if (this.anim.finished && this.burstLeft > 0) {
        this._firedClip = false;
        this._playBossAnim(BOSS_STATES.ranged_attack, { restart: true });
      }
      return;
    }
    this._fireAtPlayer(player, game);
    this.burstLeft -= 1;
    this._firedClip = true;
    this.burstGap = 0.16;
    this.weapon.cool = 0.05;
    if (this.burstLeft <= 0) this._setState(BOSS_STATES.recovery);
  }

  _fireAtPlayer(player, game) {
    if (!game || !player?.alive) return;
    const muzzle = this.muzzleWorld();
    const aimX = player.footX;
    const aimY = player.footY - 90;
    const dx = aimX - muzzle.x;
    const dy = aimY - muzzle.y;
    const len = Math.max(1, Math.hypot(dx, dy));
    const speed = this.cfg.projectileSpeed;
    const def = projectileDef(this.weapon.projectileId);
    game.acquireHostileShot({
      x: muzzle.x - (def.hitW || 32) / 2,
      y: muzzle.y - (def.hitH || 20) / 2,
      vx: (dx / len) * speed,
      vy: (dy / len) * speed,
      damage: this.cfg.projectileDamage,
      type: def.id,
      frame: def.frame,
      w: def.hitW,
      h: def.hitH,
      vis: def.vis,
      flip: def.flip,
      lifetime: 2.4,
      sheet: game.assets?.sheet("projectiles") || null,
      impactFx: this.weapon.impactFx,
    });
    this.weapon.cool = 0.05;
  }

  takeDamage(amount) {
    if (this.deathStarted || this.state === BOSS_STATES.death || this.state === BOSS_STATES.complete) return 0;
    if (this.state === BOSS_STATES.entrance || this.state === BOSS_STATES.phase_transition) return 0;
    const scored = super.takeDamage(amount);
    if (this.deathStarted || this.health <= 0) return 0;
    if (this.alive && this.state !== BOSS_STATES.phase_transition) {
      this.resumeState = this.state === BOSS_STATES.charge ? BOSS_STATES.recovery : BOSS_STATES.idle;
      this.burstLeft = 0;
      this._setState(BOSS_STATES.hit);
      this.tryPhaseTwo();
    }
    return scored;
  }

  draw(ctx, camera) {
    super.draw(ctx, camera);
    if (this.phase === 2 && this.alive && this.state !== BOSS_STATES.death) {
      const origin = camera.worldToScreen(this.footX, this.footY);
      ctx.save();
      ctx.globalAlpha = 0.35 + (this.phaseFx > 0 ? 0.35 : 0);
      ctx.strokeStyle = "#f97316";
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
    this.cfg = EXECUTIVE_PRODUCER_BOSS;
    this.clearBanner = false;
  }

  destroy() {
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

  hudView() {
    if (!this.hudVisible || !this.boss) return null;
    if (this.phase === ENCOUNTER.complete && !this.boss.alive && this.boss.state === BOSS_STATES.complete) return null;
    return {
      name: this.cfg.displayName,
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

  start() {
    if (this.phase === ENCOUNTER.warning || this.phase === ENCOUNTER.spawn || this.phase === ENCOUNTER.combat) return;
    this.clearHostile();
    this._removeBosses();
    this.phase = ENCOUNTER.warning;
    this.timer = 0;
    this.warningOnce = false;
    this.spawnedOnce = false;
    this.hudVisible = false;
    this.scoreAwarded = false;
    this.clearBanner = false;
    this.cfg = this.game.world?.boss || EXECUTIVE_PRODUCER_BOSS;
    const enc = (this.game.world?.encounters || []).find((e) => e.boss);
    if (enc) enc.activated = true;
    this.lockArena();
    this.placePlayerInArena();
    this.captureArenaCheckpoint();
    if (this.game.waves) this.game.waves.banner = { title: "WARNING", subtitle: "EXECUTIVE PRODUCER INCOMING" };
    this.game.hud?.invalidate();
  }

  restartCombat() {
    this.unlockArena();
    this.clearHostile();
    this._removeBosses();
    this.phase = ENCOUNTER.idle;
    this.begin();
    this.start();
  }

  onPlayerDied() {
    if (this.boss) {
      this.boss.combatEnabled = false;
      this.boss.hitboxEnabled = false;
      this.boss.vx = 0;
      this.boss.burstLeft = 0;
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

  placePlayerInArena() {
    const player = this.game.player;
    const arena = this.arenaBox();
    if (!player) return;
    if (player.footX < arena.left + 80) player.footX = arena.left + 120;
    if (player.footX > arena.right - 80) player.footX = arena.right - 160;
    player.vx = 0;
    player._syncBox?.();
  }

  _removeBosses() {
    this.game.enemies = (this.game.enemies || []).filter((e) => !e.isBoss);
    this.boss = null;
  }

  clearHostile() {
    const game = this.game;
    if (!game.hostilePool) game.hostilePool = new HostileProjectilePool();
    game.hostileProjectiles = game.hostilePool.clear(game.hostileProjectiles || []);
    for (const shot of game.projectiles || []) {
      if (shot.owner === "enemy" || shot.faction === "boss") shot.disable();
    }
    game.projectiles = (game.projectiles || []).filter((p) => p.alive);
  }

  spawnBoss() {
    if (this.spawnedOnce && this.boss) return this.boss;
    this._removeBosses();
    const arena = this.arenaBox();
    const kit = this.game.assets.enemyKit("executive_producer");
    const spawn = {
      id: "boss_executive_producer",
      x: arena.right - 180,
      y: arena.groundY ?? this.game.world.ground?.y ?? 960,
      activated: true,
      activateRange: 4000,
      arena,
    };
    const boss = new BossEnemy(spawn, kit, this.cfg);
    boss.direction = -1;
    boss._applyFacingFlip();
    boss.spawnId = spawn.id;
    this.game.enemies.push(boss);
    this.boss = boss;
    this.spawnedOnce = true;
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
      this.game.checkpoint.waves = this.game.waves?.snapshot?.() || this.game.checkpoint.waves;
    }
  }

  playWarningAudio() {
    if (this.warningOnce) return;
    this.warningOnce = true;
    this.game.sfx("boss_warning", { force: true });
    this.game._bossWarned.add("enc_final");
    this.game._bossMusic = true;
    this.game.playBossMusic();
  }

  update(dt) {
    if (this.phase === ENCOUNTER.idle || this.phase === ENCOUNTER.complete) return;
    this.timer += dt;

    if (this.phase === ENCOUNTER.pending) {
      const living = (this.game.enemies || []).some((e) => e.alive && !e.isBoss);
      const shots = (this.game.projectiles || []).some((p) => p.alive && p.owner === "enemy");
      if (living || shots) return;
      this.start();
      return;
    }

    if (this.phase === ENCOUNTER.warning) {
      if (!this.warningOnce) this.playWarningAudio();
      if (this.timer >= this.cfg.warningSec) {
        this.game.waves.banner = null;
        this.phase = ENCOUNTER.spawn;
        this.timer = 0;
        this.spawnBoss();
        this.captureArenaCheckpoint();
      }
      return;
    }

    if (this.phase === ENCOUNTER.spawn) {
      if (!this.boss) this.spawnBoss();
      if (this.boss && this.boss.state !== BOSS_STATES.entrance) {
        this.phase = ENCOUNTER.combat;
        this.hudVisible = true;
        this.game.hud?.invalidate();
      }
      return;
    }

    if (this.phase === ENCOUNTER.combat) {
      if (this.boss?.state === BOSS_STATES.phase_transition) this.game.hud?.invalidate();
      if (this.boss && (this.boss.deathStarted || this.boss.state === BOSS_STATES.death)) {
        this.phase = ENCOUNTER.dying;
        this.timer = 0;
        this.boss.hitboxEnabled = false;
        this.boss.combatEnabled = false;
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
        } else if (this.timer >= 1.25) {
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
    if (this.game.waves) this.game.waves.banner = { title: "STUDIO 01 CLEAR", subtitle: "WRAP COMPLETE" };
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
