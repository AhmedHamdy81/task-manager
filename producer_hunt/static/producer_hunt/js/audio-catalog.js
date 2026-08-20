/** Data-driven Producer Hunt audio registry. MP3 files are optional until supplied. */

export const AUDIO_BASE = "audio";
export const AUDIO_EXTENSIONS = [".mp3"];
export const MUSIC_CROSSFADE_SEC = 0.7;
export const MUSIC_LOOP_CROSSFADE_SEC = 0.35;

export const DEFAULT_MIX = {
  masterVolume: 1,
  musicVolume: 0.45,
  effectsVolume: 0.75,
};

function sound(id, file, category, extra = {}) {
  return {
    id,
    path: `${AUDIO_BASE}/${file}`,
    category,
    volume: 1,
    loop: false,
    maxInstances: 2,
    cooldown: 0.05,
    spatial: category === "effects",
    ...extra,
  };
}

export const SOUND_DEFS = {
  music_menu: sound("music_menu", "music/menu_theme", "music", {
    volume: 0.4,
    loop: true,
    loopCrossfade: MUSIC_LOOP_CROSSFADE_SEC,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  music_studio_01: sound("music_studio_01", "music/studio_01_theme", "music", {
    volume: 0.42,
    loop: true,
    loopCrossfade: MUSIC_LOOP_CROSSFADE_SEC,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  music_gameplay: sound("music_gameplay", "music/gameplay_music", "music", {
    volume: 0.6,
    loop: true,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  music_boss: sound("music_boss", "music/boss_music", "music", {
    volume: 0.62,
    loop: true,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  music_boss_01: sound("music_boss_01", "music/boss_01_theme", "music", {
    volume: 0.62,
    loop: true,
    loopCrossfade: MUSIC_LOOP_CROSSFADE_SEC,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  music_game_over: sound("music_game_over", "music/game_over_music", "music", {
    volume: 0.7,
    loop: true,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  player_shoot: sound("player_shoot", "sfx/player_shoot", "effects", {
    volume: 0.72,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  player_hit: sound("player_hit", "sfx/player_hit", "effects", {
    volume: 0.65,
    maxInstances: 1,
    cooldown: 0.12,
    spatial: false,
  }),
  player_jump: sound("player_jump", "sfx/player_jump", "effects", {
    volume: 0.6,
    maxInstances: 1,
    cooldown: 0.08,
    spatial: false,
  }),
  player_land: sound("player_land", "sfx/player_land", "effects", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.08,
    spatial: false,
  }),
  player_death: sound("player_death", "sfx/player_death", "effects", {
    volume: 0.75,
    maxInstances: 1,
    cooldown: 0.4,
    spatial: false,
  }),
  enemy_hit: sound("enemy_hit", "sfx/enemy_hit", "effects", {
    volume: 0.65,
    maxInstances: 3,
    cooldown: 0.05,
  }),
  enemy_death: sound("enemy_death", "sfx/enemy_death", "effects", {
    volume: 0.72,
    maxInstances: 2,
    cooldown: 0.06,
  }),
  projectile_impact: sound("projectile_impact", "sfx/projectile_impact", "effects", {
    volume: 0.6,
    maxInstances: 4,
    cooldown: 0.03,
  }),
  pickup_collect: sound("pickup_collect", "sfx/pickup_collect", "effects", {
    volume: 0.65,
    maxInstances: 2,
    cooldown: 0.05,
  }),
  health_pickup: sound("health_pickup", "sfx/health_pickup", "effects", {
    volume: 0.68,
    maxInstances: 2,
    cooldown: 0.08,
  }),
  ammo_pickup: sound("ammo_pickup", "sfx/ammo_pickup", "effects", {
    volume: 0.68,
    maxInstances: 2,
    cooldown: 0.08,
  }),
  powerup_collect: sound("powerup_collect", "sfx/powerup_collect", "effects", {
    volume: 0.7,
    maxInstances: 2,
    cooldown: 0.1,
  }),
  boss_warning: sound("boss_warning", "sfx/boss_warning", "effects", {
    volume: 0.8,
    maxInstances: 1,
    cooldown: 0.5,
    spatial: false,
  }),
  level_complete: sound("level_complete", "sfx/level_complete", "effects", {
    volume: 0.8,
    maxInstances: 1,
    cooldown: 0.4,
    spatial: false,
  }),
  game_over: sound("game_over", "sfx/game_over", "effects", {
    volume: 0.8,
    maxInstances: 1,
    cooldown: 0.5,
    spatial: false,
  }),
  ui_hover: sound("ui_hover", "sfx/ui_hover", "ui", {
    volume: 0.5,
    maxInstances: 1,
    cooldown: 0.04,
    spatial: false,
  }),
  ui_confirm: sound("ui_confirm", "sfx/ui_confirm", "ui", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.05,
    spatial: false,
  }),
  ui_back: sound("ui_back", "sfx/ui_back", "ui", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.05,
    spatial: false,
  }),
  pause: sound("pause", "sfx/pause", "ui", {
    volume: 0.6,
    maxInstances: 1,
    cooldown: 0.12,
    spatial: false,
  }),
};

/** Legacy event ids share the production MP3 so old call sites stay valid. */
export const SOUND_ALIASES = {
  menu_theme: "music_menu",
  studio_01_theme: "music_studio_01",
  boss_01_theme: "music_boss_01",
  ui_move: "ui_hover",
  editor_shoot: "player_shoot",
  assistant_shoot: "player_shoot",
  vfx_supervisor_shoot: "player_shoot",
  colorist_shoot: "player_shoot",
  post_producer_attack: "player_shoot",
  checkpoint_activate: "pickup_collect",
  door_open: "ui_confirm",
};

export const WEAPON_SOUND_ID = {
  editor_pulse: "player_shoot",
  assistant_scan_bolt: "player_shoot",
  vfx_orb: "player_shoot",
  colorist_chroma_bolt: "player_shoot",
};

export const SOUND_LIST = Object.values(SOUND_DEFS);

export const LEVEL_MUSIC = {
  studio_01: "music_studio_01",
};

export const MUSIC_PLAY_OPTS = {
  music_menu: { loop: true, volume: 0.4 },
  music_studio_01: { loop: true, volume: 0.42 },
  music_boss: { loop: true, volume: 0.62 },
  music_boss_01: { loop: true, volume: 0.62 },
};

export function resolveSoundId(id) {
  return SOUND_ALIASES[id] || id;
}

export function soundDef(id) {
  const resolved = resolveSoundId(id);
  return SOUND_DEFS[resolved] || null;
}

export function musicForLevel(levelId, override) {
  if (override) {
    const resolved = resolveSoundId(override);
    if (SOUND_DEFS[resolved]) return resolved;
  }
  return LEVEL_MUSIC[levelId] || "music_gameplay";
}

export function musicPlayOpts(id) {
  const resolved = resolveSoundId(id);
  return { loop: true, ...(MUSIC_PLAY_OPTS[resolved] || {}) };
}

export function pickupSoundId(effect) {
  if (effect === "health") return "health_pickup";
  if (effect === "ammo") return "ammo_pickup";
  if (effect === "ability") return "powerup_collect";
  return "pickup_collect";
}
