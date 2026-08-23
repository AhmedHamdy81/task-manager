/** Studio 01 results presentation. Saving happens before count-up animation. */

import { DESIGN_H, DESIGN_W } from "./config.js";
import { formatClock, RANK_WEIGHTS } from "./score-manager.js";
import { menuButtons, hitMenu, moveMenuIndex } from "./ui.js";

const LINES = [
  { key: "finalScore", label: "Final Score", format: (n) => String(Math.round(n)), record: "score" },
  { key: "time", label: "Completion Time", format: (n) => formatClock(n), record: "time" },
  { key: "enemiesDefeated", label: "Enemies Defeated", format: (n) => String(Math.round(n)) },
  { key: "highestCombo", label: "Highest Combo", format: (n) => String(Math.round(n)), record: "combo" },
  { key: "accuracy", label: "Accuracy", format: (n) => `${Math.round(n)}%`, record: "accuracy" },
  { key: "damageTaken", label: "Damage Taken", format: (n) => String(Math.round(n)) },
  { key: "deaths", label: "Player Deaths", format: (n) => String(Math.round(n)) },
  { key: "rescues", label: "Crew Rescued", format: (_n, data) => `${data.rescuesFound}/4`, record: "rescues" },
  { key: "destructiblesDestroyed", label: "Destructibles Destroyed", format: (n) => String(Math.round(n)) },
  { key: "boss", label: "Boss Defeated", format: (_n, data) => (data.bossesDefeated ? "YES" : "NO") },
  { key: "difficulty", label: "Difficulty", format: (_n, data) => String(data.difficulty || "Normal").toUpperCase() },
];

export class ResultsScreen {
  constructor() {
    this.reset();
  }

  reset() {
    this.active = false;
    this.saved = false;
    this.data = null;
    this.reveal = 0;
    this.rankOn = false;
    this.skipped = false;
    this.menuIndex = 1;
    this.tickAcc = 0;
  }

  begin(data) {
    if (this.active && this.data) return this.data;
    this.active = true;
    this.saved = true;
    this.data = data;
    this.reveal = 0;
    this.rankOn = false;
    this.skipped = false;
    this.menuIndex = 1;
    this.tickAcc = 0;
    return data;
  }

  skip() {
    if (!this.active || !this.data) return;
    this.skipped = true;
    this.reveal = LINES.length;
    this.rankOn = true;
  }

  update(dt, input) {
    if (!this.active || !this.data) return;
    const counting = !this.skipped && this.reveal < LINES.length;
    if (counting) {
      if (input?.consume?.("confirm") || input?.consume?.("shoot") || input?.consume?.("pause")) {
        this.skip();
        return null;
      }
      this.tickAcc += dt;
      if (this.tickAcc >= 0.12) {
        this.tickAcc = 0;
        this.reveal += 1;
        if (this.reveal >= LINES.length) this.rankOn = true;
        return "score_tick";
      }
      return null;
    }
    this.rankOn = true;
    return null;
  }

  buttons() {
    return [
      { id: "CONTINUE — COMING SOON", label: "CONTINUE — COMING SOON", disabled: true },
      { id: "RETRY STUDIO 01", label: "RETRY STUDIO 01" },
      { id: "CHARACTER SELECT", label: "CHARACTER SELECT" },
      { id: "MAIN MENU", label: "MAIN MENU" },
    ].map((b, i) => ({
      ...b,
      x: DESIGN_W / 2 + 220,
      y: 430 + i * 62,
      w: 420,
      h: 52,
    }));
  }

  navButtons() {
    return menuButtons(
      ["RETRY STUDIO 01", "CHARACTER SELECT", "MAIN MENU"],
      500,
      { gap: 62, w: 420 }
    );
  }

  hit(x, y) {
    const all = this.buttons();
    const hit = hitMenu(all, x, y);
    if (!hit || hit.disabled || hit.id.startsWith("CONTINUE")) return null;
    return hit;
  }

  move(dir) {
    const playable = this.buttons().filter((b) => !b.disabled && !b.id.startsWith("CONTINUE"));
    const idx = Math.max(0, playable.findIndex((b) => b.id === playable[this.menuIndex]?.id));
    this.menuIndex = moveMenuIndex(idx, dir, playable.length);
    return playable[this.menuIndex];
  }

  draw(ctx, assets, opts = {}) {
    const data = this.data;
    if (!data) return;
    ctx.save();
    ctx.fillStyle = "rgba(5, 7, 12, 0.82)";
    ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    ctx.fillStyle = "#e8b84a";
    ctx.font = "bold 42px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("STUDIO 01 COMPLETE", DESIGN_W / 2, 72);

    const kit = assets?.characterKit?.(data.characterId);
    const portrait = kit?.portraitImage;
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(72, 110, 160, 160);
    if (portrait) ctx.drawImage(portrait, 80, 118, 144, 144);
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 22px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(data.characterName || "CREW", 72, 298);
    if (data.badge) {
      ctx.fillStyle = "#67e8f9";
      ctx.font = "bold 16px sans-serif";
      ctx.fillText(data.badge.name, 72, 324);
    }

    const shown = this.skipped ? LINES.length : this.reveal;
    LINES.forEach((line, i) => {
      if (i >= shown) return;
      const y = 118 + i * 34;
      const value = line.key === "finalScore" ? data.finalScore : line.key === "time" ? data.time : line.key === "accuracy" ? data.accuracy : data[line.key];
      ctx.fillStyle = "#94a3b8";
      ctx.font = "16px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(line.label, 280, y);
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 18px sans-serif";
      ctx.fillText(line.format(value, data), 620, y);
      if (line.record && data.records?.improved?.[line.record]) {
        ctx.fillStyle = "#86efac";
        ctx.font = "bold 13px sans-serif";
        ctx.fillText("NEW RECORD", 860, y);
      }
    });

    if (this.rankOn) {
      ctx.textAlign = "center";
      ctx.fillStyle = opts.reducedFlash ? "#f4f1ea" : "#e8b84a";
      ctx.font = "bold 64px sans-serif";
      ctx.fillText(`RANK ${data.rank}`, DESIGN_W * 0.78, 200);
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "16px sans-serif";
      ctx.fillText("RANK BREAKDOWN", DESIGN_W * 0.78, 250);
      const labels = [
        ["Combat", RANK_WEIGHTS.combat, data.rankInputs.combat],
        ["Time", RANK_WEIGHTS.time, data.rankInputs.time],
        ["Accuracy", RANK_WEIGHTS.accuracy, data.rankInputs.accuracy],
        ["Rescues", RANK_WEIGHTS.rescues, data.rankInputs.rescues],
        ["Survival", RANK_WEIGHTS.survival, data.rankInputs.survival],
        ["Skill bonuses", RANK_WEIGHTS.skill, data.rankInputs.skill],
      ];
      labels.forEach((row, i) => {
        const y = 280 + i * 24;
        ctx.textAlign = "right";
        ctx.fillStyle = "#94a3b8";
        ctx.font = "14px sans-serif";
        ctx.fillText(`${row[0]} (${Math.round(row[1] * 100)}%)`, DESIGN_W * 0.78 + 40, y);
        ctx.textAlign = "left";
        ctx.fillStyle = "#f4f1ea";
        ctx.fillText(`${Math.round(row[2] * 100)}`, DESIGN_W * 0.78 + 52, y);
      });
      ctx.textAlign = "center";
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "14px sans-serif";
      const why =
        data.rank === "S"
          ? "Boss down, full crew, and strong overall performance."
          : data.sBlocked?.length
            ? `S locked: ${data.sBlocked.join(" · ")}`
            : `Weighted score ${Math.round((data.rankTotal || 0) * 100)}.`;
      ctx.fillText(why, DESIGN_W * 0.78, 440);
    }
    ctx.restore();
  }
}
