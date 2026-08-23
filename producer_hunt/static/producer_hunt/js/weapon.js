import { Projectile } from "./projectile.js";
import { projectileDef } from "./combat.js";

export function weaponShots(result) {
  if (!result) return [];
  return Array.isArray(result) ? result.filter(Boolean) : [result];
}

export class Weapon {
  constructor(spec) {
    this.spec = spec;
    this.id = spec.id;
    this.name = spec.name;
    this.damage = spec.damage;
    this.cooldownSec = spec.cooldown ?? spec.cooldownSec ?? 0.25;
    this.projectileSpeed = spec.speed ?? spec.projectileSpeed ?? 650;
    this.lifetime = spec.lifetime ?? 2;
    this.maxAmmo = spec.ammo ?? spec.maxAmmo ?? 120;
    this.ammo = this.maxAmmo;
    this.weaponFrame = spec.weaponFrame ?? 0;
    this.projectileId = spec.projectileId;
    this.spawnFrame = spec.spawnFrame ?? 1;
    this.muzzle = spec.muzzle;
    this.muzzleFx = spec.muzzleFx;
    this.impactFx = spec.impactFx;
    this.automatic = Boolean(spec.automatic);
    this.pelletCount = Math.max(1, spec.pelletCount || 1);
    this.spread = Number(spec.spread) || 0;
    this.splashRadius = Number(spec.splashRadius) || 0;
    this.splashDamage = Number(spec.splashDamage) || 0;
    this.cool = 0;
  }

  update(dt) {
    if (this.cool > 0) this.cool -= dt;
  }

  canFire() {
    return this.cool <= 0 && this.ammo !== 0;
  }

  _shotVelocity(facing, vx, vy, index, count) {
    const speed = this.projectileSpeed;
    if (vx != null) return { vx, vy: vy || 0 };
    const spread = this.spread || 0;
    let angle = 0;
    if (count > 1 && spread) {
      const half = spread / 2;
      angle = count === 1 ? 0 : -half + (spread * index) / (count - 1);
    } else if (spread) {
      angle = (Math.random() * 2 - 1) * spread;
    }
    const dir = facing || 1;
    return {
      vx: Math.cos(angle) * speed * dir,
      vy: Math.sin(angle) * speed,
    };
  }

  _buildShot({ x, y, facing, damageMul, owner, faction, vx, vy, projectile, index, count }) {
    const def = projectileDef(this.projectileId);
    const w = def.hitW;
    const h = def.hitH;
    const vel = this._shotVelocity(facing, vx, vy, index, count);
    const opts = {
      x: x - w / 2,
      y: y - h / 2,
      vx: vel.vx,
      vy: vel.vy,
      damage: this.damage * damageMul,
      owner,
      faction: faction || owner,
      type: def.id,
      frame: def.frame,
      w,
      h,
      vis: def.vis,
      flip: def.flip,
      lifetime: this.lifetime,
      impactFx: this.impactFx,
    };
    if (projectile && typeof projectile.reset === "function" && index === 0) return projectile.reset(opts);
    return new Projectile(opts);
  }

  tryFire({ x, y, facing, damageMul = 1, owner = "player", faction = "", vx = null, vy = 0, projectile }) {
    if (!this.canFire()) return null;
    this.cool = this.cooldownSec;
    if (this.ammo > 0) this.ammo = Math.max(0, this.ammo - 1);
    const count = Math.max(1, this.pelletCount || 1);
    const shots = [];
    for (let i = 0; i < count; i += 1) {
      shots.push(
        this._buildShot({
          x,
          y,
          facing,
          damageMul,
          owner,
          faction,
          vx,
          vy,
          projectile: i === 0 ? projectile : null,
          index: i,
          count,
        })
      );
    }
    return count === 1 ? shots[0] : shots;
  }

  isAmmoFull() {
    return this.ammo < 0 || this.ammo >= this.maxAmmo;
  }

  addAmmo(n) {
    if (this.ammo < 0) return 0;
    const before = Math.max(0, this.ammo);
    const amount = Math.max(0, Number(n) || 0);
    this.ammo = Math.min(this.maxAmmo, before + amount);
    return this.ammo - before;
  }
}
