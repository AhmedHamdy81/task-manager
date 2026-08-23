import { aabb } from "./collision.js";
import { ENEMY_TYPES, migrateEnemyType } from "./enemy.js";

export const WAVE_STATES = {
  waiting: "waiting",
  spawning: "spawning",
  active: "active",
  cleared: "cleared",
  complete: "complete",
};

export const WAVE_TIMING = {
  prepareSec: 2,
  announceSec: 1,
  betweenSec: 2.5,
};

export const WAVE_MIN_PLAYER_DX = 500;
export const STUDIO_CLEAR_BONUS = 500;

export const WAVE_ENEMY_TYPES = new Set(["post_producer", "client", "colorist", "vfx_supervisor"]);
const ALLOWED = WAVE_ENEMY_TYPES;

export function resolveWaveEnemyType(typeId) {
  const id = migrateEnemyType(typeId);
  return ALLOWED.has(id) && ENEMY_TYPES[id] ? id : "post_producer";
}

export function flattenWaveQueue(wave) {
  const queue = [];
  for (const pack of wave?.enemies || []) {
    const type = resolveWaveEnemyType(pack.type);
    const count = Math.max(0, Math.floor(Number(pack.count) || 0));
    const modifiers = pack.modifiers ? { ...pack.modifiers } : null;
    for (let i = 0; i < count; i += 1) {
      queue.push({ type, modifiers });
    }
  }
  return queue;
}

export function waveAnnouncement(wave, index) {
  if (!wave) return { title: "", subtitle: "" };
  if (wave.id === "final_wave" || wave.final) {
    return { title: "FINAL WAVE", subtitle: wave.announce || "SENIOR POST PRODUCER" };
  }
  const types = [...new Set((wave.enemies || []).map((e) => resolveWaveEnemyType(e.type)))];
  let subtitle = wave.announce || "";
  if (!subtitle) {
    if (types.includes("post_producer") && types.includes("client")) subtitle = "POST PRODUCERS + CLIENTS";
    else if (types.includes("client")) subtitle = "THE CLIENT";
    else subtitle = "POST PRODUCERS";
  }
  return { title: `WAVE ${index + 1}`, subtitle };
}

function hazardBox(h) {
  return { x: h.x, y: h.y, w: h.w || 96, h: h.h || 96 };
}

export function spawnBlocked(world, x, y, w, h, extras = []) {
  const box = { x: x - w / 2, y: y - h, w, h };
  const solids = world.solids || [];
  const buried = solids.some((s) => s.y + 8 < y - 8 && aabb(box, s));
  if (buried) return true;
  const onSupport = solids.some((s) => {
    const over = x >= s.x && x <= s.x + s.w;
    const onTop = Math.abs(y - s.y) <= 12;
    return over && onTop;
  });
  if (!onSupport) return true;
  for (const hz of world.hazards || []) {
    if (hz.enabled === false) continue;
    if (aabb(box, hazardBox(hz))) return true;
  }
  for (const d of world.destructibles || []) {
    if (!d.blocksMovement || d.state === "gone" || d.state === "rubble") continue;
    if (aabb(box, d)) return true;
  }
  for (const p of world.props || []) {
    if (aabb(box, { x: p.x, y: p.y, w: p.w || 128, h: p.h || 128 })) return true;
  }
  for (const door of world.doors || []) {
    if (door.state === "open") continue;
    const b = door.block || door;
    if (aabb(box, b)) return true;
  }
  for (const extra of extras) {
    if (extra && aabb(box, extra)) return true;
  }
  const width = world.width || 0;
  if (width && (x < 96 || x > width - 96)) return true;
  return false;
}

export function collectFloorPoints(world) {
  const groundY = world.ground?.y ?? 960;
  const points = [];
  for (const z of world.spawnZones || []) {
    const y = z.y || groundY;
    const x0 = z.x;
    const x1 = z.x + (z.w || 64);
    for (let x = x0 + 40; x <= x1 - 40; x += 48) points.push({ x, y });
  }
  for (const s of world.solids || []) {
    if (!(s.w >= 80) || s.h > 80) continue;
    for (let x = s.x + 40; x <= s.x + s.w - 40; x += 64) {
      points.push({ x, y: s.y });
    }
  }
  if (!points.length) {
    const width = world.width || 2000;
    for (let x = 200; x < width - 200; x += 64) points.push({ x, y: groundY });
  }
  return points;
}

/** World-space spawn. Never uses camera/screen coordinates. */
export function pickWaveSpawn(world, player, enemies, body = { w: 88, h: 210 }) {
  const px = player?.footX ?? 0;
  const facing = player?.facing || 1;
  const extras = (enemies || []).filter((e) => e.alive).map((e) => e.bounds());
  const w = body.w || 88;
  const h = body.h || 210;
  const ranked = collectFloorPoints(world).map((p) => {
    const dx = p.x - px;
    const dist = Math.abs(dx);
    const ahead = Math.sign(dx || 1) === Math.sign(facing || 1);
    return { ...p, dist, ahead };
  });
  ranked.sort((a, b) => {
    if (a.ahead !== b.ahead) return a.ahead ? -1 : 1;
    return Math.abs(a.dist - 720) - Math.abs(b.dist - 720);
  });
  for (const c of ranked) {
    if (c.dist < WAVE_MIN_PLAYER_DX) continue;
    if (spawnBlocked(world, c.x, c.y, w, h, extras)) continue;
    return { x: c.x, y: c.y };
  }
  for (const c of ranked) {
    if (c.dist < 280) continue;
    if (spawnBlocked(world, c.x, c.y, w, h, extras)) continue;
    return { x: c.x, y: c.y };
  }
  for (const c of ranked) {
    if (spawnBlocked(world, c.x, c.y, w, h, extras)) continue;
    return { x: c.x, y: c.y };
  }
  const fallbackX = Math.max(160, Math.min((world.width || 2000) - 160, px + facing * WAVE_MIN_PLAYER_DX));
  return { x: fallbackX, y: world.ground?.y ?? 960 };
}

export class WaveController {
  constructor(game, waves) {
    this.game = game;
    this.waves = (waves || []).map((w) => ({
      ...w,
      enemies: (w.enemies || []).map((e) => ({
        ...e,
        modifiers: e.modifiers ? { ...e.modifiers } : undefined,
      })),
    }));
    this.state = WAVE_STATES.waiting;
    this.waveIndex = 0;
    this.timer = 0;
    this.prepareLeft = 0;
    this.announceLeft = 0;
    this.spawnAcc = 0;
    this.queue = [];
    this.scheduled = 0;
    this.spawned = 0;
    this.living = 0;
    this.defeated = 0;
    this.banner = null;
    this._finished = false;
    this._destroyed = false;
  }

  destroy() {
    this._destroyed = true;
    this.state = WAVE_STATES.complete;
    this.queue = [];
    this.banner = null;
    this.prepareLeft = 0;
    this.announceLeft = 0;
  }

  get blocksInput() {
    return this.state === WAVE_STATES.waiting && this.prepareLeft > 0 && this.waveIndex === 0;
  }

  get livingEnemyCount() {
    return this.living;
  }

  get allEnemiesSpawned() {
    return this.queue.length === 0 && this.spawned >= this.scheduled;
  }

  get hud() {
    if (!this.waves.length || this.state === WAVE_STATES.complete) {
      return { index: this.waves.length, total: this.waves.length, living: 0 };
    }
    return {
      index: Math.min(this.waveIndex + 1, this.waves.length),
      total: this.waves.length,
      living: this.living,
    };
  }

  log(event, extra = {}) {
    if (!this.game?.allowDebug) return;
    console.info(`[Producer Hunt Wave] ${event}`, extra);
  }

  start() {
    if (this._destroyed || !this.waves.length) return;
    this._finished = false;
    this.beginWave(0, { prepare: true });
  }

  beginWave(index, opts = {}) {
    if (this._destroyed) return;
    const wave = this.waves[index];
    if (!wave) {
      this.finishWaves();
      if (!this.game.world?.boss) this.game.awardStudioClear?.();
      return;
    }
    this.waveIndex = index;
    this.state = WAVE_STATES.waiting;
    this.timer = 0;
    this.prepareLeft = opts.prepare ? WAVE_TIMING.prepareSec : 0;
    this.announceLeft = WAVE_TIMING.announceSec;
    this.spawnAcc = 0;
    this.queue = flattenWaveQueue(wave);
    this.scheduled = this.queue.length;
    this.spawned = 0;
    this.living = 0;
    this.defeated = 0;
    this.banner = null;
    this.log("Wave started", {
      id: wave.id,
      index: index + 1,
      scheduled: this.scheduled,
    });
    for (const item of this.queue) {
      this.log("Enemy scheduled", { type: item.type, wave: wave.id });
    }
    this.game.syncWaveCheckpoint?.();
  }

  snapshot() {
    const living = (this.game.enemies || [])
      .filter((e) => e.waveTracked && e.alive)
      .map((e) => ({
        type: e.type,
        modifiers: e.waveMods ? { ...e.waveMods } : null,
        health: e.health,
      }));
    return {
      waveIndex: this.waveIndex,
      state: this.state,
      prepareLeft: this.prepareLeft,
      announceLeft: this.announceLeft,
      spawnAcc: this.spawnAcc,
      queue: this.queue.map((q) => ({ type: q.type, modifiers: q.modifiers ? { ...q.modifiers } : null })),
      scheduled: this.scheduled,
      spawned: this.spawned,
      livingCount: this.living,
      defeated: this.defeated,
      living,
      finished: this._finished,
    };
  }

  applySnapshot(snap) {
    if (!snap || this._destroyed) return;
    if (snap.finished || snap.state === WAVE_STATES.complete) {
      this.state = WAVE_STATES.complete;
      this._finished = true;
      this.queue = [];
      this.banner = null;
      return;
    }
    this.waveIndex = Math.max(0, Math.min(this.waves.length - 1, Number(snap.waveIndex) || 0));
    this.queue = Array.isArray(snap.queue)
      ? snap.queue.map((q) => ({ type: resolveWaveEnemyType(q.type), modifiers: q.modifiers || null }))
      : flattenWaveQueue(this.waves[this.waveIndex]);
    this.scheduled = Number.isFinite(snap.scheduled) ? snap.scheduled : this.queue.length + (snap.living?.length || 0);
    this.spawned = Number(snap.spawned) || 0;
    this.defeated = Number(snap.defeated) || 0;
    this.living = 0;
    this.prepareLeft = 0;
    this.announceLeft = 0;
    this.spawnAcc = Number(snap.spawnAcc) || 0;
    this.banner = null;
    (snap.living || []).forEach((spec, i) => {
      const enemy = this.game.spawnWaveEnemy(resolveWaveEnemyType(spec.type), spec.modifiers, {
        health: spec.health,
        id: `wave_restore_${this.waveIndex}_${i}`,
      });
      if (enemy) this.living += 1;
    });
    const restored = snap.state;
    if (restored === WAVE_STATES.waiting || restored === WAVE_STATES.spawning) {
      this.state = this.queue.length ? WAVE_STATES.spawning : WAVE_STATES.active;
    } else if (restored === WAVE_STATES.cleared) {
      this.state = WAVE_STATES.cleared;
      this.timer = 0;
    } else {
      this.state = WAVE_STATES.active;
    }
    if (this.allEnemiesSpawned && this.livingEnemyCount === 0 && this.state !== WAVE_STATES.cleared) {
      this.state = WAVE_STATES.cleared;
      this.timer = 0;
    }
  }

  onEnemyExit(enemy, reason) {
    if (this._destroyed || !enemy?.waveTracked) return;
    this.living = Math.max(0, this.living - 1);
    this.defeated += 1;
    this.log(reason === "defeated" ? "Enemy defeated" : "Enemy defeated", {
      reason,
      type: enemy.type,
      id: enemy.spawnId,
    });
    this.log("Living count", { living: this.living, spawned: this.spawned, scheduled: this.scheduled });
    this.game.hud?.invalidate();
    this.game.syncWaveCheckpoint?.();
  }

  _deathAnimsPlaying() {
    return (this.game.enemies || []).some(
      (e) => e.waveTracked && !e.alive && e.anim && e.anim.name === "death" && !e.anim.finished
    );
  }

  update(dt) {
    if (this._destroyed || this._finished || !this.waves.length) return;
    if (this.state === WAVE_STATES.complete) return;

    if (this.state === WAVE_STATES.waiting) {
      if (this.prepareLeft > 0) {
        this.prepareLeft -= dt;
        return;
      }
      if (!this.banner) {
        this.banner = waveAnnouncement(this.waves[this.waveIndex], this.waveIndex);
        this.game.hud?.invalidate();
      }
      this.announceLeft -= dt;
      if (this.announceLeft <= 0) {
        this.state = WAVE_STATES.spawning;
        this.spawnAcc = 999;
      }
      return;
    }

    if (this.state === WAVE_STATES.spawning) {
      this._spawnTick(dt);
      if (this.allEnemiesSpawned) this.state = WAVE_STATES.active;
      return;
    }

    if (this.state === WAVE_STATES.active) {
      if (this.banner && this.announceLeft < -0.35) this.banner = null;
      this.announceLeft -= dt;
      if (this.allEnemiesSpawned && this.livingEnemyCount === 0 && !this._deathAnimsPlaying()) {
        this.state = WAVE_STATES.cleared;
        this.timer = 0;
        this.log("Wave cleared", { id: this.waves[this.waveIndex]?.id, index: this.waveIndex + 1 });
        const last = this.waveIndex >= this.waves.length - 1;
        this.banner = last && !this.game.world?.boss ? { title: "STUDIO 01 CLEAR", subtitle: "WRAP COMPLETE" } : null;
        this.game.hud?.invalidate();
        this.game.syncWaveCheckpoint?.();
      }
      return;
    }

    if (this.state === WAVE_STATES.cleared) {
      this.timer += dt;
      if (this.timer < WAVE_TIMING.betweenSec) return;
      if (this.livingEnemyCount > 0) return;
      if (this.waveIndex >= this.waves.length - 1) {
        this.finishWaves();
        return;
      }
      this.beginWave(this.waveIndex + 1, { prepare: false });
    }
  }

  _spawnTick(dt) {
    const wave = this.waves[this.waveIndex];
    const interval = Math.max(0, Number(wave?.spawnInterval) || 0) / 1000;
    this.spawnAcc += dt;
    if (!this.queue.length) return;
    if (this.spawnAcc < interval && this.spawned > 0) return;
    this.spawnAcc = 0;
    const next = this.queue.shift();
    const spawned = this.game.spawnWaveEnemy(next.type, next.modifiers);
    if (spawned) {
      this.spawned += 1;
      this.living += 1;
      this.log("Enemy spawned", {
        type: spawned.type,
        id: spawned.spawnId,
        x: spawned.footX,
        y: spawned.footY,
      });
      this.log("Living count", { living: this.living });
      this.game.hud?.invalidate();
      this.game.syncWaveCheckpoint?.();
    } else {
      this.queue.unshift(next);
    }
  }

  finishWaves() {
    if (this._finished || this._destroyed) return;
    this._finished = true;
    this.state = WAVE_STATES.complete;
    this.queue = [];
    this.banner = null;
    this.log("Studio 01 waves cleared", { level: this.game.world?.id });
    if (this.game.world) this.game.world.wavesComplete = true;
    this.game.onStudioWavesCleared?.();
  }

  completeStudio() {
    this.log("Studio 01 completed", { level: this.game.world?.id });
  }

  finishStudio() {
    this.finishWaves();
    if (!this.game.world?.boss) {
      this.completeStudio();
      this.game.awardStudioClear?.();
    }
  }
}
