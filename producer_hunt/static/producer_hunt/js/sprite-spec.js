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

export const DEFAULT_BODY = {
  renderWidth: SPRITE_FRAME_WIDTH,
  renderHeight: SPRITE_FRAME_HEIGHT,
  collisionWidth: 80,
  collisionHeight: 170,
  collisionOffsetX: 0,
  collisionOffsetY: 0,
  anchorX: 0.5,
  anchorY: 1.0,
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
  return {
    id,
    frameWidth: SPRITE_FRAME_WIDTH,
    frameHeight: SPRITE_FRAME_HEIGHT,
    ...DEFAULT_BODY,
    ...extras,
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
    collisionHeight: 170,
    collisionOffsetX: 0,
    collisionOffsetY: 0,
    ...rest,
    animations: buildAnimMap((anim) => (srcFn ? srcFn(anim) : enemySpriteSrc(id, anim)), anims),
  };
}
