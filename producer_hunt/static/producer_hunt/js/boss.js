import { DESIGN_H, DEBUG_REPLAY_BOSS_INTRO } from "./config.js";
import { instantiatePickup } from "./pickups.js";
import { BOSS_01 } from "./combat.js";
import { Projectile } from "./projectile.js";
import {
  BOSS_STATES,
  BossEnemy,
  drawBossDebug,
  scaleBossConfig,
} from "./boss-brain.js";

export { BOSS_STATES, BossEnemy, drawBossDebug, scaleBossConfig };

const ENCOUNTER = {
  idle: "idle",
  pending: "pending",
  intro: "intro",
  spawn: "spawn",
  combat: "combat",
  dying: "dying",
  defeat_cinematic: "defeat_cinematic",
  complete: "complete",
};

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
    this.cfg = BOSS_01;
    this.introPlayed = false;
    this.clearBanner = false;
    this._phaseClear = false;
    this.dropTimer = 0;
    this.dropIndex = 0;
    this.defeatSequenceStarted = false;
    this.defeatVideoPlayed = false;
    this._defeatFinished = false;
    this._musicFaded = false;
    this.displayedHealth = 0;
  }

  destroy() {
    this.game.cinematic?.cancel();
    this.unlockArena();
    this.clearHealthDrops();
    this.clearHostile();
    if (this.boss) {
      this.game.enemies = (this.game.enemies || []).filter((e) => e !== this.boss);
    }
    this.reset();
  }

  get active() {
    return this.phase !== ENCOUNTER.idle && this.phase !== ENCOUNTER.complete;
  }

  get blocksInput() {
    if (this.phase === ENCOUNTER.intro || this.phase === ENCOUNTER.spawn) return true;
    if (this.phase === ENCOUNTER.dying || this.phase === ENCOUNTER.defeat_cinematic) return true;
    return Boolean(this.boss && (this.boss.state === BOSS_STATES.ready || this.boss.state === BOSS_STATES.spawning));
  }

  hudView() {
    if (!this.hudVisible || !this.boss) return null;
    if (this.phase === ENCOUNTER.complete) return null;
    if (this.phase === ENCOUNTER.dying || this.phase === ENCOUNTER.defeat_cinematic) return null;
    if (this.boss.state === BOSS_STATES.completed || this.boss.state === BOSS_STATES.complete) return null;
    const health = Math.max(0, this.boss.health);
    this.displayedHealth += (health - (this.displayedHealth ?? health)) * 0.18;
    return {
      name: this.cfg.displayName,
      title: this.cfg.title,
      health,
      displayedHealth: this.displayedHealth,
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

  start(opts = {}) {
    if (this.phase === ENCOUNTER.intro || this.phase === ENCOUNTER.spawn || this.phase === ENCOUNTER.combat) {
      return;
    }
    this.clearHostile();
    this._removeBosses();
    this.timer = 0;
    this.warningOnce = false;
    this.spawnedOnce = false;
    this.hudVisible = false;
    this.scoreAwarded = false;
    this.clearBanner = false;
    this.cfg = this.game.world?.boss || BOSS_01;
    const enc = (this.game.world?.encounters || []).find((e) => e.boss);
    if (enc) enc.activated = true;
    this.lockArena();
    this.captureArenaCheckpoint();
    if (this.game.waves) this.game.waves.banner = null;
    this.game.hud?.invalidate();
    const skipIntro = Boolean(opts.skipIntro) && !DEBUG_REPLAY_BOSS_INTRO;
    if (skipIntro) {
      this.afterIntro("skipped-run");
      return;
    }
    this.phase = ENCOUNTER.intro;
    this.game.playBossIntro({
      onComplete: () => this.afterIntro("intro"),
    });
  }

  afterIntro() {
    if (this.phase === ENCOUNTER.spawn || this.phase === ENCOUNTER.combat) return;
    this.introPlayed = true;
    if (this.game.checkpoint) this.game.checkpoint.bossIntroWatched = true;
    this.game.audio?.setGameplayMuted?.(false);
    // Let playBossMusic mark the flag only after the post-video audio context
    // is unlocked and a real (or level fallback) track has been selected.
    this.game._bossMusic = false;
    this.game._bossWarned.add("enc_final");
    this.placePlayerCombatStart();
    this.phase = ENCOUNTER.spawn;
    this.timer = 0;
    this.spawnBoss();
    this.hudVisible = true;
    this.game.playBossMusic();
    this.game.scoreboard?.markBossFight?.();
    if (this.game.waves) {
      this.game.waves.banner = { title: this.cfg.displayName, subtitle: this.cfg.title };
    }
    this.captureArenaCheckpoint();
    this.game.hud?.invalidate();
  }

  restartCombat() {
    this.unlockArena();
    this.clearHealthDrops();
    this.clearHostile();
    this._removeBosses();
    this.game.cinematic?.cancel();
    this.phase = ENCOUNTER.idle;
    this.begin();
    this.spawnedOnce = false;
    this.scoreAwarded = false;
    this.defeatSequenceStarted = false;
    this.defeatVideoPlayed = false;
    this._defeatFinished = false;
    this._musicFaded = false;
    const watched = Boolean(this.game.checkpoint?.bossIntroWatched);
    this.start({ skipIntro: watched && !DEBUG_REPLAY_BOSS_INTRO });
  }

  onPlayerDied() {
    if (this.boss) {
      this.boss.combatEnabled = false;
      this.boss.hitboxEnabled = false;
      this.boss.vx = 0;
      this.boss.clearMelee();
      this.boss.cancelTimers?.();
      if (this.boss.state !== BOSS_STATES.death && this.boss.state !== BOSS_STATES.completed && this.boss.state !== BOSS_STATES.complete) {
        this.boss.state = BOSS_STATES.choose_attack;
      }
    }
    this.clearHostile();
    this.clearHealthDrops();
  }

  clearHealthDrops() {
    const world = this.game.world;
    if (world?.pickups) world.pickups = world.pickups.filter((p) => !p.bossDrop);
    this.dropTimer = 0;
  }

  _updateHealthDrops(dt) {
    if (this.boss?.state === BOSS_STATES.phase_transition) return;
    if (this.boss?.deathStarted || this.boss?.state === BOSS_STATES.death) return;
    const interval = this.cfg.healthDropSec || 15;
    this.dropTimer += dt;
    if (this.dropTimer < interval) return;
    if (!this._spawnHealthDrop()) return;
    this.dropTimer = 0;
  }

  _spawnHealthDrop() {
    const world = this.game.world;
    if (!world) return false;
    const max = this.cfg.healthDropMax || 2;
    world.pickups = (world.pickups || []).filter((p) => !p.bossDrop || !p.taken);
    const live = world.pickups.filter((p) => p.bossDrop && !p.taken);
    if (live.length >= max) return false;
    const arena = this.arenaBox();
    const ground = arena.groundY ?? world.ground?.y ?? 960;
    const spots = [
      { x: arena.left + 120, y: ground - 64 },
      { x: (arena.left + arena.right) / 2 - 32, y: ground - 64 },
      { x: arena.right - 180, y: ground - 64 },
    ];
    const spot = spots[this.dropIndex % spots.length];
    this.dropIndex += 1;
    const pickup = instantiatePickup(
      {
        id: `boss_health_drop_${this.dropIndex}`,
        kind: "health",
        x: spot.x,
        y: spot.y,
      },
      this.dropIndex,
      world.id
    );
    pickup.bossDrop = true;
    pickup.ephemeral = true;
    pickup.persistence = "session";
    pickup.respawn = false;
    world.pickups.push(pickup);
    return true;
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

  playerInArena(opts = {}) {
    const player = this.game.player;
    const arena = this.arenaBox();
    if (!player || !arena) return false;
    const pad = opts.pad ?? 48;
    return player.footX >= arena.left - pad && player.footX <= arena.right + pad;
  }

  placePlayerCombatStart() {
    const player = this.game.player;
    const arena = this.arenaBox();
    if (!player || !arena) return;
    player.footX = arena.left + 150;
    player.footY = arena.groundY ?? player.footY;
    player.vx = 0;
    player.vy = 0;
    player.direction = 1;
    player.facing = 1;
    player._syncBox?.();
  }

  _removeBosses() {
    this.game.enemies = (this.game.enemies || []).filter((e) => !e.isBoss);
    this.boss = null;
    this.hudVisible = false;
  }

  clearHostile() {
    const game = this.game;
    if (!game.hostilePool) game.hostilePool = new HostileProjectilePool();
    game.hostileProjectiles = game.hostilePool.clear(game.hostileProjectiles || []);
    for (const shot of game.projectiles || []) {
      if (shot.owner === "enemy" || shot.faction === "boss") shot.disable();
    }
    game.projectiles = (game.projectiles || []).filter((p) => p.alive);
    this.boss?.clearMelee?.();
    if (game.dangerZones) {
      game.dangerZones = game.dangerZones.filter((z) => z.owner !== "boss" && z.kind !== "fall_mark");
    }
  }

  spawnBoss() {
    if (this.spawnedOnce && this.boss) return this.boss;
    this._removeBosses();
    const arena = this.arenaBox();
    const kit = this.game.assets.enemyKit("boss_01");
    const spawn = {
      id: "boss_01",
      x: arena.right - 180,
      y: arena.groundY ?? this.game.world.ground?.y ?? 960,
      activated: true,
      activateRange: 4000,
      arena,
    };
    const scaled = scaleBossConfig(this.cfg, this.game.settings?.difficulty);
    const boss = new BossEnemy(spawn, kit, scaled);
    boss.health = scaled.maxHealth;
    this.cfg = { ...this.cfg, maxHealth: scaled.maxHealth, scoreValue: this.cfg.scoreValue };
    this.displayedHealth = scaled.maxHealth;
    boss.phase = 1;
    boss.phaseShifted = false;
    boss.direction = -1;
    boss._applyFacingFlip();
    boss.spawnId = spawn.id;
    this.game.enemies.push(boss);
    this.boss = boss;
    this.spawnedOnce = true;
    this.hudVisible = true;
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
      this.game.checkpoint.bossIntroWatched = Boolean(this.game.checkpoint.bossIntroWatched || this.introPlayed);
      this.game.checkpoint.waves = this.game.waves?.snapshot?.() || this.game.checkpoint.waves;
    }
  }

  update(dt) {
    if (this.phase === ENCOUNTER.idle || this.phase === ENCOUNTER.complete) return;
    this.timer += dt;

    if (this.phase === ENCOUNTER.pending) {
      const living = (this.game.enemies || []).some((e) => e.alive && !e.isBoss);
      const shots = (this.game.projectiles || []).some((p) => p.alive && p.owner === "enemy");
      if (living || shots) return;
      if (!this.playerInArena()) return;
      this.start();
      return;
    }

    if (this.phase === ENCOUNTER.intro) return;

    if (this.phase === ENCOUNTER.spawn) {
      if (!this.boss) this.spawnBoss();
      if (this.timer > 2.4 && this.game.waves?.banner?.title === this.cfg.displayName) {
        this.game.waves.banner = null;
      }
      if (this.boss && this.boss.state !== BOSS_STATES.ready && this.boss.state !== BOSS_STATES.spawning) {
        this.phase = ENCOUNTER.combat;
        this.hudVisible = true;
        this.game.hud?.invalidate();
      }
      return;
    }

    if (this.phase === ENCOUNTER.combat) {
      this._updateHealthDrops(dt);
      if (this.boss?.state === BOSS_STATES.phase_transition) {
        if (!this._phaseClear) {
          this._phaseClear = true;
          this.boss.clearMelee();
          this.clearHostile();
        }
        this.game.hud?.invalidate();
      } else {
        this._phaseClear = false;
      }
      if (this.boss && (this.boss.deathStarted || this.boss.state === BOSS_STATES.death)) {
        this.phase = ENCOUNTER.dying;
        this.timer = 0;
        this._lockOutCombat();
        this._fadeBossMusic();
      }
      return;
    }

    if (this.phase === ENCOUNTER.dying) {
      if (this.boss && (this.boss.state === BOSS_STATES.completed || this.boss.state === BOSS_STATES.complete)) {
        this.startDefeatSequence();
      }
      return;
    }

    if (this.phase === ENCOUNTER.defeat_cinematic) return;
  }

  _lockOutCombat() {
    if (this.boss) {
      this.boss.hitboxEnabled = false;
      this.boss.combatEnabled = false;
      this.boss.vx = 0;
      this.boss.cancelTimers?.();
    }
    this.clearHostile();
    this.clearHealthDrops();
    const game = this.game;
    if (game?.player) {
      game.player.vx = 0;
      game.player.vy = 0;
    }
    game?.cancelActivePowers?.();
    if (game) {
      for (const shot of game.projectiles || []) {
        if (shot.owner === "enemy" || shot.faction === "boss") shot.disable?.();
      }
      game.projectiles = (game.projectiles || []).filter((p) => p.alive);
      game.hostileProjectiles = game.hostilePool?.clear?.(game.hostileProjectiles || []) || [];
    }
  }

  _fadeBossMusic() {
    if (this._musicFaded) return;
    this._musicFaded = true;
    this.game._bossMusic = false;
    this.game.audio?.stopMusic?.(0.8);
  }

  startDefeatSequence() {
    if (this.defeatSequenceStarted) return;
    this.defeatSequenceStarted = true;
    this._lockOutCombat();
    this._prepareClear();
    this.phase = ENCOUNTER.defeat_cinematic;
    this.game.playBossDefeat({
      onComplete: (reason) => this.afterDefeatCinematic(reason),
    });
  }

  afterDefeatCinematic() {
    if (this._defeatFinished) return;
    this._defeatFinished = true;
    this.defeatVideoPlayed = true;
    if (!this.scoreAwarded) {
      this.scoreAwarded = true;
      this.game.scoreboard?.awardBoss?.();
      this.game.scoreboard?.sync?.(this.game);
    }
    this.phase = ENCOUNTER.complete;
    this.game.awardStudioClear?.();
  }

  _prepareClear() {
    this.hudVisible = false;
    this.clearHostile();
    this.clearHealthDrops();
    this.unlockArena();
    this.game._bossMusic = false;
    this.game.audio.stopMusic(0.45);
    if (this.game.waves) this.game.waves.banner = { title: "BOSS DEFEATED", subtitle: this.cfg.displayName };
    this.game.waves?.completeStudio?.();
    const enc = (this.game.world?.encounters || []).find((e) => e.boss || e.id === "enc_final");
    if (enc) {
      enc.activated = true;
      enc.cleared = true;
    }
    this.game.hud?.invalidate();
  }
}
