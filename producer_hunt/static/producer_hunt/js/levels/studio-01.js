import { t } from "./world.js";

const G = t(15);
const W = t(118);

/** The Post Suite — first complete playable studio level. */
export const STUDIO_01 = {
  id: "studio_01",
  name: "The Post Suite",
  music: "studio_01_theme",
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
    { id: "studio_01_start", x: t(4), y: G, spawnX: t(4), spawnY: G, isStart: true, activated: true },
    { id: "studio_01_mid", x: t(62), y: G, spawnX: t(60), spawnY: G },
  ],
  doors: [
    {
      id: "studio_01_gate",
      kind: "studio",
      x: t(94),
      y: G - 256,
      requireKeys: 1,
      persistent: true,
    },
    {
      id: "studio_01_exit",
      kind: "exit",
      x: t(112),
      y: G - 256,
      requireKeys: 1,
      requireDoors: ["studio_01_gate"],
      requireEncounters: ["enc_final"],
      persistent: true,
    },
  ],
  objectives: [
    { id: "enter", type: "enter", label: "Enter the post suite" },
    { id: "checkpoint", type: "checkpoint", checkpointId: "studio_01_mid", label: "Reach the checkpoint" },
    { id: "key", type: "keys", count: 1, label: "Collect the access key" },
    { id: "door", type: "door", doorId: "studio_01_gate", label: "Unlock the studio door" },
    { id: "final", type: "encounter", encounterId: "enc_final", label: "Clear the wrap stage" },
    { id: "exit", type: "exit", label: "Activate the exit" },
  ],
  exitRequires: {
    keys: 1,
    doorsOpen: ["studio_01_gate", "studio_01_exit"],
    encountersCleared: ["enc_final"],
  },
  encounters: [
    { id: "enc_client_test", activateX: t(11), enemyIds: ["studio_01_client_test_01"] },
    { id: "enc_intro", activateX: t(44), enemyIds: ["pp_intro"] },
    { id: "enc_mid", activateX: t(66), enemyIds: ["pp_mid_a", "pp_mid_b"] },
    { id: "enc_final", activateX: t(98), enemyIds: ["pp_final_a", "pp_final_b"] },
  ],
  hints: [
    { x: t(3.2), y: G - 150, text: "MOVE  A / D" },
    { x: t(3.2), y: G - 178, text: "JUMP  W" },
    { x: t(8), y: G - 150, text: "CROUCH  S" },
    { x: t(8), y: G - 178, text: "SHOOT  SPACE" },
  ],
  platforms: [
    { x: 0, y: 0, w: t(1), h: G },
    { x: W - t(1), y: 0, w: t(1), h: G },
    { x: 0, y: G, w: W, h: 120 },
    { x: t(14), y: G - t(4), w: t(4), h: 32 },
    { x: t(20), y: G - t(4), w: t(4), h: 32 },
    { x: t(32), y: G - t(4), w: t(5), h: 32 },
    { x: t(39), y: G - t(4), w: t(4), h: 32 },
    { x: t(68), y: G - t(4), w: t(4), h: 32 },
    { x: t(74), y: G - t(4), w: t(4), h: 32 },
    { x: t(76), y: G - t(4), w: t(6), h: 32 },
    { x: t(84), y: G - t(4), w: t(5), h: 32 },
  ],
  hazards: [
    { id: "studio_01_cable_intro", kind: "live_cable", x: t(78), y: G - 128 },
    { id: "studio_01_light", kind: "hot_light", x: t(82), y: G - 128 },
    { id: "studio_01_cases", kind: "falling_cases", x: t(87), y: G - 128 },
  ],
  pickups: [
    { id: "studio_01_token_intro", kind: "production_token", x: t(28), y: G - 64 },
    { id: "studio_01_token_opt", kind: "production_token", x: t(40), y: G - t(4) - 64 },
    { id: "studio_01_energy_post", kind: "energy", x: t(54), y: G - 64 },
    { id: "studio_01_health_post", kind: "health", x: t(80), y: G - 64 },
    { id: "studio_01_key", kind: "access_key", x: t(86), y: G - t(4) - 64 },
    { id: "studio_01_energy_final", kind: "energy", x: t(100), y: G - 64 },
    { id: "studio_01_bonus", kind: "bonus", x: t(108), y: G - 64 },
  ],
  props: [
    { frame: 0, x: t(2), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 1, x: t(10), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 3, x: t(24), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 7, x: t(36), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 6, x: t(58), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 2, x: t(76), y: G - 128, w: 128, h: 128, layer: "back" },
    { frame: 5, x: t(102), y: G - 128, w: 128, h: 128, layer: "front" },
    { frame: 4, x: t(106), y: G - 128, w: 128, h: 128, layer: "front" },
  ],
  enemySpawns: [
    {
      id: "studio_01_client_test_01",
      type: "client",
      x: t(13),
      y: G,
      patrolMin: t(11),
      patrolMax: t(16),
      activateRange: 640,
    },
    { id: "pp_intro", type: "post_producer", x: t(50), y: G, patrolMin: t(47), patrolMax: t(55), activateRange: 560 },
    { id: "pp_mid_a", type: "post_producer", x: t(70), y: G, patrolMin: t(67), patrolMax: t(74), activateRange: 520 },
    { id: "pp_mid_b", type: "post_producer", x: t(76), y: G - t(4), patrolMin: t(74), patrolMax: t(77), activateRange: 520 },
    { id: "pp_final_a", type: "post_producer", x: t(102), y: G, patrolMin: t(99), patrolMax: t(106), activateRange: 480 },
    { id: "pp_final_b", type: "post_producer", x: t(107), y: G, patrolMin: t(104), patrolMax: t(110), activateRange: 480 },
  ],
  zones: [
    { label: "BAY A", x: t(1), y: 160, w: t(13), color: "#1d4ed8" },
    { label: "RUNWAY", x: t(14), y: 160, w: t(18), color: "#334155" },
    { label: "STAGE 1", x: t(46), y: 160, w: t(12), color: "#6d28d9" },
    { label: "SUITE", x: t(58), y: 160, w: t(8), color: "#0f766e" },
    { label: "HAZARD LANE", x: t(66), y: 160, w: t(26), color: "#92400e" },
    { label: "WRAP STAGE", x: t(98), y: 160, w: t(19), color: "#e8b84a" },
  ],
};

export { STUDIO_01 as LEVEL_01 };
