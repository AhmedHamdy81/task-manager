import { Weapon } from "./weapon.js";
import { makeCharacterSpriteConfig } from "./sprite-spec.js";
import { weaponDefForCharacter } from "./combat.js";

export const DEFAULT_CHARACTER_ID = "editor";

/** Shared gameplay stats — no per-character balancing in this pass. */
export const SHARED_PLAYER = {
  health: 100,
  speed: 320,
  jumpStrength: 700,
};

function makeCharacter({ id, displayName, color, accent, initials, special }) {
  const weapon = weaponDefForCharacter(id);
  return {
    id,
    displayName,
    name: displayName,
    health: SHARED_PLAYER.health,
    speed: SHARED_PLAYER.speed,
    jumpStrength: SHARED_PLAYER.jumpStrength,
    color,
    accent,
    initials,
    spriteRoot: `characters/${id}`,
    portrait: `characters/${id}/portrait.png`,
    weapon,
    specialAbility: special,
    sprite: makeCharacterSpriteConfig(id),
  };
}

export const CHARACTERS = [
  makeCharacter({
    id: "editor",
    displayName: "The Editor",
    color: "#4ade80",
    accent: "#166534",
    initials: "ED",
    special: { id: "cut", name: "CUT!", duration: 2.2, cooldown: 8 },
  }),
  makeCharacter({
    id: "assistant",
    displayName: "The Assistant",
    color: "#38bdf8",
    accent: "#075985",
    initials: "AE",
    special: { id: "turbo_sync", name: "Turbo Sync", duration: 2.4, cooldown: 7 },
  }),
  makeCharacter({
    id: "vfx_supervisor",
    displayName: "The VFX Supervisor",
    color: "#c084fc",
    accent: "#6b21a8",
    initials: "FX",
    special: { id: "final_render", name: "FINAL RENDER", duration: 0.35, cooldown: 9 },
  }),
  makeCharacter({
    id: "colorist",
    displayName: "The Colorist",
    color: "#fb7185",
    accent: "#9f1239",
    initials: "CL",
    special: { id: "grade_shift", name: "GRADE SHIFT", duration: 3, cooldown: 8 },
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
