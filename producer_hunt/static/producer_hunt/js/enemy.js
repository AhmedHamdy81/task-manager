import { SpriteAnimator } from "./animation.js";
import { aabb, keepInWorld, resolveSolids } from "./collision.js";
import { applyGravity } from "./physics.js";
import { makeEnemySpriteConfig } from "./sprite-spec.js";

const STATE_TO_ANIM = {
  idle: "idle",
  patrol: "walk",
  alert: "idle",
  chase: "run",
  attack: "attack",
  hit: "hit",
  death: "death",
};

export const ENEMY_TYPES = {
  assistant_producer: {
    id: "assistant_producer",
    type: "assistant_producer",
    name: "ASSISTANT PRODUCER",
    health: 50,
    speed: 150,
    chaseSpeed: 210,
    damage: 10,
    scoreValue: 100,
    detectionRange: 340,
    attackRange: 58,
    color: "#f59e0b",
    accent: "#78350f",
    sprite: makeEnemySpriteConfig("assistant_producer"),
  },
};

export class Enemy {
  constructor(typeId, spawn, spriteKit = null) {
    const spec = ENEMY_TYPES[typeId] || ENEMY_TYPES.assistant_producer;
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
    this.patrolMin = spawn.patrolMin ?? spawn.x - 120;
    this.patrolMax = spawn.patrolMax ?? spawn.x + 120;
    this.anim = new SpriteAnimator(spriteKit || spec.sprite);
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

  update(dt, player, world) {
    if (!this.alive) {
      this.deadTimer += dt;
      this.state = "death";
      this.anim.play("death");
      this.anim.flip = this.direction < 0;
      this.anim.update(dt);
      return;
    }
    if (this.hitFlash > 0) this.hitFlash -= dt;
    if (this.attackCool > 0) this.attackCool -= dt;
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

    const dx = player.footX - this.footX;
    const closeY = Math.abs(player.footY - this.footY) < 160;
    const distX = Math.abs(dx);
    const detected = player.alive && closeY && distX < this.spec.detectionRange;

    if (this.hitFlash > 0) this.state = "hit";
    else if (detected && distX <= this.spec.attackRange) this.state = "attack";
    else if (detected && this.alertTimer > 0.15) this.state = "chase";
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
    } else if (this.state === "chase" || this.state === "attack") {
      this.direction = dx >= 0 ? 1 : -1;
      this.vx = this.direction * this.spec.chaseSpeed;
    } else if (this.state === "hit") {
      this.vx = 0;
    }

    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();
    this._playAnim();
    this.anim.flip = this.direction < 0;
    this.anim.update(dt);
  }

  _playAnim() {
    const desired = STATE_TO_ANIM[this.state] || "idle";
    const cur = this.anim.name;
    if (cur === "death") return;
    if (cur === "hit" && !this.anim.finished && desired !== "death") return;
    this.anim.play(desired);
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

  tryAttack(player) {
    if (!this.alive || this.state !== "attack" || this.attackCool > 0) return false;
    if (!player.alive || !aabb(this.bounds(), player.bounds())) return false;
    this.attackCool = 0.7;
    player.takeDamage(this.spec.damage);
    return true;
  }

  draw(ctx, camera) {
    if (!this.alive && this.deadTimer > 0.5) return;
    const origin = camera.worldToScreen(this.footX, this.footY);
    const color = this.spec.color;
    ctx.globalAlpha = this.alive ? 1 : 0.35;
    this.anim.draw(ctx, origin.x, origin.y, (g, fw, fh) => {
      g.fillStyle = color;
      g.fillRect(-44, -fh + 86, 88, 162);
      g.fillStyle = "#1c1408";
      g.font = "11px sans-serif";
      g.textAlign = "center";
      g.fillText("AP", 0, -fh * 0.42);
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
