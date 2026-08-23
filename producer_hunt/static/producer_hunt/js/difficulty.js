export const DIFFICULTY_IDS = ["easy", "normal", "hard"];

export const DIFFICULTY = {
  easy: {
    id: "easy",
    label: "Easy",
    health: 0.8,
    reaction: 1.4,
    interval: 1,
    projSpeed: 0.82,
    maxRanged: 1,
    maxClose: 1,
    pickup: 1.4,
    aimSpread: 0.14,
    playerInvuln: 1.15,
  },
  normal: {
    id: "normal",
    label: "Normal",
    health: 1,
    reaction: 1,
    interval: 1,
    projSpeed: 1,
    maxRanged: 2,
    maxClose: 1,
    pickup: 1,
    aimSpread: 0.08,
    playerInvuln: 0.85,
  },
  hard: {
    id: "hard",
    label: "Hard",
    health: 1.25,
    reaction: 0.82,
    interval: 1,
    projSpeed: 1.15,
    maxRanged: 2,
    maxClose: 2,
    pickup: 0.72,
    aimSpread: 0.05,
    playerInvuln: 0.72,
  },
};

export function resolveDifficulty(id) {
  const key = String(id || "normal").toLowerCase();
  return DIFFICULTY[key] || DIFFICULTY.normal;
}

export function cycleDifficulty(id, dir = 1) {
  const i = Math.max(0, DIFFICULTY_IDS.indexOf(String(id || "normal")));
  const next = DIFFICULTY_IDS[(i + dir + DIFFICULTY_IDS.length) % DIFFICULTY_IDS.length];
  return next;
}
