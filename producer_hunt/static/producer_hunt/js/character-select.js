import { SpriteAnimator } from "./animation.js";
import { abilityMenuInfo } from "./abilities.js";
import { CHARACTERS, DEFAULT_CHARACTER_ID, characterById, characterSelectStats, weaponSelectCopy } from "./characters.js";
import { DESIGN_H, DESIGN_W } from "./config.js";
import { characterUnlockRequirement, isCharacterUnlocked } from "./progression.js";
import { loadSettings, saveSettings } from "./settings.js";
import { drawButtons, hitButton } from "./ui.js";
import { drawSheetFrame } from "./asset-catalog.js";

const STAT_ORDER = [
  ["health", "HEALTH"],
  ["damage", "DAMAGE"],
  ["speed", "SPEED"],
  ["fireRate", "FIRE RATE"],
  ["defense", "DEFENSE"],
  ["special", "SPECIAL"],
];

function emptyBars() {
  return { health: 3, damage: 3, speed: 3, fireRate: 3, defense: 3, special: 3 };
}

function drawContainedImage(ctx, img, x, y, w, h) {
  if (!img) return false;
  const scale = Math.min(w / img.width, h / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  return true;
}

function roundRect(ctx, x, y, w, h, r = 8) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function wrapText(ctx, text, maxWidth) {
  const raw = String(text || "").trim();
  if (!raw) return [];
  if (maxWidth <= 0) return [raw];
  const words = raw.split(/\s+/);
  const lines = [];
  let cur = "";
  for (const word of words) {
    const next = cur ? `${cur} ${word}` : word;
    if (ctx.measureText(next).width <= maxWidth) {
      cur = next;
      continue;
    }
    if (cur) lines.push(cur);
    if (ctx.measureText(word).width <= maxWidth) {
      cur = word;
      continue;
    }
    let chunk = "";
    for (const ch of word) {
      const trial = chunk + ch;
      if (ctx.measureText(trial).width <= maxWidth) chunk = trial;
      else {
        if (chunk) lines.push(chunk);
        chunk = ch;
      }
    }
    cur = chunk;
  }
  if (cur) lines.push(cur);
  return lines;
}

export class CharacterSelect {
  constructor() {
    this.list = CHARACTERS;
    const saved = loadSettings().characterId;
    const initial = characterById(saved || DEFAULT_CHARACTER_ID);
    this.selectedId = initial.id;
    this.focusIndex = Math.max(
      0,
      this.list.findIndex((c) => c.id === this.selectedId)
    );
    this.preview = new SpriteAnimator(null);
    this._bars = emptyBars();
    this._barTarget = emptyBars();
    this._lockFlash = 0;
    this._entered = false;
    this._abilityImages = new Map();
    this._weaponImages = new Map();
    this._settings = loadSettings();
  }

  get selected() {
    return this.list[this.focusIndex] || characterById(this.selectedId);
  }

  enter(assets) {
    this._entered = true;
    this._settings = loadSettings();
    this._lockFlash = 0;
    this._syncPreview(assets, { restart: true });
    this._barTarget = characterSelectStats(this.selected);
    this._bars = { ...this._barTarget };
    this._loadMenuImages(assets);
  }

  leave() {
    this._entered = false;
    this.preview.pause();
    this.preview.setKit(null);
  }

  update(dt, assets) {
    if (!this._entered) return;
    if (this._lockFlash > 0) this._lockFlash = Math.max(0, this._lockFlash - dt);
    const speed = 10;
    for (const key of Object.keys(this._barTarget)) {
      const cur = this._bars[key];
      const next = this._barTarget[key];
      this._bars[key] = cur + (next - cur) * Math.min(1, dt * speed);
    }
    this.preview.resume();
    this.preview.update(dt);
    if (assets && this.preview.kit !== assets.characterKit?.(this.selected.id)) {
      this._syncPreview(assets);
    }
  }

  move(dir) {
    const n = this.list.length;
    this.focusIndex = (this.focusIndex + dir + n) % n;
    this._onFocusChanged();
  }

  setFocus(i) {
    if (i < 0 || i >= this.list.length) return;
    if (i === this.focusIndex) return;
    this.focusIndex = i;
    this._onFocusChanged();
  }

  _onFocusChanged() {
    this.selectedId = this.selected.id;
    this._barTarget = characterSelectStats(this.selected);
    this._syncPreview(this._assets, { restart: true });
  }

  persist() {
    this.selectedId = this.selected.id;
    saveSettings({ characterId: this.selectedId });
  }

  isUnlocked(id = this.selected.id) {
    return isCharacterUnlocked(id, this._settings);
  }

  notifyLocked() {
    this._lockFlash = 0.85;
  }

  confirmButton() {
    return { id: "CONFIRM", label: "CONFIRM", x: DESIGN_W / 2 - 140, y: DESIGN_H - 96, w: 280, h: 52 };
  }

  backButton() {
    return { id: "BACK", label: "BACK", x: 72, y: DESIGN_H - 96, w: 200, h: 52 };
  }

  prevButton() {
    return { id: "PREV", label: "◀", x: 72, y: 430, w: 64, h: 72 };
  }

  nextButton() {
    return { id: "NEXT", label: "▶", x: 780, y: 430, w: 64, h: 72 };
  }

  handleClick(x, y) {
    if (hitButton(this.prevButton(), x, y)) {
      this.move(-1);
      return "focus";
    }
    if (hitButton(this.nextButton(), x, y)) {
      this.move(1);
      return "focus";
    }
    if (hitButton(this.confirmButton(), x, y)) return "confirm";
    if (hitButton(this.backButton(), x, y)) return "back";
    const stage = this._stage();
    if (x >= stage.x && x <= stage.x + stage.w && y >= stage.y && y <= stage.y + stage.h) {
      return this.isUnlocked() ? "confirm" : "locked";
    }
    return null;
  }

  _stage() {
    return { x: 160, y: 128, w: 600, h: 620 };
  }

  _syncPreview(assets, opts = {}) {
    this._assets = assets || this._assets;
    const kit = this._assets?.characterKit?.(this.selected.id) || this.selected.sprite;
    this.preview.setKit(kit);
    this.preview.flip = false;
    this.preview.play(this.selected.previewAnimation || "idle", { restart: Boolean(opts.restart) });
  }

  async _loadMenuImages(assets) {
    if (!assets?.loadOptionalImage) return;
    for (const ch of this.list) {
      const power = abilityMenuInfo(ch.specialAbility);
      if (power.image) {
        const img = await assets.loadOptionalImage(`menu-ability:${power.id}`, power.image);
        if (img) this._abilityImages.set(power.id, img);
      }
    }
  }

  draw(ctx, assets) {
    this._assets = assets || this._assets;
    ctx.textAlign = "center";
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 40px sans-serif";
    ctx.fillText("SELECT CHARACTER", DESIGN_W / 2, 64);
    ctx.font = "16px sans-serif";
    ctx.fillStyle = "#7dd3fc";
    ctx.fillText("← →  navigate   ·   ENTER / SPACE confirm   ·   ESC back", DESIGN_W / 2, 96);

    this._drawPreview(ctx, assets);
    this._drawInfo(ctx, assets);

    const confirm = this.confirmButton();
    const locked = !this.isUnlocked();
    drawButtons(ctx, [this.backButton(), { ...confirm, label: locked ? "LOCKED" : "CONFIRM" }]);
    this._drawNavArrow(ctx, this.prevButton());
    this._drawNavArrow(ctx, this.nextButton());
  }

  _drawNavArrow(ctx, btn) {
    roundRect(ctx, btn.x, btn.y, btn.w, btn.h, 8);
    ctx.fillStyle = "#172033";
    ctx.fill();
    ctx.strokeStyle = "#22d3ee";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 28px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(btn.label, btn.x + btn.w / 2, btn.y + btn.h / 2 + 1);
    ctx.textBaseline = "alphabetic";
  }

  _drawPreview(ctx, assets) {
    const stage = this._stage();
    const ch = this.selected;
    const unlocked = this.isUnlocked();
    roundRect(ctx, stage.x, stage.y, stage.w, stage.h, 12);
    ctx.fillStyle = "#0b1220";
    ctx.fill();
    ctx.strokeStyle = this._lockFlash > 0 ? "#ef4444" : "#22d3ee";
    ctx.lineWidth = 2;
    ctx.stroke();

    const baseline = stage.y + stage.h - 148;
    ctx.strokeStyle = "rgba(232, 184, 74, 0.35)";
    ctx.beginPath();
    ctx.moveTo(stage.x + 40, baseline);
    ctx.lineTo(stage.x + stage.w - 40, baseline);
    ctx.stroke();

    const originX = stage.x + stage.w / 2;
    const scale = Math.min((stage.w - 80) / 256, (stage.h - 220) / 256);
    ctx.save();
    ctx.translate(originX, baseline);
    ctx.scale(scale, scale);
    if (!unlocked) ctx.globalAlpha = 0.22;
    this.preview.flip = false;
    this.preview.draw(ctx, 0, 0, (g, rw, rh) => {
      g.fillStyle = ch.color;
      g.fillRect(-rw * 0.18, -rh * 0.72, rw * 0.36, rh * 0.72);
      g.fillStyle = "#071018";
      g.font = "bold 28px sans-serif";
      g.textAlign = "center";
      g.fillText(ch.initials, 0, -rh * 0.4);
    });
    ctx.restore();

    if (!this.preview.image) {
      const kit = assets?.characterKit(ch.id);
      const portrait = kit?.portraitImage;
      if (portrait) {
        ctx.save();
        if (!unlocked) ctx.globalAlpha = 0.28;
        drawContainedImage(ctx, portrait, stage.x + 80, stage.y + 36, stage.w - 160, stage.h - 220);
        ctx.restore();
      }
    }

    if (!unlocked) {
      ctx.fillStyle = "rgba(8, 12, 20, 0.55)";
      ctx.fillRect(stage.x + 8, stage.y + 8, stage.w - 16, stage.h - 16);
      ctx.fillStyle = "#ef4444";
      ctx.font = "bold 36px sans-serif";
      ctx.fillText("LOCKED", originX, stage.y + 88);
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "18px sans-serif";
      ctx.fillText(characterUnlockRequirement(ch.id) || "Unavailable", originX, stage.y + 124);
    }

    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 32px sans-serif";
    ctx.fillText(String(ch.displayName || ch.name).toUpperCase(), originX, stage.y + stage.h - 78);
    ctx.fillStyle = "#e8b84a";
    ctx.font = "18px sans-serif";
    ctx.fillText(ch.role || "", originX, stage.y + stage.h - 44);
  }

  _drawInfo(ctx, assets) {
    const unlocked = this.isUnlocked();
    const ch = this.selected;
    const weapon = weaponSelectCopy(ch.weapon);
    const power = abilityMenuInfo(ch.specialAbility);
    this._drawCard(ctx, {
      x: 900,
      y: 128,
      w: 460,
      h: 300,
      kicker: "WEAPON",
      title: unlocked ? weapon.name.toUpperCase() : "????",
      lines: unlocked
        ? [weapon.category, weapon.damageText, weapon.rangeText, weapon.fireText]
        : ["Hidden until unlocked"],
      image: unlocked ? this._weaponImages.get(weapon.id) : null,
      sheet: assets?.sheet("player_weapons"),
      frame: weapon.frame,
      accent: "#22d3ee",
    });
    this._drawCard(ctx, {
      x: 1388,
      y: 128,
      w: 460,
      h: 300,
      kicker: "SPECIAL POWER",
      title: unlocked ? (power.implemented ? power.name.toUpperCase() : "COMING SOON") : "????",
      lines: unlocked
        ? power.implemented
          ? [power.description, power.resource]
          : ["This special power is not available yet."]
        : ["Hidden until unlocked"],
      image: unlocked ? this._abilityImages.get(power.id) : null,
      accent: "#e8b84a",
    });
    this._drawStats(ctx, unlocked);
  }

  _drawCard(ctx, opts) {
    const pad = 22;
    const textX = opts.x + 160;
    const textMax = opts.x + opts.w - pad - textX;
    roundRect(ctx, opts.x, opts.y, opts.w, opts.h, 10);
    ctx.fillStyle = "#121a28";
    ctx.fill();
    ctx.strokeStyle = opts.accent || "#334155";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.save();
    roundRect(ctx, opts.x, opts.y, opts.w, opts.h, 10);
    ctx.clip();
    ctx.textAlign = "left";
    ctx.fillStyle = opts.accent || "#7dd3fc";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText(opts.kicker, opts.x + pad, opts.y + 28);
    const imgBox = { x: opts.x + pad, y: opts.y + 44, w: 120, h: 120 };
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(imgBox.x, imgBox.y, imgBox.w, imgBox.h);
    ctx.strokeStyle = "#334155";
    ctx.strokeRect(imgBox.x + 0.5, imgBox.y + 0.5, imgBox.w - 1, imgBox.h - 1);
    const drawn =
      drawContainedImage(ctx, opts.image, imgBox.x + 8, imgBox.y + 8, imgBox.w - 16, imgBox.h - 16) ||
      drawSheetFrame(ctx, opts.sheet, opts.frame || 0, imgBox.x + 8, imgBox.y + 8, imgBox.w - 16, imgBox.h - 16);
    if (!drawn) {
      ctx.fillStyle = "#475569";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("NO IMAGE", imgBox.x + imgBox.w / 2, imgBox.y + imgBox.h / 2 + 4);
    }
    ctx.textAlign = "left";
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 20px sans-serif";
    const titleLines = wrapText(ctx, opts.title, textMax);
    titleLines.forEach((line, i) => {
      ctx.fillText(line, textX, opts.y + 68 + i * 24);
    });
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "15px sans-serif";
    const body = [];
    for (const line of opts.lines || []) body.push(...wrapText(ctx, line, textMax));
    const bodyStart = opts.y + 68 + titleLines.length * 24 + 8;
    body.forEach((line, i) => {
      ctx.fillText(line, textX, bodyStart + i * 22);
    });
    ctx.restore();
  }

  _drawStats(ctx, unlocked) {
    const x = 900;
    const y = 452;
    const w = 948;
    const h = 420;
    roundRect(ctx, x, y, w, h, 10);
    ctx.fillStyle = "#121a28";
    ctx.fill();
    ctx.strokeStyle = "#e8b84a";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#e8b84a";
    ctx.font = "bold 14px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("STATISTICS", x + 22, y + 28);
    if (!unlocked) {
      ctx.fillStyle = "#94a3b8";
      ctx.font = "18px sans-serif";
      ctx.fillText("Unknown until unlocked", x + 22, y + 72);
      return;
    }
    STAT_ORDER.forEach(([key, label], i) => {
      const rowY = y + 58 + i * 54;
      const value = Math.max(1, Math.min(5, Math.round(this._bars[key] || 1)));
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 16px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(label, x + 22, rowY);
      ctx.fillStyle = "#94a3b8";
      ctx.font = "14px sans-serif";
      ctx.fillText(String(value), x + 168, rowY);
      for (let s = 0; s < 5; s += 1) {
        const bx = x + 210 + s * 138;
        const by = rowY - 18;
        ctx.fillStyle = s < value ? "#22d3ee" : "#1f2937";
        ctx.fillRect(bx, by, 118, 22);
        ctx.strokeStyle = "#0f172a";
        ctx.strokeRect(bx + 0.5, by + 0.5, 117, 21);
      }
    });
  }
}
