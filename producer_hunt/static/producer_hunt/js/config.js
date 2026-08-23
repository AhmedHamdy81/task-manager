/** Internal game resolution. Physics uses these units, not CSS pixels. */

export const DESIGN_W = 1920;
export const DESIGN_H = 1080;

export const GRAVITY = 2600;
export const MAX_FALL = 1600;
export const MOVE_ACCEL = 5200;
export const MOVE_DECEL = 9200;
export const MOVE_REVERSE = 16000;
export const AIR_CONTROL = 0.8;
export const JUMP_SPEED = 700;
export const JUMP_SCALE = 1.75;
/** Editor launch speed. Multipliers apply once at jump time; this value is not mutated. */
export const BASE_JUMP_VELOCITY = JUMP_SPEED * JUMP_SCALE;
export const COYOTE_SEC = 0.12;
export const JUMP_BUFFER_SEC = 0.14;
/** Multiply remaining upward velocity when Jump is released. */
export const JUMP_CUT_MUL = 0.45;
export const PLAYER_INVULN_SEC = 0.85;
export const PLAYER_HIT_FLASH_SEC = 0.12;
export const ENEMY_HIT_FLASH_SEC = 0.1;
export const HITSTOP_LIGHT_SEC = 0.045;
export const HITSTOP_HEAVY_SEC = 0.085;
export const SHAKE_LIGHT = 0.1;
export const SHAKE_HEAVY = 0.38;
export const DEBUG_JUMP = false;

export const CAMERA = {
  look: 140,
  lookLerp: 4.2,
  followX: 9.5,
  followY: 6.4,
  focusX: 0.38,
  focusY: 0.7,
  airFocusY: 0.58,
  deadY: 64,
  shakeDecay: 4.4,
};
/** Sprite frame / collision / muzzle overlay. Disabled in production. */
export const DEBUG_QUERY = "debug";
export const DEBUG_ASSETS = false;
export const DEBUG_COMBAT = false;
export const ASSET_CACHE_KEY = "ph-20260821-defeat";
export const DEBUG_REPLAY_BOSS_INTRO = false;
export const BOSS_INTRO_SRC = "videos/boss_01_intro.mp4";
export const BOSS_DEFEAT_SRC = "videos/boss_01_defeat.mp4";

export const DEFAULT_KEYMAP = {
  moveLeft: ["KeyA", "ArrowLeft"],
  moveRight: ["KeyD", "ArrowRight"],
  jump: ["KeyW", "ArrowUp"],
  crouch: ["KeyS", "ArrowDown"],
  shoot: ["Space"],
  special: ["KeyQ"],
  weapon1: ["Digit1"],
  weapon2: ["Digit2"],
  weapon3: ["Digit3"],
  weapon4: ["Digit4"],
  weaponCycle: ["KeyE"],
  pause: ["Escape"],
  confirm: ["Enter"],
  interact: ["KeyF", "Enter"],
  debug: ["F1"],
};
