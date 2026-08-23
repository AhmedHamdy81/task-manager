import { aabb } from "./collision.js";
import { collectFloorPoints, spawnBlocked } from "./waves.js";
import { migrateEnemyType } from "./enemy.js";

const SAFETY = 420;

function inArena(x, arena) {
  if (!arena) return true;
  const left = arena.left ?? arena.arenaLeft;
  const right = arena.right ?? arena.arenaRight;
  if (left == null || right == null) return true;
  return x >= left + 40 && x <= right - 40;
}

export function pickEncounterSpawn(world, player, enemies, body, arena, spawnPoints = []) {
  const px = player?.footX ?? 0;
  const py = player?.footY ?? world.ground?.y ?? 960;
  const extras = (enemies || []).filter((e) => e.alive).map((e) => e.bounds());
  const w = body.w || 88;
  const h = body.h || 210;
  const configured = (spawnPoints || []).map((p) => ({ x: p.x, y: p.y ?? world.ground?.y ?? 960 }));
  const floor = collectFloorPoints(world).filter((p) => inArena(p.x, arena));
  const ranked = [...configured, ...floor].map((p) => ({
    ...p,
    dist: Math.hypot(p.x - px, (p.y || py) - py),
  }));
  ranked.sort((a, b) => Math.abs(a.dist - 640) - Math.abs(b.dist - 640));
  const tryList = (minDist) => {
    for (const c of ranked) {
      if (c.dist < minDist) continue;
      if (c.x === 0 && c.y === 0) continue;
      if (!inArena(c.x, arena)) continue;
      if (spawnBlocked(world, c.x, c.y, w, h, extras)) continue;
      return { x: c.x, y: c.y };
    }
    return null;
  };
  return (
    tryList(SAFETY) ||
    tryList(280) ||
    tryList(120) || {
      x: ((arena?.left ?? arena?.arenaLeft ?? px) + (arena?.right ?? arena?.arenaRight ?? px)) / 2,
      y: world.ground?.y ?? 960,
    }
  );
}

export function makeArenaWalls(arena, world) {
  const groundY = world.ground?.y ?? 960;
  const h = groundY;
  return [
    { x: (arena.left ?? arena.arenaLeft) - 24, y: 0, w: 24, h, arenaWall: true },
    { x: arena.right ?? arena.arenaRight, y: 0, w: 24, h, arenaWall: true },
  ];
}

export class EncounterDirector {
  constructor(game) {
    this.game = game;
    this.retry = new Map();
  }

  destroy() {
    this.unlockAll();
    this.retry.clear();
  }

  get hud() {
    const enc = (this.game.world?.encounters || []).find((e) => e.scripted && e.activated && !e.cleared);
    if (!enc) return null;
    return {
      index: (enc.waveIndex || 0) + 1,
      total: (enc.waves || []).length || 1,
      living: enc.living || 0,
    };
  }

  snapshot() {
    const world = this.game.world;
    return Object.fromEntries(
      (world?.encounters || [])
        .filter((e) => e.scripted)
        .map((e) => [
          e.id,
          {
            activated: e.activated,
            cleared: e.cleared,
            waveIndex: e.waveIndex || 0,
            rewarded: Boolean(e.rewarded),
            living: (this.game.enemies || [])
              .filter((en) => en.encounterId === e.id && en.alive)
              .map((en) => ({ type: en.type, x: en.footX, y: en.footY, health: en.health })),
          },
        ])
    );
  }

  applySnapshot(snap) {
    if (!snap) return;
    for (const enc of this.game.world?.encounters || []) {
      const rec = snap[enc.id];
      if (!rec || !enc.scripted) continue;
      enc.activated = Boolean(rec.activated);
      enc.cleared = Boolean(rec.cleared);
      enc.waveIndex = rec.waveIndex || 0;
      enc.rewarded = Boolean(rec.rewarded);
      enc.locked = false;
      if (enc.activated && !enc.cleared) {
        this.lockArena(enc);
        this.game.scoreboard?.markEncounterStart(enc.id);
        (rec.living || []).forEach((spec, i) => {
          this.game.spawnEncounterEnemy(enc, migrateEnemyType(spec.type), {
            health: spec.health,
            id: `${enc.id}_restore_${i}`,
            x: spec.x,
            y: spec.y,
          });
        });
      }
    }
  }

  lockArena(enc) {
    if (!enc.arenaLeft || !enc.arenaRight || enc.locked) return;
    const walls = makeArenaWalls(enc, this.game.world);
    this.game.world.solids.push(...walls);
    enc.locked = true;
    enc._walls = walls;
  }

  unlockArena(enc) {
    if (!enc?.locked) return;
    const world = this.game.world;
    world.solids = (world.solids || []).filter((s) => !s.arenaWall || !(enc._walls || []).includes(s));
    enc.locked = false;
    enc._walls = null;
  }

  unlockAll() {
    for (const enc of this.game.world?.encounters || []) this.unlockArena(enc);
  }

  update(dt) {
    const game = this.game;
    const player = game.player;
    if (!player || !game.world) return;
    const px = player.footX;
    for (const enc of game.world.encounters || []) {
      if (!enc.scripted || enc.cleared) continue;
      if (enc.id === "enc_client" && game.vehicle && (game.vehicle.occupied || game.vehicle.sequenceDone)) continue;
      if (!enc.activated && px >= (enc.triggerX ?? enc.activateX)) this.activate(enc);
      if (!enc.activated || enc.cleared) continue;
      this._updateActive(enc, dt);
    }
  }

  activate(enc) {
    enc.activated = true;
    enc.waveIndex = 0;
    enc.spawned = 0;
    enc.living = 0;
    enc.warned = false;
    this.retry.delete(enc.id);
    this.lockArena(enc);
    this.game.scoreboard?.markEncounterStart(enc.id);
    this.game.combatHint = { text: enc.warning || "ENCOUNTER", until: (this.game._worldTime || 0) + 1.6 };
    this.game.sfx?.("encounter_start", { force: true });
    this.game.hud?.invalidate();
    this._beginWave(enc, 0);
  }

  _beginWave(enc, index) {
    const wave = (enc.waves || [])[index];
    enc.waveIndex = index;
    enc.queue = flattenPacks(wave);
    enc.spawnAcc = 0.35;
    enc.maxActive = enc.maximumActiveEnemies || 6;
    this.game.combatHint = {
      text: wave?.announce || `WAVE ${index + 1}`,
      until: (this.game._worldTime || 0) + 1.2,
    };
  }

  _updateActive(enc, dt) {
    enc.spawnAcc = (enc.spawnAcc || 0) + dt;
    const living = this.game.enemies.filter((e) => e.alive && e.encounterId === enc.id);
    enc.living = living.length;
    while (enc.queue?.length && living.length + (enc._pending || 0) < (enc.maxActive || 6) && enc.spawnAcc >= 0.28) {
      const next = enc.queue.shift();
      const spawned = this.game.spawnEncounterEnemy(enc, next.type, { modifiers: next.modifiers });
      enc.spawnAcc = 0;
      if (!spawned) {
        const n = (this.retry.get(enc.id) || 0) + 1;
        this.retry.set(enc.id, n);
        if (n > 8) {
          console.warn(`[Producer Hunt] Encounter "${enc.id}" skipped a spawn for ${next.type}. Expected a reachable spawnPoint inside the arena.`);
          if (n > 14) {
            console.warn(`[Producer Hunt] Encounter "${enc.id}" dropped remaining queued spawns to avoid a deadlock.`);
            enc.queue = [];
          }
          break;
        }
        enc.queue.unshift(next);
        if (n === 1) {
          console.warn(`[Producer Hunt] Encounter "${enc.id}" delayed a spawn; retrying a valid point.`);
        }
        break;
      }
    }
    const dying = this.game.enemies.some(
      (e) => e.encounterId === enc.id && !e.alive && e.anim && e.anim.name === "death" && !e.anim.finished
    );
    if (enc.queue?.length) return;
    if (living.length || dying) return;
    const last = enc.waveIndex >= (enc.waves || []).length - 1;
    if (!last) {
      this._beginWave(enc, enc.waveIndex + 1);
      return;
    }
    this.complete(enc);
  }

  complete(enc) {
    if (enc.cleared) return;
    enc.cleared = true;
    this.unlockArena(enc);
    if (!enc.rewarded) {
      enc.rewarded = true;
      const reward = Number(enc.reward) || 0;
      this.game.scoreboard?.awardEncounter(enc.id, reward);
      this.game.scoreboard?.sync(this.game);
      this.game.sfx?.("encounter_complete");
      if (enc.checkpointAfterCompletion) this.game.captureCheckpoint(null, { silent: false });
      if (enc.unlockBoss) {
        if (this.game.world) this.game.world.wavesComplete = true;
        this.game.onStudioWavesCleared?.();
      }
    }
    this.game.hud?.invalidate();
  }
}

function flattenPacks(wave) {
  const queue = [];
  for (const pack of wave?.enemies || []) {
    const type = migrateEnemyType(pack.type);
    const count = Math.max(0, Math.floor(Number(pack.count) || 0));
    for (let i = 0; i < count; i += 1) queue.push({ type, modifiers: pack.modifiers || null });
  }
  return queue;
}

export { flattenPacks, SAFETY, aabb };
