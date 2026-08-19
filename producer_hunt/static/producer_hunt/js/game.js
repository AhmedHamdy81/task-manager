import { DEBUG_ASSETS, DESIGN_H, DESIGN_W } from "./config.js";
import { GameState, GameStateManager } from "./game-state.js";
import { Input } from "./input.js";
import { Camera } from "./camera.js";
import { Player } from "./player.js";
import { ENEMY_TYPES, Enemy } from "./enemy.js";
import { HUD } from "./hud.js";
import { CharacterSelect } from "./character-select.js";
import { aabb, hitsSolid } from "./collision.js";
import { LEVEL_01, buildWorld } from "./levels/level-01.js";
import { AssetLoader } from "./asset-loader.js";
import { WORLD_SHEETS, drawCoverImage, drawSheetFrame } from "./asset-catalog.js";
import { AudioManager } from "./audio.js";
import { drawButtons, drawMenu, hitMenu, menuButtons } from "./ui.js";
import { CHARACTERS } from "./characters.js";
import { FxSprite } from "./fx.js";
import {
  drawDecorSheet,
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
    this.assets = new AssetLoader(options.assetBase || "");
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
      await this.assets.loadEnemyKit(ENEMY_TYPES.assistant_producer.sprite);
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
      if (this.select.handleClick(p.x, p.y)) this.beginLevel(this.select.selected);
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

  beginLevel(character) {
    this.character = character;
    this.world = buildWorld(LEVEL_01);
    this.spawn = { ...this.world.spawn };
    const kit = this.assets.characterKit(character.id);
    this.player = new Player(character, this.spawn, kit);
    this.enemies = this.world.enemySpawns.map(
      (s) =>
        new Enemy(s.type, { x: s.x, y: s.y, patrolMin: s.patrolMin, patrolMax: s.patrolMax }, this.assets.enemyKit(s.type))
    );
    this.projectiles = [];
    this.effects = [];
    this.score = 0;
    this.camera.x = 0;
    this.camera.look = 0;
    this.state.set(GameState.PLAYING);
  }

  restartLevel() {
    if (!this.character) return;
    this.beginLevel(this.character);
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
      if (this.input.consume("confirm")) this.beginLevel(this.select.selected);
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
    if (!this.state.is(GameState.PLAYING, GameState.PLAYER_DEAD)) return;

    if (st === GameState.PLAYING && this.input.consume("pause")) {
      this.state.set(GameState.PAUSED);
      return;
    }

    const ctx = this;
    if (st === GameState.PLAYING) {
      this.player.update(dt, this.input, this.world, this.projectiles, ctx);
      this.camera.follow(this.player, this.world, dt);
      for (const enemy of this.enemies) {
        enemy.update(dt, this.player, this.world);
        enemy.tryAttack(this.player);
      }
      this.updateProjectiles(dt);
      this.updateEffects(dt);
      this.updatePickups();
      const cp = this.world.checkpoints.find((c) => aabb(this.player.bounds(), c));
      if (cp) this.spawn = { x: this.player.footX, y: this.player.footY };
      if (aabb(this.player.bounds(), this.world.end)) {
        this.state.set(GameState.LEVEL_COMPLETE);
        return;
      }
      if (!this.player.alive) this.state.set(GameState.PLAYER_DEAD);
      return;
    }

    if (st === GameState.PLAYER_DEAD) {
      this.player.update(dt, this.input, this.world, this.projectiles, ctx);
      this.updateEffects(dt);
      if (this.player.deadTimer > 0.85) this.state.set(GameState.GAME_OVER);
    }
  }

  spawnFx(opts) {
    const sheet = this.assets.sheet(opts.sheetKey || "effects");
    this.effects.push(
      new FxSprite({
        sheet,
        frame: opts.frame || 0,
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
    this.spawnFx({
      sheetKey: "projectiles",
      frame: 6,
      x: shot.x + shot.w / 2,
      y: shot.y + shot.h / 2,
      size: 48,
      life: 0.16,
    });
  }

  updateProjectiles(dt) {
    for (const shot of this.projectiles) {
      shot.update(dt);
      let hit = false;
      if (shot.x < -40 || shot.x > this.world.width + 40) {
        shot.alive = false;
      }
      if (shot.alive && hitsSolid(shot.bounds(), this.world.solids)) {
        shot.alive = false;
        hit = true;
      }
      if (shot.alive && shot.owner === "player") {
        for (const enemy of this.enemies) {
          if (!enemy.alive) continue;
          if (aabb(shot.bounds(), enemy.bounds())) {
            this.score += enemy.takeDamage(shot.damage);
            shot.alive = false;
            hit = true;
            break;
          }
        }
      }
      if (hit) this.spawnImpact(shot);
    }
    this.projectiles = this.projectiles.filter((p) => p.alive);
    this.enemies = this.enemies.filter((e) => e.alive || e.deadTimer < 0.55);
  }

  updatePickups() {
    for (const pickup of this.world.pickups) {
      if (pickup.taken || !aabb(this.player.bounds(), pickup)) continue;
      pickup.taken = true;
      this.spawnFx({
        sheetKey: "effects",
        frame: 6,
        x: pickup.x + pickup.w / 2,
        y: pickup.y + pickup.h / 2,
        size: 72,
        life: 0.28,
      });
      if (pickup.kind === "ammo") this.player.weapon.addAmmo(pickup.amount);
      if (pickup.kind === "health") {
        this.player.health = Math.min(this.player.maxHealth, this.player.health + pickup.amount);
      }
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
      ctx.fillStyle = "#0c1220";
      ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
      this.select.draw(ctx, this.assets);
      return;
    }

    if (this.world) this.drawWorld(ctx);
    for (const enemy of this.enemies) enemy.draw(ctx, this.camera);
    for (const shot of this.projectiles) shot.draw(ctx, this.camera);
    if (this.player) this.player.draw(ctx, this.camera);
    for (const fx of this.effects) fx.draw(ctx, this.camera, drawSheetFrame);
    if (this.player && this.state.is(GameState.PLAYING, GameState.PAUSED, GameState.PLAYER_DEAD)) {
      this.hud.draw(ctx, { player: this.player, score: this.score, assets: this.assets });
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

    if (!drawTiledPlatforms(ctx, this.assets, this.world.solids, cam)) {
      for (const solid of this.world.solids) {
        const s = cam.worldToScreen(solid.x, solid.y);
        ctx.fillStyle = "#3f3a32";
        ctx.fillRect(s.x, s.y, solid.w, solid.h);
        ctx.fillStyle = "#c9a227";
        ctx.fillRect(s.x, s.y, solid.w, 5);
      }
    }

    drawDecorSheet(ctx, this.assets, "props", this.world.props, cam, 128);
    drawDecorSheet(ctx, this.assets, "hazards", this.world.hazards, cam, 128);
    drawPickups(ctx, this.assets, this.world.pickups, cam);
    drawProgression(ctx, this.assets, this.world, cam);
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
    ];
    lines.forEach((l, i) => ctx.fillText(l, DESIGN_W - 364, 50 + i * 22));
    ctx.strokeStyle = "#38bdf8";
    ctx.strokeRect(1, 1, DESIGN_W - 2, DESIGN_H - 2);
    if (p) p.drawAssetDebug(ctx, this.camera, this.world);
    for (const e of this.enemies) e.drawAssetDebug(ctx, this.camera);
  }
}
