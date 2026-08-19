import { JUMP_SCALE, MOVE_ACCEL, MOVE_DECEL } from "./config.js";
import { SpriteAnimator } from "./animation.js";
import { aabb, keepInWorld, resolveSolids } from "./collision.js";
import { applyGravity, arcadeAxis } from "./physics.js";
import { makeWeapon } from "./characters.js";
import { SpecialAbility } from "./abilities.js";
import { DEFAULT_BODY } from "./sprite-spec.js";
import { COMBAT } from "./combat.js";
import { drawSheetFrame } from "./asset-catalog.js";
import { WEAPON_SOUND_ID } from "./audio-catalog.js";

export class Player {
  constructor(character, spawn, spriteKit = null) {
    this.character = character;
    const body = { ...DEFAULT_BODY, ...(character.sprite || {}), ...(spriteKit || {}) };
    this.sprite = body;
    this.collisionWidth = body.collisionWidth;
    this.standH = body.collisionHeight;
    this.crouchH = Math.round(body.collisionHeight * 0.62);
    this.collisionOffsetX = body.collisionOffsetX || 0;
    this.collisionOffsetY = body.collisionOffsetY || 0;
    this.w = this.collisionWidth;
    this.h = this.standH;
    this.footX = spawn.x;
    this.footY = spawn.y;
    this._syncBox();
    this.vx = 0;
    this.vy = 0;
    this.facing = 1;
    this.onGround = false;
    this.crouching = false;
    this.health = character.health;
    this.maxHealth = character.health;
    this.keys = 0;
    this.invuln = 0;
    this.alive = true;
    this.deadTimer = 0;
    this.hitFlash = 0;
    this.speedMul = 1;
    this.damageMul = 1;
    this.renderBurst = 0;
    this.weapon = makeWeapon(character);
    this.ability = new SpecialAbility(character.specialAbility);
    this.anim = new SpriteAnimator(spriteKit || character.sprite);
    this.shooting = false;
    this._firedClip = false;
  }

  _standingBox() {
    return {
      x: this.footX - this.w / 2 + this.collisionOffsetX,
      y: this.footY - this.standH + this.collisionOffsetY,
      w: this.w,
      h: this.standH,
    };
  }

  _canStand(world) {
    const box = this._standingBox();
    return !world.solids.some((s) => s.y + 4 < this.footY && aabb(box, s));
  }

  _syncBox() {
    this.x = this.footX - this.w / 2 + this.collisionOffsetX;
    this.y = this.footY - this.h + this.collisionOffsetY;
  }

  _syncFeet() {
    this.footX = this.x + this.w / 2 - this.collisionOffsetX;
    this.footY = this.y + this.h - this.collisionOffsetY;
  }

  origin() {
    return { x: this.footX, y: this.footY };
  }

  /** Dest size / source frame size. Identity (1) when render size matches the strip. */
  renderScale() {
    const fw = this.anim?.frameWidth || this.sprite.frameWidth || 256;
    const fh = this.anim?.frameHeight || this.sprite.frameHeight || 256;
    const rw = this.anim?.renderWidth || this.sprite.renderWidth || fw;
    const rh = this.anim?.renderHeight || this.sprite.renderHeight || fh;
    return { x: rw / fw, y: rh / fh };
  }

  _muzzleOffset() {
    const map = this.character.muzzleByAnim || {};
    const anim = this.anim?.name;
    if (anim && map[anim]) return map[anim];
    if (anim === "crouch_shoot" || anim === "crouch" || this.crouching) {
      return map.crouch_shoot || COMBAT.player.muzzle.crouch;
    }
    return map.shoot || COMBAT.player.muzzle.stand;
  }

  muzzleWorld() {
    const off = this._muzzleOffset();
    const scale = this.renderScale();
    const sx = (off.x || 0) * scale.x;
    const sy = (off.y || 0) * scale.y;
    return {
      x: this.footX + this.facing * sx,
      y: this.footY + sy,
    };
  }

  bounds() {
    return { x: this.x, y: this.y, w: this.w, h: this.h };
  }

  _drawWeapon(ctx, camera, assets) {
    if (!this.alive || !assets) return;
    if (!this.character.renderWeaponOverlay) return;
    const muzzle = this.muzzleWorld();
    const s = camera.worldToScreen(muzzle.x, muzzle.y);
    const size = 72;
    drawSheetFrame(
      ctx,
      assets.sheet("player_weapons"),
      this.weapon.weaponFrame ?? 0,
      s.x - size / 2,
      s.y - size / 2,
      size,
      size,
      this.facing < 0
    );
  }

  update(dt, input, world, projectiles, ctx) {
    if (!this.alive) {
      this.deadTimer += dt;
      this.anim.play("death");
      this.anim.flip = this.facing < 0;
      this.anim.update(dt);
      return;
    }

    if (this.invuln > 0) this.invuln -= dt;
    if (this.hitFlash > 0) this.hitFlash -= dt;
    if (this.renderBurst > 0) this.renderBurst -= dt;
    this.weapon.update(dt);
    this.ability.update(dt, ctx);

    const locked = Boolean(ctx?.inputLocked);
    const wantCrouch = !locked && input.isDown("crouch") && this.onGround;
    if (wantCrouch) this.crouching = true;
    else if (this.crouching && this._canStand(world)) this.crouching = false;
    this.h = this.crouching ? this.crouchH : this.standH;
    this._syncBox();

    let wish = 0;
    if (!locked && input.isDown("moveLeft")) wish -= 1;
    if (!locked && input.isDown("moveRight")) wish += 1;
    if (wish !== 0) this.facing = wish;

    const maxSpeed = this.character.speed * this.speedMul * (this.crouching ? 0.42 : 1);
    arcadeAxis(this, wish, dt, { accel: MOVE_ACCEL, decel: MOVE_DECEL, maxSpeed });

    if (!locked && input.consume("jump") && this.onGround && !this.crouching) {
      this.vy = -this.character.jumpStrength * JUMP_SCALE;
      this.onGround = false;
    }

    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();

    this.shooting = !locked && input.isDown("shoot");
    if (!locked && input.consume("special")) this.ability.activate(ctx);

    const started = this._animState();
    if (started) this._firedClip = false;
    this.anim.flip = this.facing < 0;
    this.anim.update(dt);
    this._trySpawnShot(projectiles, ctx);
  }

  _trySpawnShot(projectiles, ctx) {
    if (!this.alive || this._firedClip) return;
    const clip = this.anim.name;
    if (clip !== "shoot" && clip !== "crouch_shoot") return;
    const release =
      this.character.fireFrameByAnim?.[clip] ?? this.weapon.spawnFrame ?? COMBAT.player.spawnFrame;
    if (this.anim.frame < release) return;
    if (!this.weapon.canFire()) return;
    const muzzle = this.muzzleWorld();
    const shot = this.weapon.tryFire({
      x: muzzle.x,
      y: muzzle.y,
      facing: this.facing,
      damageMul: this.damageMul,
      owner: "player",
    });
    this._firedClip = true;
    if (!shot) return;
    shot.sheet = ctx.assets?.sheet("projectiles") || null;
    ctx.audio.play(WEAPON_SOUND_ID[this.weapon.id] || "editor_shoot", { x: muzzle.x, camera: ctx.camera });
    const fx = this.weapon.muzzleFx || COMBAT.player.muzzleFx;
    ctx.spawnFx?.({
      sheetKey: fx.sheetKey,
      frame: fx.frame,
      x: muzzle.x,
      y: muzzle.y,
      size: fx.size,
      life: fx.life,
      flipX: this.facing < 0,
    });
    projectiles.push(shot);
  }

  _desiredAnim() {
    if (!this.alive) return "death";
    if (this.hitFlash > 0) return "hit";
    if (this.crouching && this.shooting) return "crouch_shoot";
    if (this.shooting) return "shoot";
    if (!this.onGround) return this.vy < 0 ? "jump" : "fall";
    if (this.crouching) return "crouch";
    if (Math.abs(this.vx) > 20) return "run";
    return "idle";
  }

  _animState() {
    const desired = this._desiredAnim();
    const cur = this.anim.name;
    const locked = (cur === "death" && !this.anim.finished) || (cur === "hit" && !this.anim.finished && desired !== "death");
    if (locked) return;
    const restartOnce = (desired === "shoot" || desired === "crouch_shoot") && this.anim.finished;
    const started = this.anim.play(desired, { restart: restartOnce });
    return started || restartOnce;
  }

  takeDamage(amount, opts = {}) {
    if (!this.alive || this.invuln > 0) return 0;
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    const before = this.health;
    this.health = Math.max(0, this.health - amount);
    this.invuln = 0.85;
    this.hitFlash = 0.18;
    this.anim.play("hit", { restart: true });
    if (opts.knockbackX != null && this.health > 0) {
      this.vx = opts.knockbackX;
      this.vy = Math.min(this.vy, -180);
    }
    if (this.health <= 0) {
      this.alive = false;
      this.health = 0;
      this.vx = 0;
      this.anim.play("death", { restart: true });
    }
    return before - this.health;
  }

  heal(amount) {
    if (!this.alive) return 0;
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    const before = this.health;
    this.health = Math.min(this.maxHealth, this.health + amt);
    return this.health - before;
  }

  isHealthFull() {
    return this.health >= this.maxHealth;
  }

  draw(ctx, camera, assets = null) {
    const origin = camera.worldToScreen(this.footX, this.footY);
    const color = this.character.color;
    const initials = this.character.initials;
    if (this.hitFlash > 0) ctx.globalAlpha = 0.7;
    this.anim.draw(ctx, origin.x, origin.y, (g, fw, fh) => {
      g.fillStyle = color;
      g.fillRect(-40, -fh + 86, 80, 162);
      g.fillStyle = "#071018";
      g.font = "18px sans-serif";
      g.textAlign = "center";
      g.fillText(initials, 0, -fh * 0.45);
    });
    ctx.globalAlpha = 1;
    this._drawWeapon(ctx, camera, assets);
    if (this.renderBurst > 0) {
      ctx.save();
      ctx.strokeStyle = "rgba(192,132,252,0.85)";
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y - 90, 90, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  drawAssetDebug(ctx, camera, world) {
    const origin = camera.worldToScreen(this.footX, this.footY);
    const box = camera.worldToScreen(this.x, this.y);
    const rw = this.anim.renderWidth || this.anim.frameWidth;
    const rh = this.anim.renderHeight || this.anim.frameHeight;
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.strokeRect(origin.x - rw / 2, origin.y - rh, rw, rh);
    ctx.strokeStyle = "#22c55e";
    ctx.strokeRect(box.x, box.y, this.w, this.h);
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, 4, 0, Math.PI * 2);
    ctx.fill();
    if (world && world.ground) {
      const g = camera.worldToScreen(camera.x, world.ground.y);
      ctx.strokeStyle = "#facc15";
      ctx.beginPath();
      ctx.moveTo(0, g.y);
      ctx.lineTo(camera.w, g.y);
      ctx.stroke();
    }
    const muzzle = this.muzzleWorld();
    const mz = camera.worldToScreen(muzzle.x, muzzle.y);
    ctx.fillStyle = "#facc15";
    ctx.strokeStyle = "#fb7185";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(mz.x, mz.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#86efac";
    ctx.font = "13px monospace";
    ctx.textAlign = "left";
    const lines = [
      `Animation: ${this.anim.name}`,
      `Frame: ${this.anim.frame + 1} / ${this.anim.frames}`,
      `FPS: ${this.anim.fps}`,
      `Player X ${this.footX.toFixed(1)}  Y ${this.footY.toFixed(1)}`,
    ];
    lines.forEach((line, i) => ctx.fillText(line, origin.x + 12, origin.y - rh - 8 - (lines.length - 1 - i) * 16));
    ctx.restore();
  }
}
