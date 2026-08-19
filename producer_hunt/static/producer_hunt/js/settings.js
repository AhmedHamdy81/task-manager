/** Lightweight persistence for Producer Hunt menu settings. */

export const SETTINGS_KEY = "producerHunt.settings";

export function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    console.warn("[Producer Hunt] Could not read saved settings. Using defaults.", err);
    return {};
  }
}

export function saveSettings(patch) {
  const next = { ...loadSettings(), ...patch };
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
  } catch (err) {
    console.warn("[Producer Hunt] Could not save settings.", err);
  }
  return next;
}
