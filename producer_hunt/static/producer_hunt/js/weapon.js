import { Projectile } from "./projectile.js";

export class Weapon {
  constructor(spec) {
    this.id = spec.id;
    this.name = spec.name;
    this.damage = spec.damage;
    this.fireRate = spec.fireRate;
    this.projectileSpeed = spec.projectileSpeed;
    this.maxAmmo = spec.maxAmmo ?? spec.ammo ?? 99;
    this.ammo = spec.ammo ?? this.maxAmmo;
    this.spread = spec.spread || 0;
    this.projectileType = spec.projectileType || "shot";
    this.cooldown = 0;
  }

  clone() {
    return new Weapon({
      id: this.id,
      name: this.name,
      damage: this.damage,
      fireRate: this.fireRate,
      projectileSpeed: this.projectileSpeed,
      ammo: this.maxAmmo,
      maxAmmo: this.maxAmmo,
      spread: this.spread,
      projectileType: this.projectileType,
    });
  }

  update(dt) {
    if (this.cooldown > 0) this.cooldown -= dt;
  }

  canFire() {
    return this.cooldown <= 0 && this.ammo !== 0;
  }

  tryFire({ x, y, facing, damageMul = 1, owner = "player" }) {
    if (!this.canFire()) return null;
    this.cooldown = 1 / Math.max(0.1, this.fireRate);
    if (this.ammo > 0) this.ammo -= 1;
    const w = 22;
    const h = 16;
    return new Projectile({
      x: x - w / 2,
      y: y - h / 2,
      vx: facing * this.projectileSpeed,
      damage: this.damage * damageMul,
      owner,
      type: this.projectileType,
    });
  }

  addAmmo(n) {
    if (this.ammo < 0) return;
    this.ammo = Math.min(this.maxAmmo, this.ammo + n);
  }
}
