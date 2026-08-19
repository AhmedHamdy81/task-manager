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
  const combat = enemyId === "client" ? COMBAT.client : COMBAT.enemy;
  return {
    id: projectileId,
    name: enemyId === "client" ? "Revision Pulse" : "Deadline",
    projectileId,
    ...combat,
    ammo: -1,
    maxAmmo: -1,
    projectile: projectileDef(projectileId),
  };
}
