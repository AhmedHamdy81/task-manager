/** Lightweight persistence for Producer Hunt only. */

import { MIX } from "./presentation.js";

export const SETTINGS_KEY = "bigbangadmin.producer_hunt";

export const LEGACY_SETTINGS_KEY = "producerHunt.settings";

const ALLOWED_CHARACTER_IDS = new Set(["editor", "assistant", "colorist", "vfx_supervisor"]);
const ALLOWED_LEVEL_IDS = new Set(["studio_01", "studio_02"]);

export const SETTINGS_DEFAULTS = {
  masterVolume: MIX.masterVolume,
  musicVolume: MIX.musicVolume,
  effectsVolume: MIX.effectsVolume,
  voiceVolume: MIX.voiceVolume,
  ambienceVolume: MIX.ambienceVolume,
  muted: false,
  screenShake: "full",
  particleDensity: "medium",
  reducedMotion: false,
  reducedFlashes: false,
  hazardSymbols: true,
  captions: false,
  characterId: "",
  completedLevels: [],
  phase2Complete: false,
  difficulty: "normal",
};

let _saveWarn = false;

function clamp01(value, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(1, n));
}

function warnRejected(reason) {
  if (_saveWarn) return;
  _saveWarn = true;
  console.warn(`[Producer Hunt] Save data was rejected or migrated. ${reason}`);
}

function normalizeShake(src) {
  if (src.screenShake === false || src.screenShake === "off") return "off";
  if (src.screenShake === "reduced") return "reduced";
  return "full";
}

function normalizeDensity(src) {
  if (src.particleDensity === "high" || src.particleDensity === "low") return src.particleDensity;
  return "medium";
}

export function normalizeSettings(raw) {
  const src = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  if (raw != null && (typeof raw !== "object" || Array.isArray(raw))) {
    warnRejected("Payload was not a settings object.");
  }
  let characterId = typeof src.characterId === "string" ? src.characterId : "";
  if (characterId && !ALLOWED_CHARACTER_IDS.has(characterId)) {
    warnRejected("Unknown character identifier.");
    characterId = "";
  }
  const completed = Array.isArray(src.completedLevels)
    ? src.completedLevels.filter((id) => typeof id === "string" && ALLOWED_LEVEL_IDS.has(id))
    : [];
  return {
    masterVolume: clamp01(src.masterVolume, SETTINGS_DEFAULTS.masterVolume),
    musicVolume: clamp01(src.musicVolume, SETTINGS_DEFAULTS.musicVolume),
    effectsVolume: clamp01(src.effectsVolume, SETTINGS_DEFAULTS.effectsVolume),
    voiceVolume: clamp01(src.voiceVolume, SETTINGS_DEFAULTS.voiceVolume),
    ambienceVolume: clamp01(src.ambienceVolume, SETTINGS_DEFAULTS.ambienceVolume),
    muted: src.muted === true,
    screenShake: normalizeShake(src),
    particleDensity: normalizeDensity(src),
    reducedMotion: src.reducedMotion === true,
    reducedFlashes: src.reducedFlashes === true,
    hazardSymbols: src.hazardSymbols !== false,
    captions: src.captions === true,
    characterId,
    completedLevels: completed,
    phase2Complete: src.phase2Complete === true || completed.includes("studio_02"),
    difficulty: src.difficulty === "easy" || src.difficulty === "hard" ? src.difficulty : "normal",
  };
}

function readStoredRaw() {
  try {
    const current = localStorage.getItem(SETTINGS_KEY);
    if (current) return current;
    const legacy = localStorage.getItem(LEGACY_SETTINGS_KEY);
    if (!legacy) return null;
    localStorage.setItem(SETTINGS_KEY, legacy);
    localStorage.removeItem(LEGACY_SETTINGS_KEY);
    warnRejected("Legacy key producerHunt.settings was migrated.");
    return legacy;
  } catch (err) {
    console.warn("[Producer Hunt] Could not read saved settings. Using defaults.", err);
    return null;
  }
}

export function loadSettings() {
  const raw = readStoredRaw();
  if (!raw) return normalizeSettings({});
  try {
    return normalizeSettings(JSON.parse(raw));
  } catch (err) {
    warnRejected("JSON parse failed.");
    return normalizeSettings({});
  }
}

export function saveSettings(patch) {
  const next = normalizeSettings({ ...loadSettings(), ...patch });
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
  } catch (err) {
    console.warn("[Producer Hunt] Could not save settings.", err);
  }
  return next;
}
