/** Internal game resolution. Physics uses these units, not CSS pixels. */

export const DESIGN_W = 1920;
export const DESIGN_H = 1080;

export const GRAVITY = 2600;
export const MAX_FALL = 1600;
export const MOVE_ACCEL = 2800;
export const MOVE_DECEL = 3600;
export const JUMP_SCALE = 1.75;

export const CAMERA = {
  look: 140,
  lookLerp: 3.6,
  followX: 8,
  followY: 5.2,
  focusX: 0.38,
  focusY: 0.7,
};
/** Sprite frame / collision / muzzle overlay. Disabled in production. */
export const DEBUG_QUERY = "debug";
export const DEBUG_ASSETS = false;
export const ASSET_CACHE_KEY = "ph-20260820-boss01";
export const DEBUG_REPLAY_BOSS_INTRO = false;
export const BOSS_INTRO_SRC = "videos/boss_01_intro.mp4";

export const DEFAULT_KEYMAP = {
  moveLeft: ["KeyA", "ArrowLeft"],
  moveRight: ["KeyD", "ArrowRight"],
  jump: ["KeyW", "ArrowUp"],
  crouch: ["KeyS", "ArrowDown"],
  shoot: ["Space"],
  special: ["ShiftLeft", "ShiftRight"],
  pause: ["Escape"],
  confirm: ["Enter"],
  debug: ["F1"],
};
