/** Data-driven combat values. Player and enemies look up ids; they do not branch on names. */

export const COMBAT = {
  player: {
    damage: 10,
    cooldown: 0.25,
    lifetime: 2,
    speed: 650,
    spawnFrame: 1,
    ammo: 120,
    muzzle: {
      stand: { x: 42, y: -104 },
      crouch: { x: 48, y: -63 },
    },
    muzzleFx: { sheetKey: "projectiles", frame: 5, size: 52, life: 0.1 },
    impactFx: { sheetKey: "projectiles", frame: 6, size: 56, life: 0.18 },
  },
  enemy: {
    damage: 10,
    cooldown: 1.4,
    lifetime: 2.5,
    speed: 360,
    spawnFrame: 2,
    attackRange: 460,
    muzzle: { x: 48, y: -158 },
    impactFx: { sheetKey: "post_producer_impact", frames: 4, fps: 16, size: 96 },
  },
  client: {
    damage: 20,
    cooldown: 1.8,
    lifetime: 2.4,
    speed: 520,
    spawnFrame: 2,
    attackRange: 520,
    muzzle: { x: 46, y: -172 },
    impactFx: { sheetKey: "client_impact", frames: 4, fps: 16, size: 96 },
  },
  colorist: {
    damage: 20,
    cooldown: 1.35,
    lifetime: 0.35,
    speed: 0,
    spawnFrame: 1,
    attackRange: 92,
    muzzle: { x: 48, y: -150 },
    impactFx: { sheetKey: "effects", frame: 3, size: 88, life: 0.2 },
  },
  vfx_supervisor: {
    damage: 20,
    cooldown: 2.4,
    lifetime: 2.2,
    speed: 280,
    spawnFrame: 2,
    attackRange: 480,
    muzzle: { x: 50, y: -168 },
    impactFx: { sheetKey: "effects", frame: 4, size: 96, life: 0.24 },
  },
  boss_01: {
    damage: 10,
    cooldown: 1.8,
    lifetime: 2.6,
    speed: 420,
    spawnFrame: 3,
    attackRange: 640,
    muzzle: { x: 58, y: -128 },
    impactFx: { sheetKey: "effects", frames: 1, fps: 0, size: 72, frame: 5, life: 0.18 },
  },
};

/** Studio 01 Boss 1. Unit values scale to player HP / shot damage (10). Spec 120 HP → 1200. */
export const BOSS_01 = {
  id: "boss_01",
  displayName: "ESSAM SALAMA",
  title: "THE MASTER BARBER",
  maxHealth: 120 * COMBAT.player.damage,
  contactDamage: 2 * COMBAT.player.damage,
  projectileDamage: 1 * COMBAT.player.damage,
  meleeDamage: 2 * COMBAT.player.damage,
  chargeDamage: 2 * COMBAT.player.damage,
  slamDamage: 2 * COMBAT.player.damage,
  waveDamage: 1 * COMBAT.player.damage,
  walkSpeed: 90,
  chargeSpeed: 430,
  attackCooldown: 1.6,
  thinkDelay: 0.42,
  hitInvuln: 0.05,
  phaseTwoHealthRatio: 0.65,
  phaseThreeHealthRatio: 0.32,
  scoreValue: 10000,
  meleeRange: 128,
  preferredRange: 280,
  rangeBand: 48,
  chargeCooldown: 3.2,
  spawnSec: 0.9,
  throwPrepareSec: 0.55,
  recoverySec: 0.65,
  chargePrepareSec: 0.75,
  chargeStaggerSec: 1.1,
  phaseTransitionSec: 0.85,
  phaseThreeTransitionSec: 0.55,
  meleeTelegraphSec: 0.5,
  meleeActiveSec: 0.18,
  meleeRecoverSec: 0.75,
  slamTelegraphSec: 0.85,
  fallingWarnSec: 0.9,
  meleeHitStartFrame: 2,
  meleeHitEndFrame: 4,
  throwReleaseFrame: 3,
  projectileSpeedRazor: 520,
  projectileSpeedScissors: 480,
  projectileSpeedClippers: 420,
  razorGravity: 0,
  shotgunBossCap: 12,
  specialBossCap: 80,
  chargeArmor: 0.55,
  contactCooldown: 0.7,
  chargeContactCooldown: 0.55,
  knockback: 240,
  chargeKnockback: 380,
  meleeKnockback: 320,
  healthDropSec: 15,
  healthDropMax: 2,
  phase2: {
    walkSpeedMul: 1.12,
    attackCooldownMul: 0.88,
    chargeSpeedMul: 1.06,
  },
  phase3: {
    walkSpeedMul: 1.18,
    attackCooldownMul: 0.82,
    chargeSpeedMul: 1.1,
  },
};

export const PROJECTILE_DEFS = {
  editor_pulse: {
    id: "editor_pulse",
    frame: 0,
    hitW: 32,
    hitH: 20,
    vis: 48,
    flip: true,
  },
  assistant_scan_bolt: {
    id: "assistant_scan_bolt",
    frame: 1,
    hitW: 32,
    hitH: 20,
    vis: 48,
    flip: true,
  },
  vfx_orb: {
    id: "vfx_orb",
    frame: 2,
    hitW: 36,
    hitH: 36,
    vis: 52,
    flip: false,
  },
  colorist_chroma_bolt: {
    id: "colorist_chroma_bolt",
    frame: 3,
    hitW: 32,
    hitH: 20,
    vis: 48,
    flip: true,
  },
  machine_gun_round: {
    id: "machine_gun_round",
    frame: 1,
    hitW: 28,
    hitH: 16,
    vis: 40,
    flip: true,
  },
  shotgun_pellet: {
    id: "shotgun_pellet",
    frame: 3,
    hitW: 16,
    hitH: 16,
    vis: 28,
    flip: true,
  },
  heavy_blast: {
    id: "heavy_blast",
    frame: 2,
    hitW: 40,
    hitH: 40,
    vis: 64,
    flip: false,
  },
  deadline_projectile: {
    id: "deadline_projectile",
    frame: 4,
    hitW: 34,
    hitH: 24,
    vis: 52,
    flip: true,
  },
  client_revision_pulse: {
    id: "client_revision_pulse",
    frame: 4,
    hitW: 34,
    hitH: 18,
    vis: 52,
    flip: true,
  },
  color_blast_pulse: {
    id: "color_blast_pulse",
    frame: 3,
    hitW: 40,
    hitH: 40,
    vis: 56,
    flip: false,
  },
  vfx_arc: {
    id: "vfx_arc",
    frame: 2,
    hitW: 36,
    hitH: 36,
    vis: 56,
    flip: false,
  },
  client_mark: {
    id: "client_mark",
    frame: 4,
    hitW: 28,
    hitH: 18,
    vis: 48,
    flip: true,
  },
  boss_01_razor: {
    id: "boss_01_razor",
    sheetKey: "boss_01_razor",
    frames: 4,
    fps: 16,
    hitW: 36,
    hitH: 22,
    vis: 80,
    spin: 12,
    gravity: 110,
    lifetime: 2.2,
    flip: false,
  },
  boss_01_scissors: {
    id: "boss_01_scissors",
    sheetKey: "boss_01_scissors",
    frames: 4,
    fps: 18,
    hitW: 34,
    hitH: 34,
    vis: 78,
    spin: 18,
    lifetime: 2.4,
    flip: false,
  },
  boss_01_clippers: {
    id: "boss_01_clippers",
    sheetKey: "boss_01_clippers",
    frames: 4,
    fps: 14,
    hitW: 38,
    hitH: 26,
    vis: 84,
    spin: 5,
    lifetime: 2.6,
    interruptMove: true,
    tint: "#22d3ee",
    flip: false,
  },
  boss_01_brush: {
    id: "boss_01_brush",
    sheetKey: "boss_01_brush",
    frames: 4,
    fps: 12,
    hitW: 40,
    hitH: 28,
    vis: 86,
    throw: false,
    flip: false,
  },
  straight_razor: {
    id: "straight_razor",
    sheetKey: "straight_razor",
    frames: 4,
    fps: 16,
    hitW: 40,
    hitH: 18,
    vis: 72,
    spin: 10,
    lifetime: 2.2,
    flip: false,
  },
  barber_scissors: {
    id: "barber_scissors",
    sheetKey: "barber_scissors",
    frames: 4,
    fps: 18,
    hitW: 28,
    hitH: 28,
    vis: 64,
    spin: 16,
    lifetime: 2.3,
    flip: false,
  },
  electric_clipper_energy: {
    id: "electric_clipper_energy",
    sheetKey: "electric_clipper_energy",
    frames: 4,
    fps: 14,
    hitW: 32,
    hitH: 22,
    vis: 70,
    spin: 4,
    lifetime: 2.4,
    interruptMove: true,
    tint: "#67e8f9",
    flip: false,
  },
  falling_barber_tool: {
    id: "falling_barber_tool",
    sheetKey: "falling_barber_tool",
    frames: 4,
    fps: 12,
    hitW: 36,
    hitH: 36,
    vis: 64,
    spin: 8,
    gravity: 980,
    lifetime: 2.8,
    flip: false,
  },
  ground_wave: {
    id: "ground_wave",
    sheetKey: "ground_wave",
    frames: 4,
    fps: 14,
    hitW: 48,
    hitH: 16,
    vis: 72,
    lifetime: 1.6,
    flip: true,
  },
};

export const WEAPON_DEFS = {
  editor_pulse: {
    id: "editor_pulse",
    name: "Editing Pulse",
    weaponFrame: 0,
    projectileId: "editor_pulse",
    ...COMBAT.player,
  },
  assistant_scan_bolt: {
    id: "assistant_scan_bolt",
    name: "Scanner Blaster",
    weaponFrame: 1,
    projectileId: "assistant_scan_bolt",
    ...COMBAT.player,
  },
  vfx_orb: {
    id: "vfx_orb",
    name: "VFX Emitter",
    weaponFrame: 2,
    projectileId: "vfx_orb",
    ...COMBAT.player,
  },
  colorist_chroma_bolt: {
    id: "colorist_chroma_bolt",
    name: "Chroma Pistol",
    weaponFrame: 3,
    projectileId: "colorist_chroma_bolt",
    ...COMBAT.player,
  },
};

export const CHARACTER_WEAPON_ID = {
  editor: "editor_pulse",
  assistant: "assistant_scan_bolt",
  vfx_supervisor: "vfx_orb",
  colorist: "colorist_chroma_bolt",
};

export const ENEMY_WEAPON_ID = {
  post_producer: "deadline_projectile",
  client: "client_revision_pulse",
  colorist: "color_blast_pulse",
  vfx_supervisor: "vfx_arc",
  boss_01: "boss_01_razor",
};

export function projectileDef(id) {
  return PROJECTILE_DEFS[id] || PROJECTILE_DEFS.editor_pulse;
}

export function weaponDefForCharacter(characterId) {
  const id = CHARACTER_WEAPON_ID[characterId] || CHARACTER_WEAPON_ID.editor;
  return WEAPON_DEFS[id];
}

/**
 * Per-type, per-animation muzzle offsets from the enemy bottom-center anchor.
 * Horizontal values are for facing right; they are mirrored in world space.
 * Vertical values are never mirrored.
 */
export const ENEMY_MUZZLE = {
  post_producer: {
    idle: { x: 46, y: -158 },
    walk: { x: 48, y: -158 },
    attack: { x: 62, y: -162 },
    hit: { x: 46, y: -156 },
    death: { x: 40, y: -140 },
  },
  client: {
    idle: { x: 44, y: -172 },
    walk: { x: 46, y: -172 },
    attack: { x: 56, y: -176 },
    hit: { x: 44, y: -170 },
    death: { x: 36, y: -150 },
  },
  colorist: {
    idle: { x: 42, y: -150 },
    walk: { x: 44, y: -148 },
    attack: { x: 58, y: -152 },
    hit: { x: 40, y: -146 },
    death: { x: 32, y: -120 },
  },
  vfx_supervisor: {
    idle: { x: 46, y: -168 },
    walk: { x: 48, y: -166 },
    attack: { x: 60, y: -170 },
    hit: { x: 44, y: -164 },
    death: { x: 36, y: -140 },
  },
};

export function enemyMuzzleOffset(typeId, animName) {
  const map = ENEMY_MUZZLE[typeId];
  const fallback =
    typeId === "client"
      ? COMBAT.client.muzzle
      : typeId === "colorist"
        ? COMBAT.colorist.muzzle
        : typeId === "vfx_supervisor"
          ? COMBAT.vfx_supervisor.muzzle
          : COMBAT.enemy.muzzle;
  if (!map) return fallback;
  const key = animName === "shoot" ? "attack" : animName;
  return map[key] || map.attack || map.idle || fallback;
}

/** Chest / shoulder aim point from the player's current collision height. */
export function playerTorsoAim(player) {
  if (!player) return { x: 0, y: 0 };
  const bodyH = Math.max(1, Number(player.h) || Number(player.standH) || 170);
  return {
    x: player.footX,
    y: player.footY - bodyH * 0.72,
  };
}

export function enemyWeaponDef(enemyId) {
  const projectileId = ENEMY_WEAPON_ID[enemyId] || ENEMY_WEAPON_ID.post_producer;
  const combat =
    enemyId === "client"
      ? COMBAT.client
      : enemyId === "colorist"
        ? COMBAT.colorist
        : enemyId === "vfx_supervisor"
          ? COMBAT.vfx_supervisor
          : enemyId === "boss_01"
            ? COMBAT.boss_01
            : COMBAT.enemy;
  const names = {
    client: "Revision Pulse",
    boss_01: "Straight Razor",
    colorist: "Grade Blast",
    vfx_supervisor: "VFX Arc",
    post_producer: "Deadline",
  };
  return {
    id: projectileId,
    name: names[enemyId] || "Deadline",
    projectileId,
    ...combat,
    ammo: -1,
    maxAmmo: -1,
    projectile: projectileDef(projectileId),
  };
}
