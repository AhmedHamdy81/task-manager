import { JUMP_SPEED } from "./config.js";
import { Weapon } from "./weapon.js";
import { makeCharacterSpriteConfig } from "./sprite-spec.js";
import { weaponDefForCharacter } from "./combat.js";
import { specialPowerSpec } from "./abilities.js";

export const DEFAULT_CHARACTER_ID = "editor";

/** Design hearts map onto the existing 10-damage shot economy. Editor 8 hearts = 100 HP. */
export const HEART_HP = 12.5;
export const CHARACTER_HEARTS = {
  editor: 8,
  assistant: 6,
  colorist: 8,
  vfx_supervisor: 11,
};

/** Editor baseline. Per-character values live on CHARACTER_STATS. */
export const SHARED_PLAYER = {
  health: Math.round(CHARACTER_HEARTS.editor * HEART_HP),
  speed: 320,
  jumpStrength: JUMP_SPEED,
  energyMax: 100,
  energyRegen: 8,
};

export const CHARACTER_STATS = {
  editor: {
    maxHealth: Math.round(CHARACTER_HEARTS.editor * HEART_HP),
    damageMultiplier: 1.0,
    moveSpeedMultiplier: 1.0,
    fireRateMultiplier: 1.0,
    defenseMultiplier: 1.0,
    jumpMultiplier: 1.0,
    accelMultiplier: 1.0,
    airControlMultiplier: 1.0,
    energyMax: 100,
    energyRegenMultiplier: 1.0,
  },
  assistant: {
    maxHealth: Math.round(CHARACTER_HEARTS.assistant * HEART_HP),
    damageMultiplier: 0.85,
    moveSpeedMultiplier: 1.18,
    fireRateMultiplier: 1.2,
    defenseMultiplier: 0.85,
    jumpMultiplier: 1.08,
    accelMultiplier: 1.1,
    airControlMultiplier: 1.12,
    energyMax: 110,
    energyRegenMultiplier: 1.2,
  },
  colorist: {
    maxHealth: Math.round(CHARACTER_HEARTS.colorist * HEART_HP),
    damageMultiplier: 1.3,
    moveSpeedMultiplier: 0.92,
    fireRateMultiplier: 0.88,
    defenseMultiplier: 0.95,
    jumpMultiplier: 1.0,
    accelMultiplier: 1.0,
    airControlMultiplier: 1.0,
    energyMax: 125,
    energyRegenMultiplier: 1.1,
  },
  vfx_supervisor: {
    maxHealth: Math.round(CHARACTER_HEARTS.vfx_supervisor * HEART_HP),
    damageMultiplier: 1.05,
    moveSpeedMultiplier: 0.82,
    fireRateMultiplier: 0.9,
    defenseMultiplier: 1.25,
    jumpMultiplier: 1.0,
    accelMultiplier: 0.82,
    airControlMultiplier: 0.88,
    energyMax: 90,
    energyRegenMultiplier: 0.9,
  },
};

function applyStatsToWeapon(weapon, stats) {
  const cooldown = Number(weapon.cooldown) || 0.25;
  const damage = Number(weapon.damage) || 10;
  return {
    ...weapon,
    damage: Math.max(1, Math.round(damage * stats.damageMultiplier)),
    cooldown: cooldown / Math.max(0.05, stats.fireRateMultiplier),
  };
}

/**
 * Shoot sheets already contain each character's weapon. Overlay is opt-in.
 * Muzzle offsets are unscaled, right-facing, relative to bottom-center (anchor 0.5, 1.0).
 * fireFrameByAnim uses the SpriteAnimator 0-based frame index (art "frame 2" => 1).
 */
function makeCharacter({
  id,
  displayName,
  role,
  color,
  accent,
  initials,
  specialPowerId,
  renderWeaponOverlay = false,
  muzzleByAnim = null,
  fireFrameByAnim = null,
}) {
  const stats = CHARACTER_STATS[id] || CHARACTER_STATS.editor;
  const weapon = applyStatsToWeapon(weaponDefForCharacter(id), stats);
  const special = specialPowerSpec(specialPowerId);
  return {
    id,
    displayName,
    name: displayName,
    role: role || "Crew",
    stats,
    health: stats.maxHealth,
    speed: Math.round(SHARED_PLAYER.speed * stats.moveSpeedMultiplier),
    jumpStrength: SHARED_PLAYER.jumpStrength,
    jumpMultiplier: stats.jumpMultiplier,
    energyMax: stats.energyMax,
    color,
    accent,
    initials,
    spriteRoot: `characters/${id}`,
    portrait: `characters/${id}/portrait.png`,
    previewAnimation: "idle",
    weapon,
    specialPowerId: special.id,
    specialAbility: special,
    sprite: makeCharacterSpriteConfig(id),
    renderWeaponOverlay: Boolean(renderWeaponOverlay),
    anchorX: 0.5,
    anchorY: 1.0,
    muzzleByAnim: muzzleByAnim || {
      shoot: { x: 42, y: -104 },
      crouch_shoot: { x: 48, y: -63 },
    },
    fireFrameByAnim: fireFrameByAnim || { shoot: 1, crouch_shoot: 1 },
  };
}

function muzzleSet(shoot, crouchShoot) {
  return {
    idle: { x: shoot.x - 18, y: shoot.y + 8 },
    run: { x: shoot.x - 14, y: shoot.y + 6 },
    jump: { x: shoot.x - 14, y: shoot.y + 8 },
    fall: { x: shoot.x - 14, y: shoot.y + 10 },
    shoot,
    crouch: { x: crouchShoot.x - 10, y: crouchShoot.y + 4 },
    crouch_shoot: crouchShoot,
    crouchShoot,
  };
}

export const CHARACTERS = [
  makeCharacter({
    id: "editor",
    displayName: "The Editor",
    role: "Balanced Fighter",
    color: "#4ade80",
    accent: "#166534",
    initials: "ED",
    specialPowerId: "timeline_freeze",
    renderWeaponOverlay: false,
    muzzleByAnim: muzzleSet({ x: 71, y: -186 }, { x: 89, y: -130 }),
    fireFrameByAnim: { shoot: 1, crouch_shoot: 1 },
  }),
  makeCharacter({
    id: "assistant",
    displayName: "The Assistant",
    role: "Mobile Support",
    color: "#38bdf8",
    accent: "#075985",
    initials: "AE",
    specialPowerId: "production_rush",
    renderWeaponOverlay: false,
    muzzleByAnim: muzzleSet({ x: 52, y: -184 }, { x: 66, y: -128 }),
    fireFrameByAnim: { shoot: 1, crouch_shoot: 1 },
  }),
  makeCharacter({
    id: "vfx_supervisor",
    displayName: "The VFX Supervisor",
    role: "Durable Specialist",
    color: "#c084fc",
    accent: "#6b21a8",
    initials: "FX",
    specialPowerId: "particle_storm",
    renderWeaponOverlay: false,
    muzzleByAnim: muzzleSet({ x: 62, y: -176 }, { x: 99, y: -141 }),
    fireFrameByAnim: { shoot: 1, crouch_shoot: 1 },
  }),
  makeCharacter({
    id: "colorist",
    displayName: "The Colorist",
    role: "Damage Specialist",
    color: "#fb7185",
    accent: "#9f1239",
    initials: "CL",
    specialPowerId: "color_blast",
    renderWeaponOverlay: false,
    muzzleByAnim: muzzleSet({ x: 58, y: -196 }, { x: 77, y: -133 }),
    fireFrameByAnim: { shoot: 1, crouch_shoot: 1 },
  }),
];

let _unknownCharacterWarned = false;

export function isPlayableCharacterId(id) {
  return CHARACTERS.some((c) => c.id === id);
}

export function characterById(id) {
  const found = CHARACTERS.find((c) => c.id === id);
  if (found) return found;
  if (id && !_unknownCharacterWarned) {
    console.warn(`[Producer Hunt] Unknown character "${id}". Falling back to "${DEFAULT_CHARACTER_ID}".`);
    _unknownCharacterWarned = true;
  }
  return CHARACTERS.find((c) => c.id === DEFAULT_CHARACTER_ID) || CHARACTERS[0];
}

export function makeWeapon(character) {
  return new Weapon(character.weapon);
}

function clampRating(n) {
  const v = Math.round(Number(n));
  if (!Number.isFinite(v)) return 3;
  return Math.max(1, Math.min(5, v));
}

export function rateStat(value, lo, hi) {
  const n = Number(value);
  if (!Number.isFinite(n) || hi <= lo) return 3;
  const t = (n - lo) / (hi - lo);
  return clampRating(1 + t * 4);
}

function healthRating(h) {
  if (h >= 130) return 5;
  if (h >= 110) return 4;
  if (h >= 90) return 3;
  if (h >= 70) return 2;
  return 1;
}

function mulRating(m) {
  if (m >= 1.22) return 5;
  if (m >= 1.08) return 4;
  if (m >= 0.97) return 3;
  if (m >= 0.93) return 3;
  if (m >= 0.84) return 2;
  return 1;
}

function specialRating(energyMax) {
  if (energyMax >= 120) return 5;
  if (energyMax >= 100) return 4;
  if (energyMax >= 85) return 3;
  return 2;
}

export function weaponSelectCopy(weapon) {
  const dmg = Number(weapon?.damage);
  const cd = Number(weapon?.cooldown);
  const spd = Number(weapon?.speed);
  const life = Number(weapon?.lifetime);
  const reach = (Number.isFinite(spd) ? spd : 0) * (Number.isFinite(life) ? life : 0);
  const damageText = !Number.isFinite(dmg) ? "Unknown damage" : dmg <= 8 ? "Low damage" : dmg <= 12 ? "Medium damage" : "High damage";
  const rangeText = reach <= 900 ? "Short range" : reach <= 1500 ? "Medium range" : "Long range";
  const fireText = !Number.isFinite(cd) ? "Unknown fire rate" : cd <= 0.22 ? "Rapid fire rate" : cd <= 0.35 ? "Steady fire rate" : "Slow fire rate";
  const category = weapon?.name?.includes("Orb") || weapon?.name?.includes("Emitter")
    ? "Orb"
    : weapon?.name?.includes("Pulse")
      ? "Pulse"
      : weapon?.name?.includes("Bolt") || weapon?.name?.includes("Blaster")
        ? "Blaster"
        : weapon?.name?.includes("Pistol")
          ? "Pistol"
          : "Production weapon";
  return {
    id: weapon?.id || "",
    name: weapon?.name || "Unknown weapon",
    category,
    image: weapon?.id ? `weapons/${weapon.id}.png` : "",
    frame: weapon?.weaponFrame ?? 0,
    description: "Reliable production weapon.",
    damageText,
    rangeText,
    fireText,
  };
}

export function characterSelectStats(character) {
  const stats = character?.stats || CHARACTER_STATS[character?.id] || CHARACTER_STATS.editor;
  return {
    health: healthRating(stats.maxHealth),
    damage: mulRating(stats.damageMultiplier),
    speed: mulRating(stats.moveSpeedMultiplier),
    fireRate: mulRating(stats.fireRateMultiplier),
    defense: mulRating(stats.defenseMultiplier),
    special: specialRating(stats.energyMax),
  };
}
