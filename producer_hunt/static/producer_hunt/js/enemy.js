import { SpriteAnimator } from "./animation.js";
import { aabb, keepInWorld, lineBlocked, resolveSolids } from "./collision.js";
import { applyGravity } from "./physics.js";
import { BOSS_01_ANIMATIONS, characterSpriteSrc, crewEnemySpriteSrc, makeEnemySpriteConfig } from "./sprite-spec.js";
import { BOSS_01, COMBAT, enemyMuzzleOffset, enemyWeaponDef, playerTorsoAim } from "./combat.js";
import { DEBUG_COMBAT, ENEMY_HIT_FLASH_SEC } from "./config.js";
import { Weapon, weaponShots } from "./weapon.js";
import { instantiatePickup } from "./pickups.js";
import {
  aimAtTorso,
  applyDifficultyToEnemy,
  AttackCoordinator,
  detected,
  enterState,
  onCamera,
  rememberPlayer,
  shouldDropPickup,
  tickTimeout,
} from "./enemy-ai.js";

const STATE_TO_ANIM = {
  spawn: "idle",
  idle: "idle",
  patrol: "walk",
  alert: "idle",
  chase: "walk",
  position: "walk",
  telegraph: "attack",
  attack: "attack",
  recover: "idle",
  hit: "hit",
  retreat: "walk",
  death: "death",
  charge: "walk",
};

export const DEFAULT_ENEMY_ID = "post_producer";

/** Legacy spawn ids from older levels / saves. Not preloaded. */
export const LEGACY_ENEMY_ALIASES = {
  assistant_producer: DEFAULT_ENEMY_ID,
};

let _legacyEnemyWarned = false;

export function migrateEnemyType(typeId) {
  const raw = String(typeId || "").trim();
  if (LEGACY_ENEMY_ALIASES[raw]) {
    if (!_legacyEnemyWarned) {
      console.warn(
        '[Producer Hunt] Migrated legacy enemy type "assistant_producer" to "post_producer".'
      );
      _legacyEnemyWarned = true;
    }
    return LEGACY_ENEMY_ALIASES[raw];
  }
  return raw || DEFAULT_ENEMY_ID;
}

export function resolveEnemyType(typeId) {
  const id = migrateEnemyType(typeId);
  if (ENEMY_TYPES[id]) return ENEMY_TYPES[id];
  return ENEMY_TYPES[DEFAULT_ENEMY_ID];
}

export const ENEMY_TYPES = {
  post_producer: {
    id: "post_producer",
    type: "post_producer",
    name: "Assistant Producer",
    initials: "AP",
    role: "ranged",
    behavior: "ranged",
    artFacing: 1,
    health: 50,
    speed: 95,
    chaseSpeed: 120,
    damage: 10,
    contactDamage: 10,
    scoreValue: 100,
    detectionRange: 560,
    detectionY: 220,
    preferredRange: 420,
    minRetreatRange: 150,
    attackRange: COMBAT.enemy.attackRange,
    hitStun: 0.16,
    reactionDelay: 0.28,
    needsLos: true,
    color: "#c084fc",
    accent: "#6b21a8",
    sprite: makeEnemySpriteConfig("post_producer"),
    impactSheet: "post_producer_impact",
    loot: { kind: "ammo", chance: 0.18 },
  },
  colorist: {
    id: "colorist",
    type: "colorist",
    name: "Colorist",
    initials: "CO",
    role: "close",
    behavior: "close",
    artFacing: 1,
    health: 90,
    speed: 75,
    chaseSpeed: 90,
    chargeSpeed: 260,
    damage: 20,
    contactDamage: 20,
    chargeDamage: 20,
    scoreValue: 175,
    detectionRange: 420,
    detectionY: 200,
    preferredRange: 70,
    attackRange: 92,
    hitStun: 0.2,
    reactionDelay: 0.22,
    color: "#fb7185",
    accent: "#9f1239",
    sprite: makeEnemySpriteConfig("colorist", {
      srcFn: (anim) => crewEnemySpriteSrc("colorist", anim),
      collisionWidth: 80,
      collisionHeight: 190,
      renderWidth: 236,
      renderHeight: 236,
    }),
    impactSheet: "effects",
    loot: { kind: "health", chance: 0.2 },
  },
  vfx_supervisor: {
    id: "vfx_supervisor",
    type: "vfx_supervisor",
    name: "VFX Supervisor",
    initials: "FX",
    role: "area",
    behavior: "area",
    artFacing: 1,
    health: 130,
    speed: 55,
    chaseSpeed: 62,
    damage: 20,
    hazardDamage: 10,
    contactDamage: 12,
    scoreValue: 250,
    detectionRange: 640,
    detectionY: 260,
    preferredRange: 340,
    minRetreatRange: 160,
    attackRange: 480,
    hitStun: 0.22,
    reactionDelay: 0.4,
    needsLos: true,
    color: "#a78bfa",
    accent: "#5b21b6",
    sprite: makeEnemySpriteConfig("vfx_supervisor", {
      srcFn: (anim) => crewEnemySpriteSrc("vfx_supervisor", anim),
      collisionWidth: 92,
      collisionHeight: 200,
      renderWidth: 236,
      renderHeight: 236,
    }),
    impactSheet: "effects",
    loot: { kind: "ammo", chance: 0.28 },
  },
  client: {
    id: "client",
    type: "client",
    name: "The Client",
    initials: "CL",
    role: "elite",
    behavior: "elite",
    artFacing: -1,
    health: 100,
    speed: 85,
    chaseSpeed: 85,
    damage: 20,
    contactDamage: 12,
    impactDamage: 20,
    scoreValue: 300,
    detectionRange: 620,
    detectionY: 220,
    preferredRange: 380,
    minRetreatRange: 190,
    attackRange: 520,
    rangeBand: 36,
    hitStun: 0.18,
    reactionDelay: 0.32,
    needsLos: true,
    color: "#fb7185",
    accent: "#9f1239",
    sprite: makeEnemySpriteConfig("client", {
      collisionWidth: 54,
      collisionHeight: 210,
    }),
    impactSheet: "client_impact",
    loot: { kind: "health", chance: 0.3 },
  },
  boss_01: {
    id: "boss_01",
    type: "boss_01",
    name: BOSS_01.displayName,
    title: BOSS_01.title,
    initials: "ES",
    behavior: "boss",
    isBoss: true,
    artFacing: 1,
    health: BOSS_01.maxHealth,
    speed: BOSS_01.walkSpeed,
    chaseSpeed: BOSS_01.walkSpeed,
    damage: BOSS_01.projectileDamage,
    contactDamage: BOSS_01.contactDamage,
    scoreValue: BOSS_01.scoreValue,
    detectionRange: 2400,
    preferredRange: BOSS_01.preferredRange,
    attackRange: COMBAT.boss_01.attackRange,
    rangeBand: BOSS_01.rangeBand,
    hitStun: BOSS_01.hitInvuln,
    color: "#f59e0b",
    accent: "#92400e",
    sprite: makeEnemySpriteConfig("boss_01", {
      srcFn: (anim) => characterSpriteSrc("boss_01", anim),
      animationMap: BOSS_01_ANIMATIONS,
      collisionWidth: 92,
      collisionHeight: 198,
      collisionOffsetX: 0,
      collisionOffsetY: 0,
    }),
    impactSheet: "effects",
    boss: BOSS_01,
  },
};

export class Enemy {
  constructor(typeId, spawn, spriteKit = null) {
    const spec = resolveEnemyType(typeId);
    this.spec = spec;
    this.id = spec.id;
    this.type = spec.type;
    const body = spriteKit || spec.sprite || {};
    this.collisionOffsetX = body.collisionOffsetX || 0;
    this.collisionOffsetY = body.collisionOffsetY || 0;
    this.w = body.collisionWidth || spec.sprite?.collisionWidth || 88;
    this.h = body.collisionHeight || spec.sprite?.collisionHeight || 210;
    this.footX = spawn.x;
    this.footY = spawn.y;
    this._syncBox();
    this.vx = 0;
    this.vy = 0;
    this.direction = spec.artFacing || 1;
    this.onGround = false;
    this.health = spec.health;
    this.alive = true;
    this.state = "spawn";
    this.stateAge = 0;
    this.spawnLock = 0.45;
    this.hitFlash = 0;
    this.frozen = 0;
    this.deadTimer = 0;
    this.attackCool = 0;
    this.alertTimer = 0;
    this.contactCool = 0;
    this._firedClip = false;
    this.patrolMin = spawn.patrolMin ?? spawn.x - 120;
    this.patrolMax = spawn.patrolMax ?? spawn.x + 120;
    this.zoneLeft = spawn.zoneLeft ?? this.patrolMin - 40;
    this.zoneRight = spawn.zoneRight ?? this.patrolMax + 40;
    this.anim = new SpriteAnimator(spriteKit || spec.sprite);
    this.anim.play("idle", { restart: true });
    this._applyFacingFlip();
    this.weapon = new Weapon(enemyWeaponDef(spec.id));
    this.activated = Boolean(spawn.activated);
    this.activateRange = spawn.activateRange || 640;
    this.spawnId = spawn.id || spec.id;
    this.waveTracked = false;
    this.waveMods = null;
    this.elite = false;
    this._waveDeathReported = false;
    this.onWaveExit = null;
    this.isBoss = Boolean(spec.isBoss);
    this.hitboxEnabled = true;
    this.invuln = 0;
    this.combatEnabled = true;
    this.meleeActive = false;
    this._dropped = false;
    this._attackArmed = false;
    this.chargeTimer = 0;
    this.markTimer = 0;
    this.encounterId = spawn.encounterId || null;
  }

  applyWaveModifiers(mods) {
    if (!mods) return;
    this.spec = { ...this.spec };
    this.waveMods = { ...mods };
    const hm = Number(mods.healthMultiplier) || 1;
    const sm = Number(mods.speedMultiplier) || 1;
    const dm = Number(mods.damageMultiplier) || 1;
    this.spec.health = this.spec.health * hm;
    this.health = this.spec.health;
    this.spec.speed *= sm;
    this.spec.chaseSpeed *= sm;
    this.spec.damage *= dm;
    this.spec.scoreValue = Math.round((this.spec.scoreValue || 0) * Math.max(hm, 1));
    if (this.weapon) this.weapon.damage = (this.weapon.damage || this.spec.damage) * dm;
    this.elite = Boolean(mods.elite);
    this.vx = 0;
  }

  notifyWaveExit(reason) {
    if (this._waveDeathReported) return;
    this._waveDeathReported = true;
    if (typeof this.onWaveExit === "function") this.onWaveExit(this, reason);
  }

  telegraphHold(base) {
    return Math.max(0.18, base * Math.max(0.55, this.reactionMul || 1));
  }

  _syncBox() {
    this.x = this.footX - this.w / 2 + this.collisionOffsetX;
    this.y = this.footY - this.h + this.collisionOffsetY;
  }

  _syncFeet() {
    this.footX = this.x + this.w / 2 - this.collisionOffsetX;
    this.footY = this.y + this.h - this.collisionOffsetY;
  }

  bounds() {
    if (!this.alive || this.hitboxEnabled === false) return { x: this.x, y: this.y, w: 0, h: 0 };
    return { x: this.x, y: this.y, w: this.w, h: this.h };
  }

  freeze(seconds) {
    this.frozen = Math.max(this.frozen, seconds);
  }

  muzzleWorld() {
    const off = enemyMuzzleOffset(this.spec.id, this.anim?.name);
    return {
      x: this.footX + this.direction * (off.x || 0),
      y: this.footY + (off.y || 0),
    };
  }

  _applyFacingFlip() {
    const art = this.spec.artFacing || 1;
    this.anim.flip = this.direction !== art;
  }

  _canStep(world, dir) {
    const look = 36;
    const probe = {
      x: this.footX + dir * look - 10,
      y: this.footY + 4,
      w: 20,
      h: 28,
    };
    const grounded = (world.solids || []).some((s) => aabb(probe, s));
    if (!grounded) return false;
    const wall = {
      x: this.footX + dir * 28 - 6,
      y: this.footY - this.h + 12,
      w: 12,
      h: this.h - 20,
    };
    const blocked = (world.solids || []).some((s) => s.y + s.h < this.footY - 8 && aabb(wall, s));
    return !blocked;
  }

  update(dt, player, world, projectiles = null, game = null) {
    const scale = game?.combatTimeScale?.(this) ?? 1;
    const sdt = dt * scale;
    if (this.contactCool > 0) this.contactCool -= sdt;
    if (this.invuln > 0) this.invuln -= sdt;
    if (!this.alive) {
      this.deadTimer += dt;
      this.state = "death";
      this.vx = 0;
      this.anim.play("death");
      this._applyFacingFlip();
      this.anim.update(dt);
      return;
    }
    if (this.hitFlash > 0) this.hitFlash -= sdt;
    this.weapon.update(sdt);
    this.attackCool = this.weapon.cool;
    if (this.frozen > 0) {
      this.frozen -= sdt;
      this.vx = 0;
      this.state = "idle";
      applyGravity(this, sdt);
      resolveSolids(this, world.solids, sdt);
      keepInWorld(this, world);
      this._syncFeet();
      this._playAnim();
      this._applyFacingFlip();
      this.anim.update(sdt);
      return;
    }

    if (this.spawnLock > 0) this.spawnLock -= sdt;

    if (!this.activated) {
      const far = Math.abs(player.footX - this.footX) > 1400;
      if (far) {
        if (!this.onGround) {
          applyGravity(this, sdt);
          resolveSolids(this, world.solids, sdt);
          keepInWorld(this, world);
          this._syncFeet();
        }
        return;
      }
      const near =
        !this.encounterBound &&
        player.alive &&
        Math.abs(player.footX - this.footX) <= this.activateRange &&
        Math.abs(player.footY - this.footY) < 280;
      if (near) this.activated = true;
      else {
        this.vx = 0;
        enterState(this, "idle");
        applyGravity(this, sdt);
        resolveSolids(this, world.solids, sdt);
        keepInWorld(this, world);
        this._syncFeet();
        this._playAnim();
        this._applyFacingFlip();
        this.anim.update(sdt);
        return;
      }
    }

    if (this.spec.behavior === "boss") {
      this._updateBoss(player, world, sdt, projectiles, game);
      return;
    }

    applyDifficultyToEnemy(this, game?.settings);
    this._game = game;
    this._updateAi(player, world, sdt, projectiles, game);
    this._clampToZone();

    applyGravity(this, sdt);
    resolveSolids(this, world.solids, sdt);
    keepInWorld(this, world);
    this._syncFeet();
    const started = this._playAnim();
    if (started) this._firedClip = false;
    this._applyFacingFlip();
    if (onCamera(game, this, 220) || this.state === "telegraph" || this.state === "attack") this.anim.update(sdt);
    if (projectiles && game) this._trySpawnShot(player, world, projectiles, game);
  }

  _clampToZone() {
    if (this.footX < this.zoneLeft) {
      this.footX = this.zoneLeft;
      this.direction = 1;
      this._syncBox();
    }
    if (this.footX > this.zoneRight) {
      this.footX = this.zoneRight;
      this.direction = -1;
      this._syncBox();
    }
  }

  _updateBoss() {}

  _updateAi(player, world, dt, projectiles, game) {
    tickTimeout(this, dt);
    if (this.hitFlash > 0 && this.state !== "hit") enterState(this, "hit");
    if (this.state === "hit") {
      this.vx = 0;
      this.meleeActive = false;
      return;
    }
    if (this.state === "spawn" || this.spawnLock > 0) {
      this.vx = 0;
      return;
    }
    const see = detected(this, player, world);
    if (see) rememberPlayer(this, player);
    if (see && !this._alertSfx) {
      this._alertSfx = true;
      game?.sfx?.("enemy_alert", { x: this.footX });
    }
    if (!see) this._alertSfx = false;
    const dx = (this.lastKnown?.x ?? player.footX) - this.footX;
    const distX = Math.abs(dx);
    if (see && this.alertTimer <= 0.001) game?.sfx?.("enemy_alert", { x: this.footX });
    if (see && this.alertTimer < (this.spec.reactionDelay || 0.25) * (this.reactionMul || 1)) {
      this.alertTimer += dt;
      enterState(this, "alert");
      this.vx = 0;
      this.direction = dx >= 0 ? 1 : -1;
      return;
    }
    if (see) this.alertTimer += dt;
    else this.alertTimer = 0;

    const role = this.spec.behavior;
    if (role === "close") this._aiClose(player, world, dt, game, dx, distX, see);
    else if (role === "area") this._aiArea(player, world, dt, game, dx, distX, see);
    else this._aiRanged(player, world, dt, game, dx, distX, see);
  }

  _aiRanged(player, world, dt, game, dx, distX, see) {
    const preferred = this.spec.preferredRange || 420;
    const minR = this.spec.minRetreatRange || 150;
    const atk = this.spec.attackRange || 460;
    const face = dx >= 0 ? 1 : -1;
    const coord = game?.attackCoord;
    const now = game?._worldTime || 0;
    const committed = this.state === "telegraph" || this.state === "attack" || this.state === "recover";
    if (committed) {
      this.vx = 0;
      if (this.state === "telegraph" && this.stateAge > this.telegraphHold(0.28)) enterState(this, "attack");
      if (this.state === "attack" && this.anim.finished) {
        coord?.release(this);
        enterState(this, "recover");
      }
      if (this.state === "recover" && this.stateAge > 0.35) enterState(this, "position");
      return;
    }
    if (!see) {
      enterState(this, "patrol");
      this._patrol(world);
      return;
    }
    this.direction = this.state === "attack" ? this.direction : face;
    if (distX < minR) {
      enterState(this, "retreat");
      const back = -face;
      this.vx = this._canStep(world, back) ? back * this.spec.speed : 0;
      return;
    }
    if (distX > preferred + 40) {
      enterState(this, "chase");
      this.vx = this._canStep(world, face) ? face * this.spec.chaseSpeed : 0;
      return;
    }
    const canShoot = distX <= atk && this.weapon.cool <= 0 && onCamera(game, this);
    if (canShoot && coord?.canAttack(this, "ranged", now)) {
      coord.begin(this, "ranged", now);
      enterState(this, "telegraph");
      this.vx = 0;
      game?.sfx?.("enemy_telegraph", { x: this.footX });
      if (this.spec.behavior === "elite" && Math.random() < 0.35) this._armClientMark(game, player);
      return;
    }
    enterState(this, "position");
    this.vx = 0;
  }

  _aiClose(player, world, dt, game, dx, distX, see) {
    const face = dx >= 0 ? 1 : -1;
    const coord = game?.attackCoord;
    const now = game?._worldTime || 0;
    if (this.state === "charge") {
      this.meleeActive = true;
      this.vx = this.direction * (this.spec.chargeSpeed || 260);
      if (this.stateAge > 0.42 || !this._canStep(world, this.direction)) {
        this.meleeActive = false;
        this.weapon.cool = this.weapon.cooldownSec;
        coord?.release(this);
        enterState(this, "recover");
      }
      return;
    }
    if (this.state === "telegraph" || this.state === "attack" || this.state === "recover") {
      this.vx = 0;
      if (this.state === "telegraph" && this.stateAge > this.telegraphHold(0.32)) {
        this.meleeHitOnce = false;
        enterState(this, Math.random() < 0.4 ? "charge" : "attack");
        if (this.state === "charge") this.direction = face;
        if (this.state === "attack") this.meleeActive = true;
      }
      if (this.state === "attack" && this.anim.finished) {
        this.meleeActive = false;
        this.weapon.cool = this.weapon.cooldownSec;
        coord?.release(this);
        enterState(this, "recover");
      }
      if (this.state === "recover" && this.stateAge > 0.45) enterState(this, "chase");
      return;
    }
    if (!see) {
      enterState(this, "patrol");
      this._patrol(world);
      return;
    }
    this.direction = face;
    if (distX > (this.spec.attackRange || 92) + 12) {
      enterState(this, "chase");
      this.vx = this._canStep(world, face) ? face * this.spec.chaseSpeed : 0;
      return;
    }
    if (this.weapon.cool <= 0 && coord?.canAttack(this, "close", now)) {
      coord.begin(this, "close", now);
      enterState(this, "telegraph");
      this.vx = 0;
      game?.sfx?.("enemy_telegraph", { x: this.footX });
      return;
    }
    enterState(this, "idle");
    this.vx = 0;
  }

  _aiArea(player, world, dt, game, dx, distX, see) {
    this._aiRanged(player, world, dt, game, dx, distX, see);
  }

  _patrol(world) {
    if (this.footX < this.patrolMin) this.direction = 1;
    if (this.footX > this.patrolMax) this.direction = -1;
    if (!this._canStep(world, this.direction)) this.direction *= -1;
    this.vx = this.direction * this.spec.speed;
  }

  _armClientMark(game, player) {
    const x = player.footX - 32;
    const y = player.footY - 8;
    game?.spawnDangerZone?.({
      x,
      y: y - 12,
      w: 64,
      h: 20,
      life: 0.55,
      delay: 0.55,
      damage: this.spec.impactDamage || 20,
      owner: "enemy",
      kind: "client_mark",
    });
  }

  _updateAggressive() {}

  _updateCautiousRanged() {}

  _playAnim() {
    const desired = STATE_TO_ANIM[this.state] || "idle";
    const cur = this.anim.name;
    if (cur === "death") return false;
    if (cur === "hit" && !this.anim.finished && desired !== "death") return false;
    if (cur === "attack" && this.anim.finished && desired === "attack") {
      if (this.weapon.cool > 0) return this.anim.play("idle");
      return this.anim.play("attack", { restart: true });
    }
    if (cur === "attack" && desired === "telegraph") return false;
    return this.anim.play(desired);
  }

  takeDamage(amount) {
    if (!this.alive) return 0;
    if (this.hitboxEnabled === false) return 0;
    if (this.isBoss && this.invuln > 0) return 0;
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    this.health -= amt;
    this._firedClip = true;
    if (this.health <= 0) {
      this.health = 0;
      if (typeof this.beginDeath === "function") this.beginDeath();
      else this._beginDeath();
      return amt;
    }
    this.hitFlash = ENEMY_HIT_FLASH_SEC;
    if (this.isBoss) this.invuln = Math.max(this.invuln || 0, this.spec.hitStun ?? 0.16);
    this.meleeActive = false;
    this._game?.attackCoord?.release(this);
    enterState(this, "hit");
    this.anim.play("hit", { restart: true });
    return 0;
  }

  _beginDeath() {
    if (!this.alive && this.state === "death") return;
    this.alive = false;
    this.health = 0;
    this.vx = 0;
    this.state = "death";
    this.hitboxEnabled = false;
    this.combatEnabled = false;
    this.meleeActive = false;
    this._game?.attackCoord?.release(this);
    this.anim.play("death", { restart: true });
    this.notifyWaveExit("defeated");
    this._dropLoot(this._game);
  }

  _dropLoot(game) {
    if (this._dropped) return;
    this._dropped = true;
    const loot = this.spec.loot;
    if (!loot || !game?.world) return;
    if (!shouldDropPickup(game.settings, loot.chance || 0.2)) return;
    const pickup = instantiatePickup(
      { id: `${this.spawnId}_drop`, kind: loot.kind, x: this.footX - 32, y: this.footY - 64 },
      0,
      game.world.id
    );
    pickup.respawn = false;
    game.world.pickups.push(pickup);
  }

  _trySpawnShot(player, world, projectiles, game) {
    if (!this.alive || !player.alive || this.spawnLock > 0) return;
    if (this.spec.behavior === "close") return;
    if (this.state !== "attack" || this._firedClip) return;
    if (!onCamera(game, this)) return;
    const release = this.weapon.spawnFrame ?? COMBAT.enemy.spawnFrame;
    if (this.anim.frame < release) return;
    if (!this.weapon.canFire()) return;
    const spread = this.aimSpread ?? 0.08;
    const aim = aimAtTorso(this, player, spread);
    const muzzle = aim.muzzle;
    if (lineBlocked(muzzle.x, muzzle.y, playerTorsoAim(player).x, playerTorsoAim(player).y, world.solids)) {
      this._firedClip = true;
      return;
    }
    const pb = player.bounds();
    if (aabb({ x: muzzle.x - 8, y: muzzle.y - 8, w: 16, h: 16 }, pb)) {
      muzzle.x += this.direction * 36;
    }
    const spd = this.weapon.projectileSpeed;
    const opts = {
      x: muzzle.x,
      y: muzzle.y,
      facing: this.direction,
      owner: "enemy",
      faction: "enemy",
      vx: aim.vx * spd,
      vy: aim.vy * spd,
    };
    const result = this.weapon.tryFire(opts);
    this._firedClip = true;
    const shots = weaponShots(result);
    if (!shots.length) return;
    const sheet = game.assets?.sheet("projectiles") || null;
    game.sfx?.("enemy_fire", { x: muzzle.x });
    for (const shot of shots) {
      shot.sheet = sheet;
      shot.owner = "enemy";
      shot.faction = "enemy";
      if (this.spec.behavior === "area") {
        shot.gravity = 420;
        shot.makeHazard = true;
        shot.hazardDamage = this.spec.hazardDamage || 10;
      }
      projectiles.push(shot);
    }
  }

  draw(ctx, camera) {
    if (!this.alive && this.anim.finished && this.deadTimer > 0.05) return;
    const origin = camera.worldToScreen(this.footX, this.footY);
    const color = this.spec.color;
    ctx.globalAlpha = this.alive ? 1 : 0.55;
    this.anim.draw(ctx, origin.x, origin.y, (g, fw, fh) => {
      g.fillStyle = this.elite ? "#fbbf24" : color;
      g.fillRect(-this.w / 2, -this.h + 8, this.w, this.h - 8);
      g.fillStyle = "#1c1408";
      g.font = "11px sans-serif";
      g.textAlign = "center";
      g.fillText(this.spec.initials || "??", 0, -fh * 0.42);
    });
    if (this.elite) {
      ctx.save();
      ctx.strokeStyle = "rgba(251, 191, 36, 0.9)";
      ctx.lineWidth = 2;
      ctx.strokeRect(origin.x - this.w / 2 - 2, origin.y - this.h - 2, this.w + 4, this.h + 4);
      ctx.fillStyle = "#fbbf24";
      ctx.font = "bold 16px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("★", origin.x, origin.y - this.h - 8);
      ctx.restore();
    }
    ctx.globalAlpha = 1;
    this._drawTelegraph(ctx, camera);
    if (DEBUG_COMBAT) this._drawMuzzleMarker(ctx, camera);
  }

  _drawTelegraph(ctx, camera) {
    if (this.state !== "telegraph" && this.state !== "attack") return;
    const origin = camera.worldToScreen(this.footX, this.footY);
    const dir = this.direction || 1;
    ctx.save();
    ctx.globalAlpha = this.state === "telegraph" ? 0.9 : 0.45;
    ctx.fillStyle = "#f8fafc";
    ctx.beginPath();
    ctx.moveTo(origin.x + dir * 18, origin.y - this.h * 0.55);
    ctx.lineTo(origin.x + dir * 52, origin.y - this.h * 0.62);
    ctx.lineTo(origin.x + dir * 18, origin.y - this.h * 0.69);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(248, 113, 113, 0.55)";
    ctx.fillRect(origin.x - 28, origin.y - 6, 56, 8);
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 2;
    ctx.strokeRect(origin.x - 28, origin.y - 6, 56, 8);
    ctx.fillStyle = "#f8fafc";
    ctx.font = "bold 12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(this.state === "telegraph" ? "!" : "ATK", origin.x, origin.y - this.h - 8);
    ctx.restore();
  }

  _drawMuzzleMarker(ctx, camera) {
    const muzzle = this.muzzleWorld();
    const s = camera.worldToScreen(muzzle.x, muzzle.y);
    ctx.save();
    ctx.fillStyle = "#facc15";
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(s.x, s.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  drawAssetDebug(ctx, camera) {
    const origin = camera.worldToScreen(this.footX, this.footY);
    const box = camera.worldToScreen(this.x, this.y);
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.3)";
    ctx.strokeRect(origin.x - this.anim.frameWidth / 2, origin.y - this.anim.frameHeight, this.anim.frameWidth, this.anim.frameHeight);
    ctx.strokeStyle = "#f97316";
    ctx.strokeRect(box.x, box.y, this.w, this.h);
    const detectR = this.spec.detectionRange || 0;
    const detectScreen = camera.worldToScreen(this.footX + detectR, this.footY);
    ctx.strokeStyle = "rgba(56,189,248,0.45)";
    ctx.beginPath();
    ctx.arc(origin.x, origin.y - this.h * 0.5, Math.abs(detectScreen.x - origin.x), 0, Math.PI * 2);
    ctx.stroke();
    const pref = this.spec.preferredRange || this.spec.attackRange || 0;
    const prefScreen = camera.worldToScreen(this.footX + pref, this.footY);
    ctx.strokeStyle = "rgba(250,204,21,0.55)";
    ctx.beginPath();
    ctx.arc(origin.x, origin.y - this.h * 0.4, Math.abs(prefScreen.x - origin.x), 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#86efac";
    ctx.font = "12px monospace";
    ctx.textAlign = "left";
    ctx.fillText(`${this.state} ${this.spec.name}`, origin.x + 10, origin.y - this.h - 8);
    ctx.fillText(`patrol ${this.patrolMin.toFixed(0)}-${this.patrolMax.toFixed(0)}`, origin.x + 10, origin.y - this.h - 22);
    ctx.restore();
    this._drawMuzzleMarker(ctx, camera);
  }
}
