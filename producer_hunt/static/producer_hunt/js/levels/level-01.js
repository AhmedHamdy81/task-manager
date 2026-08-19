import { PICKUP_FRAMES } from "../asset-catalog.js";

/** BigBang Studios — Level 1 placeholder world. */

export const LEVEL_01 = {
  id: "level_01",
  name: "BIGBANG STUDIOS",
  worldWidth: 10400,
  worldHeight: 1080,
  background: {
    sky: "#141c2c",
    far: "#1b2740",
    studio: "#243044",
  },
  ground: { y: 980, h: 100 },
  playerSpawn: { x: 180, y: 980 },
  levelEnd: { x: 10040, y: 780, w: 70, h: 200 },
  boss: null,
  checkpoints: [{ x: 5200, y: 860, w: 36, h: 120 }],
  pickups: [
    { kind: "ammo", x: 2450, y: 900, w: 32, h: 32, amount: 30 },
    { kind: "health", x: 6100, y: 720, w: 32, h: 32, amount: 30 },
    { kind: "ammo", x: 8200, y: 900, w: 32, h: 32, amount: 30 },
  ],
  props: [
    { frame: 0, x: 360, y: 852, w: 128, h: 128 },
    { frame: 1, x: 1180, y: 852, w: 128, h: 128 },
    { frame: 3, x: 1760, y: 852, w: 128, h: 128 },
    { frame: 7, x: 3220, y: 852, w: 128, h: 128 },
    { frame: 6, x: 4480, y: 852, w: 128, h: 128 },
    { frame: 2, x: 6200, y: 852, w: 128, h: 128 },
    { frame: 4, x: 7480, y: 852, w: 128, h: 128 },
    { frame: 5, x: 9100, y: 852, w: 128, h: 128 },
  ],
  hazards: [
    { frame: 0, x: 2100, y: 852, w: 128, h: 128 },
    { frame: 2, x: 3980, y: 852, w: 128, h: 128 },
    { frame: 4, x: 6800, y: 852, w: 128, h: 128 },
    { frame: 5, x: 8600, y: 852, w: 128, h: 128 },
  ],
  platforms: [
    { x: 0, y: 980, w: 10400, h: 100 },
    { x: 720, y: 820, w: 280, h: 28 },
    { x: 1500, y: 740, w: 240, h: 28 },
    { x: 2680, y: 800, w: 320, h: 28 },
    { x: 3600, y: 700, w: 260, h: 28 },
    { x: 4700, y: 780, w: 300, h: 28 },
    { x: 5900, y: 720, w: 280, h: 28 },
    { x: 7100, y: 800, w: 260, h: 28 },
    { x: 8300, y: 740, w: 300, h: 28 },
    { x: 9300, y: 820, w: 240, h: 28 },
  ],
  zones: [
    { label: "EDITING ROOM", x: 80, y: 160, w: 1400, color: "#1d4ed8" },
    { label: "EDITING CORRIDOR", x: 1600, y: 160, w: 1100, color: "#334155" },
    { label: "VFX", x: 2860, y: 160, w: 1500, color: "#6d28d9" },
    { label: "COLOR", x: 4520, y: 160, w: 1300, color: "#be123c" },
    { label: "STORAGE", x: 5980, y: 160, w: 1500, color: "#92400e" },
    { label: "STUDIO FLOOR", x: 7640, y: 160, w: 1800, color: "#0f766e" },
    { label: "LEVEL END", x: 9600, y: 160, w: 720, color: "#e8b84a" },
  ],
  enemySpawns: [
    { type: "assistant_producer", x: 900, y: 980, patrolMin: 760, patrolMax: 1180 },
    { type: "assistant_producer", x: 1900, y: 980, patrolMin: 1700, patrolMax: 2200 },
    { type: "assistant_producer", x: 2900, y: 800, patrolMin: 2680, patrolMax: 2980 },
    { type: "assistant_producer", x: 3800, y: 980, patrolMin: 3600, patrolMax: 4200 },
    { type: "assistant_producer", x: 5100, y: 780, patrolMin: 4700, patrolMax: 4980 },
    { type: "assistant_producer", x: 6400, y: 980, patrolMin: 6100, patrolMax: 6800 },
    { type: "assistant_producer", x: 7600, y: 980, patrolMin: 7400, patrolMax: 8000 },
    { type: "assistant_producer", x: 8800, y: 740, patrolMin: 8300, patrolMax: 8580 },
    { type: "assistant_producer", x: 9600, y: 980, patrolMin: 9400, patrolMax: 9900 },
  ],
};

export function buildWorld(level) {
  return {
    id: level.id,
    name: level.name,
    width: level.worldWidth,
    height: level.worldHeight,
    background: level.background,
    ground: level.ground ? { ...level.ground } : null,
    spawn: { ...level.playerSpawn },
    end: { ...level.levelEnd },
    checkpoints: (level.checkpoints || []).map((c) => ({ ...c })),
    pickups: (level.pickups || []).map((p) => {
      const vis = 64;
      const hit = 24;
      const cx = p.x + (p.w || vis) / 2;
      const cy = p.y + (p.h || vis) / 2;
      return {
        ...p,
        taken: false,
        vis,
        w: hit,
        h: hit,
        x: cx - hit / 2,
        y: cy - hit / 2,
        frame: p.frame ?? PICKUP_FRAMES[p.kind] ?? PICKUP_FRAMES.reserved_film,
      };
    }),
    props: (level.props || []).map((p) => ({ collidable: false, ...p })),
    hazards: (level.hazards || []).map((h) => ({ collidable: false, ...h })),
    solids: [
      ...(level.platforms || []).map((p) => ({ ...p })),
      ...(level.props || [])
        .filter((p) => p.collidable)
        .map((p) => ({ x: p.x, y: p.y, w: p.w, h: p.h })),
      ...(level.hazards || [])
        .filter((h) => h.collidable)
        .map((h) => ({ x: h.x, y: h.y, w: h.w, h: h.h })),
    ],
    enemySpawns: (level.enemySpawns || []).map((e) => ({ ...e })),
    zones: (level.zones || []).map((z) => ({ ...z })),
    boss: level.boss,
  };
}
