import { instantiatePickup } from "../pickups.js";
import { ENEMY_TYPES, migrateEnemyType } from "../enemy.js";
import { musicForLevel } from "../audio-catalog.js";
import {
  instantiateCheckpoint,
  instantiateDoor,
  instantiateHazard,
  syncDoorSolids,
} from "../progression.js";
import { instantiateDestructible, injectDestructibleSolids } from "../destructibles.js";
import { instantiateRescue } from "../rescues.js";

export const TILE = 64;
export const t = (n) => n * TILE;

export class LevelDataError extends Error {
  constructor(messages) {
    super(`[Producer Hunt] Required level data is invalid.\n${(messages || []).join("\n")}`);
    this.messages = messages || [];
    this.name = "LevelDataError";
  }
}

function overlaps(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function validateLevel(level) {
  const errors = [];
  const warnings = [];
  if (!level?.id) errors.push("Level is missing an id.");
  if (!level?.playerSpawn) errors.push("Player spawn is missing.");
  if (!(level.platforms || []).length) errors.push("Level has no platforms.");
  if (!(level.doors || []).some((d) => d.kind === "exit") && !level.levelEnd) {
    errors.push("Level has no exit door or levelEnd.");
  }

  const cpIds = (level.checkpoints || []).map((c) => c.id).filter(Boolean);
  if (new Set(cpIds).size !== cpIds.length) errors.push("Checkpoint IDs must be unique.");
  const pkIds = (level.pickups || []).map((p) => p.id).filter(Boolean);
  if (new Set(pkIds).size !== pkIds.length) errors.push("Persistent pickup IDs must be unique.");
  const doorIds = new Set((level.doors || []).map((d) => d.id));
  for (const door of level.doors || []) {
    for (const id of door.requireDoors || []) {
      if (!doorIds.has(id)) errors.push(`Door "${door.id}" references missing door "${id}".`);
    }
  }
  for (const step of level.objectives || []) {
    if (step.doorId && !doorIds.has(step.doorId)) {
      errors.push(`Objective "${step.id}" references missing door "${step.doorId}".`);
    }
    if (step.checkpointId && !cpIds.includes(step.checkpointId)) {
      errors.push(`Objective "${step.id}" references missing checkpoint "${step.checkpointId}".`);
    }
  }
  const ALLOWED_ENEMIES = new Set(["post_producer", "client", "colorist", "vfx_supervisor"]);
  for (const wave of level.waves || []) {
    if (!wave?.id) errors.push("A wave is missing an id.");
    for (const pack of wave.enemies || []) {
      const type = migrateEnemyType(pack.type);
      if (!ENEMY_TYPES[type] || !ALLOWED_ENEMIES.has(type)) {
        errors.push(`Invalid enemy type "${pack.type}" on wave "${wave.id || "?"}".`);
      }
    }
  }
  for (const enc of level.encounters || []) {
    for (const wave of enc.waves || []) {
      for (const pack of wave.enemies || []) {
        const type = migrateEnemyType(pack.type);
        if (!ENEMY_TYPES[type] || !ALLOWED_ENEMIES.has(type)) {
          errors.push(`Invalid enemy type "${pack.type}" on encounter "${enc.id || "?"}".`);
        }
      }
    }
  }
  const spawnIds = new Set();
  const width = level.worldWidth || 0;
  const height = level.worldHeight || 1080;
  for (const spawn of level.enemySpawns || []) {
    if (String(spawn.type || "").trim() === "assistant_producer") {
      warnings.push("Legacy assistant_producer spawn migrated to post_producer.");
    }
    const type = migrateEnemyType(spawn.type);
    if (!ENEMY_TYPES[type] || !ALLOWED_ENEMIES.has(type)) {
      errors.push(`Invalid enemy type "${spawn.type}" on spawn "${spawn.id || "?"}".`);
    }
    if (spawn.id) {
      if (spawnIds.has(spawn.id)) errors.push(`Duplicate enemy spawn id "${spawn.id}".`);
      spawnIds.add(spawn.id);
    }
    if (width && (spawn.x < 0 || spawn.x > width || spawn.y < 0 || spawn.y > height)) {
      errors.push(`Enemy "${spawn.id || type}" spawn is outside level bounds.`);
    }
    const ebox = { x: spawn.x - 40, y: spawn.y - 160, w: 80, h: 160 };
    const buried = (level.platforms || []).find((p) => p.y + 8 < spawn.y - 8 && overlaps(ebox, p));
    if (buried) errors.push(`Enemy "${spawn.id || type}" spawn overlaps solid collision.`);
  }
  const encounterIds = new Set();
  for (const enc of level.encounters || []) {
    if (!enc.id) errors.push("Encounter is missing an id.");
    else if (encounterIds.has(enc.id)) errors.push(`Duplicate encounter id "${enc.id}".`);
    else encounterIds.add(enc.id);
    for (const id of enc.enemyIds || []) {
      if (!spawnIds.has(id)) errors.push(`Encounter "${enc.id}" references missing enemy "${id}".`);
    }
  }
  for (const step of level.objectives || []) {
    if (step.encounterId && !encounterIds.has(step.encounterId)) {
      errors.push(`Objective "${step.id}" references missing encounter "${step.encounterId}".`);
    }
  }
  for (const door of level.doors || []) {
    for (const id of door.requireEncounters || []) {
      if (!encounterIds.has(id)) errors.push(`Door "${door.id}" references missing encounter "${id}".`);
    }
  }
  for (const solid of level.platforms || []) {
    if (!(solid.w > 0 && solid.h > 0)) errors.push("A collidable platform has invalid dimensions.");
  }

  const spawn = level.playerSpawn;
  if (spawn) {
    if (width && (spawn.x < 0 || spawn.x > width || spawn.y < 0 || spawn.y > height)) {
      errors.push("Player spawn is outside level bounds.");
    }
    const box = { x: spawn.x - 40, y: spawn.y - 170, w: 80, h: 170 };
    const hit = (level.platforms || []).find((p) => p.y + 8 < spawn.y - 8 && overlaps(box, p));
    if (hit) warnings.push("Player spawn overlaps a solid.");
  }

  for (const msg of warnings) console.warn(`[Producer Hunt Level] ${msg}`);
  if (errors.length) throw new LevelDataError(errors);
  return { warnings };
}

export function buildWorld(level) {
  validateLevel(level);
  const groundY = level.ground?.y ?? 960;
  const platformSolids = [
    ...(level.platforms || []).map((p) => ({ ...p })),
    ...(level.props || [])
      .filter((p) => p.collidable)
      .map((p) => ({ x: p.x, y: p.y, w: p.w, h: p.h })),
  ];
  const world = {
    id: level.id,
    name: level.name,
    music: musicForLevel(level.id, level.music),
    width: level.worldWidth,
    height: level.worldHeight,
    background: level.background,
    ground: level.ground ? { ...level.ground } : null,
    spawn: { ...level.playerSpawn },
    end: level.levelEnd ? { ...level.levelEnd } : null,
    checkpoints: (level.checkpoints || []).map((c, i) => instantiateCheckpoint(c, i, level.id, groundY)),
    doors: (level.doors || []).map((d, i) => instantiateDoor(d, i, level.id)),
    objectives: (level.objectives || []).map((o) => ({ ...o })),
    exitRequires: { ...(level.exitRequires || {}) },
    encounters: (level.encounters || []).map((e) => ({
      ...e,
      enemyIds: [...(e.enemyIds || [])],
      activated: Boolean(e.activated),
      cleared: false,
      boss: Boolean(e.boss),
    })),
    pickups: (level.pickups || []).map((p, i) => instantiatePickup(p, i, level.id)),
    props: (level.props || []).map((p) => ({
      ...p,
      collidable: Boolean(p.collidable),
      layer: p.layer || "back",
    })),
    hazards: (level.hazards || []).map((h, i) => instantiateHazard(h, i, level.id)),
    destructibles: (level.destructibles || []).map((d, i) => instantiateDestructible(d, i, level.id)),
    rescues: (level.rescues || []).map((r, i) => instantiateRescue(r, i, level.id)),
    ambients: (level.ambients || []).map((a) => ({ ...a })),
    hazardQuietX: level.hazardQuietX,
    moverSolids: [],
    destructibleSolids: [],
    hints: (level.hints || []).map((h) => ({ ...h })),
    platformSolids,
    solids: platformSolids.slice(),
    enemySpawns: (level.enemySpawns || []).map((e) => ({
      ...e,
      type: migrateEnemyType(e.type),
    })),
    waves: (level.waves || []).map((w) => ({
      ...w,
      enemies: (w.enemies || []).map((e) => ({
        ...e,
        modifiers: e.modifiers ? { ...e.modifiers } : undefined,
      })),
    })),
    spawnZones: (level.spawnZones || []).map((z) => ({ ...z })),
    wavesComplete: false,
    zones: (level.zones || []).map((z) => ({ ...z })),
    boss: level.boss || null,
    bossArena: level.bossArena ? { ...level.bossArena } : null,
  };
  syncDoorSolids(world);
  injectDestructibleSolids(world);
  return world;
}
