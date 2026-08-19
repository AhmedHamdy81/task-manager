import { DEBUG_ASSETS, DESIGN_H, DESIGN_W } from "./config.js";
import { GameState, GameStateManager } from "./game-state.js";
import { Input } from "./input.js";
import { Camera } from "./camera.js";
import { Player } from "./player.js";
import { ENEMY_TYPES, Enemy } from "./enemy.js";
import { HUD } from "./hud.js";
import { CharacterSelect } from "./character-select.js";
import { aabb, hitsSolid } from "./collision.js";
import { STUDIO_01, buildWorld, LevelDataError } from "./levels/level-01.js";
import { AssetLoader } from "./asset-loader.js";
import { WORLD_SHEETS, drawCoverImage, drawSheetFrame } from "./asset-catalog.js";
import { COMBAT } from "./combat.js";
import { AudioManager } from "./audio.js";
import { drawButtons, drawMenu, hitMenu, menuButtons } from "./ui.js";
import { CHARACTERS, characterById } from "./characters.js";
import { applyPickup, PICKUP_COLLECT_FX } from "./pickups.js";
import {
  canCompleteLevel,
  currentObjective,
  doorRequirementsMet,
  findSafeSpawn,
  syncDoorSolids,
  tryOpenDoor,
  updateDoors,
} from "./progression.js";
import { saveSettings } from "./settings.js";
import { FxSprite } from "./fx.js";
import {
  drawDecorSheet,
  drawHazards,
  drawHints,
  drawPickups,
  drawProgression,
  drawStudioParallax,
  drawTiledPlatforms,
} from "./world-render.js";

export class Game {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.exitUrl = options.exitUrl || "/";
    this.debug = Boolean(options.debug) || DEBUG_ASSETS;
    this.assets = new AssetLoader(options.assetBase || "", { cacheKey: options.cacheKey || "" });
    this.audio = new AudioManager();
    this.input = new Input();
    this.camera = new Camera();
    this.hud = new HUD();
    this.select = new CharacterSelect();
    this.state = new GameStateManager(GameState.BOOT);
    this.player = null;
    this.character = null;
    this.world = null;
    this.enemies = [];
    this.projectiles = [];
    this.effects = [];
    this.score = 0;
    this.checkpoint = null;
    this.fade = 0;
    this.inputLocked = false;
    this.completed = false;
    this.levelError = "";
    this._respawnTimer = 0;
    this.spawn = { x: 180, y: 980 };
    this.lastTime = 0;
    this.running = false;
    this.fps = 0;
    this._frames = 0;
    this._fpsT = 0;
    this.showControls = false;
    this._loop = (t) => this.frame(t);
    this._onResize = () => this.fitCanvas();
    this._onClick = (e) => this.onClick(e);
  }

  async start() {
    this.input.attach();
    window.addEventListener("resize", this._onResize);
    this.canvas.addEventListener("click", this._onClick);
    this.fitCanvas();
    await this.preload();
    this.state.set(GameState.START_SCREEN);
    this.running = true;
    requestAnimationFrame(this._loop);
  }

  async preload() {
    try {
      await Promise.all(CHARACTERS.map((ch) => this.assets.loadCharacterKit(ch.sprite)));
      await this.assets.loadEnemyKit(ENEMY_TYPES.post_producer.sprite);
      await this.assets.loadCatalog(WORLD_SHEETS);
    } catch (err) {
      console.error("[Producer Hunt Asset Error]\n\nPreload failed. Continuing with placeholders.", err);
    }
  }

  stop() {
    this.running = false;
    this.input.detach();
    window.removeEventListener("resize", this._onResize);
    this.canvas.removeEventListener("click", this._onClick);
  }

  fitCanvas() {
    const scale = Math.min(window.innerWidth / DESIGN_W, window.innerHeight / DESIGN_H);
    this.canvas.style.width = `${Math.floor(DESIGN_W * scale)}px`;
    this.canvas.style.height = `${Math.floor(DESIGN_H * scale)}px`;
    this.canvas.width = DESIGN_W;
    this.canvas.height = DESIGN_H;
  }

  canvasPoint(e) {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * DESIGN_W,
      y: ((e.clientY - rect.top) / rect.height) * DESIGN_H,
    };
  }

  startButtons() {
    return menuButtons(["START GAME", "CONTROLS", "EXIT"], 560);
  }

  pauseButtons() {
    return menuButtons(["RESUME", "RESTART LEVEL", "CHARACTER SELECT", "EXIT GAME"], 360);
  }

  overButtons() {
    return menuButtons(["RESTART LEVEL", "SELECT CHARACTER", "EXIT GAME"], 400);
  }

  completeButtons() {
    return menuButtons(["RESTART", "CHARACTER SELECT", "EXIT GAME"], 430);
  }

  onClick(e) {
    const p = this.canvasPoint(e);
    const st = this.state.get();
    if (st === GameState.START_SCREEN) {
      const hit = hitMenu(this.startButtons(), p.x, p.y);
      if (!hit) return;
      if (hit.id === "START GAME") this.state.set(GameState.CHARACTER_SELECT);
      if (hit.id === "CONTROLS") this.showControls = !this.showControls;
      if (hit.id === "EXIT") this.exit();
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      const act = this.select.handleClick(p.x, p.y);
      if (act === "confirm") this.confirmCharacter();
      if (act === "back") this.state.set(GameState.START_SCREEN);
      return;
    }
    if (st === GameState.PAUSED) this.handleMenu(hitMenu(this.pauseButtons(), p.x, p.y));
    if (st === GameState.GAME_OVER) this.handleMenu(hitMenu(this.overButtons(), p.x, p.y));
    if (st === GameState.LEVEL_COMPLETE) this.handleMenu(hitMenu(this.completeButtons(), p.x, p.y));
  }

  handleMenu(hit) {
    if (!hit) return;
    if (hit.id === "RESUME") this.state.set(GameState.PLAYING);
    if (hit.id === "RESTART LEVEL" || hit.id === "RESTART") this.restartLevel();
    if (hit.id === "CHARACTER SELECT" || hit.id === "SELECT CHARACTER") {
      this.state.set(GameState.CHARACTER_SELECT);
    }
    if (hit.id === "EXIT GAME" || hit.id === "EXIT") this.exit();
  }

  exit() {
    window.location.href = this.exitUrl;
  }

  confirmCharacter() {
    this.select.persist();
    this.beginLevel(this.select.selected);
  }

  beginLevel(character, opts = {}) {
    this.character = characterById(character?.id || character);
    try {
      this.world = buildWorld(STUDIO_01);
    } catch (err) {
      const msg = err instanceof LevelDataError ? err.message : `[Producer Hunt] Level failed to start.\n${err}`;
      console.error(msg);
      this.levelError = msg;
      this.world = null;
      this.player = null;
      this.state.set(GameState.START_SCREEN);
      return;
    }
    this.levelError = "";
    this.spawn = { ...this.world.spawn };
    const kit = this.assets.characterKit(this.character.id);
    this.player = new Player(this.character, this.spawn, kit);
    this.checkpoint = opts.checkpoint || null;
    this.spawnEnemies();
    this.projectiles = [];
    this.effects = [];
    this.score = 0;
    this.camera.x = 0;
    this.camera.look = 0;
    this.fade = 0;
    this.inputLocked = false;
    this.completed = false;
    this._respawnTimer = 0;
    if (this.checkpoint) {
      this.applySnapshot(this.checkpoint);
    } else {
      const start = this.world.checkpoints.find((c) => c.isStart) || this.world.checkpoints[0];
      if (start) this.captureCheckpoint(start, { silent: true });
    }
    this.hud.invalidate();
    this.camera.snap(this.player.footX - this.camera.w * 0.38, this.player.footY - this.camera.h * 0.7, this.world);
    this.state.set(GameState.PLAYING);
  }

  restartLevel() {
    if (!this.character) return;
    this.beginLevel(this.character);
  }

  captureCheckpoint(cp = null, opts = {}) {
    if (!this.player || !this.world) return;
    const safe = findSafeSpawn(
      this.world,
      cp?.spawnX ?? this.player.footX,
      cp?.spawnY ?? this.player.footY,
      this.enemies.filter((e) => e.alive).map((e) => e.bounds())
    );
    this.checkpoint = {
      checkpointId: cp?.id || this.checkpoint?.checkpointId || "start",
      levelId: this.world.id,
      characterId: this.character.id,
      x: safe.x,
      y: safe.y,
      health: Math.max(1, this.player.health),
      ammo: this.player.weapon.ammo,
      score: this.score,
      keys: this.player.keys,
      pickups: Object.fromEntries(this.world.pickups.map((p) => [p.id, p.taken])),
      doors: Object.fromEntries((this.world.doors || []).map((d) => [d.id, d.state])),
      checkpoints: Object.fromEntries((this.world.checkpoints || []).map((c) => [c.id, c.activated])),
      defeated: (this.enemies || []).filter((e) => !e.alive && e.persistent).map((e) => e.spawnId),
    };
    this.spawn = { x: safe.x, y: safe.y };
    if (!opts.silent) {
      this.audio.play("ui", "checkpoint");
      this.hud.invalidate();
    }
  }

  applySnapshot(snap) {
    if (!snap || !this.player) return;
    this.player.health = Math.max(0, Math.min(this.player.maxHealth, snap.health));
    this.player.alive = this.player.health > 0;
    this.player.deadTimer = 0;
    this.player.invuln = 0.4;
    this.player.weapon.ammo = snap.ammo;
    this.player.keys = snap.keys || 0;
    this.score = snap.score || 0;
    const safe = findSafeSpawn(this.world, snap.x, snap.y, this.enemies.filter((e) => e.alive).map((e) => e.bounds()));
    this.player.footX = safe.x;
    this.player.footY = safe.y;
    this.player.vx = 0;
    this.player.vy = 0;
    this.player._syncBox();
    this.spawn = { x: safe.x, y: safe.y };
    this.camera.snap(safe.x - this.camera.w * 0.38, safe.y - this.camera.h * 0.7, this.world);
    this.camera.look = this.player.facing * 40;
    for (const p of this.world.pickups) {
      if (p.respawn) p.taken = false;
      else p.taken = Boolean(snap.pickups && snap.pickups[p.id]);
    }
    for (const door of this.world.doors || []) {
      if (!door.persistent) {
        door.state = door.requireKeys || (door.requireDoors || []).length ? "locked" : "closed";
        continue;
      }
      const saved = snap.doors && snap.doors[door.id];
      door.state = saved === "open" || saved === "opening" ? "open" : saved || door.state;
      door.openTimer = 0;
    }
    syncDoorSolids(this.world);
    for (const cp of this.world.checkpoints || []) {
      cp.activated = Boolean(snap.checkpoints && snap.checkpoints[cp.id]);
      cp.inside = false;
    }
    this.hud.invalidate();
  }

  frame(time) {
    if (!this.running) return;
    const dt = Math.min(0.033, (time - this.lastTime) / 1000 || 0.016);
    this.lastTime = time;
    this._frames += 1;
    this._fpsT += dt;
    if (this._fpsT >= 0.4) {
      this.fps = Math.round(this._frames / this._fpsT);
      this._frames = 0;
      this._fpsT = 0;
    }
    this.input.pollGamepad();
    if (this.input.consume("debug")) this.debug = !this.debug;
    this.update(dt);
    this.render();
    this.input.endFrame();
    requestAnimationFrame(this._loop);
  }

  update(dt) {
    const st = this.state.get();
    if (st === GameState.START_SCREEN) {
      if (this.input.consume("confirm")) this.state.set(GameState.CHARACTER_SELECT);
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      if (this.input.consume("moveLeft")) this.select.move(-1);
      if (this.input.consume("moveRight")) this.select.move(1);
      if (this.input.consume("pause")) {
        this.state.set(GameState.START_SCREEN);
        return;
      }
      if (this.input.consume("confirm")) this.confirmCharacter();
      return;
    }
    if (st === GameState.PAUSED) {
      if (this.input.consume("pause") || this.input.consume("confirm")) this.state.set(GameState.PLAYING);
      return;
    }
    if (st === GameState.GAME_OVER || st === GameState.LEVEL_COMPLETE) {
      if (this.input.consume("confirm")) this.restartLevel();
      return;
    }
    if (st === GameState.RESPAWNING) {
      this._updateRespawn(dt);
      return;
    }
    if (!this.state.is(GameState.PLAYING, GameState.PLAYER_DEAD)) return;

    if (st === GameState.PLAYING && this.input.consume("pause")) {
      this.state.set(GameState.PAUSED);
      return;
    }

    const ctx = this;
    if (st === GameState.PLAYING) {
      this.player.update(dt, this.input, this.world, this.projectiles, ctx);
      this.updateEncounters();
      this.camera.follow(this.player, this.world, dt);
      for (const enemy of this.enemies) {
        enemy.update(dt, this.player, this.world, this.projectiles, this);
      }
      this.updateProjectiles(dt);
      this.updateEffects(dt);
      this.updatePickups();
      this.updateHazards(dt);
      updateDoors(this.world, dt);
      this.updateDoorsAndExit();
      this.updateCheckpoints();
      if (!this.player.alive) this.state.set(GameState.PLAYER_DEAD);
      return;
    }

    if (st === GameState.PLAYER_DEAD) {
      this.player.update(dt, this.input, this.world, this.projectiles, ctx);
      this.updateEffects(dt);
      if (this.player.deadTimer > 0.85) this.beginRespawn();
    }
  }

  updateHazards(dt) {
    for (const h of this.world.hazards || []) {
      if (h.cool > 0) h.cool -= dt;
      if (!h.enabled || !this.player.alive) continue;
      if (h.cool > 0) continue;
      if (!aabb(this.player.bounds(), h)) continue;
      const dir = Math.sign(this.player.footX - (h.x + h.w / 2)) || -1;
      const dealt = this.player.takeDamage(h.damage, { knockbackX: dir * 280 });
      if (!dealt) continue;
      h.cool = h.cooldown;
      this.hud.invalidate();
      this.audio.play("player", "hit");
      this.spawnFx({
        sheetKey: "effects",
        frame: 5,
        x: this.player.footX,
        y: this.player.footY - 90,
        size: 72,
        life: 0.2,
      });
    }
  }

  updateCheckpoints() {
    const bounds = this.player.bounds();
    for (const cp of this.world.checkpoints || []) {
      const inside = aabb(bounds, cp);
      if (inside && !cp.inside) {
        const first = !cp.activated;
        cp.activated = true;
        this.captureCheckpoint(cp, { silent: !first });
        if (first && !cp.isStart) {
          this.spawnFx({
            sheetKey: "effects",
            frame: 7,
            x: cp.x + cp.w / 2,
            y: cp.y + 40,
            size: 96,
            life: 0.35,
          });
        }
        this.hud.invalidate();
      }
      cp.inside = inside;
    }
  }

  updateDoorsAndExit() {
    if (this.completed || !this.player.alive) return;
    const bounds = this.player.bounds();
    const exit = (this.world.doors || []).find((d) => d.kind === "exit");
    if (
      exit &&
      exit.state !== "open" &&
      exit.state !== "opening" &&
      doorRequirementsMet(exit, this.player, this.world)
    ) {
      if (tryOpenDoor(exit, this.player, this.world)) {
        this.hud.invalidate();
      }
    }
    for (const door of this.world.doors || []) {
      if (door.state === "open" || door.state === "opening") continue;
      if (!aabb(bounds, door.trigger || door)) continue;
      if (tryOpenDoor(door, this.player, this.world)) {
        syncDoorSolids(this.world);
        this.audio.play("ui", "door");
        this.hud.invalidate();
      }
    }
    if (exit && exit.state === "open" && canCompleteLevel(this.world, this.player) && aabb(bounds, exit.trigger || exit)) {
      this.completeLevel();
    }
  }

  completeLevel() {
    if (this.completed) return;
    this.completed = true;
    this.inputLocked = true;
    for (const shot of this.projectiles) {
      if (shot.owner === "enemy") shot.disable();
    }
    this.projectiles = this.projectiles.filter((p) => p.alive);
    const done = saveSettings({}).completedLevels || [];
    if (!done.includes(this.world.id)) {
      saveSettings({ completedLevels: [...done, this.world.id] });
    }
    this.hud.invalidate();
    this.state.set(GameState.LEVEL_COMPLETE);
  }

  beginRespawn() {
    this.state.set(GameState.RESPAWNING);
    this.inputLocked = true;
    this._respawnTimer = 0;
    this._restored = false;
    this.fade = 0;
  }

  _updateRespawn(dt) {
    this._respawnTimer += dt;
    if (!this._restored) {
      this.fade = Math.min(1, this._respawnTimer / 0.28);
      if (this.fade < 1) return;
      this.restoreAfterDeath();
      this._restored = true;
      this._respawnTimer = 0;
      this.fade = 1;
      return;
    }
    this.fade = Math.max(0, 1 - this._respawnTimer / 0.32);
    if (this._respawnTimer >= 0.32) {
      this.fade = 0;
      this.inputLocked = false;
      this.state.set(GameState.PLAYING);
    }
  }

  restoreAfterDeath() {
    const snap = this.checkpoint;
    try {
      this.world = buildWorld(STUDIO_01);
    } catch (err) {
      const msg = err instanceof LevelDataError ? err.message : `[Producer Hunt] Level failed to start.\n${err}`;
      console.error(msg);
      this.levelError = msg;
      this.world = null;
      this.player = null;
      this.state.set(GameState.START_SCREEN);
      return;
    }
    const kit = this.assets.characterKit(this.character.id);
    const spawn = snap ? { x: snap.x, y: snap.y } : this.world.spawn;
    this.player = new Player(this.character, spawn, kit);
    this.spawnEnemies();
    this.projectiles = [];
    this.effects = [];
    if (snap) this.applySnapshot(snap);
    else this.captureCheckpoint(this.world.checkpoints.find((c) => c.isStart), { silent: true });
    this.player.alive = true;
    this.player.health = Math.max(1, this.player.health);
    this.hud.invalidate();
  }

  spawnEnemies() {
    const defeated = new Set(this.checkpoint?.defeated || []);
    this.enemies = this.world.enemySpawns.map((s, i) => {
      const spawnId = s.id || `${s.type}_${i}`;
      const bound = (this.world.encounters || []).some((enc) => (enc.enemyIds || []).includes(spawnId));
      const enemy = new Enemy(
        s.type,
        {
          x: s.x,
          y: s.y,
          patrolMin: s.patrolMin,
          patrolMax: s.patrolMax,
          activateRange: s.activateRange,
          activated: !bound,
        },
        this.assets.enemyKit(s.type)
      );
      enemy.spawnId = spawnId;
      enemy.encounterBound = bound;
      enemy.persistent = Boolean(s.persistent);
      if (enemy.persistent && defeated.has(spawnId)) {
        enemy.alive = false;
        enemy.health = 0;
        enemy.state = "death";
        enemy.deadTimer = 99;
      }
      return enemy;
    });
  }

  updateEncounters() {
    const px = this.player?.footX ?? 0;
    for (const enc of this.world.encounters || []) {
      if (!enc.activated && px >= enc.activateX) enc.activated = true;
      if (enc.activated) {
        for (const enemy of this.enemies) {
          if ((enc.enemyIds || []).includes(enemy.spawnId)) enemy.activated = true;
        }
      }
      enc.cleared = (enc.enemyIds || []).every((id) => {
        const enemy = this.enemies.find((e) => e.spawnId === id);
        return !enemy || !enemy.alive;
      });
    }
  }

  spawnFx(opts) {
    if (this.effects.length > 40) {
      this.effects = this.effects.filter((fx) => fx.alive);
    }
    const sheet = this.assets.sheet(opts.sheetKey || "effects");
    this.effects.push(
      new FxSprite({
        sheet,
        frame: opts.frame || 0,
        frames: opts.frames || 1,
        fps: opts.fps || 0,
        x: opts.x,
        y: opts.y,
        size: opts.size || 64,
        life: opts.life || 0.22,
        loop: Boolean(opts.loop),
        screenSpace: Boolean(opts.screenSpace),
        flipX: Boolean(opts.flipX),
      })
    );
  }

  updateEffects(dt) {
    for (const fx of this.effects) fx.update(dt);
    this.effects = this.effects.filter((fx) => fx.alive);
  }

  spawnImpact(shot) {
    const fx = shot.impactFx || COMBAT.player.impactFx;
    const c = shot.center ? shot.center() : { x: shot.x + shot.w / 2, y: shot.y + shot.h / 2 };
    this.spawnFx({
      sheetKey: fx.sheetKey,
      frame: fx.frame || 0,
      frames: fx.frames || 1,
      fps: fx.fps || 0,
      x: c.x,
      y: c.y,
      size: fx.size || 56,
      life: fx.life || 0.18,
    });
  }

  updateProjectiles(dt) {
    for (const shot of this.projectiles) {
      if (!shot.alive || shot.spent) continue;
      shot.update(dt);
      if (!shot.alive) continue;
      if (shot.x < -40 || shot.x > this.world.width + 40) {
        shot.disable();
        continue;
      }
      if (hitsSolid(shot.bounds(), this.world.solids)) {
        this.spawnImpact(shot);
        shot.disable();
        continue;
      }
      if (shot.owner === "player") {
        for (const enemy of this.enemies) {
          if (!enemy.alive) continue;
          if (!aabb(shot.bounds(), enemy.bounds())) continue;
          this.score += enemy.takeDamage(shot.damage);
          this.spawnImpact(shot);
          shot.disable();
          break;
        }
      } else if (shot.owner === "enemy") {
        if (this.player.alive && aabb(shot.bounds(), this.player.bounds())) {
          this.player.takeDamage(shot.damage);
          this.spawnImpact(shot);
          shot.disable();
        }
      }
    }
    this.projectiles = this.projectiles.filter((p) => p.alive);
    this.enemies = this.enemies.filter((e) => {
      if (e.alive) return true;
      if (e.anim && e.anim.name === "death" && !e.anim.finished) return true;
      return e.deadTimer < 0.9;
    });
  }

  updatePickups() {
    for (const pickup of this.world.pickups) {
      if (pickup.taken || pickup.reserved) continue;
      if (!aabb(this.player.bounds(), pickup)) continue;
      if (!applyPickup(pickup, this.player, this)) continue;
      this.audio.play("ui", "pickup");
      this.hud.invalidate();
      this.spawnFx({
        sheetKey: PICKUP_COLLECT_FX.sheetKey,
        frame: PICKUP_COLLECT_FX.frame,
        x: pickup.x + pickup.w / 2,
        y: pickup.y + pickup.h / 2,
        size: PICKUP_COLLECT_FX.size,
        life: PICKUP_COLLECT_FX.life,
      });
    }
  }

  render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, DESIGN_W, DESIGN_H);
    const st = this.state.get();

    if (st === GameState.START_SCREEN) {
      this.drawStart(ctx);
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      const titleBg = this.assets.sheet("title_bg")?.image;
      if (!drawCoverImage(ctx, titleBg, DESIGN_W, DESIGN_H)) {
        ctx.fillStyle = "#0c1220";
        ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
      }
      ctx.fillStyle = "rgba(5, 7, 12, 0.55)";
      ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
      this.select.draw(ctx, this.assets);
      return;
    }

    if (this.world) this.drawWorld(ctx);
    for (const enemy of this.enemies) enemy.draw(ctx, this.camera);
    if (this.player) this.player.draw(ctx, this.camera, this.assets);
    for (const shot of this.projectiles) shot.draw(ctx, this.camera);
    if (this.world) drawDecorSheet(ctx, this.assets, "props", this.world.props, this.camera, 128, "front");
    for (const fx of this.effects) fx.draw(ctx, this.camera, drawSheetFrame);
    if (this.fade > 0) {
      ctx.fillStyle = `rgba(5, 7, 12, ${this.fade})`;
      ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    }
    if (this.player && this.state.is(GameState.PLAYING, GameState.PAUSED, GameState.PLAYER_DEAD, GameState.RESPAWNING)) {
      this.hud.draw(ctx, {
        player: this.player,
        score: this.score,
        assets: this.assets,
        objective: currentObjective(this.world, this.player),
      });
    }
    if (this.debug) this.drawDebug(ctx);

    if (st === GameState.PAUSED) drawMenu(ctx, "PAUSED", "", this.pauseButtons());
    if (st === GameState.GAME_OVER) drawMenu(ctx, "GAME OVER", `SCORE ${this.score}`, this.overButtons());
    if (st === GameState.LEVEL_COMPLETE) {
      drawMenu(ctx, "LEVEL COMPLETE", `SCORE: ${this.score}`, this.completeButtons());
    }
  }

  drawStart(ctx) {
    ctx.fillStyle = "#0c1220";
    ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    const titleBg = this.assets.sheet("title_bg")?.image;
    if (!drawCoverImage(ctx, titleBg, DESIGN_W, DESIGN_H)) {
      ctx.fillStyle = "#0c1220";
      ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    }
    const logo = this.assets.sheet("logo")?.image;
    if (logo) {
      const maxW = 920;
      const maxH = 360;
      const scale = Math.min(maxW / logo.width, maxH / logo.height);
      const dw = logo.width * scale;
      const dh = logo.height * scale;
      ctx.drawImage(logo, (DESIGN_W - dw) / 2, 48, dw, dh);
    } else {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 86px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("PRODUCER HUNT", DESIGN_W / 2, 280);
    }
    ctx.fillStyle = "#94a3b8";
    ctx.font = "22px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("BigBang Studios  ·  run-and-gun", DESIGN_W / 2, 430);
    if (this.levelError) {
      ctx.fillStyle = "#f87171";
      ctx.font = "16px sans-serif";
      ctx.textAlign = "center";
      const lines = String(this.levelError).split("\n");
      lines.forEach((line, i) => ctx.fillText(line, DESIGN_W / 2, 470 + i * 22));
    }
    drawButtons(ctx, this.startButtons());
    if (this.showControls) {
      ctx.fillStyle = "rgba(5,7,12,0.88)";
      ctx.fillRect(560, 200, 800, 420);
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "20px sans-serif";
      ctx.textAlign = "left";
      const lines = [
        "A / ←   D / →    move",
        "W / ↑             jump",
        "S / ↓             crouch",
        "SPACE             shoot",
        "SHIFT             special",
        "ESC               pause",
        "ENTER             confirm",
      ];
      lines.forEach((l, i) => ctx.fillText(l, 640, 280 + i * 40));
    }
  }

  drawWorld(ctx) {
    const cam = this.camera;
    ctx.fillStyle = this.world.background.sky;
    ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    if (!drawStudioParallax(ctx, this.assets, cam.x)) {
      const far = cam.x * 0.25;
      ctx.fillStyle = this.world.background.far;
      for (let i = 0; i < 16; i += 1) {
        const x = i * 520 - (far % 520);
        ctx.fillRect(x - 80, 220, 300, 420);
      }
    }

    for (const zone of this.world.zones) {
      const s = cam.worldToScreen(zone.x, zone.y);
      ctx.fillStyle = zone.color;
      ctx.globalAlpha = 0.12;
      ctx.fillRect(s.x, 88, zone.w, 72);
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(`[ ${zone.label} ]`, s.x + 24, 132);
    }

    drawHints(ctx, this.world.hints, cam);
    drawDecorSheet(ctx, this.assets, "props", this.world.props, cam, 128, "back");

    if (!drawTiledPlatforms(ctx, this.assets, this.world.platformSolids || this.world.solids, cam)) {
      for (const solid of this.world.solids) {
        const s = cam.worldToScreen(solid.x, solid.y);
        ctx.fillStyle = "#3f3a32";
        ctx.fillRect(s.x, s.y, solid.w, solid.h);
        ctx.fillStyle = "#c9a227";
        ctx.fillRect(s.x, s.y, solid.w, 5);
      }
    }

    drawProgression(ctx, this.assets, this.world, cam);
    drawPickups(ctx, this.assets, this.world.pickups, cam, this.lastTime);
    drawHazards(ctx, this.assets, this.world.hazards, cam);
  }

  drawDebug(ctx) {
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.fillRect(DESIGN_W - 380, 24, 356, 168);
    ctx.fillStyle = "#86efac";
    ctx.font = "14px monospace";
    ctx.textAlign = "left";
    const p = this.player;
    const lines = [
      `state ${this.state.get()}`,
      `fps ${this.fps}`,
      p ? `anim ${p.anim.name} f${p.anim.frame}` : "anim —",
      p ? `feet ${p.footX.toFixed(0)},${p.footY.toFixed(0)}` : "player —",
      `cam ${this.camera.x.toFixed(0)}`,
      `enemies ${this.enemies.filter((e) => e.alive).length}`,
      `shots ${this.projectiles.length}`,
      `fx ${this.effects.length}`,
    ];
    lines.forEach((l, i) => ctx.fillText(l, DESIGN_W - 364, 50 + i * 22));
    ctx.strokeStyle = "#38bdf8";
    ctx.strokeRect(1, 1, DESIGN_W - 2, DESIGN_H - 2);
    if (p) p.drawAssetDebug(ctx, this.camera, this.world);
    for (const e of this.enemies) e.drawAssetDebug(ctx, this.camera);
    const drawBox = (box, color) => {
      if (!box) return;
      const s = this.camera.worldToScreen(box.x, box.y);
      ctx.strokeStyle = color;
      ctx.strokeRect(s.x, s.y, box.w, box.h);
    };
    for (const h of this.world?.hazards || []) {
      if (h.enabled) drawBox(h, "rgba(250,204,21,0.9)");
    }
    for (const d of this.world?.doors || []) {
      drawBox(d, d.state === "open" ? "rgba(74,222,128,0.9)" : "rgba(248,113,113,0.9)");
      drawBox(d.trigger, "rgba(96,165,250,0.7)");
    }
    for (const cp of this.world?.checkpoints || []) drawBox(cp, "rgba(45,212,191,0.9)");
  }
}
