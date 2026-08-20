/** World / UI production sheets. Gameplay entities look up keys; they do not load files. */

export const WORLD_SHEETS = {
  bg_far: {
    src: "environment/studio/backgrounds/studio_background_far.png",
    width: 1920,
    height: 1080,
  },
  bg_mid: {
    src: "environment/studio/backgrounds/studio_background_mid.png",
    width: 1920,
    height: 1080,
  },
  bg_near: {
    src: "environment/studio/backgrounds/studio_background_near.png",
    width: 1920,
    height: 1080,
  },
  tiles: {
    src: "environment/studio/tiles/studio_platform_tiles.png",
    width: 512,
    height: 64,
    frameWidth: 64,
    frameHeight: 64,
    frames: 8,
  },
  props: {
    src: "environment/studio/props/studio_props.png",
    width: 1024,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 8,
  },
  hazards: {
    src: "environment/studio/hazards/studio_hazards.png",
    width: 768,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 6,
  },
  progression: {
    src: "environment/studio/progression/progression_objects.png",
    width: 1536,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 6,
  },
  pickups: {
    src: "pickups/pickups.png",
    width: 512,
    height: 64,
    frameWidth: 64,
    frameHeight: 64,
    frames: 8,
  },
  projectiles: {
    src: "projectiles/projectiles.png",
    width: 1024,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 8,
  },
  boss_01_razor: {
    src: "projectiles/boss_01_razor.png",
    width: 1024,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 4,
  },
  boss_01_scissors: {
    src: "projectiles/boss_01_scissors.png",
    width: 1024,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 4,
  },
  boss_01_clippers: {
    src: "projectiles/boss_01_clippers.png",
    width: 1024,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 4,
  },
  boss_01_brush: {
    src: "projectiles/boss_01_brush.png",
    width: 1024,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 4,
  },
  effects: {
    src: "effects/gameplay_effects.png",
    width: 1024,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 8,
  },
  hud: {
    src: "ui/hud/hud_icons.png",
    width: 512,
    height: 64,
    frameWidth: 64,
    frameHeight: 64,
    frames: 8,
  },
  title_bg: {
    src: "ui/menu/title_background.png",
    width: 1920,
    height: 1080,
  },
  logo: {
    src: "ui/menu/logo.png",
    width: 1200,
    height: 500,
  },
  player_weapons: {
    src: "weapons/player_weapons.png",
    width: 1024,
    height: 256,
    frameWidth: 256,
    frameHeight: 256,
    frames: 4,
  },
  post_producer_impact: {
    src: "enemies/post_producer/effects/post_producer_attack_impact.png",
    width: 512,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 4,
  },
  client_impact: {
    src: "enemies/client/effects/client_attack_impact.png",
    width: 512,
    height: 128,
    frameWidth: 128,
    frameHeight: 128,
    frames: 4,
  },
};

export const PARALLAX = [
  { key: "bg_far", factor: 0.1 },
  { key: "bg_mid", factor: 0.3 },
  { key: "bg_near", factor: 0.55 },
];

export const PICKUP_FRAMES = {
  health: 0,
  energy: 1,
  ammo: 1,
  production_token: 2,
  reserved_film: 2,
  data_card: 3,
  reserved_drive: 3,
  access_key: 4,
  reserved_card: 4,
  ability_charge: 5,
  reserved_crystal: 5,
  headset: 6,
  reserved_shield: 6,
  bonus: 7,
  reserved_score: 7,
};

export const PROJECTILE_FRAMES = {
  editor_pulse: 0,
  assistant_scan_bolt: 1,
  vfx_orb: 2,
  colorist_chroma_bolt: 3,
  deadline_projectile: 4,
  marker: 0,
  proxy: 1,
  render: 2,
  rgb: 3,
  deadline: 4,
  muzzle: 5,
  impact: 6,
  chroma_charged: 7,
};

export const PROGRESSION_FRAMES = {
  door_closed: 0,
  door_open: 1,
  checkpoint: 2,
  checkpoint_active: 3,
  exit_locked: 4,
  exit_open: 5,
};

export const HAZARD_FRAMES = {
  live_cable: 0,
  electrical_panel: 1,
  hot_light: 2,
  falling_cases: 3,
  cable_coil: 4,
  cracked_monitor: 5,
};

export const HUD_FRAMES = {
  health: 0,
  energy: 1,
  ammo: 2,
  player: 3,
  score: 4,
  pause: 5,
  settings: 6,
  objective: 7,
};

export const EFFECT_FRAMES = {
  land: 0,
  dash: 1,
  spawn: 2,
  blast: 3,
  explode: 4,
  hit: 5,
  sparkle: 6,
  pulse: 7,
};

export const TILE = {
  left: 0,
  mid: 1,
  midCables: 2,
  midPanel: 3,
  right: 4,
  block: 5,
  pillar: 6,
  midAlt: 7,
};

export function drawSheetFrame(ctx, sheet, frameIndex, dx, dy, dw, dh, flipX = false) {
  if (!sheet?.image) return false;
  const fw = sheet.frameWidth;
  const fh = sheet.frameHeight;
  const max = sheet.frames || 1;
  const i = Math.max(0, Math.min(max - 1, frameIndex | 0));
  const sx = i * fw;
  ctx.save();
  if (flipX) {
    ctx.translate(dx + dw / 2, dy + dh / 2);
    ctx.scale(-1, 1);
    ctx.drawImage(sheet.image, sx, 0, fw, fh, -dw / 2, -dh / 2, dw, dh);
  } else {
    ctx.drawImage(sheet.image, sx, 0, fw, fh, dx, dy, dw, dh);
  }
  ctx.restore();
  return true;
}

export function drawCoverImage(ctx, img, viewW, viewH) {
  if (!img) return false;
  const scale = Math.max(viewW / img.width, viewH / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  const x = (viewW - dw) / 2;
  const y = (viewH - dh) / 2;
  ctx.drawImage(img, x, y, dw, dh);
  return true;
}

export function drawParallaxLayer(ctx, img, camX, factor, viewW, viewH) {
  if (!img) return false;
  const scale = Math.max(viewW / img.width, viewH / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  const y = (viewH - dh) / 2;
  let shift = (camX * factor) % dw;
  if (shift < 0) shift += dw;
  for (let x = -shift; x < viewW; x += dw) {
    ctx.drawImage(img, 0, 0, img.width, img.height, x, y, dw, dh);
  }
  return true;
}
