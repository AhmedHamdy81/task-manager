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
    cooldown: 1.15,
    lifetime: 2.5,
    speed: 360,
    spawnFrame: 2,
    attackRange: 460,
    muzzle: { x: 40, y: -108 },
    impactFx: { sheetKey: "post_producer_impact", frames: 4, fps: 16, size: 96 },
  },
  client: {
    damage: 12,
    cooldown: 1.5,
    lifetime: 2.4,
    speed: 420,
    spawnFrame: 2,
    attackRange: 520,
    muzzle: { x: 36, y: -96 },
    impactFx: { sheetKey: "client_impact", frames: 4, fps: 16, size: 96 },
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

/** Studio 01 Boss 1. Unit values scale to player HP / shot damage (10). */
export const BOSS_01 = {
  id: "boss_01",
  displayName: "ESSAM SALAMA",
  title: "THE MASTER BARBER",
  maxHealth: 50 * COMBAT.player.damage,
  contactDamage: 2 * COMBAT.player.damage,
  projectileDamage: 1 * COMBAT.player.damage,
  walkSpeed: 80,
  chargeSpeed: 360,
  attackCooldown: 1.8,
  hitInvuln: 0.18,
  phaseTwoHealthRatio: 0.5,
  scoreValue: 3000,
  meleeRange: 128,
  preferredRange: 280,
  rangeBand: 48,
  chargeCooldown: 3.2,
  spawnSec: 0.9,
  throwPrepareSec: 0.22,
  recoverySec: 0.45,
  chargePrepareSec: 0.42,
  phaseTransitionSec: 0.85,
  meleeHitStartFrame: 2,
  meleeHitEndFrame: 4,
  throwReleaseFrame: 3,
  projectileSpeedRazor: 420,
  projectileSpeedScissors: 300,
  projectileSpeedClippers: 220,
  razorGravity: 110,
  contactCooldown: 0.7,
  chargeContactCooldown: 0.55,
  knockback: 240,
  chargeKnockback: 380,
  meleeKnockback: 320,
  phase2: {
    walkSpeedMul: 1.2,
    attackCooldownMul: 0.72,
    chargeSpeedMul: 1.18,
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
  boss_01: "boss_01_razor",
};

export function projectileDef(id) {
  return PROJECTILE_DEFS[id] || PROJECTILE_DEFS.editor_pulse;
}

export function weaponDefForCharacter(characterId) {
  const id = CHARACTER_WEAPON_ID[characterId] || CHARACTER_WEAPON_ID.editor;
  return WEAPON_DEFS[id];
}

export function enemyWeaponDef(enemyId) {
  const projectileId = ENEMY_WEAPON_ID[enemyId] || ENEMY_WEAPON_ID.post_producer;
  const combat =
    enemyId === "client"
      ? COMBAT.client
      : enemyId === "boss_01"
        ? COMBAT.boss_01
        : COMBAT.enemy;
  const names = {
    client: "Revision Pulse",
    boss_01: "Straight Razor",
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
