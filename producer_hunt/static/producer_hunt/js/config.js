/** Internal game resolution. Physics uses these units, not CSS pixels. */

export const DESIGN_W = 1920;
export const DESIGN_H = 1080;

export const GRAVITY = 2600;
export const MAX_FALL = 1600;
export const MOVE_ACCEL = 2800;
export const MOVE_DECEL = 3600;
export const JUMP_SCALE = 1.75;

export const DEBUG_QUERY = "debug";
/** Sprite frame / collision / muzzle overlay. Also enabled via ?debug=1 or F1. */
export const DEBUG_ASSETS = false;

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
