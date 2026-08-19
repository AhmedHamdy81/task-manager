import { t } from "./world.js";

const G = t(15);
const W = t(72);

/** Client Review — Phase 2 studio with The Client and mixed encounters. */
export const STUDIO_02 = {
  id: "studio_02",
  name: "Client Review",
  worldWidth: W,
  worldHeight: 1080,
  background: {
    sky: "#141c2c",
    far: "#1b2740",
    studio: "#243044",
  },
  ground: { y: G, h: 120 },
  playerSpawn: { x: t(4), y: G },
  checkpoints: [
    { id: "studio_02_start", x: t(4), y: G, spawnX: t(4), spawnY: G, isStart: true, activated: true },
    { id: "studio_02_mid", x: t(32), y: G, spawnX: t(30), spawnY: G },
  ],
  doors: [
    {
      id: "studio_02_exit",
      kind: "exit",
      x: t(66),
      y: G - 256,
      requireEncounters: ["enc_mixed"],
      persistent: true,
    },
  ],
  objectives: [
    { id: "enter", type: "enter", label: "Enter client review" },
    { id: "checkpoint", type: "checkpoint", checkpointId: "studio_02_mid", label: "Reach the notes desk" },
    { id: "clients", type: "encounter", encounterId: "enc_clients", label: "Clear the first notes" },
    { id: "mixed", type: "encounter", encounterId: "enc_mixed", label: "Survive the mixed review" },
    { id: "exit", type: "exit", label: "Leave the suite" },
  ],
  exitRequires: {
    encountersCleared: ["enc_mixed"],
    doorsOpen: ["studio_02_exit"],
  },
  hints: [{ x: t(6), y: G - 150, text: "THE CLIENT KEEPS RANGE" }],
  platforms: [
    { x: 0, y: 0, w: t(1), h: G },
    { x: W - t(1), y: 0, w: t(1), h: G },
    { x: 0, y: G, w: W, h: 120 },
    { x: t(18), y: G - t(4), w: t(5), h: 32 },
    { x: t(42), y: G - t(4), w: t(5), h: 32 },
  ],
  hazards: [{ id: "studio_02_cable", kind: "live_cable", x: t(40), y: G - 128 }],
  pickups: [
    { id: "studio_02_health", kind: "health", x: t(20), y: G - t(4) - 64 },
    { id: "studio_02_energy", kind: "energy", x: t(44), y: G - t(4) - 64 },
  ],
  props: [
    { frame: 0, x: t(2), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 5, x: t(60), y: G - 128, w: 128, h: 128, layer: "front" },
  ],
  enemySpawns: [
    { id: "cl_a", type: "client", x: t(22), y: G, patrolMin: t(16), patrolMax: t(28), activateRange: 640 },
    { id: "cl_b", type: "client", x: t(28), y: G, patrolMin: t(22), patrolMax: t(34), activateRange: 640 },
    { id: "cl_mix", type: "client", x: t(52), y: G, patrolMin: t(46), patrolMax: t(58), activateRange: 560 },
    { id: "pp_mix", type: "post_producer", x: t(58), y: G, patrolMin: t(54), patrolMax: t(62), activateRange: 560 },
  ],
  encounters: [
    { id: "enc_clients", activateX: t(14), enemyIds: ["cl_a", "cl_b"] },
    { id: "enc_mixed", activateX: t(44), enemyIds: ["cl_mix", "pp_mix"] },
  ],
};
