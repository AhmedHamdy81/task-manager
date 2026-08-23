/** Studio 01 presentation: mix, hit feedback, camera, and quality caps. */

export const MIX = {
  masterVolume: 1,
  musicVolume: 0.65,
  effectsVolume: 0.8,
  voiceVolume: 0.9,
  ambienceVolume: 0.35,
};

export const SHAKE_SMALL = 0.1;
export const SHAKE_MEDIUM = 0.22;
export const SHAKE_LARGE = 0.38;

export const HIT_CLASS = {
  light: { hitstop: 0, shake: 0, impactSize: 40, sfx: "projectile_impact" },
  heavy: { hitstop: 0.045, shake: SHAKE_SMALL, impactSize: 64, sfx: "projectile_impact" },
  special: { hitstop: 0.07, shake: SHAKE_MEDIUM, impactSize: 88, sfx: "projectile_impact" },
};

export const FX_CAPS = { high: 48, medium: 28, low: 16 };

export const SOUND_PRIORITY = {
  high: 3,
  medium: 2,
  low: 1,
};

export const SHAKE_CYCLE = ["full", "reduced", "off"];
export const PARTICLE_CYCLE = ["high", "medium", "low"];

export function cycleValue(list, current, dir = 1) {
  const i = Math.max(0, list.indexOf(current));
  return list[(i + dir + list.length) % list.length];
}

export function normalizeShakeMode(value, reducedMotion = false) {
  if (value === false || value === "off") return "off";
  if (value === "reduced" || reducedMotion) return value === "off" ? "off" : "reduced";
  return "full";
}

export function shakeScale(settings) {
  const mode = normalizeShakeMode(settings?.screenShake, settings?.reducedMotion);
  if (mode === "off") return 0;
  if (mode === "reduced") return 0.32;
  return 1;
}

export function fxCap(settings) {
  const d = settings?.particleDensity;
  return FX_CAPS[d] || FX_CAPS.medium;
}

export function hitClassForShot(shot) {
  const stop = shot?.hitStop;
  if (stop === "heavy") return "special";
  if (stop === "light") return "heavy";
  return "light";
}
