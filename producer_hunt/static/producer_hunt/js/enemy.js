import { SpriteAnimator } from "./animation.js";
import { keepInWorld, lineBlocked, resolveSolids } from "./collision.js";
import { applyGravity } from "./physics.js";
import { makeEnemySpriteConfig } from "./sprite-spec.js";
import { COMBAT, enemyWeaponDef } from "./combat.js";
import { Weapon } from "./weapon.js";

const STATE_TO_ANIM = {
  idle: "idle",
  patrol: "walk",
  alert: "idle",
  chase: "walk",
  attack: "attack",
  hit: "hit",
  death: "death",
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
  return ENEMY_TYPES[id] || ENEMY_TYPES[DEFAULT_ENEMY_ID];
}

export const ENEMY_TYPES = {
  post_producer: {
    id: "post_producer",
    type: "post_producer",
    name: "Post Producer",
    initials: "PP",
    health: 50,
    speed: 150,
    chaseSpeed: 210,
    damage: 10,
    scoreValue: 100,
    detectionRange: 520,
    attackRange: COMBAT.enemy.attackRange,
    color: "#c084fc",
    accent: "#6b21a8",
    sprite: makeEnemySpriteConfig("post_producer"),
    impactSheet: "post_producer_impact",
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
    this.w = body.collisionWidth || 88;
    this.h = body.collisionHeight || 170;
    this.footX = spawn.x;
    this.footY = spawn.y;
    this._syncBox();
    this.vx = spec.speed;
    this.vy = 0;
    this.direction = 1;
    this.onGround = false;
    this.health = spec.health;
    this.alive = true;
    this.state = "patrol";
    this.hitFlash = 0;
    this.frozen = 0;
    this.deadTimer = 0;
    this.attackCool = 0;
    this.alertTimer = 0;
    this._firedClip = false;
    this.patrolMin = spawn.patrolMin ?? spawn.x - 120;
    this.patrolMax = spawn.patrolMax ?? spawn.x + 120;
    this.anim = new SpriteAnimator(spriteKit || spec.sprite);
    this.weapon = new Weapon(enemyWeaponDef(spec.id));
    this.activated = Boolean(spawn.activated);
    this.activateRange = spawn.activateRange || 640;
    this.spawnId = spawn.id || spec.id;
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
    return { x: this.x, y: this.y, w: this.w, h: this.h };
  }

  freeze(seconds) {
    this.frozen = Math.max(this.frozen, seconds);
  }

  muzzleWorld() {
    const off = COMBAT.enemy.muzzle;
    return {
      x: this.footX + this.direction * off.x,
      y: this.footY + off.y,
    };
  }

  update(dt, player, world, projectiles = null, game = null) {
    if (!this.alive) {
      this.deadTimer += dt;
      this.state = "death";
      this.anim.play("death");
      this.anim.flip = this.direction < 0;
      this.anim.update(dt);
      return;
    }
    if (this.hitFlash > 0) this.hitFlash -= dt;
    this.weapon.update(dt);
    this.attackCool = this.weapon.cool;
    if (this.frozen > 0) {
      this.frozen -= dt;
      this.vx = 0;
      this.state = "idle";
      applyGravity(this, dt);
      resolveSolids(this, world.solids, dt);
      keepInWorld(this, world);
      this._syncFeet();
      this._playAnim();
      this.anim.update(dt);
      return;
    }

    if (!this.activated) {
      const near =
        !this.encounterBound &&
        player.alive &&
        Math.abs(player.footX - this.footX) <= this.activateRange &&
        Math.abs(player.footY - this.footY) < 280;
      if (near) this.activated = true;
      else {
        this.vx = 0;
        this.state = "idle";
        applyGravity(this, dt);
        resolveSolids(this, world.solids, dt);
        keepInWorld(this, world);
        this._syncFeet();
        this._playAnim();
        this.anim.update(dt);
        return;
      }
    }

    const dx = player.footX - this.footX;
    const closeY = Math.abs(player.footY - this.footY) < 160;
    const distX = Math.abs(dx);
    const detected = player.alive && closeY && distX < this.spec.detectionRange;

    const releasingAttack = this.anim.name === "attack" && !this.anim.finished;
    if (this.hitFlash > 0) this.state = "hit";
    else if (detected && distX <= this.spec.attackRange && (this.weapon.cool <= 0 || releasingAttack)) {
      this.state = "attack";
    } else if (detected && this.alertTimer > 0.15) this.state = "chase";
    else if (detected) {
      this.state = "alert";
      this.alertTimer += dt;
    } else {
      this.state = "patrol";
      this.alertTimer = 0;
    }

    if (this.state === "patrol") {
      if (this.footX < this.patrolMin) this.direction = 1;
      if (this.footX > this.patrolMax) this.direction = -1;
      this.vx = this.direction * this.spec.speed;
    } else if (this.state === "alert") {
      this.vx = 0;
      this.direction = dx >= 0 ? 1 : -1;
    } else if (this.state === "chase") {
      this.direction = dx >= 0 ? 1 : -1;
      this.vx = this.direction * this.spec.chaseSpeed;
    } else if (this.state === "attack") {
      this.direction = dx >= 0 ? 1 : -1;
      this.vx = 0;
    } else if (this.state === "hit") {
      this.vx = 0;
    }

    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();
    const started = this._playAnim();
    if (started) this._firedClip = false;
    this.anim.flip = this.direction < 0;
    this.anim.update(dt);
    if (projectiles && game) this._trySpawnShot(player, world, projectiles, game);
  }

  _playAnim() {
    const desired = STATE_TO_ANIM[this.state] || "idle";
    const cur = this.anim.name;
    if (cur === "death") return false;
    if (cur === "hit" && !this.anim.finished && desired !== "death") return false;
    if (cur === "attack" && this.anim.finished && desired === "attack") {
      if (this.weapon.cool > 0) return this.anim.play("idle");
      return this.anim.play("attack", { restart: true });
    }
    return this.anim.play(desired);
  }

  takeDamage(amount) {
    if (!this.alive) return 0;
    this.health -= amount;
    this.hitFlash = 0.16;
    this.state = "hit";
    this.anim.play("hit", { restart: true });
    if (this.health <= 0) {
      this.alive = false;
      this.vx = 0;
      this.state = "death";
      this.anim.play("death", { restart: true });
      return this.spec.scoreValue;
    }
    return 0;
  }

  _trySpawnShot(player, world, projectiles, game) {
    if (!this.alive || !player.alive) return;
    if (this.anim.name !== "attack" || this._firedClip) return;
    if (this.anim.frame < (this.weapon.spawnFrame ?? COMBAT.enemy.spawnFrame)) return;
    if (!this.weapon.canFire()) return;
    const muzzle = this.muzzleWorld();
    const aimX = player.footX;
    const aimY = player.footY - 90;
    if (lineBlocked(muzzle.x, muzzle.y, aimX, aimY, world.solids)) {
      this._firedClip = true;
      return;
    }
    const shot = this.weapon.tryFire({
      x: muzzle.x,
      y: muzzle.y,
      facing: this.direction,
      owner: "enemy",
    });
    this._firedClip = true;
    if (!shot) return;
    shot.sheet = game.assets?.sheet("projectiles") || null;
    projectiles.push(shot);
  }

  draw(ctx, camera) {
    if (!this.alive && this.anim.finished && this.deadTimer > 0.05) return;
    const origin = camera.worldToScreen(this.footX, this.footY);
    const color = this.spec.color;
    ctx.globalAlpha = this.alive ? 1 : 0.55;
    this.anim.draw(ctx, origin.x, origin.y, (g, fw, fh) => {
      g.fillStyle = color;
      g.fillRect(-44, -fh + 86, 88, 162);
      g.fillStyle = "#1c1408";
      g.font = "11px sans-serif";
      g.textAlign = "center";
      g.fillText(this.spec.initials || "PP", 0, -fh * 0.42);
    });
    ctx.globalAlpha = 1;
  }

  drawAssetDebug(ctx, camera) {
    const origin = camera.worldToScreen(this.footX, this.footY);
    const box = camera.worldToScreen(this.x, this.y);
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.3)";
    ctx.strokeRect(origin.x - this.anim.frameWidth / 2, origin.y - this.anim.frameHeight, this.anim.frameWidth, this.anim.frameHeight);
    ctx.strokeStyle = "#f97316";
    ctx.strokeRect(box.x, box.y, this.w, this.h);
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}
