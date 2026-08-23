/**
 * Studio 01 release-candidate validation. Warnings name the object and the expected fix.
 * Decorative / optional assets never throw.
 */

import { CHARACTERS, CHARACTER_STATS } from "./characters.js";
import { PLAYER_WEAPON_DEFS, PLAYER_WEAPON_IDS } from "./player-weapons.js";
import { ENEMY_TYPES } from "./enemy.js";
import { ENEMY_MUZZLE, projectileDef } from "./combat.js";
import { SOUND_DEFS } from "./audio-catalog.js";
import { BOSS_DEFEAT_SRC, BOSS_INTRO_SRC } from "./config.js";
import { PLAYER_ANIMATIONS, ENEMY_ANIMATIONS, BOSS_01_ANIMATIONS } from "./sprite-spec.js";

const _warned = new Set();

function warn(code, message) {
  if (_warned.has(code)) return;
  _warned.add(code);
  console.warn(`[Producer Hunt] ${message}`);
}

function uniqueIds(items, kind) {
  const seen = new Set();
  for (const item of items || []) {
    const id = item?.id;
    if (!id) {
      warn(`missing-id:${kind}`, `${kind} is missing an id. Add a stable unique id.`);
      continue;
    }
    if (seen.has(id)) warn(`dup:${kind}:${id}`, `Duplicate ${kind} id "${id}". Expected unique ids.`);
    seen.add(id);
  }
}

export function validateCharacterConfigs() {
  const ids = ["editor", "assistant", "colorist", "vfx_supervisor"];
  for (const id of ids) {
    const ch = CHARACTERS.find((c) => c.id === id);
    const stats = CHARACTER_STATS[id];
    if (!ch) {
      warn(`char:${id}`, `Playable character "${id}" is missing from CHARACTERS. Add the roster entry.`);
      continue;
    }
    if (!stats || !(stats.maxHealth > 0)) {
      warn(`hp:${id}`, `Character "${id}" has invalid maxHealth. Expected a positive HP value.`);
    }
    if (!(ch.speed > 0)) warn(`spd:${id}`, `Character "${id}" has invalid speed.`);
    if (!ch.specialPowerId) warn(`power:${id}`, `Character "${id}" is missing specialPowerId.`);
    const shoot = ch.muzzleByAnim?.shoot;
    const crouch = ch.muzzleByAnim?.crouch_shoot;
    if (!shoot || shoot.y > -40) {
      warn(`muzzle:${id}:shoot`, `Character "${id}" standing muzzle is invalid. Expected {x,y} with y well above the feet.`);
    }
    if (!crouch || crouch.y > -20) {
      warn(`muzzle:${id}:crouch`, `Character "${id}" crouch muzzle is invalid.`);
    }
    if (!ch.portrait) warn(`portrait:${id}`, `Character "${id}" is missing portrait path.`);
  }
  const healths = ids.map((id) => CHARACTER_STATS[id]?.maxHealth);
  if (new Set(healths).size < 3) {
    warn("stats:same", "Character health values are not meaningfully different. Tune CHARACTER_STATS.");
  }
}

export function validateWeaponConfigs() {
  for (const id of PLAYER_WEAPON_IDS) {
    const def = PLAYER_WEAPON_DEFS[id];
    if (!def) {
      warn(`weapon:${id}`, `Missing weapon configuration "${id}".`);
      continue;
    }
    if (!(def.damage > 0)) warn(`weapon-dmg:${id}`, `Weapon "${id}" damage must be > 0.`);
    if (!(def.fireInterval > 0)) warn(`weapon-rate:${id}`, `Weapon "${id}" fireInterval must be > 0.`);
    if (!(def.projectileSpeed > 0)) warn(`weapon-spd:${id}`, `Weapon "${id}" projectileSpeed must be > 0.`);
    const projId = def.projectileId;
    if (projId && !projectileDef(projId)) {
      warn(`weapon-proj:${id}`, `Weapon "${id}" projectileId "${projId}" is not in PROJECTILE_DEFS.`);
    }
  }
}

export function validateEnemyConfigs() {
  for (const id of ["post_producer", "colorist", "vfx_supervisor", "client"]) {
    const spec = ENEMY_TYPES[id];
    if (!spec) {
      warn(`enemy:${id}`, `Missing enemy configuration "${id}".`);
      continue;
    }
    if (!(spec.health > 0)) warn(`enemy-hp:${id}`, `Enemy "${id}" health must be > 0.`);
    const muzzle = ENEMY_MUZZLE[id]?.attack;
    if (!muzzle || muzzle.y > -40) {
      warn(`enemy-muzzle:${id}`, `Enemy "${id}" attack muzzle is missing or too low. Expected shoulder/hand height.`);
    }
  }
}

export function validateAnimationNames() {
  const knownPlayer = new Set([...Object.keys(PLAYER_ANIMATIONS), "run_shoot", "land", "special"]);
  for (const name of ["idle", "run", "jump", "fall", "crouch", "shoot", "hit", "death"]) {
    if (!knownPlayer.has(name)) warn(`anim:player:${name}`, `Unknown player animation "${name}".`);
  }
  for (const name of Object.keys(ENEMY_ANIMATIONS)) {
    if (!name) warn("anim:enemy", "Enemy animation map has an empty name.");
  }
  for (const name of Object.keys(BOSS_01_ANIMATIONS)) {
    if (!name) warn("anim:boss", "Boss animation map has an empty name.");
  }
}

export function validateStudio01Level(level) {
  if (!level || level.id !== "studio_01") return;
  uniqueIds(level.checkpoints, "checkpoint");
  uniqueIds(level.doors, "door");
  uniqueIds(level.encounters, "encounter");
  uniqueIds(level.hazards, "hazard");
  uniqueIds(level.destructibles, "destructible");
  uniqueIds(level.rescues, "rescue");
  uniqueIds(level.vehicles, "vehicle");
  uniqueIds(level.pickups, "pickup");

  const width = level.worldWidth || 0;
  const height = level.worldHeight || 1080;
  const destructibleIds = new Set((level.destructibles || []).map((d) => d.id));
  for (const rescue of level.rescues || []) {
    if (!rescue.id) warn("rescue:id", "A rescue is missing an id.");
    if (rescue.containerId && !destructibleIds.has(rescue.containerId)) {
      warn(
        `rescue-container:${rescue.id}`,
        `Rescue "${rescue.id}" references missing container "${rescue.containerId}". Point containerId at a destructible id.`
      );
    }
  }

  const cpIds = new Set((level.checkpoints || []).map((c) => c.id));
  for (const step of level.objectives || []) {
    if (step.checkpointId && !cpIds.has(step.checkpointId)) {
      warn(
        `obj-cp:${step.id}`,
        `Objective "${step.id}" references missing checkpoint "${step.checkpointId}".`
      );
    }
  }

  const arena = level.bossArena;
  if (!arena || !(arena.left < arena.right)) {
    warn("boss-arena", "Boss arena bounds are invalid. Expected bossArena.left < bossArena.right inside the level.");
  } else {
    if (arena.left < 0 || arena.right > width) {
      warn("boss-arena-bounds", `Boss arena [${arena.left}, ${arena.right}] is outside world width ${width}.`);
    }
  }

  for (const enc of level.encounters || []) {
    if (!enc.scripted || enc.boss) continue;
    if (!(enc.arenaLeft < enc.arenaRight)) {
      warn(`enc-arena:${enc.id}`, `Encounter "${enc.id}" has invalid arenaLeft/arenaRight.`);
    }
    if (!(enc.spawnPoints || []).length) {
      warn(`enc-spawns:${enc.id}`, `Encounter "${enc.id}" has no spawnPoints. Add reachable floor points.`);
    }
    for (const p of enc.spawnPoints || []) {
      if (p.x < 0 || p.x > width || (p.y != null && (p.y < 0 || p.y > height))) {
        warn(`enc-spawn:${enc.id}`, `Encounter "${enc.id}" spawn (${p.x}, ${p.y}) is outside the level.`);
      }
    }
  }

  for (const hz of level.hazards || []) {
    if (width && (hz.x < -200 || hz.x > width + 200)) {
      warn(`hazard:${hz.id}`, `Hazard "${hz.id}" x=${hz.x} is far outside the level.`);
    }
  }

  const menuActions = ["START GAME", "HOW TO PLAY", "SETTINGS", "CONTROLS", "EXIT"];
  if (!menuActions.length) warn("menu", "Main menu actions are empty.");
}

export function validateAudioVideo(audio) {
  for (const id of ["music_menu", "music_studio_01", "music_boss_01"]) {
    const def = SOUND_DEFS[id];
    if (!def) warn(`music-def:${id}`, `Missing music definition "${id}".`);
    else if (audio && typeof audio.hasBuffer === "function" && !audio.hasBuffer(id)) {
      warn(`music-file:${id}`, `Music "${id}" file is missing (${def.path}). Gameplay continues silent for this cue.`);
    }
  }
  if (!BOSS_INTRO_SRC) warn("video:intro", "BOSS_INTRO_SRC is empty. Set videos/boss_01_intro.mp4.");
  if (!BOSS_DEFEAT_SRC) warn("video:defeat", "BOSS_DEFEAT_SRC is empty. Set videos/boss_01_defeat.mp4.");
}

export function validateStudio01Release({ level, audio } = {}) {
  validateCharacterConfigs();
  validateWeaponConfigs();
  validateEnemyConfigs();
  validateAnimationNames();
  validateStudio01Level(level);
  validateAudioVideo(audio);
}
