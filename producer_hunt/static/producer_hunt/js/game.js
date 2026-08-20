import { DEBUG_ASSETS, DESIGN_H, DESIGN_W } from "./config.js";
import { GameState, GameStateManager } from "./game-state.js";
import { Input } from "./input.js";
import { Camera } from "./camera.js";
import { Player } from "./player.js";
import { ENEMY_TYPES, Enemy, migrateEnemyType } from "./enemy.js";
import { HUD } from "./hud.js";
import { CharacterSelect } from "./character-select.js";
import { aabb, hitsSolid } from "./collision.js";
import { LEVELS, STUDIO_01, buildWorld, LevelDataError, resolveLevel, nextLevelId, levelDataLoads } from "./levels/level-01.js";
import { AssetLoader } from "./asset-loader.js";
import { WORLD_SHEETS, drawCoverImage, drawSheetFrame } from "./asset-catalog.js";
import { COMBAT } from "./combat.js";
import { AudioManager } from "./audio.js";
import { musicForLevel, musicPlayOpts, pickupSoundId } from "./audio-catalog.js";
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
import { WaveController, pickWaveSpawn, STUDIO_CLEAR_BONUS } from "./waves.js";
import { BossEncounter, HostileProjectilePool } from "./boss.js";
import { CinematicPlayer } from "./cinematic.js";
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

function enemySpawnSafetyIssues(world, enemy) {
  const issues = [];
  if (!world) return ["missing world"];
  if (!(enemy.health > 0) || !enemy.alive || enemy.state === "death") {
    issues.push("starts dead or with zero health");
  }
  const width = world.width || 0;
  const height = world.height || DESIGN_H;
  if (enemy.footX < 0 || enemy.footX > width) issues.push("outside level bounds");
  if (enemy.footY > height + 8) issues.push("below death boundary");
  const solids = world.solids || [];
  const box = { x: enemy.x, y: enemy.y, w: enemy.w, h: enemy.h };
  const buried = solids.some((s) => s.y + 8 < enemy.footY - 8 && aabb(box, s));
  if (buried) issues.push("overlaps solid collision");
  const onSupport = solids.some((s) => {
    const over = enemy.footX >= s.x && enemy.footX <= s.x + s.w;
    const onTop = Math.abs(enemy.footY - s.y) <= 12;
    return over && onTop;
  });
  if (!onSupport) issues.push("not on a valid platform");
  return issues;
}

export class Game {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.exitUrl = options.exitUrl || "/";
    this.allowDebug = Boolean(options.allowDebug);
    this.debug = this.allowDebug && (Boolean(options.debug) || DEBUG_ASSETS);
    this.assets = new AssetLoader(options.assetBase || "", { cacheKey: options.cacheKey || "" });
    this.audio = new AudioManager({ loader: this.assets });
    this.input = new Input();
    this.camera = new Camera();
    this.hud = new HUD();
    this.select = new CharacterSelect();
    this.state = new GameStateManager(GameState.BOOT);
    this.levelId = LEVELS[options.levelId] ? options.levelId : STUDIO_01.id;
    this.player = null;
    this.character = null;
    this.world = null;
    this.enemies = [];
    this.waves = null;
    this.bossEncounter = null;
    this.cinematic = new CinematicPlayer(this);
    this._cinematicActive = false;
    this.projectiles = [];
    this.hostileProjectiles = [];
    this.hostilePool = new HostileProjectilePool();
    this.effects = [];
    this._bossMusic = false;
    this._bossWarned = new Set();
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
    this.audio.attachUnlock(window);
    this._listenersOn = true;
  }

  sfx(id, extra = {}) {
    return this.audio.playSound(id, { camera: this.camera, ...extra });
  }

  playMenuMusic() {
    this.audio.playMusic("music_menu", {
      loop: true,
      volume: 0.4,
    });
  }

  playBossMusic() {
    if (this._cinematicActive) return;
    const id = this.audio.hasBuffer("music_boss_01")
      ? "music_boss_01"
      : this.audio.hasBuffer("music_boss")
        ? "music_boss"
        : musicForLevel(this.world?.id || this.levelId, this.world?.music);
    const start = () => {
      this.audio.ensureMusic(id, musicPlayOpts(id));
      this._bossMusic = true;
    };
    this.audio.unlock().then(start);
  }

  playBossIntro(opts = {}) {
    return this.cinematic.playBossIntro(opts);
  }

  beginCinematic() {
    this._cinematicActive = true;
    this.inputLocked = true;
    this.input.clearTransient();
    this.audio.stopGameplayVoices();
  }

  endCinematic() {
    this._cinematicActive = false;
    this.inputLocked = false;
    this.input.clearTransient();
  }

  updateCinematicInput() {
    if (!this._cinematicActive) return;
    const skip =
      this.input.consume("pause") ||
      this.input.consume("confirm") ||
      this.input.consume("shoot");
    if (skip) this.cinematic.trySkip();
    this.input.pressed.clear();
  }

  playLevelMusic(opts = {}) {
    const id = musicForLevel(this.world?.id || this.levelId, this.world?.music);
    const start = () => this.audio.ensureMusic(id, { ...musicPlayOpts(id), ...opts });
    if (this.audio.unlocked) start();
    else this.audio.unlock().then(start);
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
        this.playMenuMusic();
      }
      if (this.running) return;
      this.running = true;
      if (this.state.is(GameState.START_SCREEN, GameState.CHARACTER_SELECT)) {
        this.playMenuMusic();
      } else if (this.state.is(GameState.PLAYER_DEAD)) {
        if (this.audio.hasBuffer("music_game_over")) this.audio.playMusic("music_game_over");
        else this.playLevelMusic();
      } else if (this.state.is(GameState.PLAYING, GameState.RESPAWNING)) {
        this.playLevelMusic();
      } else if (this.state.is(GameState.LEVEL_COMPLETE)) {
        this.audio.stopMusic(0.15);
      }
      this._raf = requestAnimationFrame(this._loop);
    } catch (err) {
      console.error("Producer Hunt failed to initialize", err);
    }
  }

  async preload() {
    try {
      await Promise.all(CHARACTERS.map((ch) => this.assets.loadCharacterKit(ch.sprite)));
      await this.assets.loadEnemyKit(ENEMY_TYPES.post_producer.sprite);
      await this.assets.loadEnemyKit(ENEMY_TYPES.client.sprite);
      if (ENEMY_TYPES.boss_01) {
        await this.assets.loadEnemyKit(ENEMY_TYPES.boss_01.sprite);
      }
      try {
        await this.assets.loadCatalog(WORLD_SHEETS);
      } catch (err) {
        console.warn("[Producer Hunt] Optional world sheet failed. Enemies still spawn.", err);
      }
      await this.audio.preload();
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
    this.cinematic?.cancel();
    this.audio.dispose();
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
    const labels = [];
    if (this.nextPlayableLevel()) labels.push("NEXT LEVEL");
    labels.push("REPLAY LEVEL", "CHARACTER SELECTION", "MAIN MENU");
    const y0 = labels.length > 3 ? 540 : 620;
    return menuButtons(labels, y0, { gap: labels.length > 3 ? 58 : 64 });
  }

  nextPlayableLevel() {
    const nid = nextLevelId(this.world?.id || this.levelId);
    if (!nid) return null;
    if (!levelDataLoads(nid)) return null;
    return nid;
  }

  async onClick(e) {
    await this.audio.unlock();
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
        const y = 196 + i * 78;
        if (p.x >= x && p.x <= x + 760 && p.y >= y && p.y <= y + 72) {
          this.menuIndex = i;
          if (row.kind === "action") {
            this.sfx("ui_back");
            this.closeSettings();
          }
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
      this.sfx("ui_confirm");
      this.handleStart(hit.id);
      return;
    }
    if (st === GameState.CHARACTER_SELECT) {
      const act = this.select.handleClick(p.x, p.y);
      if (act === "focus") this.sfx("ui_hover");
      if (act === "confirm") {
        this.sfx("ui_confirm");
        this.confirmCharacter();
      }
      if (act === "back") {
        this.sfx("ui_back");
        this.goMainMenu({ dispose: true });
      }
      return;
    }
    if (st === GameState.PAUSED) {
      const buttons = this.pauseButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.sfx("ui_confirm");
      this.handlePause(hit.id);
      return;
    }
    if (st === GameState.PLAYER_DEAD && this._deathOverlay) {
      const buttons = this.deathButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.sfx("ui_confirm");
      this.handleDeath(hit.id);
      return;
    }
    if (st === GameState.LEVEL_COMPLETE) {
      const buttons = this.completeButtons();
      const hit = hitMenu(buttons, p.x, p.y);
      if (!hit) return;
      this.menuIndex = buttons.findIndex((b) => b.id === hit.id);
      this.sfx("ui_confirm");
      this.handleComplete(hit.id);
    }
  }

  handleStart(id) {
    if (id === "START GAME") {
      this.overlay = null;
      this.state.set(GameState.CHARACTER_SELECT);
      this.playMenuMusic();
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
    if (id === "NEXT LEVEL") this.advanceToNextLevel();
    if (id === "REPLAY LEVEL") this.restartLevel();
    if (id === "CHARACTER SELECTION") this.goCharacterSelect();
    if (id === "MAIN MENU") this.goMainMenu({ dispose: true });
  }

  advanceToNextLevel() {
    const nid = this.nextPlayableLevel();
    if (!nid) return;
    const character = this.character;
    this.levelId = nid;
    this.checkpoint = null;
    this.projectiles = [];
    this.effects = [];
    this.completed = false;
    this.beginLevel(character);
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
    this.stop();
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
    const prev = this.menuIndex;
    if (this.input.consume("jump") || this.input.consume("moveLeft")) {
      this.menuIndex = moveMenuIndex(this.menuIndex, -1, buttons.length);
    }
    if (this.input.consume("crouch") || this.input.consume("moveRight")) {
      this.menuIndex = moveMenuIndex(this.menuIndex, 1, buttons.length);
    }
    if (this.menuIndex !== prev) this.sfx("ui_hover");
    if (this.input.consume("confirm") && buttons[this.menuIndex]) {
      this.sfx("ui_confirm");
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
    this.sfx("pause");
    this.audio.setGameplayMuted(true);
    this.audio.pauseMusic();
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
    this.audio.setGameplayMuted(false);
    this.audio.resumeMusic();
    this.state.set(GameState.PLAYING);
  }

  onPlayerDied() {
    if (this.state.get() === GameState.PLAYER_DEAD) return;
    this.bossEncounter?.onPlayerDied();
    this.stats.deaths += 1;
    this._deathOverlay = false;
    this.overlay = null;
    this.menuIndex = 0;
    this.inputLocked = true;
    this.input.clearTransient();
    this.audio.setGameplayMuted(true);
    this.sfx("player_death", { force: true });
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
      this.hostileProjectiles = this.hostilePool.clear(this.hostileProjectiles || []);
      this.sfx("game_over", { force: true });
      if (this.audio.hasBuffer("music_game_over")) this.audio.playMusic("music_game_over");
    }
    if (this._deathOverlay) {
      this.updateMenuNav(this.deathButtons(), (id) => this.handleDeath(id));
    }
  }

  requestRespawn() {
    if (this._respawnLock || this.state.is(GameState.RESPAWNING)) return;
    this.audio.unlock();
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
      this.sfx("ui_back");
      this.overlay = null;
      this.menuIndex = 0;
      return;
    }
    this.sfx("ui_confirm");
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
    const prev = this.menuIndex;
    if (this.input.consume("moveLeft") || this.input.consume("jump")) this.menuIndex = 0;
    if (this.input.consume("moveRight") || this.input.consume("crouch")) this.menuIndex = 1;
    this.menuIndex = this.menuIndex ? 1 : 0;
    if (this.menuIndex !== prev) this.sfx("ui_hover");
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
      this.sfx("ui_back");
      this.closeSettings();
      return;
    }
    const prev = this.menuIndex;
    if (this.input.consume("jump")) this.menuIndex = moveMenuIndex(this.menuIndex, -1, rows.length);
    if (this.input.consume("crouch")) this.menuIndex = moveMenuIndex(this.menuIndex, 1, rows.length);
    if (this.menuIndex !== prev) this.sfx("ui_hover");
    const row = rows[this.menuIndex];
    if (!row) return;
    if (this.input.consume("moveLeft")) this.adjustSetting(row, -1);
    if (this.input.consume("moveRight")) this.adjustSetting(row, 1);
    if (this.input.consume("confirm")) {
      if (row.kind === "action") {
        this.sfx("ui_back");
        this.closeSettings();
      } else if (row.kind === "toggle") this.adjustSetting(row, 1);
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
    this.cinematic?.applyMix?.();
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
    this.destroyWaves();
    this.bossEncounter?.destroy();
    this.bossEncounter = null;
    this.cinematic?.cancel();
    this._cinematicActive = false;
    this.world = null;
    this.player = null;
    this.enemies = [];
    this.projectiles = [];
    this.hostileProjectiles = this.hostilePool.clear(this.hostileProjectiles || []);
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
    this._bossMusic = false;
    this.fade = 0;
    this.score = 0;
    this.input.clearTransient();
  }

  goMainMenu() {
    this.disposeLevel();
    this.levelId = STUDIO_01.id;
    this.menuIndex = 0;
    this.showControls = false;
    this.audio.setGameplayMuted(false);
    this.playMenuMusic();
    this.state.set(GameState.START_SCREEN);
  }

  goCharacterSelect() {
    this.disposeLevel();
    this.menuIndex = 0;
    this.playMenuMusic();
    this.state.set(GameState.CHARACTER_SELECT);
  }

  onVisibility() {
    if (document.hidden) {
      this.input.clearTransient();
      this.audio.stopGameplayVoices();
      if (this._cinematicActive) {
        this.cinematic.pause();
        return;
      }
      if (this.state.get() === GameState.PLAYING) {
        this._autoPaused = true;
        this.overlay = null;
        this.menuIndex = 0;
        this.inputLocked = true;
        this.audio.setGameplayMuted(true);
        this.audio.pauseMusic();
        this.state.set(GameState.PAUSED);
      }
      return;
    }
    this.input.clearTransient();
    if (this._cinematicActive) this.cinematic.resume();
  }

  onWindowBlur() {
    this.input.clearTransient();
    this.audio.stopGameplayVoices();
  }

  drawBossHud(ctx) {
    const view = this.bossEncounter?.hudView?.();
    if (!view) return;
    const x = DESIGN_W * 0.22;
    const y = 22;
    const w = DESIGN_W * 0.56;
    const ratio = view.maxHealth ? Math.max(0, Math.min(1, view.health / view.maxHealth)) : 0;
    ctx.save();
    ctx.fillStyle = "rgba(5, 7, 12, 0.78)";
    ctx.fillRect(x, y, w, 72);
    ctx.fillStyle = view.transitioning ? "#22d3ee" : "#e8b84a";
    ctx.font = "bold 16px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(view.name, DESIGN_W / 2, y + 20);
    ctx.fillStyle = view.phase === 2 ? "#67e8f9" : "#cbd5e1";
    ctx.font = "bold 12px sans-serif";
    ctx.fillText(view.title || "", DESIGN_W / 2, y + 38);
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(x + 18, y + 48, w - 36, 14);
    ctx.fillStyle = view.transitioning ? "#22d3ee" : view.phase === 2 ? "#f97316" : "#ef4444";
    ctx.fillRect(x + 18, y + 48, (w - 36) * ratio, 14);
    ctx.restore();
  }

  drawWaveBanner(ctx) {
    const banner = this.waves?.banner;
    if (!banner?.title || this.state.get() !== GameState.PLAYING) return;
    ctx.save();
    ctx.fillStyle = "rgba(5, 7, 12, 0.42)";
    ctx.fillRect(DESIGN_W * 0.28, DESIGN_H * 0.36, DESIGN_W * 0.44, 128);
    ctx.strokeStyle = "rgba(232, 184, 74, 0.65)";
    ctx.strokeRect(DESIGN_W * 0.28, DESIGN_H * 0.36, DESIGN_W * 0.44, 128);
    ctx.textAlign = "center";
    ctx.fillStyle = "#e8b84a";
    ctx.font = "bold 42px sans-serif";
    ctx.fillText(banner.title, DESIGN_W / 2, DESIGN_H * 0.36 + 52);
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 22px sans-serif";
    ctx.fillText(banner.subtitle || "", DESIGN_W / 2, DESIGN_H * 0.36 + 96);
    ctx.restore();
  }

  drawComplete(ctx) {
    const name = this.world?.name || "The Post Suite";
    const ch = this.character?.displayName || this.character?.name || "—";
    const time = formatClock(this.stats.time || this._playTime);
    const title = this.world?.id === "studio_02" ? "PHASE 2 COMPLETE" : this.world?.id === "studio_01" ? "STUDIO 01 CLEAR" : "LEVEL COMPLETE";
    const lines = [
      `Time  ${time}`,
      `Production tokens  ${this.stats.tokens}`,
      `Enemies defeated  ${this.stats.kills}`,
      `Character  ${ch}`,
      `Deaths  ${this.stats.deaths}`,
    ];
    drawMenu(ctx, title, name, this.completeButtons(), { focus: this.menuIndex, titleY: 140 });
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
      this.world = buildWorld(resolveLevel(this.levelId));
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
    this.attachWaves();
    this.attachBossEncounter();
    this.projectiles = [];
    this.hostileProjectiles = this.hostilePool.clear(this.hostileProjectiles || []);
    this.effects = [];
    this.score = 0;
    this.camera.x = 0;
    this.camera.look = 0;
    this.fade = 0;
    this.inputLocked = false;
    this.completed = false;
    this._studioClearAwarded = false;
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
      this.waves?.start();
      const start = this.world.checkpoints.find((c) => c.isStart) || this.world.checkpoints[0];
      if (start) this.captureCheckpoint(start, { silent: true });
    }
    this.hud.invalidate();
    this.camera.snap(this.player.footX - this.camera.w * 0.38, this.player.footY - this.camera.h * 0.7, this.world);
    this.audio.setGameplayMuted(false);
    this._bossMusic = false;
    this._bossWarned = new Set();
    this.playLevelMusic();
    this.state.set(GameState.PLAYING);
  }

  restartLevel() {
    if (!this.character) return;
    this.audio.unlock();
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
      abilityCool: this.player.ability?.cool || 0,
      pickups: Object.fromEntries(this.world.pickups.map((p) => [p.id, p.taken])),
      doors: Object.fromEntries((this.world.doors || []).map((d) => [d.id, d.state])),
      checkpoints: Object.fromEntries((this.world.checkpoints || []).map((c) => [c.id, c.activated])),
      encounters: Object.fromEntries(
        (this.world.encounters || []).map((e) => [e.id, { activated: e.activated, cleared: e.cleared }])
      ),
      defeated: (this.enemies || [])
        .filter((e) => !e.alive && (e.persistent || e.encounterBound))
        .map((e) => e.spawnId),
      waves: this.waves ? this.waves.snapshot() : null,
      bossArena: Boolean(this.checkpoint?.bossArena || this.bossEncounter?.active),
      bossIntroWatched: Boolean(this.checkpoint?.bossIntroWatched || this.bossEncounter?.introPlayed),
      stats: { ...this.stats, time: this._playTime },
    };
    this.spawn = { x: safe.x, y: safe.y };
    if (!opts.silent) {
      this.sfx("checkpoint_activate", { x: safe.x });
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
    if (this.player.ability) {
      this.player.ability.cool = Number.isFinite(snap.abilityCool) ? snap.abilityCool : 0;
      this.player.ability.active = 0;
    }
    this.player.speedMul = 1;
    this.player.damageMul = 1;
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
    this.applyEncounterSnapshot(snap);
    if (this.waves) {
      if (snap.waves) this.waves.applySnapshot(snap.waves);
      else this.waves.start();
    }
    this.hud.invalidate();
  }

  applyEncounterSnapshot(snap) {
    if (!this.world) return;
    const saved = snap?.encounters || {};
    for (const enc of this.world.encounters || []) {
      const rec = saved[enc.id];
      if (rec) {
        enc.activated = Boolean(rec.activated);
        enc.cleared = Boolean(rec.cleared);
      }
      for (const enemy of this.enemies) {
        if (!(enc.enemyIds || []).includes(enemy.spawnId)) continue;
        if (enc.cleared) {
          enemy.alive = false;
          enemy.health = 0;
          enemy.state = "death";
          enemy.deadTimer = 99;
          enemy.activated = true;
        } else if (enc.activated) {
          enemy.activated = true;
        }
      }
    }
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
      if (this.input.consume("moveLeft")) {
        this.select.move(-1);
        this.sfx("ui_hover");
      }
      if (this.input.consume("moveRight")) {
        this.select.move(1);
        this.sfx("ui_hover");
      }
      if (this.input.consume("pause")) {
        this.sfx("ui_back");
        this.goMainMenu({ dispose: true });
        return;
      }
      if (this.input.consume("confirm")) {
        this.sfx("ui_confirm");
        this.confirmCharacter();
      }
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

    if (this._cinematicActive) {
      this.updateCinematicInput();
      return;
    }

    if (this.input.consume("pause")) {
      this.openPause();
      return;
    }

    this._playTime += dt;
    this._worldTime += dt;
    this.waves?.update(dt);
    this.bossEncounter?.update(dt);
    this.inputLocked = Boolean(this.waves?.blocksInput) || Boolean(this.bossEncounter?.blocksInput);
    this.player.update(dt, this.input, this.world, this.projectiles, this);
    this.updateEncounters();
    this.camera.follow(this.player, this.world, dt);
    for (const enemy of this.enemies) {
      enemy.update(dt, this.player, this.world, this.projectiles, this);
    }
    this.updateEnemyContact(dt);
    this.updateProjectiles(dt);
    this.updateEffects(dt);
    this.updatePickups();
    this.updateHazards(dt);
    updateDoors(this.world, dt);
    this.updateDoorsAndExit();
    this.updateCheckpoints();
    if (!this.player.alive) this.onPlayerDied();
  }

  updateEnemyContact(dt) {
    if (!this.player?.alive) return;
    for (const enemy of this.enemies) {
      if (enemy.combatEnabled === false || enemy.hitboxEnabled === false) continue;
      const melee = Boolean(enemy.isBoss && enemy.meleeActive);
      if (melee && enemy.meleeHitOnce) continue;
      const dmg = enemy.spec?.contactDamage || 0;
      if (!enemy.alive || dmg <= 0) continue;
      if (!melee && enemy.contactCool > 0) continue;
      const box = melee && typeof enemy.meleeBounds === "function" ? enemy.meleeBounds() : enemy.bounds();
      if (!aabb(this.player.bounds(), box)) continue;
      const dir = Math.sign(this.player.footX - enemy.footX) || -1;
      const knock = enemy.isBoss
        ? melee
          ? enemy.cfg?.meleeKnockback || 320
          : enemy.state === "charge"
            ? enemy.cfg?.chargeKnockback || 380
            : enemy.cfg?.knockback || 240
        : 220;
      const cool = enemy.isBoss
        ? enemy.state === "charge"
          ? enemy.cfg?.chargeContactCooldown || 0.55
          : enemy.cfg?.contactCooldown || 0.7
        : 0.75;
      const dealt = this.player.takeDamage(dmg, { knockbackX: dir * knock });
      if (!dealt) continue;
      if (melee) enemy.meleeHitOnce = true;
      else enemy.contactCool = cool;
      this.player.footX += dir * (enemy.isBoss ? 52 : 8);
      this.player._syncBox?.();
      if (this.shakeEnabled()) this.camera.addShake(enemy.isBoss ? 0.55 : 0.35);
      this.hud.invalidate();
      if (this.player.alive) this.sfx("player_hit");
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
      if (this.shakeEnabled()) this.camera.addShake(0.45);
      h.cool = h.cooldown;
      this.hud.invalidate();
      if (this.player.alive) this.sfx("player_hit");
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
        this.sfx("door_open", { x: exit.x });
        this.hud.invalidate();
      }
    }
    for (const door of this.world.doors || []) {
      if (door.state === "open" || door.state === "opening") continue;
      if (!aabb(bounds, door.trigger || door)) continue;
      if (tryOpenDoor(door, this.player, this.world)) {
        syncDoorSolids(this.world);
        this.sfx("door_open", { x: door.x });
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
    this.waves?.destroy();
    this.inputLocked = true;
    this.stats.time = this._playTime;
    this.overlay = null;
    this.menuIndex = 0;
    this.input.clearTransient();
    for (const shot of this.projectiles) {
      if (shot.owner === "enemy") shot.disable();
    }
    this.projectiles = this.projectiles.filter((p) => p.alive);
    this.hostileProjectiles = this.hostilePool.clear(this.hostileProjectiles || []);
    const done = loadSettings().completedLevels || [];
    const patch = {};
    if (this.world?.id && !done.includes(this.world.id)) {
      patch.completedLevels = [...done, this.world.id];
    }
    if (this.world?.id === "studio_02") patch.phase2Complete = true;
    if (Object.keys(patch).length) this.settings = saveSettings(patch);
    this.hud.invalidate();
    this.audio.setGameplayMuted(true);
    this.sfx("level_complete", { force: true });
    this.audio.stopMusic(0.25);
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
      this.world = buildWorld(resolveLevel(this.levelId));
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
    this.attachWaves();
    this.attachBossEncounter();
    this.projectiles = [];
    this.hostileProjectiles = this.hostilePool.clear(this.hostileProjectiles || []);
    this.effects = [];
    if (snap) this.applySnapshot(snap);
    else {
      this.waves?.start();
      this.captureCheckpoint(this.world.checkpoints.find((c) => c.isStart), { silent: true });
    }
    this.player.alive = true;
    this.player.health = Math.max(1, this.player.health);
    this.inputLocked = false;
    this._deathOverlay = false;
    this._bossMusic = false;
    this.hud.invalidate();
    this.audio.setGameplayMuted(false);
    if (snap?.bossArena && this.world?.boss) {
      this.bossEncounter?.restartCombat();
    } else {
      this.playLevelMusic();
    }
  }

  spawnEnemies() {
    const defeated = new Set(this.checkpoint?.defeated || []);
    this.enemies = [];
    (this.world.enemySpawns || []).forEach((s, i) => {
      const spawnId = s.id || `${s.type}_${i}`;
      const typeId = migrateEnemyType(s.type);
      if (!ENEMY_TYPES[typeId]) {
        console.error(`[Producer Hunt] Enemy creation failed: unknown type "${s.type}" id=${spawnId}`);
        return;
      }
      const bound = (this.world.encounters || []).some((enc) => (enc.enemyIds || []).includes(spawnId));
      let enemy;
      try {
        const kit = this.assets.enemyKit(typeId) || ENEMY_TYPES[typeId].sprite;
        enemy = new Enemy(
          typeId,
          {
            id: spawnId,
            x: s.x,
            y: s.y,
            patrolMin: s.patrolMin,
            patrolMax: s.patrolMax,
            activateRange: s.activateRange,
            activated: !bound,
          },
          kit
        );
      } catch (err) {
        console.error(`[Producer Hunt] Enemy creation failed: type=${typeId} id=${spawnId} reason=${err}`);
        return;
      }
      enemy.spawnId = spawnId;
      enemy.encounterBound = bound;
      enemy.persistent = Boolean(s.persistent) || bound;
      if (enemy.persistent && defeated.has(spawnId)) {
        enemy.alive = false;
        enemy.health = 0;
        enemy.state = "death";
        enemy.deadTimer = 99;
      } else {
        const issues = enemySpawnSafetyIssues(this.world, enemy);
        if (issues.length) {
          console.warn(
            `[Producer Hunt] Unsafe enemy spawn: type=${enemy.type} id=${spawnId} ${issues.join("; ")}`
          );
        }
        if (this.allowDebug) {
          console.info(
            `[Producer Hunt] Spawned enemy:\ntype=${enemy.type}\nid=${spawnId}\nposition=${enemy.footX},${enemy.footY}\nlevel=${this.world.id || this.levelId}`
          );
        }
      }
      this.enemies.push(enemy);
    });
    this.applyEncounterSnapshot(this.checkpoint);
  }

  destroyWaves() {
    this.waves?.destroy();
    this.waves = null;
  }

  attachWaves() {
    this.destroyWaves();
    if ((this.world?.waves || []).length) {
      this.waves = new WaveController(this, this.world.waves);
    }
  }

  attachBossEncounter() {
    this.bossEncounter?.destroy();
    this.bossEncounter = this.world?.boss ? new BossEncounter(this) : null;
  }

  onStudioWavesCleared() {
    if (!this.world?.boss) {
      this.awardStudioClear();
      return;
    }
    this.bossEncounter?.begin();
  }

  acquireHostileShot(opts) {
    const shot = this.hostilePool.acquire(opts);
    this.hostileProjectiles.push(shot);
    return shot;
  }

  syncWaveCheckpoint() {
    if (!this.checkpoint || !this.waves) return;
    this.checkpoint.waves = this.waves.snapshot();
  }

  spawnWaveEnemy(typeId, modifiers = null, opts = {}) {
    const type = migrateEnemyType(typeId);
    if (!ENEMY_TYPES[type]) {
      console.error(`[Producer Hunt] Enemy creation failed: unknown type "${typeId}"`);
      return null;
    }
    const spec = ENEMY_TYPES[type];
    const kit = this.assets.enemyKit(type) || spec.sprite;
    const body = {
      w: spec.sprite?.collisionWidth || 88,
      h: spec.sprite?.collisionHeight || 210,
    };
    const pos = pickWaveSpawn(this.world, this.player, this.enemies, body);
    const spawnId = opts.id || `wave_${this.waves?.waveIndex ?? 0}_${this.waves?.spawned ?? this.enemies.length}`;
    let enemy;
    try {
      enemy = new Enemy(
        type,
        {
          id: spawnId,
          x: pos.x,
          y: pos.y,
          patrolMin: pos.x - 140,
          patrolMax: pos.x + 140,
          activateRange: 2800,
          activated: true,
        },
        kit
      );
    } catch (err) {
      console.error(`[Producer Hunt] Enemy creation failed: type=${type} id=${spawnId} reason=${err}`);
      return null;
    }
    enemy.spawnId = spawnId;
    enemy.waveTracked = true;
    enemy.persistent = false;
    enemy.applyWaveModifiers(modifiers);
    if (Number.isFinite(opts.health)) enemy.health = Math.max(1, opts.health);
    enemy.onWaveExit = (e, reason) => this.waves?.onEnemyExit(e, reason);
    const issues = enemySpawnSafetyIssues(this.world, enemy);
    if (issues.length) {
      console.warn(`[Producer Hunt] Unsafe enemy spawn: type=${enemy.type} id=${spawnId} ${issues.join("; ")}`);
    }
    if (this.allowDebug) {
      console.info(
        `[Producer Hunt] Spawned enemy:\ntype=${enemy.type}\nid=${spawnId}\nposition=${enemy.footX},${enemy.footY}\nlevel=${this.world.id || this.levelId}`
      );
    }
    this.enemies.push(enemy);
    return enemy;
  }

  awardStudioClear() {
    if (this._studioClearAwarded || this.completed) return;
    this._studioClearAwarded = true;
    this.score += STUDIO_CLEAR_BONUS;
    const enc = (this.world?.encounters || []).find((e) => e.id === "enc_final");
    if (enc) {
      enc.activated = true;
      enc.cleared = true;
    }
    if (this.world) this.world.wavesComplete = true;
    this.hud.invalidate();
    this.completeLevel();
  }

  updateEncounters() {
    const px = this.player?.footX ?? 0;
    for (const enc of this.world.encounters || []) {
      const wasCleared = Boolean(enc.cleared);
      if (!enc.activated && !enc.boss && px >= enc.activateX) enc.activated = true;
      if (enc.activated) {
        for (const enemy of this.enemies) {
          if ((enc.enemyIds || []).includes(enemy.spawnId)) enemy.activated = true;
        }
      }
      enc.cleared =
        (enc.enemyIds || []).length > 0
          ? (enc.enemyIds || []).every((id) => {
              const enemy = this.enemies.find((e) => e.spawnId === id);
              if (!enemy) return true;
              return !enemy.alive && (enemy.anim?.finished || enemy.deadTimer > 0.85);
            })
          : Boolean(enc.cleared);
      if (!wasCleared && enc.cleared) {
        for (const shot of this.projectiles) {
          if (shot.owner === "enemy") shot.disable();
        }
        this.projectiles = this.projectiles.filter((p) => p.alive);
      }
    }
    this.updateBossMusic();
  }

  updateBossMusic() {
    if (this._cinematicActive || this.bossEncounter?.phase === "intro") return;
    if (this.state.get() !== GameState.PLAYING || !this.world) return;
    const bossEnc = (this.world.encounters || []).find((enc) => enc.boss && enc.activated && !enc.cleared);
    if (bossEnc) {
      if (!this._bossWarned.has(bossEnc.id)) {
        this._bossWarned.add(bossEnc.id);
        this.sfx("boss_warning", { force: true });
      }
      if (!this._bossMusic) {
        this._bossMusic = true;
        this.playBossMusic();
      }
      return;
    }
    if (this._bossMusic) {
      this._bossMusic = false;
      this.playLevelMusic();
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

  spawnImpact(shot, opts = {}) {
    const fx = shot.impactFx || COMBAT.player.impactFx;
    const c = shot.center ? shot.center() : { x: shot.x + shot.w / 2, y: shot.y + shot.h / 2 };
    if (opts.sfx) this.sfx("projectile_impact", { x: c.x });
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

  handlePlayerProjectileHit(a, b) {
    const projectile = a?.owner === "player" ? a : b?.owner === "player" ? b : null;
    const enemy = projectile === a ? b : projectile === b ? a : null;
    if (!projectile?.alive || projectile.spent || projectile.hasHit) return false;
    if (projectile.faction === "boss" || projectile.owner === "enemy") return false;
    if (!enemy?.alive || typeof enemy.takeDamage !== "function") return false;
    if (enemy.hitboxEnabled === false) return false;
    const travel = typeof projectile.travelBounds === "function" ? projectile.travelBounds() : projectile.bounds();
    if (!aabb(travel, enemy.bounds()) && !aabb(projectile.bounds(), enemy.bounds())) return false;
    projectile.hasHit = true;
    const damage = Number(projectile.damage ?? 1);
    const wasDying = Boolean(enemy.deathStarted);
    this.score += enemy.takeDamage(damage, projectile);
    if (enemy.isBoss) {
      if (enemy.deathStarted && !wasDying) this.sfx("enemy_death", { x: enemy.footX });
      else if (!enemy.deathStarted) this.sfx("enemy_hit", { x: enemy.footX });
    } else if (!enemy.alive) {
      this.stats.kills += 1;
      this.sfx("enemy_death", { x: enemy.footX });
    } else {
      this.sfx("enemy_hit", { x: enemy.footX });
    }
    this.spawnImpact(projectile);
    projectile.disable();
    this.hud.invalidate();
    return true;
  }

  _stepProjectile(shot, dt, { hostile = false } = {}) {
    if (!shot.alive || shot.spent) return;
    shot.update(dt);
    if (!shot.alive) return;
    if (shot.x < -40 || shot.x > this.world.width + 40 || shot.y < -80 || shot.y > (this.world.height || DESIGN_H) + 80) {
      shot.disable();
      return;
    }
    const travel = typeof shot.travelBounds === "function" ? shot.travelBounds() : shot.bounds();
    if (hitsSolid(travel, this.world.solids)) {
      this.spawnImpact(shot, { sfx: true });
      shot.disable();
      return;
    }
    if (shot.owner === "player") {
      for (const enemy of this.enemies) {
        if (!enemy.alive) continue;
        if (this.handlePlayerProjectileHit(shot, enemy)) break;
      }
      return;
    }
    if (shot.owner === "enemy") {
      if (shot.faction === "boss") {
        const st = this.bossEncounter?.boss?.state;
        if (st === "spawning" || st === "death" || st === "complete" || this.bossEncounter?.phase === "intro") {
          shot.disable();
          return;
        }
      }
      if (this.player.alive && aabb(shot.bounds(), this.player.bounds())) {
        const dir = Math.sign(shot.vx) || Math.sign(this.player.footX - shot.x) || 1;
        const knock = shot.interruptMove ? dir * 420 : dir * 160;
        const dealt = this.player.takeDamage(shot.damage, shot.interruptMove ? { knockbackX: knock } : {});
        if (dealt) {
          this.sfx("player_hit");
          if (this.shakeEnabled()) this.camera.addShake(0.55);
          this.hud.invalidate();
        }
        this.spawnImpact(shot);
        shot.disable();
      }
    }
  }

  updateProjectiles(dt) {
    for (const shot of this.projectiles) this._stepProjectile(shot, dt);
    for (const shot of this.hostileProjectiles) this._stepProjectile(shot, dt, { hostile: true });
    this.projectiles = this.projectiles.filter((p) => p.alive);
    const kept = [];
    for (const shot of this.hostileProjectiles) {
      if (shot.alive) kept.push(shot);
      else this.hostilePool.release(shot);
    }
    this.hostileProjectiles = kept;
    this.enemies = this.enemies.filter((e) => {
      if (e.isBoss && this.bossEncounter && this.bossEncounter.phase !== "idle" && this.bossEncounter.phase !== "complete") {
        return true;
      }
      if (e.alive) {
        if (this.world && e.footY > (this.world.height || DESIGN_H) + 24) {
          e.notifyWaveExit?.("invalid");
          return false;
        }
        return true;
      }
      if (e.anim && e.anim.name === "death" && !e.anim.finished) return true;
      if (e.deadTimer >= 0.9) e.notifyWaveExit?.("removed");
      return e.deadTimer < 0.9;
    });
  }

  updatePickups() {
    for (const pickup of this.world.pickups) {
      if (pickup.taken || pickup.reserved) continue;
      if (!aabb(this.player.bounds(), pickup)) continue;
      if (!applyPickup(pickup, this.player, this)) continue;
      if (pickup.kind === "production_token" || pickup.kind === "bonus") this.stats.tokens += 1;
      this.sfx(pickupSoundId(pickup.effect), { x: pickup.x });
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
    for (const shot of this.hostileProjectiles || []) shot.draw(ctx, this.camera);
    if (this.world) drawDecorSheet(ctx, this.assets, "props", this.world.props, this.camera, 128, "front");
    for (const fx of this.effects) fx.draw(ctx, this.camera, drawSheetFrame);
    if (this.fade > 0) {
      ctx.fillStyle = `rgba(5, 7, 12, ${this.fade})`;
      ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    }
    if (this.player && this.state.is(GameState.PLAYING, GameState.RESPAWNING)) {
      const wave = this.waves?.hud;
      this.hud.draw(ctx, {
        player: this.player,
        score: this.score,
        assets: this.assets,
        objective: currentObjective(this.world, this.player),
        wave,
      });
      this.drawBossHud(ctx);
      this.drawWaveBanner(ctx);
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
    const drawBox = (box, color) => {
      if (!box) return;
      const s = this.camera.worldToScreen(box.x, box.y);
      ctx.strokeStyle = color;
      ctx.strokeRect(s.x, s.y, box.w, box.h);
    };
    if (p) p.drawAssetDebug(ctx, this.camera, this.world);
    for (const e of this.enemies) e.drawAssetDebug(ctx, this.camera);
    for (const shot of this.projectiles) {
      if (!shot.alive) continue;
      drawBox(shot.bounds(), shot.owner === "player" ? "rgba(253,224,71,0.95)" : "rgba(248,113,113,0.95)");
    }
    for (const h of this.world?.hazards || []) {
      if (h.enabled) drawBox(h, "rgba(250,204,21,0.9)");
    }
    for (const d of this.world?.doors || []) {
      drawBox(d, d.state === "open" ? "rgba(74,222,128,0.9)" : "rgba(248,113,113,0.9)");
      drawBox(d.trigger, "rgba(96,165,250,0.7)");
    }
    for (const cp of this.world?.checkpoints || []) drawBox(cp, "rgba(45,212,191,0.9)");
    for (const enc of this.world?.encounters || []) {
      const s = this.camera.worldToScreen(enc.activateX, 0);
      ctx.strokeStyle = enc.activated ? "rgba(74,222,128,0.85)" : "rgba(251,113,133,0.9)";
      ctx.beginPath();
      ctx.moveTo(s.x, 80);
      ctx.lineTo(s.x, DESIGN_H - 40);
      ctx.stroke();
      ctx.fillStyle = enc.activated ? "#86efac" : "#fb7185";
      ctx.font = "12px monospace";
      ctx.fillText(enc.id, s.x + 6, 96);
    }
  }
}
