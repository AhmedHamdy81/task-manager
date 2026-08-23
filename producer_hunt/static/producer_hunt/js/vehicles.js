/** Studio 01 Battle Dolly — short playable camera-rig vehicle set-piece. */

import { Projectile } from "./projectile.js";
import { SpriteAnimator } from "./animation.js";
import { aabb, keepInWorld, resolveSolids } from "./collision.js";
import { applyGravity, arcadeAxis } from "./physics.js";
import { DEBUG_COMBAT, SHAKE_HEAVY, SHAKE_LIGHT } from "./config.js";
import { findSafeSpawn } from "./progression.js";
import { damageDestructiblesInRadius, damageDestructible } from "./destructibles.js";
import { VEHICLE_ANIMATIONS } from "./sprite-spec.js";
import { COMBAT_DESTRUCTIBLE_KINDS, nextVolleyId } from "./score-manager.js";

const HP = 10;
const KIT = new Map();
const MISSING = new Set();

export const VEHICLE_SEQUENCE_ID = "studio_01_battle_dolly";

export const EXPECTED_VEHICLE_ASSETS = [
  "vehicles/battle_dolly/battle_dolly_idle.png",
  "vehicles/battle_dolly/battle_dolly_drive.png",
  "vehicles/battle_dolly/battle_dolly_hop.png",
  "vehicles/battle_dolly/battle_dolly_fire.png",
  "vehicles/battle_dolly/battle_dolly_special.png",
  "vehicles/battle_dolly/battle_dolly_hit.png",
  "vehicles/battle_dolly/battle_dolly_destroyed.png",
  "hud/vehicles/battle_dolly_icon.png",
];

export function warnMissingVehicleAsset(rel) {
  if (MISSING.has(rel)) return;
  MISSING.add(rel);
  console.warn(`[Producer Hunt] Missing vehicle asset: ${rel}. Using a labeled placeholder.`);
}

export const VEHICLE_DEFS = {
  battle_dolly: {
    id: "battle_dolly",
    displayName: "Battle Dolly",
    maxHealth: 20 * HP,
    maxSpeed: 230,
    accel: 700,
    decel: 850,
    reverse: 1100,
    hopVelocity: 1240,
    bodyW: 148,
    bodyH: 78,
    visW: 220,
    visH: 140,
    muzzle: { x: 78, y: -92 },
    contactDamage: 2 * HP,
    cannonDamage: 2 * HP,
    cannonInterval: 0.11,
    cannonSpeed: 1100,
    spotlightDamage: 6 * HP,
    spotlightCooldown: 8,
    spotlightWidth: 320,
    spotlightDuration: 0.5,
    spotlightCharge: 0.38,
    invuln: 0.5,
    warning: 1.2,
    ejectDamage: 2 * HP,
    repair: 4 * HP,
    exitCooldown: 0.85,
    color: "#1e3a5f",
  },
};

export function vehicleDef(kind) {
  return VEHICLE_DEFS[kind] || VEHICLE_DEFS.battle_dolly;
}

function kitFromImages(kind, images) {
  const def = vehicleDef(kind);
  const animations = {};
  for (const [name, clip] of Object.entries(VEHICLE_ANIMATIONS)) {
    const rel = `vehicles/${kind}/${kind}_${clip.file || name}.png`;
    const image = images?.get?.(rel) || null;
    animations[name] = { ...clip, image, frameWidth: 256, frameHeight: 256 };
  }
  return {
    id: kind,
    frameWidth: 256,
    frameHeight: 256,
    renderWidth: def.visW,
    renderHeight: def.visH,
    animations,
  };
}

export async function preloadVehicleKits(assets) {
  for (const rel of EXPECTED_VEHICLE_ASSETS) {
    const img = await assets.loadOptionalImage(rel, rel);
    if (!img) warnMissingVehicleAsset(rel);
  }
  KIT.set("battle_dolly", kitFromImages("battle_dolly", assets.images));
}

export function instantiateVehicle(raw, index, levelId) {
  const def = vehicleDef(raw.kind || "battle_dolly");
  const id = raw.id || `${levelId}_vehicle_${index}`;
  const v = {
    id,
    kind: def.id,
    def,
    sequenceId: raw.sequenceId || VEHICLE_SEQUENCE_ID,
    state: "parked",
    health: def.maxHealth,
    maxHealth: def.maxHealth,
    footX: raw.x,
    footY: raw.y,
    parkX: raw.x,
    parkY: raw.y,
    vx: 0,
    vy: 0,
    facing: 1,
    onGround: true,
    invuln: 0,
    hitFlash: 0,
    fireCool: 0,
    spotlightCool: 0,
    spotlightCharge: 0,
    spotlightActive: 0,
    spotlightHits: new Set(),
    enterLock: 0,
    exitCool: 0,
    warningTimer: 0,
    hopLock: 0,
    ramCool: 0,
    recoil: 0,
    prompt: "",
    promptHint: 2.4,
    sequenceDone: false,
    waveIndex: -1,
    waveAcc: 0,
    waveLiving: 0,
    spawnedIds: [],
    left: raw.left,
    right: raw.right,
    stopX: raw.stopX,
    camLeft: raw.camLeft ?? raw.left,
    camRight: raw.camRight ?? raw.right,
    encounterId: raw.encounterId || "enc_dolly",
    anim: new SpriteAnimator(KIT.get(def.id)),
    occupied: false,
  };
  syncVehicleBox(v);
  return v;
}

function syncVehicleBox(v) {
  v.w = v.def.bodyW;
  v.h = v.def.bodyH;
  v.x = v.footX - v.w / 2;
  v.y = v.footY - v.h;
}

function syncVehicleFeet(v) {
  v.footX = v.x + v.w / 2;
  v.footY = v.y + v.h;
}

export function vehicleBounds(v) {
  return { x: v.x, y: v.y, w: v.w, h: v.h };
}

export function muzzleWorld(v) {
  return {
    x: v.footX + v.facing * v.def.muzzle.x,
    y: v.footY + v.def.muzzle.y,
  };
}

export function spotlightBox(v) {
  const m = muzzleWorld(v);
  const w = v.def.spotlightWidth;
  const h = 118;
  if (v.facing >= 0) return { x: m.x, y: m.y - h * 0.55, w, h };
  return { x: m.x - w, y: m.y - h * 0.55, w, h };
}

function groundSensor(v, side) {
  const inset = 18;
  const x = side < 0 ? v.x + inset : v.x + v.w - inset - 10;
  return { x, y: v.y + v.h - 4, w: 10, h: 12 };
}

export function vehicleOccupied(game) {
  return Boolean(game?.vehicle?.occupied);
}

export function suppressesClientEncounter(game) {
  const v = game?.vehicle;
  return Boolean(v && (v.occupied || v.sequenceDone));
}

export function vehicleCameraLock(game, fallback) {
  const v = game?.vehicle;
  if (!v?.occupied) return fallback || null;
  return {
    left: v.camLeft,
    right: v.camRight,
    lookScale: 1.28,
    focusX: 0.42,
  };
}

export function vehicleFollowTarget(game) {
  const v = game?.vehicle;
  if (!v?.occupied || v.state === "exploding" || v.state === "wreck") return game.player;
  return v;
}

export function stopVehicleAudio(game) {
  game.audio?.stopSound?.("vehicle_engine_loop");
  game.audio?.stopSound?.("vehicle_warning");
  game.audio?.stopSound?.("vehicle_spotlight_charge");
}

export function clearVehicleProjectiles(game) {
  if (!game) return;
  const drop = (shot) => shot.weaponId === "dolly_cannon" || shot.type === "dolly_flash";
  for (const shot of game.projectiles || []) {
    if (drop(shot)) shot.disable?.();
  }
  game.projectiles = (game.projectiles || []).filter((p) => p.alive);
}

function rumble(game, ms = 80, mag = 0.28) {
  if (game.settings?.reducedMotion) return;
  if (game.settings?.vehicleRumble === false) return;
  try {
    const pads = navigator.getGamepads?.() || [];
    const pad = [...pads].find((p) => p && p.vibrationActuator);
    pad?.vibrationActuator?.playEffect?.("dual-rumble", {
      duration: ms,
      strongMagnitude: mag,
      weakMagnitude: mag * 0.6,
    });
  } catch {
    /* optional */
  }
}

function areaClear(game, v, radius = 220) {
  for (const e of game.enemies || []) {
    if (!e.alive) continue;
    if (Math.hypot(e.footX - v.footX, (e.footY || 0) - v.footY) < radius) return false;
  }
  return true;
}

function exitBlocked(game, box) {
  const world = game.world;
  const extras = [
    ...(world.solids || []),
    ...(world.hazards || []).filter((h) => h.enabled && h.damage > 0 && (h.phase == null || h.phase === "active" || h.phase === "impact")),
    ...(world.destructibleSolids || []),
    vehicleBounds(game.vehicle),
    ...(game.enemies || []).filter((e) => e.alive).map((e) => e.bounds()),
  ];
  return extras.some((b) => b && aabb(box, b));
}

function pickSafeExit(game, v) {
  const p = game.player;
  const w = p?.w || 80;
  const h = p?.h || 170;
  const candidates = [
    { x: v.footX + (v.facing >= 0 ? -92 : 92), y: v.footY },
    { x: v.footX + (v.facing >= 0 ? 92 : -92), y: v.footY },
    { x: v.footX, y: v.footY - v.h - 8 },
    { x: v.footX - 140, y: v.footY },
    { x: v.footX + 140, y: v.footY },
  ];
  for (const c of candidates) {
    const box = { x: c.x - w / 2, y: c.y - h, w, h };
    if (exitBlocked(game, box)) continue;
    const grounded = findSafeSpawn(game.world, c.x, c.y, [
      vehicleBounds(v),
      ...(game.enemies || []).filter((e) => e.alive).map((e) => e.bounds()),
    ]);
    const gbox = { x: grounded.x - w / 2, y: grounded.y - h, w, h };
    if (!exitBlocked(game, gbox)) return grounded;
  }
  return findSafeSpawn(game.world, v.parkX, v.parkY, [vehicleBounds(v)]);
}

function attachPlayer(game, v) {
  const p = game.player;
  if (!p) return;
  p.mounted = true;
  p.hidden = true;
  p.vx = 0;
  p.vy = 0;
  p.footX = v.footX;
  p.footY = v.footY - 8;
  p.facing = v.facing;
  p._syncBox?.();
}

function revealPlayer(game) {
  const p = game.player;
  if (!p) return;
  p.mounted = false;
  p.hidden = false;
}

export function bindVehicle(game) {
  const list = game.world?.vehicles || [];
  game.vehicle = list[0] || null;
  if (game.vehicle?.anim && KIT.get(game.vehicle.kind)) game.vehicle.anim.setKit(KIT.get(game.vehicle.kind));
}

function suppressClient(game) {
  const enc = (game.world?.encounters || []).find((e) => e.id === "enc_client");
  if (!enc) return;
  enc.cleared = true;
  enc.activated = true;
}

function beginEnter(game, v) {
  if (v.occupied || v.health <= 0 || v.sequenceDone) return;
  if (v.exitCool > 0) return;
  const client = (game.world?.encounters || []).find((e) => e.id === "enc_client");
  if (client?.activated && !client.cleared) return;
  v.occupied = true;
  v.state = "occupied";
  v.enterLock = 0.32;
  v.promptHint = 2.8;
  attachPlayer(game, v);
  game.player?.setNotice?.("BATTLE DOLLY", 1.4);
  game.sfx("vehicle_enter", { x: v.footX });
  game.audio?.ensureLoop?.("vehicle_engine_loop", { volume: 0.32, loop: true, maxInstances: 1 });
  rumble(game, 120, 0.35);
  if (!v.sequenceDone) {
    v.waveIndex = 0;
    v.waveAcc = 0.2;
    suppressClient(game);
  }
  game.captureCheckpoint?.(null, { silent: true });
  game.hud?.invalidate();
  game.combatHint = { text: "BATTLE DOLLY — CAMERA-FLASH CANNON", until: (game._worldTime || 0) + 1.8 };
}

function finishExit(game, v, { forced = false, wreck = false } = {}) {
  if (!v.occupied && !game.player?.mounted) return;
  const pos = pickSafeExit(game, v);
  v.occupied = false;
  v.vx = 0;
  revealPlayer(game);
  const p = game.player;
  if (p) {
    p.footX = pos.x;
    p.footY = pos.y;
    p.vx = 0;
    p.vy = 0;
    p._syncBox?.();
  }
  v.exitCool = v.def.exitCooldown;
  stopVehicleAudio(game);
  game.sfx(wreck ? "vehicle_explosion" : "vehicle_exit", { x: v.footX });
  game.camera.clearShake?.();
  game.hud?.invalidate();
  if (!wreck) {
    v.state = v.sequenceDone ? "completed" : "parked";
    game.combatHint = { text: forced ? "DISMOUNT" : "ON FOOT", until: (game._worldTime || 0) + 1.2 };
  }
}

export function forceVehicleSafeRestore(game) {
  const v = game.vehicle;
  stopVehicleAudio(game);
  clearVehicleProjectiles(game);
  if (!v) {
    revealPlayer(game);
    return;
  }
  v.spotlightActive = 0;
  v.spotlightCharge = 0;
  v.spotlightHits.clear();
  if (v.occupied || game.player?.mounted) finishExit(game, v, { forced: true });
  v.occupied = false;
  revealPlayer(game);
}

function spawnWaveEnemy(game, v, type, x, y) {
  const enc = {
    id: v.encounterId,
    arenaLeft: v.left,
    arenaRight: v.right,
    spawnPoints: [{ x, y }],
  };
  const living = (game.enemies || []).filter((e) => e.alive && e.encounterId === v.encounterId).length;
  if (living >= 4) return null;
  const enemy = game.spawnEncounterEnemy(enc, type, { x, y, id: `${v.encounterId}_${type}_${game.enemies.length}` });
  if (enemy) v.spawnedIds.push(enemy.spawnId);
  return enemy;
}

function tickWaves(game, v, dt) {
  if (!v.occupied || v.sequenceDone) return;
  const living = (game.enemies || []).filter((e) => e.alive && e.encounterId === v.encounterId);
  v.waveLiving = living.length;
  v.waveAcc += dt;
  if (v.waveIndex === 0 && v.waveAcc > 0.35 && living.length === 0) {
    spawnWaveEnemy(game, v, "post_producer", v.footX + 280, v.parkY);
    spawnWaveEnemy(game, v, "post_producer", v.footX + 420, v.parkY);
    spawnWaveEnemy(game, v, "post_producer", v.footX + 540, v.parkY);
    game.combatHint = { text: "WAVE 1 — CANNON AND RAM", until: (game._worldTime || 0) + 1.3 };
    v.waveIndex = 1;
    v.waveAcc = 0;
    return;
  }
  if (v.waveIndex === 1 && living.length === 0 && v.waveAcc > 0.5) {
    const plat = v.parkY - 256;
    spawnWaveEnemy(game, v, "post_producer", v.left + 420, plat);
    spawnWaveEnemy(game, v, "post_producer", v.left + 780, plat);
    spawnWaveEnemy(game, v, "colorist", v.footX + 360, v.parkY);
    game.combatHint = { text: "WAVE 2 — HOP AND FIRE", until: (game._worldTime || 0) + 1.3 };
    v.waveIndex = 2;
    v.waveAcc = 0;
    return;
  }
  if (v.waveIndex === 2 && living.length === 0 && v.waveAcc > 0.55) {
    spawnWaveEnemy(game, v, "vfx_supervisor", v.footX + 300, v.parkY);
    spawnWaveEnemy(game, v, "client", v.footX + 520, v.parkY);
    spawnWaveEnemy(game, v, "post_producer", v.footX + 220, v.parkY);
    spawnWaveEnemy(game, v, "post_producer", v.footX + 640, v.parkY);
    game.combatHint = { text: "WAVE 3 — SPOTLIGHT BLAST", until: (game._worldTime || 0) + 1.4 };
    v.waveIndex = 3;
    v.waveAcc = 0;
    return;
  }
  if (v.waveIndex >= 3 && living.length === 0 && v.waveAcc > 0.4) {
    v.sequenceDone = true;
  }
}

function fireCannon(game, v) {
  if (v.fireCool > 0 || v.enterLock > 0 || v.state === "warning") return;
  const m = muzzleWorld(v);
  const reduced = Boolean(game.settings?.reducedFlashes || game.settings?.reducedMotion);
  v.fireCool = v.def.cannonInterval;
  v.recoil = 6;
  const volleyId = nextVolleyId();
  const shot = new Projectile({
    x: m.x,
    y: m.y,
    vx: v.facing * v.def.cannonSpeed,
    vy: 0,
    damage: v.def.cannonDamage,
    owner: "player",
    faction: "player",
    type: "dolly_flash",
    weaponId: "dolly_cannon",
    volleyId,
    w: 28,
    h: 16,
    vis: reduced ? 28 : 42,
    lifetime: 0.9,
    tint: reduced ? "#7dd3fc" : "#e0f2fe",
    impactFx: { sheetKey: "effects", frame: 4, size: 36, life: 0.16 },
    cameraShake: reduced ? 0 : 0.04,
  });
  game.projectiles.push(shot);
  game.scoreboard?.noteAttackFired(volleyId);
  game.sfx("vehicle_cannon", { x: m.x, camera: game.camera });
  if (!reduced) {
    game.spawnFx?.({
      sheetKey: "effects",
      frame: 5,
      x: m.x,
      y: m.y,
      size: 40,
      life: 0.1,
      flipX: v.facing < 0,
    });
  }
  v.anim.play("fire", { restart: true });
}

function tickSpotlight(game, v, dt, input) {
  if (v.spotlightCool > 0) v.spotlightCool -= dt;
  if (v.spotlightCharge > 0) {
    v.spotlightCharge -= dt;
    if (v.spotlightCharge <= 0) {
      v.spotlightActive = v.def.spotlightDuration;
      v.spotlightHits = new Set();
      v._spotVolley = nextVolleyId();
      game.scoreboard?.noteAttackFired(v._spotVolley);
      game.sfx("vehicle_spotlight_fire", { x: v.footX });
      if (game.shakeEnabled?.()) game.camera.addShake(SHAKE_HEAVY * 0.55);
      rumble(game, 220, 0.45);
      v.anim.play("special", { restart: true });
    }
  }
  if (v.spotlightActive > 0) {
    v.spotlightActive -= dt;
    const box = spotlightBox(v);
    for (const e of game.enemies || []) {
      if (!e.alive || e.isBoss) continue;
      if (v.spotlightHits.has(e.spawnId || e)) continue;
      if (!aabb(box, e.bounds())) continue;
      v.spotlightHits.add(e.spawnId || e);
      const wasAlive = e.alive;
      e.takeDamage(v.def.spotlightDamage, { owner: "player" });
      if (v._spotVolley) game.scoreboard?.noteAttackHit(v._spotVolley, e.spawnId || e.id);
      if (wasAlive && !e.alive) {
        game.scoreboard?.awardEnemyDefeat(e, { weaponId: "dolly_cannon" });
        game.scoreboard?.sync(game);
      }
      game.sfx("enemy_hit", { x: e.footX });
    }
    for (const d of game.world?.destructibles || []) {
      if (d.state === "gone" || d.state === "rubble") continue;
      if (v.spotlightHits.has(d.id)) continue;
      if (!aabb(box, d)) continue;
      v.spotlightHits.add(d.id);
      if (v._spotVolley && COMBAT_DESTRUCTIBLE_KINDS.has(d.kind)) {
        game.scoreboard?.noteAttackHit(v._spotVolley, d.id);
      }
      damageDestructible(game, d, v.def.spotlightDamage);
    }
    if (v.spotlightActive <= 0) v.spotlightCool = v.def.spotlightCooldown;
  }
  if (v.enterLock > 0 || v.state === "warning" || v.state === "exploding") return;
  if (input.consume("special") && v.spotlightCool <= 0 && v.spotlightCharge <= 0 && v.spotlightActive <= 0) {
    v.spotlightCharge = v.def.spotlightCharge;
    game.sfx("vehicle_spotlight_charge", { x: v.footX });
    v.anim.play("special", { restart: true });
  }
}

export function vehicleTakeDamage(game, amount, opts = {}) {
  const v = game.vehicle;
  if (!v?.occupied || v.health <= 0) return 0;
  if (v.invuln > 0) return 0;
  const amt = Math.max(1, Math.round(Number(amount) || 0));
  if (amt <= 0) return 0;
  v.health = Math.max(0, v.health - amt);
  v.invuln = v.def.invuln;
  v.hitFlash = 0.12;
  v.anim.play("hit", { restart: true });
  game.sfx("vehicle_hit", { x: v.footX });
  if (opts.knockbackX && Math.abs(opts.knockbackX) > 40) v.vx += opts.knockbackX * 0.15;
  if (game.shakeEnabled?.()) game.camera.addShake(SHAKE_LIGHT);
  rumble(game, 70, 0.3);
  game.hud?.invalidate();
  if (v.health <= 0) beginWarning(game, v);
  return amt;
}

function beginWarning(game, v) {
  if (v.state === "warning" || v.state === "exploding") return;
  v.state = "warning";
  v.warningTimer = v.def.warning;
  game.sfx("vehicle_warning", { x: v.footX, force: true });
  game.combatHint = { text: "DOLLY OVERLOAD — EXIT", until: (game._worldTime || 0) + 1.3 };
}

function explodeVehicle(game, v) {
  v.state = "exploding";
  finishExit(game, v, { forced: true, wreck: true });
  const p = game.player;
  if (p?.alive) p.takeDamage(v.def.ejectDamage, { knockbackX: v.facing * -80 });
  damageDestructiblesInRadius(game, v.footX, v.footY - 40, 90, 30);
  game.spawnFx?.({
    sheetKey: "effects",
    frame: 3,
    x: v.footX,
    y: v.footY - 40,
    size: 160,
    life: 0.45,
  });
  if (game.shakeEnabled?.()) game.camera.addShake(SHAKE_HEAVY);
  rumble(game, 280, 0.55);
  v.state = "wreck";
  v.health = 0;
  v.anim.play("destroyed", { restart: true });
  v.sequenceDone = true;
  suppressClient(game);
}

function tryRepair(game, v) {
  if (!v.occupied || v.health >= v.maxHealth) return;
  for (const pickup of game.world?.pickups || []) {
    if (pickup.taken || pickup.effect !== "vehicle_repair") continue;
    if (!aabb(vehicleBounds(v), pickup)) continue;
    pickup.taken = true;
    v.health = Math.min(v.maxHealth, v.health + (pickup.value || v.def.repair));
    game.sfx("vehicle_repair", { x: v.footX });
    game.player?.setNotice?.("DOLLY REPAIR", 1.1);
    game.hud?.invalidate();
  }
}

function ram(game, v) {
  if (v.ramCool > 0 || Math.abs(v.vx) < 70) return;
  const box = vehicleBounds(v);
  for (const e of game.enemies || []) {
    if (!e.alive || e.isBoss) continue;
    if (!aabb(box, e.bounds())) continue;
    v.ramCool = 0.32;
    const dmg = e.type === "post_producer" ? v.def.contactDamage : Math.round(v.def.contactDamage * 0.7);
    const wasAlive = e.alive;
    e.takeDamage(dmg, { owner: "player" });
    if (wasAlive && !e.alive) {
      game.scoreboard?.awardEnemyDefeat(e, { weaponId: "dolly_cannon" });
      game.scoreboard?.sync(game);
    }
    e.vx = v.facing * 240;
    if (game.shakeEnabled?.()) game.camera.addShake(0.18);
    rumble(game, 60, 0.22);
    break;
  }
  for (const d of game.world?.destructibles || []) {
    if (d.state === "gone" || d.state === "rubble") continue;
    if (!aabb(box, d)) continue;
    v.ramCool = 0.28;
    damageDestructible(game, d, 35);
    if (game.shakeEnabled?.()) game.camera.addShake(0.16);
    break;
  }
}

function desiredAnim(v) {
  if (v.state === "wreck" || v.state === "exploding") return "destroyed";
  if (v.hitFlash > 0) return "hit";
  if (v.spotlightCharge > 0 || v.spotlightActive > 0) return "special";
  if (v.fireCool > v.def.cannonInterval * 0.45) return "fire";
  if (!v.onGround) return "hop";
  if (Math.abs(v.vx) > 28) return "drive";
  return "idle";
}

export function tickVehicles(game, dt) {
  const v = game.vehicle;
  if (!v || !game.world) return;
  if (v.anim?.kit !== KIT.get(v.kind) && KIT.get(v.kind)) v.anim.setKit(KIT.get(v.kind));
  if (v.invuln > 0) v.invuln -= dt;
  if (v.hitFlash > 0) v.hitFlash -= dt;
  if (v.fireCool > 0) v.fireCool -= dt;
  if (v.enterLock > 0) v.enterLock -= dt;
  if (v.exitCool > 0) v.exitCool -= dt;
  if (v.hopLock > 0) v.hopLock -= dt;
  if (v.ramCool > 0) v.ramCool -= dt;
  if (v.recoil > 0) v.recoil -= dt * 28;
  if (v.promptHint > 0) v.promptHint -= dt;
  v.prompt = "";

  if (game._cinematicActive || game.bossEncounter?.phase === "intro") {
    if (v.occupied || game.player?.mounted) forceVehicleSafeRestore(game);
    return;
  }

  const p = game.player;
  const input = game.input;
  const near = p && aabb(
    { x: p.footX - 40, y: p.footY - 160, w: 80, h: 170 },
    { x: v.footX - 90, y: v.footY - 140, w: 180, h: 150 }
  );

  if (!v.occupied && v.state === "parked" && v.health > 0 && !v.sequenceDone && p?.alive && near && v.exitCool <= 0) {
    const clear = areaClear(game, v);
    v.prompt = clear ? "enter" : "clear";
    if (clear && (input.consume("interact") || input.consume("confirm"))) beginEnter(game, v);
  }

  if (!v.occupied) {
    v.vx = 0;
    v.anim.play(v.state === "wreck" ? "destroyed" : "idle");
    v.anim.update(dt);
    return;
  }

  tickWaves(game, v, dt);
  tryRepair(game, v);

  const stopped = v.footX >= v.stopX - 8 || v.sequenceDone;
  if (stopped) {
    v.footX = Math.min(v.footX, v.stopX);
    syncVehicleBox(v);
    v.sequenceDone = true;
    suppressClient(game);
    v.prompt = "exit";
  }

  let wish = 0;
  if (!stopped && v.state !== "exploding") {
    if (input.isDown("moveLeft")) wish -= 1;
    if (input.isDown("moveRight")) wish += 1;
  }
  if (wish !== 0) v.facing = wish;
  arcadeAxis(v, wish, dt, {
    accel: v.def.accel,
    decel: v.def.decel,
    reverse: v.def.reverse,
    maxSpeed: v.def.maxSpeed,
  });
  if (stopped) v.vx = 0;

  if (v.state !== "exploding" && v.hopLock <= 0 && v.onGround && input.consume("jump")) {
    v.vy = -v.def.hopVelocity;
    v.onGround = false;
    v.hopLock = 0.2;
    game.sfx("vehicle_hop", { x: v.footX });
    v.anim.play("hop", { restart: true });
  }

  applyGravity(v, dt);
  resolveSolids(v, game.world.solids, dt);
  keepInWorld(v, game.world);
  v.x = Math.max(v.left, Math.min(v.x, v.right - v.w));
  if (v.footX > v.stopX) {
    v.footX = v.stopX;
    syncVehicleBox(v);
    v.vx = 0;
  }
  syncVehicleFeet(v);
  if (v.x <= v.left + 1 && v.vx < 0) v.vx = 0;
  if (v.x + v.w >= v.right - 1 && v.vx > 0) v.vx = 0;

  ram(game, v);
  if (v.state !== "warning" && v.state !== "exploding" && input.isDown("shoot")) fireCannon(game, v);
  tickSpotlight(game, v, dt, input);

  const speed = Math.abs(v.vx);
  if (v.occupied && !game.audio?.isPlaying?.("vehicle_engine_loop")) {
    game.audio?.ensureLoop?.("vehicle_engine_loop", { volume: 0.28 + Math.min(0.12, speed / 2000), loop: true });
  }

  if (v.state === "warning") {
    v.warningTimer -= dt;
    if (v.warningTimer <= 0) explodeVehicle(game, v);
  }

  attachPlayer(game, v);
  const canExit = v.state === "occupied" || v.state === "warning" || stopped;
  if (canExit && v.enterLock <= 0 && (input.consume("interact") || input.consume("confirm") || (stopped && v.promptHint < 0 && v.waveLiving === 0))) {
    const pos = pickSafeExit(game, v);
    const box = { x: pos.x - 40, y: pos.y - 170, w: 80, h: 170 };
    if (!exitBlocked(game, box) || stopped) finishExit(game, v, { forced: stopped });
  }

  const want = desiredAnim(v);
  if (v.anim.name !== want || (want === "fire" && v.anim.finished)) v.anim.play(want, { restart: want === "fire" || want === "hit" });
  v.anim.flip = v.facing < 0;
  v.anim.update(dt);
}

export function snapshotVehicles(world) {
  return (world?.vehicles || []).map((v) => ({
    id: v.id,
    state: v.occupied ? "occupied" : v.state,
    health: v.health,
    sequenceDone: Boolean(v.sequenceDone),
    waveIndex: v.waveIndex,
    occupied: Boolean(v.occupied),
    footX: v.footX,
    footY: v.footY,
    facing: v.facing,
  }));
}

export function applyVehicleSnapshot(game, snap) {
  const v = game.vehicle;
  stopVehicleAudio(game);
  clearVehicleProjectiles(game);
  if (!v) {
    revealPlayer(game);
    return;
  }
  const rows = Array.isArray(snap) ? snap : [];
  const rec = rows.find((r) => r.id === v.id) || rows[0];
  v.spotlightActive = 0;
  v.spotlightCharge = 0;
  v.spotlightHits = new Set();
  v.warningTimer = 0;
  v.enterLock = 0;
  v.fireCool = 0;
  v.recoil = 0;
  if (!rec) {
    v.state = "parked";
    v.occupied = false;
    v.health = v.maxHealth;
    v.footX = v.parkX;
    v.footY = v.parkY;
    v.sequenceDone = false;
    v.waveIndex = -1;
    syncVehicleBox(v);
    revealPlayer(game);
    return;
  }
  v.health = Math.max(0, Number(rec.health) || 0);
  v.sequenceDone = Boolean(rec.sequenceDone);
  v.waveIndex = Number.isFinite(rec.waveIndex) ? rec.waveIndex : -1;
  v.facing = rec.facing || 1;
  if (rec.state === "wreck" || rec.state === "exploding" || v.health <= 0) {
    v.state = "wreck";
    v.occupied = false;
    v.health = 0;
    v.sequenceDone = true;
    v.footX = rec.footX || v.parkX;
    v.footY = rec.footY || v.parkY;
    syncVehicleBox(v);
    v.anim.play("destroyed");
    revealPlayer(game);
    suppressClient(game);
    return;
  }
  if (rec.sequenceDone && !rec.occupied) {
    v.state = "completed";
    v.occupied = false;
    v.footX = rec.footX || v.stopX;
    v.footY = rec.footY || v.parkY;
    syncVehicleBox(v);
    revealPlayer(game);
    suppressClient(game);
    return;
  }
  if (rec.occupied && v.health > 0) {
    v.footX = rec.footX || v.parkX;
    v.footY = rec.footY || v.parkY;
    syncVehicleBox(v);
    v.state = "occupied";
    v.occupied = true;
    attachPlayer(game, v);
    game.audio?.ensureLoop?.("vehicle_engine_loop", { volume: 0.3, loop: true });
    return;
  }
  v.state = "parked";
  v.occupied = false;
  v.footX = v.parkX;
  v.footY = v.parkY;
  syncVehicleBox(v);
  revealPlayer(game);
}

export function vehicleHud(v) {
  if (!v?.occupied) return null;
  return {
    name: v.def.displayName,
    health: v.health,
    maxHealth: v.maxHealth,
    spotlight: Math.max(0, v.spotlightCool),
    spotlightMax: v.def.spotlightCooldown,
    hint: v.promptHint > 0,
    prompt: v.prompt,
  };
}

function drawFallback(ctx, v) {
  ctx.fillStyle = v.def.color;
  ctx.fillRect(-70, -v.def.visH + 18, 140, v.def.visH - 28);
  ctx.fillStyle = "#0f172a";
  ctx.fillRect(-62, -36, 124, 22);
  ctx.fillStyle = "#e0f2fe";
  ctx.beginPath();
  ctx.arc(v.facing >= 0 ? 58 : -58, -88, 14, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#f8fafc";
  ctx.font = "bold 11px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("DOLLY", 0, -48);
}

export function drawVehicles(ctx, game) {
  const v = game.vehicle;
  if (!v) return;
  const origin = game.camera.worldToScreen(v.footX + (v.facing * v.recoil || 0), v.footY);
  ctx.save();
  if (v.hitFlash > 0) ctx.globalAlpha = 0.62;
  if (v.state === "warning") ctx.globalAlpha = 0.55 + Math.sin((game._worldTime || 0) * 22) * 0.35;
  v.anim.flip = v.facing < 0;
  v.anim.draw(ctx, origin.x, origin.y, (g) => drawFallback(g, v));
  ctx.restore();

  const reduced = Boolean(game.settings?.reducedFlashes || game.settings?.reducedMotion);
  if (v.spotlightCharge > 0 || v.spotlightActive > 0) {
    const box = spotlightBox(v);
    const s = game.camera.worldToScreen(box.x, box.y);
    ctx.save();
    ctx.globalAlpha = reduced ? 0.22 : v.spotlightActive > 0 ? 0.28 : 0.16;
    ctx.fillStyle = "#7dd3fc";
    ctx.fillRect(s.x, s.y, box.w, box.h);
    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 2;
    ctx.strokeRect(s.x, s.y, box.w, box.h);
    if (game.settings?.hazardSymbols !== false || reduced) {
      ctx.fillStyle = "#fbbf24";
      ctx.font = "bold 22px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("!", s.x + box.w / 2, s.y + 28);
    }
    ctx.restore();
  }

  if (v.prompt && !v.occupied) {
    const label = v.prompt === "clear" ? "CLEAR THE AREA" : "F / ENTER  BOARD BATTLE DOLLY";
    ctx.save();
    ctx.fillStyle = "rgba(15,23,42,0.86)";
    ctx.fillRect(origin.x - 150, origin.y - v.def.visH - 40, 300, 36);
    ctx.strokeStyle = "#38bdf8";
    ctx.strokeRect(origin.x - 150, origin.y - v.def.visH - 40, 300, 36);
    ctx.fillStyle = "#e0f2fe";
    ctx.font = "bold 13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(label, origin.x, origin.y - v.def.visH - 16);
    ctx.restore();
  } else if (v.occupied && v.prompt === "exit") {
    ctx.save();
    ctx.fillStyle = "rgba(15,23,42,0.86)";
    ctx.fillRect(origin.x - 140, origin.y - v.def.visH - 44, 280, 36);
    ctx.strokeStyle = "#fbbf24";
    ctx.strokeRect(origin.x - 140, origin.y - v.def.visH - 44, 280, 36);
    ctx.fillStyle = "#fbbf24";
    ctx.font = "bold 13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("F / ENTER  EXIT BEFORE BOSS", origin.x, origin.y - v.def.visH - 20);
    ctx.restore();
  }
}

export function drawVehicleHud(ctx, view) {
  const dolly = view.vehicle;
  if (!dolly) return;
  const x = 24;
  const y = 300;
  ctx.save();
  ctx.fillStyle = "rgba(5, 7, 12, 0.62)";
  ctx.fillRect(x, y, 360, 92);
  const icon = view.assets?.get?.("hud/vehicles/battle_dolly_icon.png");
  if (icon) ctx.drawImage(icon, x + 10, y + 12, 48, 48);
  else {
    ctx.fillStyle = "#1e3a5f";
    ctx.fillRect(x + 10, y + 12, 48, 48);
  }
  ctx.fillStyle = "#e0f2fe";
  ctx.font = "bold 16px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(dolly.name.toUpperCase(), x + 68, y + 28);
  const ratio = dolly.maxHealth ? dolly.health / dolly.maxHealth : 0;
  ctx.fillStyle = "#1f2937";
  ctx.fillRect(x + 68, y + 38, 220, 12);
  ctx.fillStyle = ratio > 0.3 ? "#38bdf8" : "#f87171";
  ctx.fillRect(x + 68, y + 38, 220 * Math.max(0, Math.min(1, ratio)), 12);
  ctx.fillStyle = "#cbd5e1";
  ctx.font = "12px sans-serif";
  ctx.fillText(`${Math.ceil(dolly.health)} / ${dolly.maxHealth}`, x + 294, y + 49);
  const cd = dolly.spotlight;
  ctx.fillStyle = "#94a3b8";
  ctx.fillText("SPOTLIGHT", x + 68, y + 70);
  ctx.fillStyle = cd <= 0 ? "#e8b84a" : "#64748b";
  ctx.fillText(cd <= 0 ? "READY" : `${cd.toFixed(1)}s`, x + 168, y + 70);
  if (dolly.hint) {
    ctx.fillStyle = "#7dd3fc";
    ctx.fillText("A/D drive  W hop  SPACE flash  Q blast  F exit", x + 10, y + 86);
  }
  ctx.restore();
}

export function drawVehicleDebug(ctx, game) {
  if (!(game.debug || DEBUG_COMBAT)) return;
  const v = game.vehicle;
  if (!v) return;
  const drawBox = (box, color) => {
    const s = game.camera.worldToScreen(box.x, box.y);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.strokeRect(s.x, s.y, box.w, box.h);
  };
  drawBox(vehicleBounds(v), "rgba(56,189,248,0.95)");
  drawBox(groundSensor(v, -1), "#4ade80");
  drawBox(groundSensor(v, 1), "#4ade80");
  const m = muzzleWorld(v);
  const ms = game.camera.worldToScreen(m.x, m.y);
  ctx.fillStyle = "#facc15";
  ctx.beginPath();
  ctx.arc(ms.x, ms.y, 4, 0, Math.PI * 2);
  ctx.fill();
  if (v.spotlightCharge > 0 || v.spotlightActive > 0) drawBox(spotlightBox(v), "#fbbf24");
  const exit = pickSafeExit(game, v);
  const es = game.camera.worldToScreen(exit.x, exit.y);
  ctx.strokeStyle = "#a3e635";
  ctx.strokeRect(es.x - 40, es.y - 170, 80, 170);
  const left = game.camera.worldToScreen(v.left, 0);
  const right = game.camera.worldToScreen(v.right, 0);
  ctx.strokeStyle = "rgba(248,113,113,0.7)";
  ctx.beginPath();
  ctx.moveTo(left.x, 80);
  ctx.lineTo(left.x, 1000);
  ctx.moveTo(right.x, 80);
  ctx.lineTo(right.x, 1000);
  ctx.stroke();
  ctx.fillStyle = "#86efac";
  ctx.font = "12px monospace";
  ctx.textAlign = "left";
  ctx.fillText(
    `dolly ${v.state} hp ${v.health} inv ${v.invuln.toFixed(2)} occ ${v.occupied ? 1 : 0} wave ${v.waveIndex}`,
    24,
    1048
  );
}
