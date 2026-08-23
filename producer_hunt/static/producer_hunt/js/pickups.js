/** Data-driven pickups. Gameplay looks up ids; HUD does not store copies of these values. */

export const PICKUP_VIS = 64;
export const PICKUP_HIT = 36;

export const PICKUP_VALUES = {
  health: 25,
  energy: 25,
  production_token: 100,
  access_key: 1,
  bonus: 250,
  vehicle_repair: 40,
};

export const PICKUP_COLLECT_FX = {
  sheetKey: "effects",
  frame: 6,
  size: 72,
  life: 0.28,
};

/**
 * persistence: "persist" stays collected across checkpoint restore.
 * respawn: true restores the pickup even if it was taken at snapshot time.
 */
export const PICKUP_DEFS = {
  health: {
    id: "health",
    sprite_frame: 0,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "health",
    value: PICKUP_VALUES.health,
    persistence: "persist",
    respawn: false,
  },
  energy: {
    id: "energy",
    sprite_frame: 1,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "energy",
    value: PICKUP_VALUES.energy,
    persistence: "persist",
    respawn: false,
  },
  production_token: {
    id: "production_token",
    sprite_frame: 2,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "score",
    value: PICKUP_VALUES.production_token,
    persistence: "persist",
    respawn: false,
  },
  data_card: {
    id: "data_card",
    sprite_frame: 3,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "none",
    value: 0,
    persistence: "persist",
    respawn: false,
    reserved: true,
  },
  access_key: {
    id: "access_key",
    sprite_frame: 4,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "key",
    value: PICKUP_VALUES.access_key,
    persistence: "persist",
    respawn: false,
  },
  ability_charge: {
    id: "ability_charge",
    sprite_frame: 5,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "ability",
    value: 1,
    persistence: "persist",
    respawn: false,
  },
  headset: {
    id: "headset",
    sprite_frame: 6,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "none",
    value: 0,
    persistence: "persist",
    respawn: false,
    reserved: true,
  },
  bonus: {
    id: "bonus",
    sprite_frame: 7,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "score",
    value: PICKUP_VALUES.bonus,
    persistence: "persist",
    respawn: false,
  },
  vehicle_repair: {
    id: "vehicle_repair",
    sprite_frame: 0,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "vehicle_repair",
    value: PICKUP_VALUES.vehicle_repair,
    persistence: "persist",
    respawn: false,
    label: "DOLLY REPAIR",
  },
  ammo: {
    id: "ammo",
    sprite_frame: 1,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "ammo",
    value: 40,
    persistence: "persist",
    respawn: false,
    label: "AMMO",
  },
  machine_gun: {
    id: "machine_gun",
    sprite_frame: 3,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "weapon",
    weaponId: "machine_gun",
    value: 0,
    persistence: "persist",
    respawn: false,
    label: "MACHINE GUN",
  },
  shotgun: {
    id: "shotgun",
    sprite_frame: 6,
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "weapon",
    weaponId: "shotgun",
    value: 0,
    persistence: "persist",
    respawn: false,
    label: "SHOTGUN",
  },
  heavy_blaster: {
    id: "heavy_blaster",
    sprite_frame: 2,
    sheetKey: "player_weapons",
    collision_width: PICKUP_HIT,
    collision_height: PICKUP_HIT,
    effect: "weapon",
    weaponId: "heavy_blaster",
    value: 0,
    persistence: "persist",
    respawn: false,
    label: "HEAVY BLASTER",
  },
};

const KIND_ALIAS = {
  token: "production_token",
  key: "access_key",
  crystal: "ability_charge",
  weapon_machine_gun: "machine_gun",
  weapon_shotgun: "shotgun",
  weapon_heavy_blaster: "heavy_blaster",
};

export function pickupDef(kind) {
  const id = KIND_ALIAS[kind] || kind;
  return PICKUP_DEFS[id] || null;
}

export function instantiatePickup(raw, index, levelId) {
  const def = pickupDef(raw.kind) || PICKUP_DEFS.health;
  const vis = PICKUP_VIS;
  const hitW = def.collision_width;
  const hitH = def.collision_height;
  return {
    id: raw.id || `${levelId || "lvl"}_${def.id}_${index}`,
    kind: def.id,
    frame: def.sprite_frame,
    vis,
    w: hitW,
    h: hitH,
    x: raw.x + vis / 2 - hitW / 2,
    y: raw.y + vis / 2 - hitH / 2,
    taken: false,
    reserved: Boolean(def.reserved),
    persistence: def.persistence,
    respawn: Boolean(def.respawn),
    value: def.value,
    effect: def.effect,
    weaponId: def.weaponId || raw.weaponId || "",
    label: def.label || raw.label || "",
    sheetKey: def.sheetKey || raw.sheetKey || "pickups",
  };
}

export function canCollectPickup(pickup, player) {
  if (!pickup || pickup.taken || pickup.reserved) return false;
  if (!player?.alive) return false;
  if (pickup.effect === "none") return false;
  if (pickup.effect === "health") return player.health < player.maxHealth;
  if (pickup.effect === "ammo") {
    return Boolean(player.loadout?.canAcceptAmmo?.());
  }
  if (pickup.effect === "weapon") {
    return Boolean(player.loadout && pickup.weaponId);
  }
  if (pickup.effect === "energy") {
    const needsEnergy = (player.energy || 0) < (player.energyMax || 0);
    const needsAmmo = Boolean(player.loadout?.canAcceptAmmo?.());
    return needsEnergy || needsAmmo;
  }
  if (pickup.effect === "ability") return Boolean(player.ability) && !player.ability.ready;
  if (pickup.effect === "vehicle_repair") return false;
  return true;
}

export function applyPickup(pickup, player, game) {
  if (!canCollectPickup(pickup, player)) return false;
  pickup.taken = true;
  const v = pickup.value;
  if (pickup.effect === "health") player.heal(v);
  else if (pickup.effect === "ammo") {
    const gained = player.loadout?.addGenericAmmo?.(v) || 0;
    if (gained > 0) player.setNotice?.("AMMO", 1.2);
  }
  else if (pickup.effect === "weapon") {
    const msg = player.loadout?.collectWeapon?.(pickup.weaponId) || pickup.label || "WEAPON";
    player._syncWeaponRef?.();
    player.setNotice?.(msg, 1.6);
  }
  else if (pickup.effect === "energy") {
    player.addEnergy?.(v);
    player.loadout?.addGenericAmmo?.(v);
  }
  else if (pickup.effect === "score") {
    game.scoreboard?.award(`pickup:${pickup.id}`, v, { source: "pickup", bucket: "bonus" });
    game.scoreboard?.sync(game);
  }
  else if (pickup.effect === "key") player.keys += v;
  else if (pickup.effect === "ability") player.ability.cool = 0;
  return true;
}
