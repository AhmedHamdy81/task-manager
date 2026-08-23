import { BASE_JUMP_VELOCITY, COYOTE_SEC, DEBUG_COMBAT, DEBUG_JUMP, JUMP_BUFFER_SEC, JUMP_CUT_MUL, MOVE_ACCEL, MOVE_DECEL, MOVE_REVERSE, AIR_CONTROL, PLAYER_HIT_FLASH_SEC, PLAYER_INVULN_SEC } from "./config.js";
import { SpriteAnimator } from "./animation.js";
import { aabb, keepInWorld, resolveSolids } from "./collision.js";
import { applyGravity, arcadeAxis } from "./physics.js";
import { SpecialAbility } from "./abilities.js";
import { PLAYER_BODY } from "./sprite-spec.js";
import { COMBAT } from "./combat.js";
import { drawSheetFrame } from "./asset-catalog.js";
import { WEAPON_SOUND_ID } from "./audio-catalog.js";
import { EMPTY_CLICK_SEC, EMPTY_SWAP_SEC, WeaponLoadout, validatePlayerWeapons } from "./player-weapons.js";
import { nextVolleyId } from "./score-manager.js";

export class Player {
  constructor(character, spawn, spriteKit = null) {
    this.character = character;
    this.sprite = { ...(character.sprite || {}), ...(spriteKit || {}) };
    this.collisionWidth = PLAYER_BODY.width;
    this.standH = PLAYER_BODY.height;
    this.crouchH = Math.round(PLAYER_BODY.height * 0.62);
    this.collisionOffsetX = 0;
    this.collisionOffsetY = 0;
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
    const stats = character.stats || {};
    this.stats = stats;
    this.maxHealth = stats.maxHealth || character.health;
    this.health = this.maxHealth;
    this.energyMax = stats.energyMax || character.energyMax || 100;
    this.energy = this.energyMax;
    this.energyRegen = 8 * (stats.energyRegenMultiplier || 1);
    this.defenseMul = stats.defenseMultiplier || 1;
    this.moveSpeed = character.speed;
    this.baseJumpVelocity = BASE_JUMP_VELOCITY;
    this.jumpMultiplier = stats.jumpMultiplier || character.jumpMultiplier || 1;
    this.accelMul = stats.accelMultiplier || 1;
    this.baseAirControl = stats.airControlMultiplier || 1;
    this.airControlMul = this.baseAirControl;
    this.keys = 0;
    this.invuln = 0;
    this.alive = true;
    this.deadTimer = 0;
    this.hitFlash = 0;
    this.speedMul = 1;
    this.damageMul = 1;
    this.renderBurst = 0;
    this.powerFx = null;
    this._powerCancelled = false;
    this.coyote = 0;
    this.jumpBuffer = 0;
    this._jumpRec = null;
    this.lastJumpTest = null;
    this.loadout = new WeaponLoadout(character);
    this.weapon = this.loadout.weapon;
    this._fireCooldownBase = this.weapon.cooldownSec;
    this.notice = null;
    this._gameTime = 0;
    this.ability = new SpecialAbility(character.specialAbility);
    if (DEBUG_COMBAT) validatePlayerWeapons(character, true);
    this.anim = new SpriteAnimator(spriteKit || character.sprite);
    this.shooting = false;
    this._firedClip = false;
    this._wasAirborne = false;
    this.landTimer = 0;
    this._jumpCutPending = false;
    this.mounted = false;
    this.hidden = false;
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

  _requiredPlatformRise(world) {
    let rise = 0;
    for (const s of world?.solids || []) {
      const dy = this.footY - s.y;
      if (dy > 24 && dy < 400) rise = Math.max(rise, dy);
    }
    return rise;
  }

  _beginJumpRecord(world) {
    if (!DEBUG_JUMP) return;
    this._jumpRec = {
      character: this.character.id,
      startFootY: this.footY,
      highestFootY: this.footY,
      requiredPlatformHeight: this._requiredPlatformRise(world),
    };
  }

  _updateJumpRecord() {
    if (!this._jumpRec) return;
    if (this.footY < this._jumpRec.highestFootY) this._jumpRec.highestFootY = this.footY;
  }

  _finishJumpRecord() {
    if (!this._jumpRec) return;
    const rec = this._jumpRec;
    rec.jumpHeight = rec.startFootY - rec.highestFootY;
    rec.pass = rec.jumpHeight + 1 >= rec.requiredPlatformHeight;
    this.lastJumpTest = rec;
    this._jumpRec = null;
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
      return map.crouch_shoot || map.crouchShoot || COMBAT.player.muzzle.crouch;
    }
    if (anim === "run") return map.run || map.shoot || COMBAT.player.muzzle.stand;
    if (anim === "jump" || anim === "fall") return map.jump || map.shoot || COMBAT.player.muzzle.stand;
    if (anim === "idle") return map.idle || map.shoot || COMBAT.player.muzzle.stand;
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

  _syncWeaponRef() {
    this.weapon = this.loadout.weapon;
  }

  setNotice(text, life = 1.6) {
    this.notice = { text, life };
  }

  equipWeapon(id) {
    const ok = this.loadout.equip(id);
    this._syncWeaponRef();
    return ok;
  }

  _drawWeapon(ctx, camera, assets) {
    if (!this.alive || !assets) return;
    const showOverlay = this.character.renderWeaponOverlay || this.loadout?.currentId !== "pistol";
    if (!showOverlay) return;
    const muzzle = this.muzzleWorld();
    const s = camera.worldToScreen(muzzle.x, muzzle.y);
    const size = 72;
    drawSheetFrame(
      ctx,
      assets.sheet("player_weapons"),
      this.weapon.weaponFrame ?? this.loadout?.def()?.weaponFrame ?? 0,
      s.x - size / 2,
      s.y - size / 2,
      size,
      size,
      this.facing < 0
    );
  }

  _drawMuzzleMarker(ctx, camera) {
    const muzzle = this.muzzleWorld();
    const mz = camera.worldToScreen(muzzle.x, muzzle.y);
    ctx.save();
    ctx.fillStyle = "#facc15";
    ctx.strokeStyle = "#fb7185";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(mz.x, mz.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  update(dt, input, world, projectiles, ctx) {
    if (!this.alive) {
      if (!this._powerCancelled) {
        this.ability.cancel(ctx);
        this._powerCancelled = true;
      }
      this.deadTimer += dt;
      this.anim.play("death");
      this.anim.flip = this.facing < 0;
      this.anim.update(dt);
      return;
    }

    if (this.invuln > 0) this.invuln -= dt;
    if (this.hitFlash > 0) this.hitFlash -= dt;
    if (this.renderBurst > 0) this.renderBurst -= dt;
    this._gameTime += dt;
    if (this.notice) {
      this.notice.life -= dt;
      if (this.notice.life <= 0) this.notice = null;
    }
    this.energy = Math.min(this.energyMax, this.energy + this.energyRegen * dt);
    this.weapon.update(dt);
    this.ability.update(dt, ctx);
    this._updateEmptyWeapon(dt, ctx);

    if (this.mounted) {
      this.vx = 0;
      this.vy = 0;
      this.shooting = false;
      this.jumpBuffer = 0;
      this.anim.play("idle");
      this.anim.flip = this.facing < 0;
      this.anim.update(dt);
      return;
    }

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

    const maxSpeed = this.moveSpeed * this.speedMul * (this.crouching ? 0.42 : 1);
    const accelMul = this.accelMul || 1;
    const airFrac = this.onGround
      ? 1
      : Math.max(0.7, Math.min(0.85, AIR_CONTROL * (this.airControlMul || 1)));
    arcadeAxis(this, wish, dt, {
      accel: MOVE_ACCEL * accelMul * airFrac,
      decel: this.onGround ? MOVE_DECEL : MOVE_DECEL * 0.55,
      reverse: MOVE_REVERSE * accelMul * airFrac,
      maxSpeed,
    });

    if (!locked && input.consume("jump")) this.jumpBuffer = JUMP_BUFFER_SEC;
    else this.jumpBuffer = Math.max(0, this.jumpBuffer - dt);

    if (this.onGround) this.coyote = COYOTE_SEC;
    else this.coyote = Math.max(0, this.coyote - dt);

    if (!locked && this.jumpBuffer > 0 && this.coyote > 0) {
      if (this.crouching && this._canStand(world)) {
        this.crouching = false;
        this.h = this.standH;
        this._syncBox();
      }
      if (!this.crouching) {
        this.vy = -this.baseJumpVelocity * this.jumpMultiplier;
        this.onGround = false;
        this.coyote = 0;
        this.jumpBuffer = 0;
        this._jumpCutPending = true;
        this._beginJumpRecord(world);
        ctx?.audio?.playSound?.("player_jump");
      }
    }

    if (this._jumpCutPending && !this.onGround && this.vy < 0 && (locked || !input.isDown("jump"))) {
      this.vy *= JUMP_CUT_MUL;
      this._jumpCutPending = false;
    }
    if (this.onGround) this._jumpCutPending = false;

    const wasAirborne = this._wasAirborne;
    applyGravity(this, dt);
    resolveSolids(this, world.solids, dt);
    keepInWorld(this, world);
    this._syncFeet();
    this._updateJumpRecord();
    if (wasAirborne && this.onGround) {
      this._finishJumpRecord();
      this.landTimer = 0.14;
      ctx?.audio?.playSound?.("player_land");
      ctx?.spawnFx?.({
        sheetKey: "effects",
        frame: 0,
        x: this.footX,
        y: this.footY - 8,
        size: 48,
        life: 0.18,
        kind: "dust",
      });
    }
    if (this.landTimer > 0) this.landTimer = Math.max(0, this.landTimer - dt);
    this._wasAirborne = !this.onGround;

    if (!locked) this._handleWeaponSwitch(input, ctx);
    this.shooting = !locked && input.isDown("shoot");
    if (!locked && input.consume("special")) {
      const result = this.ability.activate(ctx);
      if (result && !result.ok) ctx?.onAbilityFailed?.(result);
    }

    const started = this._animState();
    if (started) this._firedClip = false;
    this.anim.flip = this.facing < 0;
    if (this.anim.name === "run") {
      const t = Math.min(1.25, Math.max(0.7, Math.abs(this.vx) / Math.max(40, this.moveSpeed)));
      this.anim.fps = 14 * t;
    }
    this.anim.update(dt);
    if (this.shooting) this._trySpawnShot(projectiles, ctx);
  }

  _handleWeaponSwitch(input, ctx) {
    const before = this.loadout.currentId;
    if (input.consume("weapon1")) this.equipWeapon("pistol");
    else if (input.consume("weapon2")) this.equipWeapon("machine_gun");
    else if (input.consume("weapon3")) this.equipWeapon("shotgun");
    else if (input.consume("weapon4")) this.equipWeapon("heavy_blaster");
    else if (input.consume("weaponCycle")) this.loadout.cycle();
    this._syncWeaponRef();
    if (this.loadout.currentId !== before) {
      this.setNotice(this.loadout.def().displayName.toUpperCase(), 1.1);
      ctx?.hud?.invalidate?.();
    }
  }

  _updateEmptyWeapon(dt, ctx) {
    if (this.loadout.currentId === "pistol" || this.weapon.ammo !== 0) {
      this.loadout._emptyTimer = 0;
      return;
    }
    this.loadout._emptyTimer += dt;
    if (this.notice?.text !== "EMPTY") this.setNotice("EMPTY", 0.9);
    if (this.loadout._emptyTimer >= EMPTY_SWAP_SEC) {
      this.equipWeapon("pistol");
      this.setNotice("PISTOL", 1.1);
      ctx?.hud?.invalidate?.();
    }
  }

  _playEmptyClick(ctx, muzzle) {
    if (this._gameTime - this.loadout._emptyClickAt < EMPTY_CLICK_SEC) return;
    this.loadout._emptyClickAt = this._gameTime;
    this.setNotice("EMPTY", 0.8);
    ctx?.audio?.playSound?.("weapon_empty", { x: muzzle.x, camera: ctx.camera });
  }

  _trySpawnShot(projectiles, ctx) {
    if (!this.alive) return;
    const muzzle = this.muzzleWorld();
    const attack = this.loadout.tryAttack({
      x: muzzle.x,
      y: muzzle.y,
      facing: this.facing,
      damageMul: this.damageMul,
    });
    this._syncWeaponRef();
    if (attack.empty) {
      if (this.shooting) this._playEmptyClick(ctx, muzzle);
      return;
    }
    if (!attack.fired) return;
    const volleyId = nextVolleyId();
    ctx.scoreboard?.noteAttackFired(volleyId);
    const def = attack.weapon;
    const sheet = ctx.assets?.sheet(def.projectileAsset || "projectiles") || ctx.assets?.sheet("projectiles") || null;
    const sfx = WEAPON_SOUND_ID[def.id] || def.shotSfx || "player_shoot";
    ctx.audio.playSound?.(sfx, { x: muzzle.x, camera: ctx.camera });
    const fx = this.weapon.muzzleFx || def.muzzleFlash || COMBAT.player.muzzleFx;
    ctx.spawnFx?.({
      sheetKey: fx.sheetKey,
      frame: fx.frame,
      x: muzzle.x,
      y: muzzle.y,
      size: fx.size,
      life: fx.life,
      flipX: this.facing < 0,
      kind: "muzzle",
    });
    if (def.id === "shotgun" && !ctx.settings?.reducedFlashes) {
      ctx.spawnFx?.({
        sheetKey: "effects",
        frame: 5,
        x: muzzle.x + this.facing * 18,
        y: muzzle.y,
        size: 72,
        life: 0.14,
        flipX: this.facing < 0,
        kind: "extra",
      });
    }
    if (def.id === "heavy_blaster") {
      ctx.spawnFx?.({
        sheetKey: "effects",
        frame: 7,
        x: muzzle.x,
        y: muzzle.y,
        size: 56,
        life: 0.12,
        kind: "extra",
      });
    }
    if (def.casing) {
      ctx.spawnFx?.({
        sheetKey: "effects",
        frame: 6,
        x: muzzle.x - this.facing * 10,
        y: muzzle.y + 6,
        size: 22,
        life: 0.16,
      });
    }
    if (def.recoil) this.vx -= this.facing * def.recoil;
    if (def.cameraShake) ctx.beginShake?.(def.cameraShake);
    for (const shot of attack.shots) {
      shot.sheet = sheet;
      shot.owner = "player";
      shot.faction = "player";
      shot.volleyId = volleyId;
      projectiles.push(shot);
    }
    ctx?.hud?.invalidate?.();
  }

  _desiredAnim() {
    if (!this.alive) return "death";
    if (this.hitFlash > 0) return "hit";
    const powerId = this.ability?.id || "";
    if (this.ability?.active > 0 && powerId !== "timeline_freeze" && powerId !== "production_rush") {
      return "special";
    }
    if (this.crouching && this.shooting) return "crouch_shoot";
    if (this.shooting && this.onGround && !this.crouching && Math.abs(this.vx) > 40) return "run_shoot";
    if (this.shooting) return "shoot";
    if (!this.onGround) return this.vy < 0 ? "jump" : "fall";
    if (this.crouching) return "crouch";
    if (this.landTimer > 0 && Math.abs(this.vx) < 40) return "land";
    if (Math.abs(this.vx) > 20) return "run";
    return "idle";
  }

  _animState() {
    const desired = this._desiredAnim();
    const cur = this.anim.name;
    const locked =
      (cur === "death" && !this.anim.finished) ||
      (cur === "hit" && !this.anim.finished && desired !== "death");
    if (locked) return;
    const restartOnce = (desired === "shoot" || desired === "crouch_shoot") && this.anim.finished;
    const started = this.anim.play(desired, { restart: restartOnce });
    return started || restartOnce;
  }

  takeDamage(amount, opts = {}) {
    if (this.mounted) return 0;
    if (!this.alive || this.invuln > 0) return 0;
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt <= 0) return 0;
    const before = this.health;
    const reduced = amt / Math.max(0.05, this.defenseMul || 1);
    let amtTaken = Math.max(1, Math.round(reduced));
    if (this.rescueBuff?.remain > 0) {
      amtTaken = Math.max(1, Math.round(amtTaken * (this.rescueBuff.defenseMul || 0.75)));
    }
    this.health = Math.max(0, this.health - amtTaken);
    this.invuln = this.host?.playerInvulnSec?.() ?? PLAYER_INVULN_SEC;
    this.hitFlash = PLAYER_HIT_FLASH_SEC;
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
    if (amtTaken > 0) {
      this.host?.scoreboard?.noteDamageTaken(amtTaken, {
        encounterId: (this.host.world?.encounters || []).find((e) => e.scripted && e.locked && !e.cleared)?.id || "",
      });
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
    if (this.hidden) return;
    const origin = camera.worldToScreen(this.footX, this.footY);
    ctx.save();
    ctx.fillStyle = "rgba(8, 12, 20, 0.45)";
    ctx.beginPath();
    ctx.ellipse(origin.x, origin.y - 4, 34, 8, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
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
    this._drawPowerFx(ctx, origin);
    if (DEBUG_COMBAT) this._drawMuzzleMarker(ctx, camera);
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

  spendEnergy(amount) {
    const n = Math.max(0, Number(amount) || 0);
    this.energy = Math.max(0, this.energy - n);
  }

  addEnergy(amount) {
    const n = Number(amount);
    if (!Number.isFinite(n) || n <= 0) return 0;
    const before = this.energy;
    this.energy = Math.min(this.energyMax, this.energy + n);
    return this.energy - before;
  }

  isEnergyFull() {
    return this.energy >= this.energyMax;
  }

  _drawPowerFx(ctx, origin) {
    const fx = this.powerFx;
    if (!fx) return;
    const chestY = origin.y - (this.h || this.standH) * 0.55;
    if (fx.kind === "blast") {
      const t = Math.min(1, fx.age / Math.max(0.05, fx.life || 0.45));
      const r = (fx.radius || 260) * (0.2 + 0.8 * t);
      ctx.save();
      ctx.strokeStyle = `rgba(251, 113, 133, ${1 - t})`;
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.arc(origin.x, chestY, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = `rgba(251, 113, 133, ${0.18 * (1 - t)})`;
      ctx.fill();
      ctx.restore();
      return;
    }
    if (fx.kind === "storm") {
      ctx.save();
      ctx.strokeStyle = "rgba(192, 132, 252, 0.55)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(origin.x, chestY, fx.radius || 210, 0, Math.PI * 2);
      ctx.stroke();
      for (const part of fx.particles || []) {
        const x = origin.x + Math.cos(part.a) * part.r;
        const y = chestY + Math.sin(part.a) * part.r * 0.55;
        ctx.fillStyle = "rgba(216, 180, 254, 0.9)";
        ctx.fillRect(x - 2, y - 2, 4, 4);
      }
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
    const rec = this.lastJumpTest;
    const lines = [
      `state ${this._desiredAnim()}  anim ${this.anim.name}`,
      `vel ${this.vx.toFixed(0)},${this.vy.toFixed(0)}`,
      `jump ${rec ? rec.jumpHeight.toFixed(0) : "—"}  coy ${this.coyote.toFixed(2)}`,
      `cool ${this.weapon.cool.toFixed(2)}  ammo ${this.weapon.ammo}`,
      `body ${this.w}x${this.h}  feet ${this.footX.toFixed(0)},${this.footY.toFixed(0)}`,
    ];
    lines.forEach((line, i) => ctx.fillText(line, origin.x + 12, origin.y - rh - 8 - (lines.length - 1 - i) * 16));
    ctx.restore();
  }
}
