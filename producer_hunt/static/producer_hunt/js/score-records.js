/** Versioned personal-best records for Producer Hunt Studio 01. */

export const RECORDS_KEY = "bigbangadmin.producer_hunt.records.v1";
export const RECORDS_VERSION = 1;

const RANKS = ["D", "C", "B", "A", "S"];

export function rankOrder(rank) {
  const i = RANKS.indexOf(String(rank || "").toUpperCase());
  return i < 0 ? 0 : i;
}

function emptyEntry() {
  return {
    highestScore: 0,
    bestRank: "",
    fastestTime: null,
    highestCombo: 0,
    bestAccuracy: 0,
    mostRescues: 0,
  };
}

function recordKey(levelId, difficultyId, characterId) {
  return `${levelId || "studio_01"}|${difficultyId || "normal"}|${characterId || "editor"}`;
}

function readStore() {
  try {
    if (typeof localStorage === "undefined") return { version: RECORDS_VERSION, entries: {} };
    const raw = localStorage.getItem(RECORDS_KEY);
    if (!raw) return { version: RECORDS_VERSION, entries: {} };
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== RECORDS_VERSION || typeof parsed.entries !== "object") {
      console.warn("[Producer Hunt] Records save was invalid. Using empty records.");
      return { version: RECORDS_VERSION, entries: {} };
    }
    return parsed;
  } catch (err) {
    console.warn("[Producer Hunt] Records save could not be read.", err);
    return { version: RECORDS_VERSION, entries: {} };
  }
}

function writeStore(store) {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(RECORDS_KEY, JSON.stringify(store));
  } catch (err) {
    console.warn("[Producer Hunt] Records save could not be written.", err);
  }
}

export function loadRecord(levelId, difficultyId, characterId) {
  const store = readStore();
  const entry = store.entries[recordKey(levelId, difficultyId, characterId)];
  return entry && typeof entry === "object" ? { ...emptyEntry(), ...entry } : emptyEntry();
}

export function compareAndSaveRecords({ levelId, difficultyId, characterId, stats }) {
  const previous = loadRecord(levelId, difficultyId, characterId);
  const next = { ...previous };
  const improved = {
    score: false,
    rank: false,
    time: false,
    combo: false,
    accuracy: false,
    rescues: false,
  };
  const score = Math.max(0, Math.round(Number(stats.score) || 0));
  if (score > (previous.highestScore || 0)) {
    next.highestScore = score;
    improved.score = true;
  }
  if (rankOrder(stats.rank) > rankOrder(previous.bestRank)) {
    next.bestRank = stats.rank;
    improved.rank = true;
  }
  const time = Number(stats.time);
  if (Number.isFinite(time) && time > 0 && (previous.fastestTime == null || time < previous.fastestTime)) {
    next.fastestTime = time;
    improved.time = true;
  }
  const combo = Math.max(0, Math.round(Number(stats.combo) || 0));
  if (combo > (previous.highestCombo || 0)) {
    next.highestCombo = combo;
    improved.combo = true;
  }
  const acc = Math.max(0, Number(stats.accuracy) || 0);
  if (acc > (previous.bestAccuracy || 0)) {
    next.bestAccuracy = acc;
    improved.accuracy = true;
  }
  const rescues = Math.max(0, Math.round(Number(stats.rescues) || 0));
  if (rescues > (previous.mostRescues || 0)) {
    next.mostRescues = rescues;
    improved.rescues = true;
  }
  const store = readStore();
  store.entries[recordKey(levelId, difficultyId, characterId)] = next;
  writeStore(store);
  return { previous, next, improved };
}
