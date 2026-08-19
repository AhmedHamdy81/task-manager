import { Projectile } from "./projectile.js";
import { projectileDef } from "./combat.js";

export class Weapon {
  constructor(spec) {
    this.spec = spec;
    this.id = spec.id;
    this.name = spec.name;
    this.damage = spec.damage;
    this.cooldownSec = spec.cooldown ?? 0.25;
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
    this.cool = 0;
  }

  update(dt) {
    if (this.cool > 0) this.cool -= dt;
  }

  canFire() {
    return this.cool <= 0 && this.ammo !== 0;
  }

  tryFire({ x, y, facing, damageMul = 1, owner = "player" }) {
    if (!this.canFire()) return null;
    this.cool = this.cooldownSec;
    if (this.ammo > 0) this.ammo -= 1;
    const def = projectileDef(this.projectileId);
    const w = def.hitW;
    const h = def.hitH;
    return new Projectile({
      x: x - w / 2,
      y: y - h / 2,
      vx: facing * this.projectileSpeed,
      damage: this.damage * damageMul,
      owner,
      type: def.id,
      frame: def.frame,
      w,
      h,
      vis: def.vis,
      flip: def.flip,
      lifetime: this.lifetime,
      impactFx: this.impactFx,
    });
  }

  isAmmoFull() {
    return this.ammo < 0 || this.ammo >= this.maxAmmo;
  }

  addAmmo(n) {
    if (this.ammo < 0) return 0;
    const before = this.ammo;
    this.ammo = Math.min(this.maxAmmo, this.ammo + n);
    return this.ammo - before;
  }
}
