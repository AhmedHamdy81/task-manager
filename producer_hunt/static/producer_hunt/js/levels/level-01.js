export { STUDIO_01, LEVEL_01 } from "./studio-01.js";
export { STUDIO_02 } from "./studio-02.js";
export { buildWorld, validateLevel, LevelDataError, TILE, t } from "./world.js";

import { STUDIO_01 } from "./studio-01.js";
import { STUDIO_02 } from "./studio-02.js";

export const LEVELS = {
  studio_01: STUDIO_01,
  studio_02: STUDIO_02,
};

export function resolveLevel(id) {
  return LEVELS[id] || STUDIO_01;
}
