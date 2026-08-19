/** Data-driven Producer Hunt audio registry. Files are optional until supplied. */

export const AUDIO_EXTENSIONS = [".ogg", ".mp3", ".wav"];
export const MUSIC_CROSSFADE_SEC = 0.7;

export const WEAPON_SOUND_ID = {
  editor_pulse: "editor_shoot",
  assistant_scan_bolt: "assistant_shoot",
  vfx_orb: "vfx_supervisor_shoot",
  colorist_chroma_bolt: "colorist_shoot",
  deadline_projectile: "post_producer_attack",
};

function sound(id, path, category, extra = {}) {
  return {
    id,
    path,
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
  menu_theme: sound("menu_theme", "audio/music/menu_theme", "music", {
    volume: 0.65,
    loop: true,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  studio_01_theme: sound("studio_01_theme", "audio/music/studio_01_theme", "music", {
    volume: 0.6,
    loop: true,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  level_complete_music: sound("level_complete_music", "audio/music/level_complete", "music", {
    volume: 0.8,
    loop: false,
    maxInstances: 1,
    cooldown: 0,
    spatial: false,
  }),
  ui_move: sound("ui_move", "audio/sfx/ui_move", "ui", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.04,
    spatial: false,
  }),
  ui_confirm: sound("ui_confirm", "audio/sfx/ui_confirm", "ui", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.05,
    spatial: false,
  }),
  ui_back: sound("ui_back", "audio/sfx/ui_back", "ui", {
    volume: 0.55,
    maxInstances: 1,
    cooldown: 0.05,
    spatial: false,
  }),
  editor_shoot: sound("editor_shoot", "audio/sfx/editor_shoot", "effects", {
    volume: 0.7,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  assistant_shoot: sound("assistant_shoot", "audio/sfx/assistant_shoot", "effects", {
    volume: 0.7,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  vfx_supervisor_shoot: sound("vfx_supervisor_shoot", "audio/sfx/vfx_supervisor_shoot", "effects", {
    volume: 0.7,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  colorist_shoot: sound("colorist_shoot", "audio/sfx/colorist_shoot", "effects", {
    volume: 0.7,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  post_producer_attack: sound("post_producer_attack", "audio/sfx/post_producer_attack", "effects", {
    volume: 0.7,
    maxInstances: 3,
    cooldown: 0.08,
  }),
  player_hit: sound("player_hit", "audio/sfx/player_hit", "effects", {
    volume: 0.65,
    maxInstances: 1,
    cooldown: 0.12,
    spatial: false,
  }),
  enemy_hit: sound("enemy_hit", "audio/sfx/enemy_hit", "effects", {
    volume: 0.65,
    maxInstances: 3,
    cooldown: 0.04,
  }),
  projectile_impact: sound("projectile_impact", "audio/sfx/projectile_impact", "effects", {
    volume: 0.65,
    maxInstances: 4,
    cooldown: 0.03,
  }),
  pickup_collect: sound("pickup_collect", "audio/sfx/pickup_collect", "effects", {
    volume: 0.65,
    maxInstances: 2,
    cooldown: 0.05,
  }),
  checkpoint_activate: sound("checkpoint_activate", "audio/sfx/checkpoint_activate", "effects", {
    volume: 0.75,
    maxInstances: 1,
    cooldown: 0.2,
  }),
  door_open: sound("door_open", "audio/sfx/door_open", "effects", {
    volume: 0.7,
    maxInstances: 1,
    cooldown: 0.15,
  }),
  player_death: sound("player_death", "audio/sfx/player_death", "effects", {
    volume: 0.75,
    maxInstances: 1,
    cooldown: 0.4,
    spatial: false,
  }),
  level_complete: sound("level_complete", "audio/sfx/level_complete", "effects", {
    volume: 0.8,
    maxInstances: 1,
    cooldown: 0.4,
    spatial: false,
  }),
};

export const SOUND_LIST = Object.values(SOUND_DEFS);

export function soundDef(id) {
  return SOUND_DEFS[id] || null;
}
