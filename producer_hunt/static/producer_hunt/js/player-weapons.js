/** Central player weapon registry. Player asks this system to fire; it does not branch per gun in collision. */

import { Weapon, weaponShots } from "./weapon.js";
import { COMBAT, projectileDef, weaponDefForCharacter } from "./combat.js";
import { DEBUG_COMBAT } from "./config.js";

export const PLAYER_WEAPON_IDS = ["pistol", "machine_gun", "shotgun", "heavy_blaster"];
export const EMPTY_SWAP_SEC = 0.55;
export const EMPTY_CLICK_SEC = 0.38;

/**
 * Suggested design values (damage 1–5) are scaled ×5 so Studio 01 / Boss 1
 * stay on the existing 50 HP / 500 HP economy (pistol remains medium ≈ 10).
 * Shotgun pellets stay low so a full cone is not unrestricted boss damage.
 */
export const PLAYER_WEAPON_DEFS = {
  pistol: {
    id: "pistol",
    displayName: "Pistol",
    damage: 10,
    fireInterval: 0.24,
    projectileSpeed: 900,
    ammoType: "unlimited",
    pickupAmmo: 0,
    automatic: false,
    pelletCount: 1,
    spread: 0,
    splashRadius: 0,
    splashDamage: 0,
    projectileAsset: "projectiles",
    pickupAsset: null,
    hudIcon: 0,
    shotSfx: "player_shoot",
    impactSfx: "projectile_impact",
    muzzleFlash: { sheetKey: "projectiles", frame: 5, size: 48, life: 0.09 },
    impactFx: { sheetKey: "projectiles", frame: 6, size: 52, life: 0.16 },
    cameraShake: 0,
    hitStop: "none",
    recoil: 0,
    weaponFrame: 0,
    casing: false,
  },
  machine_gun: {
    id: "machine_gun",
    displayName: "Machine Gun",
    damage: 5,
    fireInterval: 0.085,
    projectileSpeed: 1050,
    ammoType: "limited",
    pickupAmmo: 150,
    automatic: true,
    pelletCount: 1,
    spread: 0.065,
    splashRadius: 0,
    splashDamage: 0,
    projectileId: "machine_gun_round",
    projectileAsset: "projectiles",
    pickupAsset: "pickups",
    hudIcon: 1,
    shotSfx: "machine_gun_shoot",
    impactSfx: "projectile_impact",
    muzzleFlash: { sheetKey: "projectiles", frame: 5, size: 40, life: 0.07 },
    impactFx: { sheetKey: "projectiles", frame: 6, size: 44, life: 0.12 },
    cameraShake: 0,
    hitStop: "none",
    recoil: 18,
    weaponFrame: 1,
    casing: true,
  },
  shotgun: {
    id: "shotgun",
    displayName: "Shotgun",
    damage: 3,
    fireInterval: 0.65,
    projectileSpeed: 800,
    ammoType: "limited",
    pickupAmmo: 24,
    automatic: false,
    pelletCount: 6,
    spread: 0.34,
    splashRadius: 0,
    splashDamage: 0,
    projectileId: "shotgun_pellet",
    projectileAsset: "projectiles",
    pickupAsset: "pickups",
    hudIcon: 0,
    shotSfx: "shotgun_shoot",
    impactSfx: "projectile_impact",
    muzzleFlash: { sheetKey: "projectiles", frame: 5, size: 64, life: 0.12 },
    impactFx: { sheetKey: "effects", frame: 5, size: 56, life: 0.16 },
    cameraShake: 0.12,
    hitStop: "light",
    recoil: 90,
    weaponFrame: 0,
    casing: true,
    bossDamageMul: 0.45,
  },
  heavy_blaster: {
    id: "heavy_blaster",
    displayName: "Heavy Blaster",
    damage: 25,
    fireInterval: 0.8,
    projectileSpeed: 650,
    ammoType: "limited",
    pickupAmmo: 16,
    automatic: false,
    pelletCount: 1,
    spread: 0,
    splashRadius: 75,
    splashDamage: 10,
    projectileId: "heavy_blast",
    projectileAsset: "projectiles",
    pickupAsset: "pickups",
    hudIcon: 2,
    shotSfx: "heavy_blaster_shoot",
    impactSfx: "projectile_impact",
    muzzleFlash: { sheetKey: "projectiles", frame: 7, size: 72, life: 0.14 },
    impactFx: { sheetKey: "effects", frame: 4, size: 88, life: 0.22 },
    cameraShake: 0.24,
    hitStop: "heavy",
    recoil: 210,
    weaponFrame: 2,
    casing: false,
  },
};

const _warned = new Set();

function warnOnce(key, message) {
  if (_warned.has(key)) return;
  _warned.add(key);
  console.warn(`[Producer Hunt] ${message}`);
}

export function playerWeaponDef(id) {
  return PLAYER_WEAPON_DEFS[id] || null;
}

export function characterCombatStats(character) {
  return character?.stats || {
    damageMultiplier: 1,
    fireRateMultiplier: 1,
  };
}

export function specToWeaponConfig(def, character) {
  const stats = characterCombatStats(character);
  const fireMul = Math.max(0.05, Number(stats.fireRateMultiplier) || 1);
  const cosmetic = weaponDefForCharacter(character?.id);
  const projectileId = def.projectileId || cosmetic?.projectileId || "editor_pulse";
  const unlimited = def.ammoType === "unlimited";
  return {
    id: def.id,
    name: def.displayName,
    displayName: def.displayName,
    damage: def.damage,
    cooldown: def.fireInterval / fireMul,
    cooldownSec: def.fireInterval / fireMul,
    speed: def.projectileSpeed,
    projectileSpeed: def.projectileSpeed,
    lifetime: COMBAT.player.lifetime,
    ammo: unlimited ? -1 : def.pickupAmmo,
    maxAmmo: unlimited ? -1 : def.pickupAmmo * 2,
    weaponFrame: def.weaponFrame ?? cosmetic?.weaponFrame ?? 0,
    projectileId,
    spawnFrame: 1,
    muzzle: COMBAT.player.muzzle,
    muzzleFx: def.muzzleFlash,
    impactFx: def.impactFx,
    automatic: Boolean(def.automatic),
    pelletCount: Math.max(1, def.pelletCount || 1),
    spread: Number(def.spread) || 0,
    splashRadius: Number(def.splashRadius) || 0,
    splashDamage: Number(def.splashDamage) || 0,
    bossDamageMul: Number(def.bossDamageMul) || 1,
    shotSfx: def.shotSfx,
    impactSfx: def.impactSfx,
    cameraShake: Number(def.cameraShake) || 0,
    hitStop: def.hitStop || "none",
    recoil: Number(def.recoil) || 0,
    casing: Boolean(def.casing),
    hudIcon: def.hudIcon ?? 0,
    ammoType: def.ammoType,
  };
}

export class WeaponLoadout {
  constructor(character) {
    this.character = character;
    this.owned = new Set(["pistol"]);
    this.ammo = { pistol: -1, machine_gun: 0, shotgun: 0, heavy_blaster: 0 };
    this.maxAmmo = {
      pistol: -1,
      machine_gun: PLAYER_WEAPON_DEFS.machine_gun.pickupAmmo * 2,
      shotgun: PLAYER_WEAPON_DEFS.shotgun.pickupAmmo * 2,
      heavy_blaster: PLAYER_WEAPON_DEFS.heavy_blaster.pickupAmmo * 2,
    };
    this.currentId = "pistol";
    this.weapon = null;
    this._emptyTimer = 0;
    this._emptyClickAt = -99;
    this.rebuildWeapon();
  }

  rebuildWeapon() {
    const def = PLAYER_WEAPON_DEFS[this.currentId] || PLAYER_WEAPON_DEFS.pistol;
    const spec = specToWeaponConfig(def, this.character);
    const prevCool = this.weapon?.cool || 0;
    this.weapon = new Weapon(spec);
    const stored = this.ammo[this.currentId];
    this.weapon.ammo = stored == null ? spec.ammo : stored;
    this.weapon.maxAmmo = this.maxAmmo[this.currentId] ?? spec.maxAmmo;
    this.weapon.cool = prevCool;
    this.syncAmmoFromWeapon();
  }

  syncAmmoFromWeapon() {
    if (!this.weapon) return;
    if (this.weapon.ammo < 0) {
      this.ammo[this.currentId] = -1;
      return;
    }
    this.ammo[this.currentId] = Math.max(0, this.weapon.ammo);
  }

  owns(id) {
    return this.owned.has(id);
  }

  def() {
    return PLAYER_WEAPON_DEFS[this.currentId] || PLAYER_WEAPON_DEFS.pistol;
  }

  equip(id) {
    const next = PLAYER_WEAPON_DEFS[id] ? id : "pistol";
    if (!this.owned.has(next)) return false;
    this.syncAmmoFromWeapon();
    this.currentId = next;
    this._emptyTimer = 0;
    this.rebuildWeapon();
    this.weapon.cool = 0;
    return true;
  }

  selectSlot(slot) {
    const id = PLAYER_WEAPON_IDS[slot - 1];
    if (!id) return false;
    return this.equip(id);
  }

  cycle() {
    const owned = PLAYER_WEAPON_IDS.filter((id) => this.owned.has(id));
    if (owned.length < 2) return false;
    const i = owned.indexOf(this.currentId);
    return this.equip(owned[(i + 1) % owned.length]);
  }

  addAmmo(id, n) {
    const def = PLAYER_WEAPON_DEFS[id];
    if (!def || def.ammoType === "unlimited") return 0;
    const amount = Math.max(0, Math.round(Number(n) || 0));
    if (!amount) return 0;
    this.owned.add(id);
    const cap = this.maxAmmo[id] ?? def.pickupAmmo;
    const before = Math.max(0, this.ammo[id] || 0);
    this.ammo[id] = Math.min(cap, before + amount);
    if (this.currentId === id && this.weapon) {
      this.weapon.ammo = this.ammo[id];
      this.weapon.maxAmmo = cap;
    }
    return this.ammo[id] - before;
  }

  addGenericAmmo(n) {
    if (this.weapon && this.weapon.ammo >= 0) return this.addAmmo(this.currentId, n);
    for (const id of PLAYER_WEAPON_IDS) {
      if (id === "pistol" || !this.owned.has(id)) continue;
      if ((this.ammo[id] || 0) < (this.maxAmmo[id] || 0)) return this.addAmmo(id, n);
    }
    return 0;
  }

  canAcceptAmmo() {
    if (this.weapon && this.weapon.ammo >= 0 && this.weapon.ammo < this.weapon.maxAmmo) return true;
    return PLAYER_WEAPON_IDS.some(
      (id) => id !== "pistol" && this.owned.has(id) && (this.ammo[id] || 0) < (this.maxAmmo[id] || 0)
    );
  }

  collectWeapon(id) {
    const def = PLAYER_WEAPON_DEFS[id];
    if (!def || def.ammoType === "unlimited") return "";
    const wasOwned = this.owned.has(id);
    this.owned.add(id);
    if (wasOwned) this.addAmmo(id, def.pickupAmmo);
    else {
      this.ammo[id] = def.pickupAmmo;
      this.maxAmmo[id] = def.pickupAmmo * 2;
    }
    this.equip(id);
    return wasOwned ? `${def.displayName.toUpperCase()} +AMMO` : def.displayName.toUpperCase();
  }

  snapshot() {
    this.syncAmmoFromWeapon();
    return {
      currentId: this.currentId,
      owned: [...this.owned],
      ammo: { ...this.ammo },
    };
  }

  applySnapshot(snap) {
    if (!snap || typeof snap !== "object") {
      this.owned = new Set(["pistol"]);
      this.ammo = { pistol: -1, machine_gun: 0, shotgun: 0, heavy_blaster: 0 };
      this.equip("pistol");
      return;
    }
    this.owned = new Set(["pistol", ...(snap.owned || [])].filter((id) => PLAYER_WEAPON_DEFS[id]));
    this.ammo = { pistol: -1, machine_gun: 0, shotgun: 0, heavy_blaster: 0, ...(snap.ammo || {}) };
    this.ammo.pistol = -1;
    for (const id of PLAYER_WEAPON_IDS) {
      if (id === "pistol") continue;
      this.ammo[id] = Math.max(0, Number(this.ammo[id]) || 0);
    }
    const next = this.owned.has(snap.currentId) ? snap.currentId : "pistol";
    this.equip(next);
  }

  resetFireState() {
    if (this.weapon) this.weapon.cool = 0;
    this._emptyTimer = 0;
    this._emptyClickAt = -99;
  }

  damageMultiplier(playerDamageMul = 1) {
    const stats = characterCombatStats(this.character);
    return (Number(stats.damageMultiplier) || 1) * (Number(playerDamageMul) || 1);
  }

  tryAttack(ctx) {
    const def = this.def();
    if (!this.weapon) return { shots: [], empty: true };
    if (this.weapon.ammo === 0) return { shots: [], empty: true, weapon: def };
    if (!this.weapon.canFire()) return { shots: [], empty: false };
    const damageMul = this.damageMultiplier(ctx.damageMul);
    const result = this.weapon.tryFire({
      x: ctx.x,
      y: ctx.y,
      facing: ctx.facing,
      damageMul,
      owner: "player",
      faction: "player",
    });
    this.syncAmmoFromWeapon();
    if (this.weapon.ammo < 0) this.weapon.ammo = -1;
    const shots = weaponShots(result).map((shot) => {
      shot.weaponId = def.id;
      shot.faction = "player";
      shot.owner = "player";
      shot.splashRadius = def.splashRadius || 0;
      shot.splashDamage = def.splashDamage ? Math.max(1, Math.round(def.splashDamage * damageMul)) : 0;
      shot.bossDamageMul = def.bossDamageMul || 1;
      shot.hitStop = def.hitStop;
      shot.impactSfx = def.impactSfx;
      shot.cameraShake = def.cameraShake || 0;
      return shot;
    });
    return { shots, empty: false, weapon: def, fired: shots.length > 0 };
  }
}

export function validatePlayerWeapons(character, force = false) {
  if (!force && !DEBUG_COMBAT) return;
  for (const id of PLAYER_WEAPON_IDS) {
    const def = PLAYER_WEAPON_DEFS[id];
    if (!def) {
      warnOnce(`missing:${id}`, `Missing weapon configuration: ${id}`);
      continue;
    }
    if (!(def.damage > 0)) warnOnce(`dmg:${id}`, `Invalid damage for weapon "${id}": ${def.damage}`);
    if (!(def.fireInterval > 0)) warnOnce(`rate:${id}`, `Invalid fire interval for weapon "${id}": ${def.fireInterval}`);
    const projId = def.projectileId || weaponDefForCharacter(character?.id)?.projectileId;
    const proj = projectileDef(projId);
    if (!proj) warnOnce(`proj:${id}`, `Missing projectile texture mapping for weapon "${id}" (${projId})`);
    if (def.ammoType !== "unlimited" && !def.pickupAsset) {
      warnOnce(`pickup:${id}`, `Missing pickup texture for weapon "${id}"`);
    }
    if (def.hudIcon == null) warnOnce(`hud:${id}`, `Missing HUD icon for weapon "${id}"`);
  }
  const muzzle = character?.muzzleByAnim?.shoot || character?.muzzleByAnim?.idle;
  if (!muzzle || !Number.isFinite(muzzle.x) || !Number.isFinite(muzzle.y) || muzzle.y > -40) {
    warnOnce(`muzzle:${character?.id}`, `Invalid muzzle offset for character "${character?.id || "?"}"`);
  }
}

export function warnProjectileFaction(shot) {
  if (!shot || shot.owner === "player" || shot.owner === "enemy") return;
  warnOnce(`faction:${shot.type}`, `Projectile "${shot.type || "unknown"}" has no owner/faction`);
}
