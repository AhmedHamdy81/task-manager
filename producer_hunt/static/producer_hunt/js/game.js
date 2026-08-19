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
import { drawButtons, drawConfirm, drawMenu, drawSettings, hitMenu, menuButtons, moveMenuIndex, settingsRows, confirmButtons } from "./ui.js";
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
import { loadSettings, saveSettings } from "./settings.js";
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

function emptyStats() {
  return { tokens: 0, kills: 0, deaths: 0, time: 0 };
}

function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export class Game {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.exitUrl = options.exitUrl || "/";
    this.allowDebug = Boolean(options.allowDebug);
    this.debug = this.allowDebug && (Boolean(options.debug) || DEBUG_ASSETS);
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
    this.overlay = null;
    this.confirmKind = null;
    this.menuIndex = 0;
    this._userPaused = false;
    this._autoPaused = false;
    this._deathOverlay = false;
    this._respawnLock = false;
    this._worldTime = 0;
    this._playTime = 0;
    this.stats = emptyStats();
    this.settings = loadSettings();
    this._loop = (t) => this.frame(t);
    this._onResize = () => this.fitCanvas();
    this._onClick = (e) => this.onClick(e);
    this._onVisibility = () => this.onVisibility();
    this._onBlur = () => this.onWindowBlur();
    this._onFullscreen = () => this.hud.invalidate();
    this._raf = 0;
    this._bootStarted = false;
    this._listenersOn = false;
    this._onPreventScroll = (e) => {
      const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"];
      if (keys.includes(e.code)) e.preventDefault();
    };
  }

  _bindShell() {
    if (this._listenersOn) return;
    this.input.attach();
    window.addEventListener("resize", this._onResize);
    document.addEventListener("visibilitychange", this._onVisibility);
    window.addEventListener("blur", this._onBlur);
    document.addEventListener("fullscreenchange", this._onFullscreen);
    window.addEventListener("keydown", this._onPreventScroll, { passive: false });
    this.canvas.addEventListener("click", this._onClick);
    this._listenersOn = true;
  }

  async start() {
    try {
      this._bindShell();
      this.fitCanvas();
      this.applySettings();
      if (!this._bootStarted) {
        this._bootStarted = true;
        await this.preload();
        this.state.set(GameState.START_SCREEN);
      }
      if (this.running) return;
      this.running = true;
      this._raf = requestAnimationFrame(this._loop);
    } catch (err) {
      console.error("Producer Hunt failed to initialize", err);
    }
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
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    this.input.detach();
    window.removeEventListener("resize", this._onResize);
    document.removeEventListener("visibilitychange", this._onVisibility);
    window.removeEventListener("blur", this._onBlur);
    document.removeEventListener("fullscreenchange", this._onFullscreen);
    this.canvas.removeEventListener("click", this._onClick);
    window.removeEventListener("keydown", this._onPreventScroll);
    this._listenersOn = false;
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
    return menuButtons(["START GAME", "SETTINGS", "CONTROLS", "EXIT"], 520, { gap: 64 });
  }

  pauseButtons() {
    return menuButtons(
      ["RESUME", "RESTART FROM CHECKPOINT", "RESTART LEVEL", "SETTINGS", "RETURN TO MAIN MENU"],
      280,
      { gap: 64 }
    );
  }

  deathButtons() {
    return menuButtons(["RESUME FROM CHECKPOINT", "RESTART LEVEL", "MAIN MENU"], 400, { gap: 66 });
  }

  completeButtons() {
    return menuButtons(["REPLAY LEVEL", "CHARACTER SELECTION", "MAIN MENU"], 620, { gap: 64 });
  }

  onClick(e) {
    const p = this.canvasPoint(e);
    const st = this.state.get();
    if (this.overlay === "confirm") {
      const hit = hitMenu(confirmButtons(), p.x, p.y);
      if (hit) this.handleConfirm(hit.id);
      return;
    }
    if (this.overlay === "settings") {
      const rows = settingsRows();
      const x = DESIGN_W / 2 - 380;
      rows.forEach((row, i) => {
        const y = 210 + i * 88;
        if (p.x >= x && p.x <= x + 760 && p.y >= y && p.y <= y + 72) {
          this.menuIndex = i;
          if (row.kind === "action") this.closeSettings();
          else if (row.kind === "toggle") this.adjustSetting(row, 1);
          else if (row.kind === "slider") {
            const t = (p.x - (x + 400)) / 280;
            this.setSlider(row.id, t);
          }
        }
      });
      return;
    }
    if (st === GameState.START_SCREEN) {
      const buttons = this.startButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.handleStart(hit.id);
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      const act = this.select.handleClick(p.x, p.y);
      if (act === "confirm") this.confirmCharacter();
      if (act === "back") this.goMainMenu({ dispose: true });
      return;
    }
    if (st === GameState.PAUSED) {
      const buttons = this.pauseButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.handlePause(hit.id);
      return;
    }
    if (st === GameState.PLAYER_DEAD && this._deathOverlay) {
      const buttons = this.deathButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.handleDeath(hit.id);
      return;
    }
    if (st === GameState.LEVEL_COMPLETE) {
      const buttons = this.completeButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.handleComplete(hit.id);
    }
  }

  handleStart(id) {
    if (id === "START GAME") {
      this.overlay = null;
      this.state.set(GameState.CHARACTER_SELECT);
    }
    if (id === "SETTINGS") this.openSettings();
    if (id === "CONTROLS") this.showControls = !this.showControls;
    if (id === "EXIT") this.exit();
  }

  handlePause(id) {
    if (id === "RESUME") this.resumePlay();
    if (id === "RESTART FROM CHECKPOINT") this.requestRespawn();
    if (id === "RESTART LEVEL") this.askConfirm("restart");
    if (id === "SETTINGS") this.openSettings();
    if (id === "RETURN TO MAIN MENU") this.askConfirm("menu");
  }

  handleDeath(id) {
    if (id === "RESUME FROM CHECKPOINT") this.requestRespawn();
    if (id === "RESTART LEVEL") this.askConfirm("restart");
    if (id === "MAIN MENU") this.askConfirm("menu");
  }

  handleComplete(id) {
    if (id === "REPLAY LEVEL") this.restartLevel();
    if (id === "CHARACTER SELECTION") this.goCharacterSelect();
    if (id === "MAIN MENU") this.goMainMenu({ dispose: true });
  }

  handleMenu(hit) {
    if (!hit) return;
    const st = this.state.get();
    if (st === GameState.PAUSED) this.handlePause(hit.id);
    else if (st === GameState.PLAYER_DEAD) this.handleDeath(hit.id);
    else if (st === GameState.LEVEL_COMPLETE) this.handleComplete(hit.id);
    else if (st === GameState.START_SCREEN) this.handleStart(hit.id);
  }

  exit() {
    window.location.href = this.exitUrl;
  }

  currentButtons() {
    const st = this.state.get();
    if (st === GameState.START_SCREEN) return this.startButtons();
    if (st === GameState.PAUSED) return this.pauseButtons();
    if (st === GameState.PLAYER_DEAD) return this.deathButtons();
    if (st === GameState.LEVEL_COMPLETE) return this.completeButtons();
    return [];
  }

  updateMenuNav(buttons, onConfirm) {
    if (this.input.consume("jump") || this.input.consume("moveLeft")) {
      this.menuIndex = moveMenuIndex(this.menuIndex, -1, buttons.length);
    }
    if (this.input.consume("crouch") || this.input.consume("moveRight")) {
      this.menuIndex = moveMenuIndex(this.menuIndex, 1, buttons.length);
    }
    if (this.input.consume("confirm") && buttons[this.menuIndex]) {
      onConfirm(buttons[this.menuIndex].id);
    }
  }

  openPause() {
    if (this.state.get() !== GameState.PLAYING) return;
    this._userPaused = true;
    this._autoPaused = false;
    this.overlay = null;
    this.menuIndex = 0;
    this.inputLocked = true;
    this.input.clearTransient();
    this.state.set(GameState.PAUSED);
  }

  resumePlay() {
    if (this.state.get() !== GameState.PAUSED) return;
    if (this.overlay) return;
    this.overlay = null;
    this._userPaused = false;
    this._autoPaused = false;
    this.inputLocked = false;
    this.input.clearTransient();
    this.state.set(GameState.PLAYING);
  }

  onPlayerDied() {
    if (this.state.get() === GameState.PLAYER_DEAD) return;
    this.stats.deaths += 1;
    this._deathOverlay = false;
    this.overlay = null;
    this.menuIndex = 0;
    this.inputLocked = true;
    this.input.clearTransient();
    this.state.set(GameState.PLAYER_DEAD);
  }

  updateDeath(dt) {
    if (!this.player) return;
    this.player.update(dt, this.input, this.world, this.projectiles, this);
    this.updateEffects(dt);
    const animDone = this.player.anim?.name === "death" && this.player.anim.finished;
    if (!this._deathOverlay && (animDone || this.player.deadTimer > 0.95)) {
      this._deathOverlay = true;
      this.menuIndex = 0;
      for (const shot of this.projectiles) {
        if (shot.owner === "enemy") shot.disable();
      }
      this.projectiles = this.projectiles.filter((p) => p.alive);
    }
    if (this._deathOverlay) {
      this.updateMenuNav(this.deathButtons(), (id) => this.handleDeath(id));
    }
  }

  requestRespawn() {
    if (this._respawnLock || this.state.is(GameState.RESPAWNING)) return;
    this.beginRespawn();
  }

  askConfirm(kind) {
    this.confirmKind = kind;
    this.overlay = "confirm";
    this.menuIndex = 1;
  }

  confirmCopy() {
    if (this.confirmKind === "menu") {
      return "Return to the main menu? Unsaved progress since the last checkpoint will be lost.";
    }
    return "Restart the level? Progress since the last checkpoint will be lost.";
  }

  handleConfirm(id) {
    if (id === "CANCEL") {
      this.overlay = null;
      this.menuIndex = 0;
      return;
    }
    const kind = this.confirmKind;
    this.overlay = null;
    this.confirmKind = null;
    if (kind === "restart") this.restartLevel();
    if (kind === "menu") this.goMainMenu({ dispose: true });
  }

  updateConfirmInput() {
    if (this.input.consume("pause")) {
      this.handleConfirm("CANCEL");
      return;
    }
    if (this.input.consume("moveLeft") || this.input.consume("jump")) this.menuIndex = 0;
    if (this.input.consume("moveRight") || this.input.consume("crouch")) this.menuIndex = 1;
    this.menuIndex = this.menuIndex ? 1 : 0;
    if (this.input.consume("confirm")) this.handleConfirm(this.menuIndex === 0 ? "CONFIRM" : "CANCEL");
  }

  openSettings() {
    this.overlay = "settings";
    this.menuIndex = 0;
  }

  closeSettings() {
    this.overlay = null;
    this.menuIndex = 0;
  }

  updateSettingsInput() {
    const rows = settingsRows();
    if (this.input.consume("pause")) {
      this.closeSettings();
      return;
    }
    if (this.input.consume("jump")) this.menuIndex = moveMenuIndex(this.menuIndex, -1, rows.length);
    if (this.input.consume("crouch")) this.menuIndex = moveMenuIndex(this.menuIndex, 1, rows.length);
    const row = rows[this.menuIndex];
    if (!row) return;
    if (this.input.consume("moveLeft")) this.adjustSetting(row, -1);
    if (this.input.consume("moveRight")) this.adjustSetting(row, 1);
    if (this.input.consume("confirm")) {
      if (row.kind === "action") this.closeSettings();
      else if (row.kind === "toggle") this.adjustSetting(row, 1);
    }
  }

  adjustSetting(row, dir) {
    if (row.kind === "slider") {
      this.setSlider(row.id, (this.settings[row.id] ?? 0) + dir * 0.05);
      return;
    }
    if (row.id === "fullscreen") {
      this.toggleFullscreen();
      return;
    }
    if (row.kind === "toggle") {
      this.settings = saveSettings({ [row.id]: !this.settings[row.id] });
      this.applySettings();
    }
  }

  setSlider(id, value) {
    const n = Math.max(0, Math.min(1, value));
    this.settings = saveSettings({ [id]: n });
    this.applySettings();
  }

  applySettings() {
    this.settings = { ...this.settings, ...loadSettings() };
    this.audio.applyMix(this.settings);
  }

  shakeEnabled() {
    return this.settings.screenShake !== false && !this.settings.reducedMotion;
  }

  isFullscreen() {
    return Boolean(document.fullscreenElement);
  }

  async toggleFullscreen() {
    try {
      if (this.isFullscreen()) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (err) {
      console.warn("[Producer Hunt] Fullscreen request was rejected.", err);
    }
  }

  disposeLevel() {
    this.world = null;
    this.player = null;
    this.enemies = [];
    this.projectiles = [];
    this.effects = [];
    this.checkpoint = null;
    this.completed = false;
    this.inputLocked = false;
    this._deathOverlay = false;
    this._respawnLock = false;
    this.overlay = null;
    this.confirmKind = null;
    this._userPaused = false;
    this._autoPaused = false;
    this.fade = 0;
    this.score = 0;
    this.input.clearTransient();
  }

  goMainMenu() {
    this.disposeLevel();
    this.menuIndex = 0;
    this.showControls = false;
    this.state.set(GameState.START_SCREEN);
  }

  goCharacterSelect() {
    this.disposeLevel();
    this.menuIndex = 0;
    this.state.set(GameState.CHARACTER_SELECT);
  }

  onVisibility() {
    if (document.hidden) {
      this.input.clearTransient();
      if (this.state.get() === GameState.PLAYING) {
        this._autoPaused = true;
        this.overlay = null;
        this.menuIndex = 0;
        this.inputLocked = true;
        this.state.set(GameState.PAUSED);
      }
      return;
    }
    this.input.clearTransient();
  }

  onWindowBlur() {
    this.input.clearTransient();
  }

  drawComplete(ctx) {
    const name = this.world?.name || "The Post Suite";
    const ch = this.character?.displayName || this.character?.name || "—";
    const time = formatClock(this.stats.time || this._playTime);
    const lines = [
      `Time  ${time}`,
      `Production tokens  ${this.stats.tokens}`,
      `Enemies defeated  ${this.stats.kills}`,
      `Character  ${ch}`,
      `Deaths  ${this.stats.deaths}`,
    ];
    drawMenu(ctx, "LEVEL COMPLETE", name, this.completeButtons(), { focus: this.menuIndex, titleY: 140 });
    ctx.textAlign = "center";
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "22px sans-serif";
    lines.forEach((line, i) => ctx.fillText(line, DESIGN_W / 2, 250 + i * 36));
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
      const msg = err instanceof LevelDataError ? err.message : `[Producer Hunt] Required level data is invalid.\n${err}`;
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
    this._deathOverlay = false;
    this._respawnLock = false;
    this.overlay = null;
    this.confirmKind = null;
    this._userPaused = false;
    this._autoPaused = false;
    this._playTime = 0;
    this._worldTime = 0;
    this.stats = emptyStats();
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
      stats: { ...this.stats, time: this._playTime },
    };
    this.spawn = { x: safe.x, y: safe.y };
    if (!opts.silent) {
      this.audio.play("ui", "checkpoint");
      this.hud.invalidate();
    }
  }

  applySnapshot(snap) {
    if (!snap || !this.player) return;
    this.player.health = Number.isFinite(snap.health)
      ? Math.max(0, Math.min(this.player.maxHealth, snap.health))
      : this.player.maxHealth;
    this.player.alive = this.player.health > 0;
    this.player.deadTimer = 0;
    this.player.invuln = 0.4;
    this.player.weapon.ammo = Number.isFinite(snap.ammo) ? snap.ammo : this.player.weapon.ammo;
    this.player.keys = Number.isFinite(snap.keys) ? snap.keys : 0;
    this.score = Number.isFinite(snap.score) ? snap.score : 0;
    if (snap.stats && typeof snap.stats === "object") {
      this.stats = {
        tokens: Number(snap.stats.tokens) || 0,
        kills: Number(snap.stats.kills) || 0,
        deaths: Number(snap.stats.deaths) || 0,
        time: Number(snap.stats.time) || 0,
      };
      this._playTime = this.stats.time;
    }
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
    if (this.allowDebug && this.input.consume("debug")) this.debug = !this.debug;
    else this.input.consume("debug");
    this.update(dt);
    this.render();
    this.input.endFrame();
    this._raf = requestAnimationFrame(this._loop);
  }

  update(dt) {
    const st = this.state.get();
    this.camera.updateShake(st === GameState.PLAYING ? dt : 0, this.shakeEnabled());

    if (this.overlay === "confirm") {
      this.updateConfirmInput();
      return;
    }
    if (this.overlay === "settings") {
      this.updateSettingsInput();
      return;
    }

    if (st === GameState.START_SCREEN) {
      this.updateMenuNav(this.startButtons(), (id) => this.handleStart(id));
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      if (this.input.consume("moveLeft")) this.select.move(-1);
      if (this.input.consume("moveRight")) this.select.move(1);
      if (this.input.consume("pause")) {
        this.goMainMenu({ dispose: true });
        return;
      }
      if (this.input.consume("confirm")) this.confirmCharacter();
      return;
    }
    if (st === GameState.PAUSED) {
      if (this.input.consume("pause")) {
        this.resumePlay();
        return;
      }
      this.updateMenuNav(this.pauseButtons(), (id) => this.handlePause(id));
      return;
    }
    if (st === GameState.LEVEL_COMPLETE) {
      this.updateMenuNav(this.completeButtons(), (id) => this.handleComplete(id));
      return;
    }
    if (st === GameState.RESPAWNING) {
      this._updateRespawn(dt);
      return;
    }
    if (st === GameState.PLAYER_DEAD) {
      this.updateDeath(dt);
      return;
    }
    if (st !== GameState.PLAYING) return;

    if (this.input.consume("pause")) {
      this.openPause();
      return;
    }

    this._playTime += dt;
    this._worldTime += dt;
    this.inputLocked = false;
    this.player.update(dt, this.input, this.world, this.projectiles, this);
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
    if (!this.player.alive) this.onPlayerDied();
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
      if (this.shakeEnabled()) this.camera.addShake(0.45);
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
    if (this.completed || this.state.get() !== GameState.PLAYING) return;
    this.completed = true;
    this.inputLocked = true;
    this.stats.time = this._playTime;
    this.overlay = null;
    this.menuIndex = 0;
    this.input.clearTransient();
    for (const shot of this.projectiles) {
      if (shot.owner === "enemy") shot.disable();
    }
    this.projectiles = this.projectiles.filter((p) => p.alive);
    const done = loadSettings().completedLevels || [];
    if (this.world?.id && !done.includes(this.world.id)) {
      this.settings = saveSettings({ completedLevels: [...done, this.world.id] });
    }
    this.hud.invalidate();
    this.state.set(GameState.LEVEL_COMPLETE);
  }

  beginRespawn() {
    if (this._respawnLock || this.state.get() === GameState.RESPAWNING) return;
    this._respawnLock = true;
    this._deathOverlay = false;
    this.overlay = null;
    this.inputLocked = true;
    this.input.clearTransient();
    this.state.set(GameState.RESPAWNING);
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
      this._respawnLock = false;
      this._userPaused = false;
      this.state.set(GameState.PLAYING);
    }
  }

  restoreAfterDeath() {
    const snap = this.checkpoint;
    try {
      this.world = buildWorld(STUDIO_01);
    } catch (err) {
      const msg = err instanceof LevelDataError ? err.message : `[Producer Hunt] Required level data is invalid.\n${err}`;
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
    this.inputLocked = false;
    this._deathOverlay = false;
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
      const travel = typeof shot.travelBounds === "function" ? shot.travelBounds() : shot.bounds();
      if (hitsSolid(travel, this.world.solids)) {
        this.spawnImpact(shot);
        shot.disable();
        continue;
      }
      if (shot.owner === "player") {
        for (const enemy of this.enemies) {
          if (!enemy.alive) continue;
          if (!aabb(shot.bounds(), enemy.bounds())) continue;
          this.score += enemy.takeDamage(shot.damage);
          if (!enemy.alive) this.stats.kills += 1;
          this.spawnImpact(shot);
          shot.disable();
          break;
        }
      } else if (shot.owner === "enemy") {
        if (this.player.alive && aabb(shot.bounds(), this.player.bounds())) {
          const dealt = this.player.takeDamage(shot.damage);
          if (dealt && this.shakeEnabled()) this.camera.addShake(0.55);
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
      if (pickup.kind === "production_token" || pickup.kind === "bonus") this.stats.tokens += 1;
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
      if (this.overlay === "settings") {
        drawSettings(ctx, this.settings, this.menuIndex, { fullscreen: this.isFullscreen() });
      }
      if (this.debug) this.drawDebug(ctx);
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
    if (this.player && this.state.is(GameState.PLAYING, GameState.RESPAWNING)) {
      this.hud.draw(ctx, {
        player: this.player,
        score: this.score,
        assets: this.assets,
        objective: currentObjective(this.world, this.player),
      });
    }
    if (this.debug) this.drawDebug(ctx);

    if (st === GameState.PAUSED && this.overlay !== "settings" && this.overlay !== "confirm") {
      drawMenu(ctx, "PAUSED", this.world?.name || "", this.pauseButtons(), { focus: this.menuIndex, titleY: 150 });
    }
    if (st === GameState.PLAYER_DEAD && this._deathOverlay && this.overlay !== "confirm") {
      drawMenu(ctx, "DEFEATED", "The deadline held.", this.deathButtons(), { focus: this.menuIndex, titleY: 200 });
    }
    if (st === GameState.LEVEL_COMPLETE) {
      this.drawComplete(ctx);
    }
    if (this.overlay === "settings") {
      drawSettings(ctx, this.settings, this.menuIndex, { fullscreen: this.isFullscreen() });
    }
    if (this.overlay === "confirm") {
      drawConfirm(ctx, "CONFIRM", this.confirmCopy(), this.menuIndex);
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
      const maxW = 840;
      const maxH = 280;
      const scale = Math.min(maxW / logo.width, maxH / logo.height);
      const dw = logo.width * scale;
      const dh = logo.height * scale;
      ctx.drawImage(logo, (DESIGN_W - dw) / 2, 36, dw, dh);
    } else {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 86px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("PRODUCER HUNT", DESIGN_W / 2, 220);
    }
    ctx.fillStyle = "#94a3b8";
    ctx.font = "22px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("BigBang Studios  ·  run-and-gun", DESIGN_W / 2, 360);
    if (this.levelError) {
      ctx.fillStyle = "#f87171";
      ctx.font = "16px sans-serif";
      ctx.textAlign = "center";
      const lines = String(this.levelError).split("\n");
      lines.forEach((line, i) => ctx.fillText(line, DESIGN_W / 2, 400 + i * 22));
    }
    if (this.overlay !== "settings") {
      drawButtons(ctx, this.startButtons(), { focus: this.menuIndex });
    }
    if (this.showControls && this.overlay !== "settings") {
      ctx.fillStyle = "rgba(5,7,12,0.88)";
      ctx.fillRect(560, 160, 800, 420);
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
    drawPickups(ctx, this.assets, this.world.pickups, cam, this._worldTime * 1000);
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
