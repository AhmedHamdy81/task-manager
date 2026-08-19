export { STUDIO_01, LEVEL_01 } from "./studio-01.js";
export { STUDIO_02 } from "./studio-02.js";
export { buildWorld, validateLevel, LevelDataError, TILE, t } from "./world.js";

import { STUDIO_01 } from "./studio-01.js";
import { STUDIO_02 } from "./studio-02.js";
import { validateLevel } from "./world.js";

export const LEVELS = {
  studio_01: STUDIO_01,
  studio_02: STUDIO_02,
};

export const LEVEL_ORDER = ["studio_01", "studio_02"];

export function resolveLevel(id) {
  return LEVELS[id] || STUDIO_01;
}

export function nextLevelId(currentId) {
  const i = LEVEL_ORDER.indexOf(currentId);
  if (i < 0 || i >= LEVEL_ORDER.length - 1) return null;
  const nid = LEVEL_ORDER[i + 1];
  return LEVELS[nid] ? nid : null;
}

export function levelDataLoads(id) {
  const data = LEVELS[id];
  if (!data) return false;
  try {
    validateLevel(data);
    return true;
  } catch (err) {
    console.error(err);
    return false;
  }
}
