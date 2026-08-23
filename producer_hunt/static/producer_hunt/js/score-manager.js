/** Authoritative Studio 01 scoring, combos, bonuses, rank, and run stats. */

import { DEBUG_COMBAT } from "./config.js";
import { resolveDifficulty } from "./difficulty.js";
import { compareAndSaveRecords } from "./score-records.js";

export const SCORE_VERSION = 1;
export const STUDIO_CLEAR_BONUS = 5000;
export const COMBO_WINDOW_SEC = 3.5;
export const MULTI_KILL_WINDOW_SEC = 1;

export const SCORE_VALUES = {
  post_producer: 100,
  assistant_producer: 100,
  colorist: 175,
  vfx_supervisor: 250,
  client: 300,
  boss_01: 10000,
  equipment_crate: 25,
  production_monitor: 40,
  film_reel_container: 50,
  electrical_control_box: 75,
  compressed_air_canister: 100,
  camera_operator: 500,
  sound_engineer: 500,
  stunt_performer: 750,
  production_intern: 750,
  all_rescues: 2000,
  studio_01_complete: STUDIO_CLEAR_BONUS,
  multi_kill: 500,
  chain_reaction: 400,
  no_damage_encounter: 750,
  boss_perfect: 3000,
  weapon_master: 1000,
};

export const COMBAT_DESTRUCTIBLE_KINDS = new Set([
  "equipment_crate",
  "production_monitor",
  "film_reel_container",
  "electrical_control_box",
  "compressed_air_canister",
]);

export const PLAYER_WEAPON_CATEGORIES = ["pistol", "machine_gun", "shotgun", "heavy_blaster"];

export const DIFFICULTY_SCORE_MUL = { easy: 0.9, normal: 1, hard: 1.2 };

export const RANK_WEIGHTS = {
  combat: 0.35,
  time: 0.15,
  accuracy: 0.15,
  rescues: 0.15,
  survival: 0.1,
  skill: 0.1,
};

export const RANK_THRESHOLDS = {
  S: 0.86,
  A: 0.72,
  B: 0.58,
  C: 0.42,
};

export const RANK_PAR = {
  combat: 14000,
  timeBest: 240,
  timeWorst: 780,
  skillMax: 7650,
};

export const CHARACTER_BADGES = {
  editor: { id: "timeline_controller", name: "Timeline Controller", hint: "Use Timeline Freeze" },
  assistant: { id: "rapid_production", name: "Rapid Production", hint: "Use Production Rush" },
  colorist: { id: "precision_finish", name: "Precision Finish", hint: "Finish with 65%+ accuracy" },
  vfx_supervisor: { id: "controlled_chaos", name: "Controlled Chaos", hint: "Trigger a chain reaction" },
};

function newRunId() {
  return `run_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function comboMultiplierFor(count) {
  const n = Number(count) || 0;
  if (n >= 15) return 2.5;
  if (n >= 10) return 2.0;
  if (n >= 6) return 1.5;
  if (n >= 3) return 1.25;
  return 1;
}

export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function logScore(event) {
  if (!DEBUG_COMBAT) return;
  const flag = event.rejected ? "REJECT" : "AWARD";
  console.info(
    `[Producer Hunt][score] ${flag} id=${event.id} src=${event.source} base=${event.base} mul=${event.multiplier} run=${event.runId}`
  );
}

export class ScoreManager {
  constructor() {
    this.reset();
  }

  reset() {
    this.runId = newRunId();
    this.currentScore = 0;
    this.comboCount = 0;
    this.comboMultiplier = 1;
    this.comboTimer = 0;
    this.highestCombo = 0;
    this.enemiesDefeated = 0;
    this.bossesDefeated = 0;
    this.rescuesFound = 0;
    this.destructiblesDestroyed = 0;
    this.shotsFired = 0;
    this.shotsHit = 0;
    this.abilityUses = 0;
    this.damageTaken = 0;
    this.deaths = 0;
    this.missionTime = 0;
    this.combatScore = 0;
    this.bonusScore = 0;
    this.rescueScore = 0;
    this.bonuses = [];
    this.awarded = new Set();
    this.hitVolleys = new Set();
    this.firedVolleys = new Set();
    this.killTimes = [];
    this.chainIds = new Set();
    this.chainTimer = 0;
    this.weaponsUsed = new Set();
    this.abilitiesUsed = new Set();
    this.encounterDamage = {};
    this.bossFightDamage = 0;
    this.bossFightStarted = false;
    this._finalized = null;
    this._lastAward = null;
    this.notices = [];
    this.comboPulse = 0;
  }

  snapshot() {
    return {
      version: SCORE_VERSION,
      runId: this.runId,
      currentScore: this.currentScore,
      highestCombo: this.highestCombo,
      enemiesDefeated: this.enemiesDefeated,
      bossesDefeated: this.bossesDefeated,
      rescuesFound: this.rescuesFound,
      destructiblesDestroyed: this.destructiblesDestroyed,
      shotsFired: this.shotsFired,
      shotsHit: this.shotsHit,
      abilityUses: this.abilityUses,
      damageTaken: this.damageTaken,
      deaths: this.deaths,
      missionTime: this.missionTime,
      combatScore: this.combatScore,
      bonusScore: this.bonusScore,
      rescueScore: this.rescueScore,
      bonuses: this.bonuses.slice(),
      awarded: [...this.awarded],
      hitVolleys: [...this.hitVolleys],
      firedVolleys: [...this.firedVolleys],
      weaponsUsed: [...this.weaponsUsed],
      abilitiesUsed: [...this.abilitiesUsed],
      encounterDamage: { ...this.encounterDamage },
      bossFightDamage: this.bossFightDamage,
      bossFightStarted: this.bossFightStarted,
    };
  }

  applySnapshot(snap) {
    if (!snap || typeof snap !== "object") return;
    this.runId = snap.runId || this.runId;
    this.currentScore = Number(snap.currentScore) || 0;
    this.highestCombo = Number(snap.highestCombo) || 0;
    this.enemiesDefeated = Number(snap.enemiesDefeated) || 0;
    this.bossesDefeated = Number(snap.bossesDefeated) || 0;
    this.rescuesFound = Number(snap.rescuesFound) || 0;
    this.destructiblesDestroyed = Number(snap.destructiblesDestroyed) || 0;
    this.shotsFired = Number(snap.shotsFired) || 0;
    this.shotsHit = Number(snap.shotsHit) || 0;
    this.abilityUses = Number(snap.abilityUses) || 0;
    this.damageTaken = Number(snap.damageTaken) || 0;
    this.deaths = Number(snap.deaths) || 0;
    this.missionTime = Number(snap.missionTime) || 0;
    this.combatScore = Number(snap.combatScore) || 0;
    this.bonusScore = Number(snap.bonusScore) || 0;
    this.rescueScore = Number(snap.rescueScore) || 0;
    this.bonuses = Array.isArray(snap.bonuses) ? snap.bonuses.slice() : [];
    this.awarded = new Set(snap.awarded || []);
    this.hitVolleys = new Set(snap.hitVolleys || []);
    this.firedVolleys = new Set(snap.firedVolleys || []);
    this.weaponsUsed = new Set(snap.weaponsUsed || []);
    this.abilitiesUsed = new Set(snap.abilitiesUsed || []);
    this.encounterDamage = snap.encounterDamage && typeof snap.encounterDamage === "object" ? { ...snap.encounterDamage } : {};
    this.bossFightDamage = Number(snap.bossFightDamage) || 0;
    this.bossFightStarted = Boolean(snap.bossFightStarted);
    this.clearCombo();
  }

  sync(game) {
    if (!game) return;
    game.score = this.currentScore;
    if (!game.stats) game.stats = {};
    game.stats.kills = this.enemiesDefeated;
    game.stats.deaths = this.deaths;
    game.stats.time = this.missionTime;
    game.stats.rescuesFound = this.rescuesFound;
    game.stats.rescueScore = this.rescueScore;
    game.stats.allRescuesAwarded = this.awarded.has("bonus:all_rescues");
    game.stats.allRescuesBonus = this.awarded.has("bonus:all_rescues") ? SCORE_VALUES.all_rescues : 0;
  }

  update(dt, opts = {}) {
    if (this.comboPulse > 0) this.comboPulse = Math.max(0, this.comboPulse - dt * 3);
    this.notices = this.notices.filter((n) => {
      n.age += dt;
      return n.age < n.life;
    });
    if (opts.frozen) return;
    this.missionTime += dt;
    if (this.comboCount > 0) {
      this.comboTimer -= dt;
      if (this.comboTimer <= 0) this.breakCombo();
    }
    if (this.chainTimer > 0) {
      this.chainTimer -= dt;
      if (this.chainTimer <= 0) this.chainIds.clear();
    }
  }

  accuracy() {
    if (this.shotsFired <= 0) return 0;
    return Math.max(0, Math.min(100, (this.shotsHit / this.shotsFired) * 100));
  }

  award(id, base, opts = {}) {
    const eventId = String(id || "");
    const source = opts.source || "unknown";
    const raw = Math.max(0, Math.round(Number(base) || 0));
    if (!eventId || raw <= 0) return 0;
    if (this.awarded.has(eventId)) {
      this._lastAward = { id: eventId, source, base: raw, multiplier: 0, rejected: true, runId: this.runId };
      logScore(this._lastAward);
      return 0;
    }
    this.awarded.add(eventId);
    const mul = opts.combo ? this.comboMultiplier : 1;
    const granted = Math.max(1, Math.round(raw * mul));
    this.currentScore += granted;
    if (opts.bucket === "combat") this.combatScore += granted;
    if (opts.bucket === "bonus") this.bonusScore += granted;
    if (opts.bucket === "rescue") this.rescueScore += granted;
    this._lastAward = { id: eventId, source, base: raw, multiplier: mul, rejected: false, runId: this.runId, granted };
    logScore(this._lastAward);
    return granted;
  }

  pushNotice(text, sfx) {
    this.notices.push({ text, age: 0, life: 2.2, sfx: sfx || "bonus_awarded" });
  }

  awardBonus(key, label) {
    const id = `bonus:${key}`;
    const value = SCORE_VALUES[key];
    if (!value) return 0;
    const granted = this.award(id, value, { source: key, bucket: "bonus" });
    if (granted) {
      this.bonuses.push({ id: key, label, value: granted });
      this.pushNotice(label, "bonus_awarded");
    }
    return granted;
  }

  clearCombo() {
    this.comboCount = 0;
    this.comboMultiplier = 1;
    this.comboTimer = 0;
  }

  breakCombo() {
    if (this.comboCount > 0) this.pushNotice("COMBO BREAK", "combo_break");
    this.clearCombo();
  }

  bumpCombo() {
    const prevMul = this.comboMultiplier;
    this.comboCount += 1;
    this.comboTimer = COMBO_WINDOW_SEC;
    this.comboMultiplier = comboMultiplierFor(this.comboCount);
    if (this.comboCount > this.highestCombo) this.highestCombo = this.comboCount;
    this.comboPulse = 1;
    if (this.comboMultiplier > prevMul) this.pushNotice(`COMBO ×${this.comboMultiplier}`, "combo_increase");
  }

  reduceCombo() {
    if (this.comboCount <= 0) return;
    if (this.comboCount <= 2) {
      this.breakCombo();
      return;
    }
    this.comboCount = Math.max(0, this.comboCount - 2);
    this.comboMultiplier = comboMultiplierFor(this.comboCount);
    this.comboTimer = Math.min(this.comboTimer, COMBO_WINDOW_SEC * 0.6);
    if (this.comboCount <= 0) this.breakCombo();
  }

  noteAttackFired(volleyId) {
    const id = String(volleyId || "");
    if (!id || this.firedVolleys.has(id)) return;
    this.firedVolleys.add(id);
    this.shotsFired += 1;
  }

  noteAttackHit(volleyId, targetKey) {
    const id = String(volleyId || "");
    if (!id) return;
    const hitId = `${id}>${targetKey || "*"}`;
    if (this.awarded.has(`hit:${hitId}`)) return;
    this.awarded.add(`hit:${hitId}`);
    if (!this.hitVolleys.has(id)) {
      this.hitVolleys.add(id);
      this.shotsHit += 1;
    }
  }

  noteAbilityUse(id) {
    this.abilityUses += 1;
    if (id) this.abilitiesUsed.add(id);
  }

  noteDamageTaken(amount, context = {}) {
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0) return;
    this.damageTaken += amt;
    if (this.bossFightStarted) this.bossFightDamage += amt;
    if (context.encounterId) {
      this.encounterDamage[context.encounterId] = (this.encounterDamage[context.encounterId] || 0) + amt;
    }
    this.reduceCombo();
  }

  noteDeath() {
    this.deaths += 1;
    this.clearCombo();
  }

  markBossFight() {
    this.bossFightStarted = true;
    this.bossFightDamage = 0;
  }

  markEncounterStart(encounterId) {
    if (!encounterId || this.encounterDamage[encounterId] != null) return;
    this.encounterDamage[encounterId] = 0;
  }

  awardEnemyDefeat(enemy, source = {}) {
    if (!enemy || enemy.isBoss) return 0;
    const spawnId = enemy.spawnId || enemy.id;
    const eventId = `enemy:${spawnId}`;
    if (this.awarded.has(eventId)) return 0;
    this.bumpCombo();
    const type = enemy.type || enemy.spec?.type || "post_producer";
    const base = SCORE_VALUES[type] || enemy.spec?.scoreValue || 100;
    const granted = this.award(eventId, base, { source: type, combo: true, bucket: "combat" });
    if (!granted) return 0;
    this.enemiesDefeated += 1;
    const weaponId = source.weaponId || "";
    if (PLAYER_WEAPON_CATEGORIES.includes(weaponId)) this.weaponsUsed.add(weaponId);
    const now = this.missionTime;
    this.killTimes.push(now);
    this.killTimes = this.killTimes.filter((t) => now - t <= MULTI_KILL_WINDOW_SEC);
    if (this.killTimes.length >= 3) this.awardBonus("multi_kill", "MULTI-KILL +500");
    if (this.weaponsUsed.size >= PLAYER_WEAPON_CATEGORIES.length) {
      this.awardBonus("weapon_master", "WEAPON MASTER +1000");
    }
    this.noteChainMember(`enemy:${spawnId}`);
    return granted;
  }

  awardDestructible(kind, objectId, opts = {}) {
    const id = objectId || kind;
    const base = SCORE_VALUES[kind] || opts.fallback || 0;
    const combat = COMBAT_DESTRUCTIBLE_KINDS.has(kind) || Boolean(opts.combat);
    const granted = this.award(`destructible:${id}`, base, {
      source: kind,
      combo: combat && this.comboCount > 0,
      bucket: "combat",
    });
    if (granted) {
      this.destructiblesDestroyed += 1;
      this.noteChainMember(`prop:${id}`);
    }
    return granted;
  }

  noteChainMember(id) {
    if (!id) return;
    this.chainIds.add(id);
    this.chainTimer = 1.15;
    if (this.chainIds.size >= 3) this.awardBonus("chain_reaction", "CHAIN REACTION +400");
  }

  awardRescue(kind, rescueId) {
    const base = SCORE_VALUES[kind] || 500;
    const granted = this.award(`rescue:${rescueId || kind}`, base, { source: kind, bucket: "rescue" });
    if (granted) this.rescuesFound += 1;
    return granted;
  }

  awardAllRescues(found, total) {
    if (found < total || total < 4) return 0;
    return this.awardBonus("all_rescues", "FULL RESCUE +2000");
  }

  awardEncounter(encounterId, reward = 0) {
    if (reward > 0) this.award(`encounter:${encounterId}`, reward, { source: "encounter", bucket: "combat" });
    if ((this.encounterDamage[encounterId] || 0) <= 0) {
      const granted = this.award(`bonus:no_damage_encounter:${encounterId}`, SCORE_VALUES.no_damage_encounter, {
        source: "no_damage_encounter",
        bucket: "bonus",
      });
      if (granted) {
        this.bonuses.push({
          id: `no_damage:${encounterId}`,
          label: "NO DAMAGE ENCOUNTER +750",
          value: granted,
        });
        this.pushNotice("NO DAMAGE ENCOUNTER +750", "bonus_awarded");
      }
    }
  }

  awardBoss() {
    const granted = this.award("boss:boss_01", SCORE_VALUES.boss_01, { source: "boss_01", bucket: "combat" });
    if (granted) this.bossesDefeated += 1;
    if (this.bossFightStarted && this.bossFightDamage <= 0) {
      this.awardBonus("boss_perfect", "BOSS PERFECT +3000");
    }
    return granted;
  }

  awardMissionComplete() {
    return this.award("mission:studio_01", SCORE_VALUES.studio_01_complete, {
      source: "studio_01_complete",
      bucket: "bonus",
    });
  }

  characterBadge(characterId) {
    const spec = CHARACTER_BADGES[characterId];
    if (!spec) return null;
    let ok = false;
    if (characterId === "editor") ok = this.abilitiesUsed.has("timeline_freeze");
    else if (characterId === "assistant") ok = this.abilitiesUsed.has("production_rush");
    else if (characterId === "colorist") ok = this.accuracy() >= 65;
    else if (characterId === "vfx_supervisor") ok = this.bonuses.some((b) => b.id === "chain_reaction");
    return ok ? spec : null;
  }

  rankInputs() {
    const combat = Math.max(0, Math.min(1, this.combatScore / RANK_PAR.combat));
    const span = RANK_PAR.timeWorst - RANK_PAR.timeBest;
    const time = Math.max(0, Math.min(1, 1 - (this.missionTime - RANK_PAR.timeBest) / span));
    const accuracy = this.accuracy() / 100;
    const rescues = Math.max(0, Math.min(1, this.rescuesFound / 4));
    const deathPart = this.deaths <= 0 ? 1 : this.deaths === 1 ? 0.82 : this.deaths === 2 ? 0.64 : 0.38;
    const dmgPart = Math.max(0.35, 1 - this.damageTaken / 220);
    const survival = Math.max(0, Math.min(1, deathPart * 0.7 + dmgPart * 0.3));
    const skill = Math.max(0, Math.min(1, this.bonusScore / RANK_PAR.skillMax));
    return { combat, time, accuracy, rescues, survival, skill };
  }

  computeRank(inputs) {
    const w = RANK_WEIGHTS;
    const total =
      inputs.combat * w.combat +
      inputs.time * w.time +
      inputs.accuracy * w.accuracy +
      inputs.rescues * w.rescues +
      inputs.survival * w.survival +
      inputs.skill * w.skill;
    let rank = "D";
    if (total >= RANK_THRESHOLDS.S) rank = "S";
    else if (total >= RANK_THRESHOLDS.A) rank = "A";
    else if (total >= RANK_THRESHOLDS.B) rank = "B";
    else if (total >= RANK_THRESHOLDS.C) rank = "C";
    const sBlocked = [];
    if (!this.bossesDefeated) sBlocked.push("Boss not defeated");
    if (this.rescuesFound < 4) sBlocked.push("Not all crew rescued");
    if (this.deaths > 2) sBlocked.push("Too many deaths");
    if (rank === "S" && sBlocked.length) rank = "A";
    return { rank, total, sBlocked };
  }

  finalize(ctx = {}) {
    if (this._finalized) return this._finalized;
    const difficulty = resolveDifficulty(ctx.difficulty);
    const mul = DIFFICULTY_SCORE_MUL[difficulty.id] || 1;
    const rawScore = this.currentScore;
    const finalScore = Math.round(rawScore * mul);
    const inputs = this.rankInputs();
    const ranked = this.computeRank(inputs);
    const stats = {
      score: finalScore,
      rawScore,
      difficultyMul: mul,
      time: this.missionTime,
      rank: ranked.rank,
      combo: this.highestCombo,
      accuracy: this.accuracy(),
      rescues: this.rescuesFound,
    };
    const records = compareAndSaveRecords({
      levelId: ctx.levelId || "studio_01",
      difficultyId: difficulty.id,
      characterId: ctx.characterId || "editor",
      stats,
    });
    this._finalized = {
      runId: this.runId,
      finalScore,
      rawScore,
      difficultyMul: mul,
      difficulty: difficulty.label || difficulty.id,
      difficultyId: difficulty.id,
      time: this.missionTime,
      enemiesDefeated: this.enemiesDefeated,
      bossesDefeated: this.bossesDefeated,
      highestCombo: this.highestCombo,
      accuracy: this.accuracy(),
      shotsFired: this.shotsFired,
      shotsHit: this.shotsHit,
      damageTaken: this.damageTaken,
      deaths: this.deaths,
      rescuesFound: this.rescuesFound,
      destructiblesDestroyed: this.destructiblesDestroyed,
      bonuses: this.bonuses.slice(),
      rank: ranked.rank,
      rankTotal: ranked.total,
      rankInputs: inputs,
      rankWeights: RANK_WEIGHTS,
      sBlocked: ranked.sBlocked,
      records,
      badge: this.characterBadge(ctx.characterId),
      characterId: ctx.characterId,
      characterName: ctx.characterName,
    };
    if (DEBUG_COMBAT) {
      console.info("[Producer Hunt][score] finalize", {
        runId: this.runId,
        inputs,
        rank: ranked.rank,
        total: ranked.total,
        records,
      });
    }
    return this._finalized;
  }
}

let _volley = 0;
export function nextVolleyId() {
  _volley += 1;
  return `v${_volley}`;
}
