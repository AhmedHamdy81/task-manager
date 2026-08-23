/** Shared sprite-sheet contract. Gameplay reads this; art is drop-in PNG strips. */

export const PORTRAIT_WIDTH = 512;
export const PORTRAIT_HEIGHT = 512;
export const SPRITE_FRAME_WIDTH = 256;
export const SPRITE_FRAME_HEIGHT = 256;

export const PLAYER_ANIMATIONS = {
  idle: { frames: 6, fps: 8, loop: true },
  run: { frames: 8, fps: 14, loop: true },
  jump: { frames: 4, fps: 10, loop: false },
  fall: { frames: 2, fps: 8, loop: true },
  crouch: { frames: 2, fps: 6, loop: false },
  shoot: { frames: 4, fps: 16, loop: false },
  crouch_shoot: { frames: 4, fps: 16, loop: false },
  hit: { frames: 3, fps: 14, loop: false },
  death: { frames: 8, fps: 10, loop: false },
};

export const ENEMY_ANIMATIONS = {
  idle: { frames: 6, fps: 8, loop: true },
  walk: { frames: 8, fps: 10, loop: true },
  attack: { frames: 4, fps: 12, loop: false },
  hit: { frames: 3, fps: 14, loop: false },
  death: { frames: 6, fps: 10, loop: false },
};

export const BOSS_01_ANIMATIONS = {
  idle: { frames: 8, fps: 8, loop: true },
  walk: { frames: 8, fps: 10, loop: true },
  throw: { frames: 6, fps: 12, loop: false },
  melee: { frames: 6, fps: 14, loop: false },
  charge: { frames: 6, fps: 12, loop: true },
  hit: { frames: 4, fps: 14, loop: false },
  phase_transition: { frames: 8, fps: 10, loop: false },
  death: { frames: 6, fps: 8, loop: false },
};

export const RESCUE_ANIMATIONS = {
  idle: { frames: 4, fps: 6, loop: true, file: "rescue_idle" },
  release: { frames: 4, fps: 10, loop: false, file: "rescue_release" },
  celebrate: { frames: 4, fps: 10, loop: false, file: "rescue_celebrate" },
  run: { frames: 6, fps: 12, loop: true, file: "rescue_run" },
};

export const VEHICLE_ANIMATIONS = {
  idle: { frames: 4, fps: 8, loop: true, file: "idle" },
  drive: { frames: 6, fps: 12, loop: true, file: "drive" },
  hop: { frames: 2, fps: 10, loop: false, file: "hop" },
  fire: { frames: 3, fps: 16, loop: false, file: "fire" },
  special: { frames: 4, fps: 12, loop: false, file: "special" },
  hit: { frames: 2, fps: 14, loop: false, file: "hit" },
  destroyed: { frames: 4, fps: 8, loop: false, file: "destroyed" },
};

/** Editor idle opaque height (~229px in a 256 frame) is the in-game visual reference. */
export const PLAYER_VISUAL_PROFILE = {
  targetStandingHeight: 229,
  targetStandingWidth: 112,
  originX: 0.5,
  originY: 1,
};

/**
 * Normalized standing collision. Independent of sprite scale / animation padding.
 * Matches Editor's existing in-game body (not the 256px art frame).
 */
export const PLAYER_BODY = {
  width: 80,
  height: 170,
};

/**
 * One scale per character for every animation.
 * Assistant / Colorist / VFX fill more of the 256 frame than Editor (~248 vs ~229).
 */
export const CHARACTER_RENDER_SCALE = {
  editor: 1,
  assistant: 0.92,
  colorist: 0.92,
  vfx_supervisor: 0.92,
};

export const DEFAULT_BODY = {
  renderWidth: SPRITE_FRAME_WIDTH,
  renderHeight: SPRITE_FRAME_HEIGHT,
  collisionWidth: PLAYER_BODY.width,
  collisionHeight: PLAYER_BODY.height,
  collisionOffsetX: 0,
  collisionOffsetY: 0,
  anchorX: PLAYER_VISUAL_PROFILE.originX,
  anchorY: PLAYER_VISUAL_PROFILE.originY,
  muzzleOffset: { x: 42, y: -104 },
};

export function characterSpriteDir(id) {
  return `characters/${id}`;
}

export function characterSpriteSrc(id, animName) {
  return `${characterSpriteDir(id)}/sprites/${id}_${animName}.png`;
}

export function characterPortraitSrc(id) {
  return `${characterSpriteDir(id)}/portrait.png`;
}

export function enemySpriteSrc(id, animName) {
  return `enemies/${id}/sprites/${id}_${animName}.png`;
}

/** Playable strips reused when a dedicated enemy sheet is missing. */
export function crewEnemySpriteSrc(characterId, animName) {
  const map = { walk: "run", attack: "shoot" };
  const clip = map[animName] || animName;
  return `characters/${characterId}/sprites/${characterId}_${clip}.png`;
}

export function clientSpriteCandidates(animName) {
  return [
    `characters/client/sprites/client_${animName}.png`,
    `enemies/client/sprites/client_${animName}.png`,
  ];
}

/** Legacy Assistant Producer path (inactive). Kept so old references remain resolvable. */
export function enemySpriteSrcLegacy(id, animName) {
  return `enemies/${id}/${id}_${animName}.png`;
}

export function buildAnimMap(srcFn, defaults) {
  const animations = {};
  for (const [name, spec] of Object.entries(defaults)) {
    animations[name] = {
      src: srcFn(name),
      frames: spec.frames,
      fps: spec.fps,
      loop: spec.loop,
    };
  }
  return animations;
}

export function makeCharacterSpriteConfig(id, extras = {}) {
  const renderScale = extras.renderScale ?? CHARACTER_RENDER_SCALE[id] ?? 1;
  const { renderScale: _ignored, ...rest } = extras;
  return {
    id,
    frameWidth: SPRITE_FRAME_WIDTH,
    frameHeight: SPRITE_FRAME_HEIGHT,
    ...DEFAULT_BODY,
    ...rest,
    renderScale,
    renderWidth: Math.round(SPRITE_FRAME_WIDTH * renderScale),
    renderHeight: Math.round(SPRITE_FRAME_HEIGHT * renderScale),
    collisionWidth: PLAYER_BODY.width,
    collisionHeight: PLAYER_BODY.height,
    animations: buildAnimMap((anim) => characterSpriteSrc(id, anim), PLAYER_ANIMATIONS),
    portrait: characterPortraitSrc(id),
  };
}

export function makeEnemySpriteConfig(id, extras = {}) {
  const { animationMap, srcFn, ...rest } = extras;
  const anims = animationMap || ENEMY_ANIMATIONS;
  return {
    id,
    frameWidth: SPRITE_FRAME_WIDTH,
    frameHeight: SPRITE_FRAME_HEIGHT,
    renderWidth: SPRITE_FRAME_WIDTH,
    renderHeight: SPRITE_FRAME_HEIGHT,
    collisionWidth: 88,
    // Visible torso, not the full 256×256 transparent frame. Bottom-center anchored.
    collisionHeight: 210,
    collisionOffsetX: 0,
    collisionOffsetY: 0,
    ...rest,
    animations: buildAnimMap((anim) => (srcFn ? srcFn(anim) : enemySpriteSrc(id, anim)), anims),
  };
}
