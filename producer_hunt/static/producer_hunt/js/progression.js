/** Studio hazards, doors, checkpoints, and exit. Level data looks up ids. */

/** Character roster unlocks. The select menu reads this; it does not grant unlocks. */
export const CHARACTER_UNLOCKS = {
  editor: { id: "editor", always: true },
  assistant: { id: "assistant", always: true },
  vfx_supervisor: {
    id: "vfx_supervisor",
    type: "completedLevel",
    levelId: "studio_01",
    label: "Defeat Boss 1",
  },
  colorist: {
    id: "colorist",
    type: "completedLevel",
    levelId: "studio_02",
    label: "Complete Studio 02",
  },
};

export function isCharacterUnlocked(characterId, settings = {}) {
  const rule = CHARACTER_UNLOCKS[characterId] || CHARACTER_UNLOCKS.editor;
  if (rule.always) return true;
  const done = Array.isArray(settings.completedLevels) ? settings.completedLevels : [];
  if (rule.type === "completedLevel") return done.includes(rule.levelId);
  if (rule.type === "phase2") return Boolean(settings.phase2Complete);
  return false;
}

export function characterUnlockRequirement(characterId) {
  const rule = CHARACTER_UNLOCKS[characterId];
  if (!rule || rule.always) return "";
  return rule.label || "LOCKED";
}


export const HAZARD_DAMAGE = 10;
export const HAZARD_COOLDOWN = 0.75;
export const HAZARD_VIS = 128;
export const PROGRESSION_VIS = 256;

export const HAZARD_DEFS = {
  live_cable: {
    id: "live_cable",
    sprite_frame: 0,
    collision_width: 92,
    collision_height: 28,
    hitOffsetX: 18,
    hitOffsetY: 92,
    damage: HAZARD_DAMAGE,
    cooldown: HAZARD_COOLDOWN,
    animation: "spark",
    enabled: true,
  },
  electrical_panel: {
    id: "electrical_panel",
    sprite_frame: 1,
    collision_width: 52,
    collision_height: 86,
    hitOffsetX: 38,
    hitOffsetY: 28,
    damage: HAZARD_DAMAGE,
    cooldown: HAZARD_COOLDOWN,
    animation: "spark",
    enabled: true,
  },
  hot_light: {
    id: "hot_light",
    sprite_frame: 2,
    collision_width: 48,
    collision_height: 52,
    hitOffsetX: 40,
    hitOffsetY: 6,
    damage: HAZARD_DAMAGE,
    cooldown: HAZARD_COOLDOWN,
    animation: "heat",
    enabled: true,
  },
  falling_cases: {
    id: "falling_cases",
    sprite_frame: 3,
    collision_width: 68,
    collision_height: 90,
    hitOffsetX: 30,
    hitOffsetY: 30,
    damage: HAZARD_DAMAGE,
    cooldown: HAZARD_COOLDOWN,
    animation: "crush",
    enabled: true,
  },
  cable_coil: {
    id: "cable_coil",
    sprite_frame: 4,
    collision_width: 80,
    collision_height: 36,
    hitOffsetX: 24,
    hitOffsetY: 84,
    damage: 0,
    cooldown: HAZARD_COOLDOWN,
    animation: "none",
    enabled: false,
    reserved: true,
  },
  cracked_monitor: {
    id: "cracked_monitor",
    sprite_frame: 5,
    collision_width: 70,
    collision_height: 82,
    hitOffsetX: 30,
    hitOffsetY: 24,
    damage: HAZARD_DAMAGE,
    cooldown: HAZARD_COOLDOWN,
    animation: "spark",
    enabled: true,
  },
  steam_vent: {
    id: "steam_vent",
    sprite_frame: 4,
    collision_width: 48,
    collision_height: 150,
    hitOffsetX: 40,
    hitOffsetY: -22,
    damage: HAZARD_DAMAGE,
    telegraphDuration: 0.8,
    activeDuration: 1.2,
    inactiveDuration: 2.2,
    cooldown: 0.75,
    knockback: 280,
    animation: "steam",
    sound: "env_steam",
    cycle: true,
    enabled: true,
  },
  electrical_floor: {
    id: "electrical_floor",
    sprite_frame: 1,
    collision_width: 140,
    collision_height: 18,
    hitOffsetX: 0,
    hitOffsetY: 110,
    damage: HAZARD_DAMAGE,
    telegraphDuration: 1.0,
    activeDuration: 0.9,
    inactiveDuration: 2.6,
    cooldown: 0.75,
    knockback: 160,
    animation: "spark",
    sound: "env_electric",
    cycle: true,
    enabled: true,
  },
  falling_light: {
    id: "falling_light",
    sprite_frame: 2,
    collision_width: 48,
    collision_height: 28,
    hitOffsetX: 40,
    hitOffsetY: 6,
    damage: HAZARD_DAMAGE * 2,
    telegraphDuration: 1.2,
    cooldown: 0.75,
    knockback: 200,
    animation: "fall",
    sound: "env_alarm",
    cycle: true,
    enabled: true,
  },
  camera_rig: {
    id: "camera_rig",
    sprite_frame: 5,
    collision_width: 160,
    collision_height: 24,
    hitOffsetX: 0,
    hitOffsetY: 0,
    damage: 0,
    cooldown: 0,
    animation: "track",
    sound: "env_machine",
    enabled: true,
  },
  rolling_cart: {
    id: "rolling_cart",
    sprite_frame: 3,
    collision_width: 110,
    collision_height: 70,
    hitOffsetX: 0,
    hitOffsetY: 58,
    damage: HAZARD_DAMAGE,
    telegraphDuration: 0.9,
    inactiveDuration: 7,
    cooldown: 0.75,
    knockback: 340,
    animation: "roll",
    sound: "env_alarm",
    cycle: true,
    enabled: true,
  },
};

const HAZARD_BY_FRAME = Object.fromEntries(
  Object.values(HAZARD_DEFS).map((d) => [d.sprite_frame, d.id])
);

export const DOOR_DEFS = {
  studio: {
    id: "studio",
    closedFrame: 0,
    openFrame: 1,
    vis: PROGRESSION_VIS,
    block: { offsetX: 88, offsetY: 36, w: 80, h: 210 },
  },
  exit: {
    id: "exit",
    closedFrame: 4,
    openFrame: 5,
    vis: PROGRESSION_VIS,
    block: { offsetX: 58, offsetY: 28, w: 140, h: 220 },
  },
};

export const CHECKPOINT_FRAMES = { idle: 2, active: 3 };

export function hazardDef(kindOrFrame) {
  if (HAZARD_DEFS[kindOrFrame]) return HAZARD_DEFS[kindOrFrame];
  const id = HAZARD_BY_FRAME[kindOrFrame];
  return (id && HAZARD_DEFS[id]) || HAZARD_DEFS.live_cable;
}

export function instantiateHazard(raw, index, levelId) {
  const def = hazardDef(raw.kind || raw.frame);
  const vis = HAZARD_VIS;
  const x = Number.isFinite(raw.hitX) ? raw.hitX : raw.x + (def.hitOffsetX || 0);
  const y = Number.isFinite(raw.hitY) ? raw.hitY : raw.y + (def.hitOffsetY || 0);
  return {
    id: raw.id || `${levelId || "lvl"}_hazard_${index}`,
    kind: def.id,
    frame: def.sprite_frame,
    vis,
    vx: 0,
    x,
    y,
    w: raw.w || def.collision_width,
    h: raw.h || def.collision_height,
    drawX: raw.x,
    drawY: raw.y,
    damage: raw.damage != null ? Number(raw.damage) : def.damage,
    cooldown: raw.cooldown ?? def.cooldown,
    cool: 0,
    animation: def.animation,
    sound: raw.sound || def.sound,
    enabled: raw.enabled !== false && def.enabled !== false && !def.reserved,
    reserved: Boolean(def.reserved),
    cycle: Boolean(def.cycle),
    phase: def.cycle ? "idle" : null,
    phaseAge: 0,
    telegraphDuration: raw.telegraphDuration ?? def.telegraphDuration,
    activeDuration: raw.activeDuration ?? def.activeDuration,
    inactiveDuration: raw.inactiveDuration ?? def.inactiveDuration,
    knockback: raw.knockback ?? def.knockback ?? 220,
    hitCooldown: 0.75,
    pathLeft: raw.pathLeft,
    pathRight: raw.pathRight,
    speed: raw.speed,
    dir: raw.dir || 1,
    endPause: raw.endPause,
    moverX: x,
    pause: 0,
    trigger: raw.trigger,
    triggerX: raw.triggerX,
    impactX: raw.impactX,
    impactY: raw.impactY,
    impactRadius: raw.impactRadius ?? 65,
    ceilingY: raw.ceilingY,
    reset: raw.reset,
    idleWait: raw.idleWait,
    cartX: x,
    visible: def.id !== "rolling_cart",
    hitsEnemies: Boolean(raw.hitsEnemies),
    hitsBoss: Boolean(raw.hitsBoss),
  };
}

export function instantiateDoor(raw, index, levelId) {
  const def = DOOR_DEFS[raw.kind] || DOOR_DEFS.studio;
  const vis = def.vis;
  const requireKeys = raw.requireKeys ?? 0;
  const requireDoors = raw.requireDoors || [];
  const requireEncounters = raw.requireEncounters || [];
  const locked = requireKeys > 0 || requireDoors.length || requireEncounters.length;
  const state = raw.state || (locked ? "locked" : "closed");
  const block = {
    x: raw.x + def.block.offsetX,
    y: raw.y + def.block.offsetY,
    w: def.block.w,
    h: def.block.h,
  };
  return {
    id: raw.id || `${levelId || "lvl"}_door_${index}`,
    kind: def.id,
    closedFrame: def.closedFrame,
    openFrame: def.openFrame,
    vis,
    drawX: raw.x,
    drawY: raw.y,
    x: block.x,
    y: block.y,
    w: block.w,
    h: block.h,
    trigger: {
      x: raw.x + vis * 0.2,
      y: raw.y + vis * 0.15,
      w: vis * 0.6,
      h: vis * 0.85,
    },
    requireKeys,
    requireDoors,
    requireEncounters,
    persistent: raw.persistent !== false,
    state,
    openTimer: 0,
  };
}

export function instantiateCheckpoint(raw, index, levelId, groundY = 980) {
  const vis = PROGRESSION_VIS;
  const footX = raw.x;
  const footY = raw.y ?? groundY;
  const drawX = footX - vis / 2;
  const drawY = footY - vis;
  const spawnX = raw.spawnX ?? footX - 70;
  const spawnY = raw.spawnY ?? footY;
  return {
    id: raw.id || `${levelId || "lvl"}_cp_${index}`,
    vis,
    drawX,
    drawY,
    x: footX - 36,
    y: footY - 160,
    w: 72,
    h: 160,
    spawnX,
    spawnY,
    activated: Boolean(raw.activated),
    inside: false,
    isStart: Boolean(raw.isStart),
  };
}

export function doorFrame(door) {
  return door.state === "open" || door.state === "opening" ? door.openFrame : door.closedFrame;
}

export function checkpointFrame(cp) {
  return cp.activated ? CHECKPOINT_FRAMES.active : CHECKPOINT_FRAMES.idle;
}

export function doorRequirementsMet(door, player, world) {
  if ((player.keys || 0) < (door.requireKeys || 0)) return false;
  for (const id of door.requireDoors || []) {
    const other = (world.doors || []).find((d) => d.id === id);
    if (!other || other.state !== "open") return false;
  }
  for (const id of door.requireEncounters || []) {
    const enc = (world.encounters || []).find((e) => e.id === id);
    if (!enc || !enc.cleared) return false;
  }
  return true;
}

export function tryOpenDoor(door, player, world) {
  if (door.state === "open" || door.state === "opening") return false;
  if (!doorRequirementsMet(door, player, world)) {
    door.state = "locked";
    return false;
  }
  door.state = "opening";
  door.openTimer = 0.28;
  return true;
}

export function updateDoors(world, dt) {
  let changed = false;
  for (const door of world.doors || []) {
    if (door.state !== "opening") continue;
    door.openTimer -= dt;
    if (door.openTimer <= 0) {
      door.state = "open";
      changed = true;
    }
  }
  if (changed) syncDoorSolids(world);
}

export function syncDoorSolids(world) {
  const blocking = (world.doors || [])
    .filter((d) => d.state !== "open")
    .map((d) => ({ x: d.x, y: d.y, w: d.w, h: d.h, doorId: d.id }));
    world.solids = [
      ...(world.platformSolids || []),
      ...blocking,
      ...(world.moverSolids || []),
      ...(world.destructibleSolids || []),
    ];
}

export function currentObjective(world, player) {
  const steps = world.objectives || [];
  for (const step of steps) {
    if (!isStepComplete(step, world, player)) return step.label;
  }
  return "Reach the wrap";
}

function isStepComplete(step, world, player) {
  if (step.type === "checkpoint") {
    const cp = (world.checkpoints || []).find((c) => c.id === step.checkpointId);
    return Boolean(cp && cp.activated);
  }
  if (step.type === "keys") return (player.keys || 0) >= (step.count || 1);
  if (step.type === "door") {
    const door = (world.doors || []).find((d) => d.id === step.doorId);
    return Boolean(door && door.state === "open");
  }
  if (step.type === "encounter") {
    const enc = (world.encounters || []).find((e) => e.id === step.encounterId);
    return Boolean(enc && enc.cleared);
  }
  if (step.type === "waves") return Boolean(world.wavesComplete);
  if (step.type === "exit") return false;
  return true;
}

export function canCompleteLevel(world, player) {
  const req = world.exitRequires || {};
  if ((player.keys || 0) < (req.keys || 0)) return false;
  for (const id of req.doorsOpen || []) {
    const door = (world.doors || []).find((d) => d.id === id);
    if (!door || door.state !== "open") return false;
  }
  for (const id of req.encountersCleared || []) {
    const enc = (world.encounters || []).find((e) => e.id === id);
    if (!enc || !enc.cleared) return false;
  }
  return true;
}

export function spawnClearOf(box, blockers) {
  return !blockers.some((b) => b && box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y);
}

export function findSafeSpawn(world, spawnX, spawnY, extra = []) {
  const w = 80;
  const h = 170;
  const candidates = [0, -90, 90, -180, 180, -270, 270];
  const blockers = [
    ...(world.solids || []),
    ...(world.hazards || []).filter((h) => h.enabled && h.damage > 0 && (h.phase == null || h.phase === "active" || h.phase === "impact")),
    ...(world.destructibleSolids || []),
    ...(world.doors || []).filter((d) => d.state !== "open"),
    ...extra,
  ];
  for (const dx of candidates) {
    const x = spawnX + dx - w / 2;
    const y = spawnY - h;
    if (spawnClearOf({ x, y, w, h }, blockers)) return { x: spawnX + dx, y: spawnY };
  }
  return { x: spawnX, y: spawnY };
}
