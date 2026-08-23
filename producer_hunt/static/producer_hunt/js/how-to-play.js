/** Paged How to Play guide. Reads live registries; does not duplicate combat values. */

import { DESIGN_H, DESIGN_W, DEFAULT_KEYMAP } from "./config.js";
import { CHARACTERS, characterSelectStats, weaponSelectCopy } from "./characters.js";
import { PLAYER_WEAPON_DEFS, PLAYER_WEAPON_IDS } from "./player-weapons.js";
import { abilityMenuInfo } from "./abilities.js";
import { PICKUP_DEFS } from "./pickups.js";
import { ENEMY_TYPES } from "./enemy.js";
import { BOSS_01 } from "./combat.js";
import { HAZARD_DEFS } from "./progression.js";
import { drawButtons, hitButton, hitMenu } from "./ui.js";
import {
  drawSheetFrame,
  HUD_FRAMES,
  HAZARD_FRAMES,
  PROGRESSION_FRAMES,
} from "./asset-catalog.js";

export const GUIDE_SECTIONS = [
  { id: "basics", title: "Basics" },
  { id: "controls", title: "Controls" },
  { id: "characters", title: "Characters" },
  { id: "weapons", title: "Weapons" },
  { id: "powers", title: "Special Powers" },
  { id: "pickups", title: "Pickups" },
  { id: "enemies", title: "Enemies" },
  { id: "boss", title: "Boss Battles" },
  { id: "hazards", title: "Hazards" },
  { id: "hud", title: "HUD" },
  { id: "checkpoints", title: "Checkpoints and Death" },
  { id: "winning", title: "Winning a Level" },
];

export const GUIDE_IMAGES = {
  editor: { kit: "character", id: "editor", anim: "idle" },
  assistant: { kit: "character", id: "assistant", anim: "idle" },
  colorist: { kit: "character", id: "colorist", anim: "idle" },
  vfx_supervisor: { kit: "character", id: "vfx_supervisor", anim: "idle" },
  post_producer: { kit: "enemy", id: "post_producer", anim: "idle" },
  client: { kit: "enemy", id: "client", anim: "idle" },
  boss01: { kit: "enemy", id: "boss_01", anim: "idle" },
  health: { sheet: "pickups", frame: 0 },
  energy: { sheet: "pickups", frame: 1 },
  token: { sheet: "pickups", frame: 2 },
  key: { sheet: "pickups", frame: 4 },
  bonus: { sheet: "pickups", frame: 7 },
  charge: { sheet: "pickups", frame: 5 },
  checkpoint: { sheet: "progression", frame: PROGRESSION_FRAMES.checkpoint },
  door: { sheet: "progression", frame: PROGRESSION_FRAMES.door_closed },
  exit: { sheet: "progression", frame: PROGRESSION_FRAMES.exit_open },
};

const CHAR_BLURB = {
  editor: "Balanced and reliable.",
  assistant: "Fast movement and rapid fire, but lower durability.",
  colorist: "High damage and powerful area attacks, but slower movement.",
  vfx_supervisor: "High health and defense with sustained special damage, but slower speed.",
};

const ENEMY_COPY = {
  post_producer: {
    attack: "Ranged deadline shots from shoulder height.",
    threat: "Medium",
    tactic: "Keep moving and attack between shots.",
  },
  colorist: {
    attack: "Close-range color blast and a short shoulder charge.",
    threat: "High",
    tactic: "Back away during the wind-up, then punish recovery.",
  },
  vfx_supervisor: {
    attack: "Arcing VFX shots that leave a brief hazard pool.",
    threat: "High",
    tactic: "Prioritize this enemy, then leave the marked ground.",
  },
  client: {
    attack: "Fast complaint shots and occasional marked danger zones.",
    threat: "Elite",
    tactic: "Watch attack telegraphs and do not stand in the mark.",
  },
};

const HAZARD_COPY = {
  live_cable: { name: "Live Cable", avoid: "Jump over it or stay out of the sparking area." },
  steam_vent: { name: "Steam Vent", avoid: "Watch the warning puff, then step aside before the jet." },
  electrical_floor: { name: "Electrical Floor", avoid: "Leave the cyan strip when the panel sparks." },
  falling_light: { name: "Falling Studio Light", avoid: "Move out of the ground marker before the fixture drops." },
  camera_rig: { name: "Camera Rig", avoid: "Ride the track or wait at the ends. It will not crush you." },
  rolling_cart: { name: "Equipment Cart", avoid: "Heed the warning light, then jump the rolling cart." },
  hot_light: { name: "Hot Studio Light", avoid: "Do not stand under the heated lamp." },
  falling_cases: { name: "Falling Cases", avoid: "Watch for the warning, then move out of the marked area." },
  electrical_panel: { name: "Electrical Panel", avoid: "Keep clear of the charged cabinet." },
  cracked_monitor: { name: "Cracked Monitor", avoid: "Avoid the sparking screen on contact." },
};

const PICKUP_GUIDE = {
  health: {
    name: "Health",
    category: "Recovery",
    note: "Restores player health. Cannot increase health above the character’s maximum.",
  },
  energy: {
    name: "Energy",
    category: "Recovery",
    note: "Restores energy used by special powers and also restores ammunition.",
  },
  production_token: {
    name: "Production Token",
    category: "Score",
    note: "Adds to level rewards and the production-token count.",
  },
  access_key: {
    name: "Access Key",
    category: "Progression",
    note: "Unlocks required studio doors.",
  },
  bonus: {
    name: "Bonus",
    category: "Score",
    note: "Awards additional score.",
  },
  ability_charge: {
    name: "Ability Charge",
    category: "Combat",
    note: "Immediately refreshes the special-power cooldown.",
  },
  ammo: {
    name: "Ammo",
    category: "Combat",
    note: "Adds ammunition to the active limited weapon. Does not apply to the pistol.",
  },
  machine_gun: {
    name: "Machine Gun",
    category: "Combat",
    note: "Equips the machine gun or adds ammunition if you already have it.",
  },
  shotgun: {
    name: "Shotgun",
    category: "Combat",
    note: "Equips the shotgun or adds shells if you already have it.",
  },
  heavy_blaster: {
    name: "Heavy Blaster",
    category: "Combat",
    note: "Equips the heavy blaster or adds charges if you already have it.",
  },
};

const CATEGORY_ORDER = ["Recovery", "Combat", "Progression", "Score"];

let _missingWarned = new Set();

function warnMissing(key) {
  if (_missingWarned.has(key)) return;
  _missingWarned.add(key);
  console.warn(`[Producer Hunt] How to Play image missing: ${key}`);
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

function wrapLines(ctx, text, maxWidth) {
  const raw = String(text || "").trim();
  if (!raw) return [];
  const words = raw.split(/\s+/);
  const lines = [];
  let cur = "";
  for (const word of words) {
    const next = cur ? `${cur} ${word}` : word;
    if (ctx.measureText(next).width <= maxWidth) cur = next;
    else {
      if (cur) lines.push(cur);
      cur = word;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

function drawPanel(ctx, x, y, w, h, accent = "#334155") {
  roundRect(ctx, x, y, w, h, 10);
  ctx.fillStyle = "#121a28";
  ctx.fill();
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  ctx.stroke();
}

function drawPlaceholder(ctx, x, y, w, h) {
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "#334155";
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
  ctx.fillStyle = "#475569";
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("NO IMAGE", x + w / 2, y + h / 2 + 4);
}

function drawClipFrame(ctx, clip, x, y, size) {
  if (!clip?.image) return false;
  const fw = clip.frameWidth || 256;
  const fh = clip.frameHeight || 256;
  const scale = Math.min(size / fw, size / fh);
  const dw = fw * scale;
  const dh = fh * scale;
  ctx.drawImage(clip.image, 0, 0, fw, fh, x + (size - dw) / 2, y + (size - dh) / 2, dw, dh);
  return true;
}

function drawFramed(ctx, x, y, w, h, drawer) {
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "#22d3ee";
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
  ctx.save();
  ctx.beginPath();
  ctx.rect(x + 2, y + 2, w - 4, h - 4);
  ctx.clip();
  const ok = drawer();
  ctx.restore();
  if (!ok) drawPlaceholder(ctx, x, y, w, h);
  return ok;
}

function formatCodes(codes) {
  return (codes || []).map((c) => {
    if (c.startsWith("Key")) return c.slice(3);
    if (c === "ArrowLeft") return "←";
    if (c === "ArrowRight") return "→";
    if (c === "ArrowUp") return "↑";
    if (c === "ArrowDown") return "↓";
    if (c === "Space") return "Space";
    if (c === "Escape") return "Esc";
    if (c === "Enter") return "Enter";
    if (c.startsWith("Shift")) return "Shift";
    return c;
  }).join("  /  ");
}

function drawKeycap(ctx, label, x, y, w = 86, h = 36) {
  ctx.fillStyle = "#172033";
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = "#22d3ee";
  ctx.lineWidth = 2;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
  ctx.fillStyle = "#f4f1ea";
  ctx.font = "bold 14px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(label, x + w / 2, y + h / 2 + 5);
}

function drawStatBar(ctx, x, y, value) {
  for (let s = 0; s < 5; s += 1) {
    ctx.fillStyle = s < value ? "#22d3ee" : "#1f2937";
    ctx.fillRect(x + s * 22, y, 18, 10);
  }
}

function enabledPickups() {
  return Object.values(PICKUP_DEFS).filter((d) => d && !d.reserved && d.effect !== "none" && d.effect !== "vehicle_repair");
}

function enabledHazards() {
  const ids = ["steam_vent", "electrical_floor", "falling_light", "camera_rig", "rolling_cart", "live_cable"];
  return ids.map((id) => HAZARD_DEFS[id]).filter((d) => d && d.enabled && !d.reserved);
}

function enabledEnemies() {
  return ["post_producer", "colorist", "vfx_supervisor", "client"].map((id) => ENEMY_TYPES[id]).filter(Boolean);
}

export class HowToPlay {
  constructor() {
    this.page = 0;
    this.from = "menu";
    this.open = false;
  }

  enter(from = "menu") {
    this.from = from;
    this.open = true;
  }

  leave() {
    this.open = false;
  }

  get section() {
    return GUIDE_SECTIONS[this.page] || GUIDE_SECTIONS[0];
  }

  sidebar() {
    return GUIDE_SECTIONS.map((s, i) => ({
      id: `page:${i}`,
      label: s.title,
      index: i,
      x: 48,
      y: 128 + i * 62,
      w: 280,
      h: 52,
    }));
  }

  footerButtons() {
    return [
      { id: "PREV", label: "PREVIOUS", x: 360, y: 1008, w: 220, h: 48 },
      { id: "NEXT", label: "NEXT", x: 600, y: 1008, w: 220, h: 48 },
      { id: "BACK", label: "BACK TO MENU", x: 1540, y: 1008, w: 332, h: 48 },
    ];
  }

  setPage(i) {
    const n = GUIDE_SECTIONS.length;
    this.page = ((i % n) + n) % n;
  }

  handleAction(id) {
    if (id === "PREV") {
      this.setPage(this.page - 1);
      return "nav";
    }
    if (id === "NEXT") {
      this.setPage(this.page + 1);
      return "nav";
    }
    if (id === "BACK") return "back";
    if (String(id).startsWith("page:")) {
      this.setPage(Number(String(id).slice(5)));
      return "nav";
    }
    return null;
  }

  handleClick(x, y) {
    const side = this.sidebar().find((b) => hitButton(b, x, y));
    if (side) return this.handleAction(side.id);
    const hit = hitMenu(this.footerButtons(), x, y);
    if (hit) return this.handleAction(hit.id);
    return null;
  }

  handleInput(input) {
    if (input.consume("pause")) return "back";
    if (input.consume("moveLeft")) return this.handleAction("PREV");
    if (input.consume("moveRight") || input.consume("confirm")) return this.handleAction("NEXT");
    if (input.consume("jump")) return this.handleAction("PREV");
    if (input.consume("crouch")) return this.handleAction("NEXT");
    return null;
  }

  async preload(assets) {
    if (!assets?.loadOptionalImage) return;
    for (const ch of CHARACTERS) {
      const power = abilityMenuInfo(ch.specialAbility);
      if (power.image) await assets.loadOptionalImage(`guide-ability:${power.id}`, power.image);
    }
  }

  draw(ctx, assets, keymap = DEFAULT_KEYMAP) {
    ctx.fillStyle = "rgba(5, 7, 12, 0.88)";
    ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
    drawPanel(ctx, 32, 24, 1856, 1032, "#22d3ee");

    ctx.textAlign = "left";
    ctx.fillStyle = "#e8b84a";
    ctx.font = "bold 36px sans-serif";
    ctx.fillText("HOW TO PLAY", 56, 72);
    ctx.fillStyle = "#94a3b8";
    ctx.font = "16px sans-serif";
    ctx.fillText(`Page ${this.page + 1} / ${GUIDE_SECTIONS.length}`, 1680, 68);

    this._drawSidebar(ctx);
    ctx.save();
    ctx.beginPath();
    ctx.rect(348, 104, 1524, 880);
    ctx.clip();
    this._drawPage(ctx, assets, keymap);
    ctx.restore();

    drawButtons(ctx, this.footerButtons(), { focus: -1 });
  }

  _drawSidebar(ctx) {
    this.sidebar().forEach((b, i) => {
      const on = i === this.page;
      ctx.fillStyle = on ? "#1b3a4a" : "#172033";
      ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.strokeStyle = on ? "#22d3ee" : "#334155";
      ctx.lineWidth = on ? 3 : 1;
      ctx.strokeRect(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1);
      ctx.fillStyle = on ? "#f4f1ea" : "#94a3b8";
      ctx.font = on ? "bold 16px sans-serif" : "15px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(`${i + 1}.  ${b.label}`, b.x + 16, b.y + 32);
    });
  }

  _drawPage(ctx, assets, keymap) {
    const id = this.section.id;
    if (id === "basics") this._drawBasics(ctx, assets);
    else if (id === "controls") this._drawControls(ctx, keymap);
    else if (id === "characters") this._drawCharacters(ctx, assets);
    else if (id === "weapons") this._drawWeapons(ctx, assets);
    else if (id === "powers") this._drawPowers(ctx, assets);
    else if (id === "pickups") this._drawPickups(ctx, assets);
    else if (id === "enemies") this._drawEnemies(ctx, assets);
    else if (id === "boss") this._drawBoss(ctx, assets);
    else if (id === "hazards") this._drawHazards(ctx, assets);
    else if (id === "hud") this._drawHud(ctx, assets);
    else if (id === "checkpoints") this._drawCheckpoints(ctx, assets);
    else this._drawWinning(ctx, assets);
  }

  _heading(ctx, text, x = 372, y = 148) {
    ctx.fillStyle = "#e8b84a";
    ctx.font = "bold 28px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(text, x, y);
  }

  _body(ctx, text, x, y, maxW) {
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "18px sans-serif";
    ctx.textAlign = "left";
    const lines = wrapLines(ctx, text, maxW);
    lines.forEach((line, i) => ctx.fillText(line, x, y + i * 26));
    return lines.length;
  }

  _kitClip(assets, kind, id, anim) {
    const kit = kind === "character" ? assets?.characterKit?.(id) : assets?.enemyKit?.(id);
    return kit?.animations?.[anim] || kit?.animations?.idle || null;
  }

  _drawSpec(ctx, assets, spec, x, y, size, key) {
    return drawFramed(ctx, x, y, size, size, () => {
      if (!spec) {
        warnMissing(key || "unknown");
        return false;
      }
      if (spec.kit) {
        const ok = drawClipFrame(ctx, this._kitClip(assets, spec.kit, spec.id, spec.anim), x, y, size);
        if (!ok) warnMissing(key || spec.id);
        return ok;
      }
      if (spec.sheet) {
        const ok = drawSheetFrame(ctx, assets?.sheet(spec.sheet), spec.frame || 0, x + 8, y + 8, size - 16, size - 16);
        if (!ok) warnMissing(key || spec.sheet);
        return ok;
      }
      if (spec.image) {
        const img = assets?.get?.(spec.image);
        if (!img) {
          warnMissing(spec.image);
          return false;
        }
        const s = Math.min((size - 16) / img.width, (size - 16) / img.height);
        ctx.drawImage(img, x + (size - img.width * s) / 2, y + (size - img.height * s) / 2, img.width * s, img.height * s);
        return true;
      }
      return false;
    });
  }

  _drawBasics(ctx, assets) {
    this._heading(ctx, "The job");
    const lines = [
      "Fight through each studio.",
      "Defeat enemy waves.",
      "Collect useful pickups.",
      "Reach checkpoints.",
      "Survive the boss battle.",
      "Complete the level and unlock the next studio.",
    ];
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "20px sans-serif";
    lines.forEach((line, i) => ctx.fillText(`•  ${line}`, 372, 200 + i * 36));
    const tiles = [
      ["Player", GUIDE_IMAGES.editor],
      ["Enemy", GUIDE_IMAGES.post_producer],
      ["Pickup", GUIDE_IMAGES.health],
      ["Boss", GUIDE_IMAGES.boss01],
      ["Exit", GUIDE_IMAGES.exit],
    ];
    tiles.forEach(([label, spec], i) => {
      const x = 372 + i * 290;
      this._drawSpec(ctx, assets, spec, x, 460, 220, label);
      ctx.fillStyle = "#94a3b8";
      ctx.font = "bold 16px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, x + 110, 710);
    });
  }

  _drawControls(ctx, keymap) {
    this._heading(ctx, "Keyboard");
    const rows = [
      ["MOVE", formatCodes([...(keymap.moveLeft || []), ...(keymap.moveRight || [])])],
      ["JUMP", formatCodes(keymap.jump)],
      ["CROUCH", formatCodes(keymap.crouch)],
      ["SHOOT", formatCodes(keymap.shoot)],
      ["WEAPON 1-4", formatCodes([...(keymap.weapon1 || []), ...(keymap.weapon2 || []), ...(keymap.weapon3 || []), ...(keymap.weapon4 || [])])],
      ["CYCLE WEAPON", formatCodes(keymap.weaponCycle)],
      ["SPECIAL POWER", formatCodes(keymap.special)],
      ["RESCUE / VEHICLE", formatCodes(keymap.interact || keymap.confirm)],
      ["PAUSE", formatCodes(keymap.pause)],
      ["CONFIRM", formatCodes(keymap.confirm)],
    ];
    rows.forEach((row, i) => {
      const y = 196 + i * 70;
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 18px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(row[0], 372, y + 24);
      drawKeycap(ctx, row[1], 640, y, 420, 40);
    });
    this._heading(ctx, "Gamepad", 1120, 148);
    const pad = [
      ["MOVE", "Left stick / D-pad"],
      ["JUMP", "A  /  D-pad Up"],
      ["CROUCH", "D-pad Down"],
      ["SHOOT", "X"],
      ["CYCLE WEAPON", "LB"],
      ["SPECIAL POWER", "RB / RT"],
      ["RESCUE / VEHICLE", "Y"],
      ["PAUSE", "B / Start"],
      ["CONFIRM", "A"],
    ];
    pad.forEach((row, i) => {
      const y = 196 + i * 70;
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 18px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(row[0], 1120, y + 24);
      drawKeycap(ctx, row[1], 1388, y, 360, 40);
    });
  }

  _drawCharacters(ctx, assets) {
    this._heading(ctx, "Playable crew");
    CHARACTERS.forEach((ch, i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = 372 + col * 740;
      const y = 176 + row * 400;
      drawPanel(ctx, x, y, 700, 372, ch.accent || "#22d3ee");
      this._drawSpec(ctx, assets, GUIDE_IMAGES[ch.id], x + 20, y + 20, 160, ch.id);
      const stats = characterSelectStats(ch);
      const power = abilityMenuInfo(ch.specialAbility);
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(ch.displayName, x + 200, y + 48);
      ctx.fillStyle = "#e8b84a";
      ctx.font = "16px sans-serif";
      ctx.fillText(ch.role, x + 200, y + 76);
      ctx.fillStyle = "#cbd5e1";
      ctx.fillText(`Weapon  ${ch.weapon?.name || "—"}`, x + 200, y + 108);
      ctx.fillText(`Power  ${power.name}`, x + 200, y + 134);
      const bars = [
        ["Health", stats.health],
        ["Damage", stats.damage],
        ["Speed", stats.speed],
        ["Fire rate", stats.fireRate],
        ["Defense", stats.defense],
        ["Special", stats.special],
      ];
      bars.forEach((b, bi) => {
        const by = y + 168 + bi * 24;
        ctx.fillStyle = "#94a3b8";
        ctx.font = "14px sans-serif";
        ctx.fillText(b[0], x + 200, by);
        drawStatBar(ctx, x + 310, by - 12, b[1]);
      });
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "16px sans-serif";
      this._body(ctx, CHAR_BLURB[ch.id] || "", x + 20, y + 340, 660);
    });
  }

  _drawWeapons(ctx, assets) {
    this._heading(ctx, "Player weapons");
    this._body(ctx, "Damage and fire rate scale with the selected character. Press 1–4 to switch owned weapons, or E to cycle. Q remains the special power.", 372, 168, 1450);
    PLAYER_WEAPON_IDS.forEach((id, i) => {
      const def = PLAYER_WEAPON_DEFS[id];
      const x = 372 + (i % 2) * 740;
      const y = 220 + Math.floor(i / 2) * 390;
      drawPanel(ctx, x, y, 700, 360, "#22d3ee");
      drawFramed(ctx, x + 24, y + 36, 140, 140, () =>
        drawSheetFrame(ctx, assets?.sheet("player_weapons"), def.hudIcon || 0, x + 32, y + 44, 124, 124)
      );
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 24px sans-serif";
      ctx.fillText(def.displayName.toUpperCase(), x + 188, y + 64);
      ctx.fillStyle = "#e8b84a";
      ctx.font = "16px sans-serif";
      const ammoText = def.ammoType === "unlimited" ? "Unlimited ammo" : `Pickup ${def.pickupAmmo} ammo`;
      ctx.fillText(ammoText, x + 188, y + 94);
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "18px sans-serif";
      const lines = [
        def.automatic ? "Automatic" : "Semi-automatic",
        def.pelletCount > 1 ? `${def.pelletCount} pellets` : "Single projectile",
        def.splashRadius ? `Splash ${def.splashRadius}` : "No splash",
        `Interval ${(def.fireInterval * 1000).toFixed(0)} ms`,
      ];
      lines.forEach((line, li) => ctx.fillText(line, x + 188, y + 132 + li * 28));
      const tip =
        id === "pistol"
          ? "Default fallback. Always available."
          : id === "machine_gun"
            ? "Hold fire for a stream with light spread."
            : id === "shotgun"
              ? "Strong at close range. Pellets are limited against bosses."
              : "Heavy impact with area damage. Does not hurt you.";
      this._body(ctx, tip, x + 24, y + 300, 650);
    });
  }

  _drawPowers(ctx, assets) {
    this._heading(ctx, "Special powers");
    this._body(ctx, "Special powers consume energy and may have a cooldown. The power cannot activate when energy is insufficient or the cooldown is active. Press Q (or RB / RT on a gamepad).", 372, 186, 1450);
    CHARACTERS.forEach((ch, i) => {
      const power = abilityMenuInfo(ch.specialAbility);
      const x = 372 + (i % 2) * 740;
      const y = 250 + Math.floor(i / 2) * 360;
      drawPanel(ctx, x, y, 700, 336, "#e8b84a");
      const img = assets?.get?.(`guide-ability:${power.id}`);
      drawFramed(ctx, x + 20, y + 20, 120, 120, () => {
        if (!img) {
          warnMissing(power.image || power.id);
          return false;
        }
        const s = Math.min(104 / img.width, 104 / img.height);
        ctx.drawImage(img, x + 28 + (104 - img.width * s) / 2, y + 28 + (104 - img.height * s) / 2, img.width * s, img.height * s);
        return true;
      });
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(power.name, x + 160, y + 52);
      ctx.fillStyle = "#e8b84a";
      ctx.font = "16px sans-serif";
      ctx.fillText(ch.displayName, x + 160, y + 80);
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "16px sans-serif";
      this._body(ctx, power.description, x + 160, y + 112, 500);
      ctx.fillText(`Duration  ${power.duration || 0}s`, x + 160, y + 200);
      ctx.fillText(`Cooldown  ${power.cooldown || 0}s`, x + 160, y + 228);
      ctx.fillText(`Energy  ${power.energyCost || 0}`, x + 160, y + 256);
      ctx.fillText("Activate  Q  /  RB", x + 160, y + 284);
    });
  }

  _drawPickups(ctx, assets) {
    this._heading(ctx, "Pickups in circulation");
    const items = enabledPickups()
      .map((def) => ({ def, copy: PICKUP_GUIDE[def.id] }))
      .filter((row) => row.copy)
      .sort((a, b) => CATEGORY_ORDER.indexOf(a.copy.category) - CATEGORY_ORDER.indexOf(b.copy.category));
    items.forEach((row, i) => {
      const col = i % 3;
      const r = Math.floor(i / 3);
      const x = 372 + col * 490;
      const y = 180 + r * 380;
      drawPanel(ctx, x, y, 468, 350, "#22d3ee");
      drawFramed(ctx, x + 24, y + 24, 96, 96, () =>
        drawSheetFrame(ctx, assets?.sheet("pickups"), row.def.sprite_frame, x + 32, y + 32, 80, 80)
      );
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(row.copy.name, x + 140, y + 56);
      ctx.fillStyle = "#e8b84a";
      ctx.font = "14px sans-serif";
      ctx.fillText(row.copy.category.toUpperCase(), x + 140, y + 82);
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(row.def.effect === "score" || row.def.effect === "health" || row.def.effect === "energy" ? `Value  ${row.def.value}` : row.def.effect, x + 140, y + 108);
      this._body(ctx, row.copy.note, x + 24, y + 150, 420);
    });
  }

  _drawEnemies(ctx, assets) {
    this._heading(ctx, "Studio 01 opposition");
    enabledEnemies().forEach((en, i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = 372 + col * 740;
      const y = 180 + row * 360;
      const copy = ENEMY_COPY[en.id] || {};
      drawPanel(ctx, x, y, 700, 340, en.accent || "#fb7185");
      this._drawSpec(ctx, assets, GUIDE_IMAGES[en.id], x + 24, y + 24, 140, en.id);
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 24px sans-serif";
      ctx.fillText(en.name.toUpperCase(), x + 188, y + 56);
      ctx.fillStyle = "#e8b84a";
      ctx.font = "16px sans-serif";
      ctx.fillText(`Threat  ${copy.threat || "Medium"}`, x + 188, y + 86);
      this._body(ctx, copy.attack, x + 188, y + 118, 480);
      this._body(ctx, copy.tactic, x + 24, y + 250, 650);
    });
  }

  _drawBoss(ctx, assets) {
    this._heading(ctx, `${BOSS_01.displayName}`);
    ctx.fillStyle = "#e8b84a";
    ctx.font = "20px sans-serif";
    ctx.fillText(BOSS_01.title, 372, 186);
    this._drawSpec(ctx, assets, GUIDE_IMAGES.boss01, 372, 210, 280, "boss01");
    const tools = [
      ["Straight razor", "boss_01_razor"],
      ["Scissors", "boss_01_scissors"],
      ["Electric clippers", "boss_01_clippers"],
      ["Barber brush", "boss_01_brush"],
    ];
    tools.forEach((tool, i) => {
      const x = 700 + (i % 2) * 420;
      const y = 210 + Math.floor(i / 2) * 200;
      drawFramed(ctx, x, y, 120, 120, () => drawSheetFrame(ctx, assets?.sheet(tool[1]), 0, x + 8, y + 8, 104, 104));
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 18px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(tool[0], x + 140, y + 68);
    });
    const notes = [
      "Boss battles begin after the introduction cinematic.",
      "Watch attack telegraphs.",
      "Avoid thrown barber tools.",
      "Move away during the charge.",
      "Keep distance from the brush attack.",
      "At 50% health, Boss 1 enters a faster and more aggressive second phase.",
      "Dying at the boss checkpoint resumes the fight. The introduction does not replay if it was already watched.",
    ];
    notes.forEach((line, i) => {
      ctx.fillStyle = i === notes.length - 1 ? "#f87171" : "#cbd5e1";
      ctx.font = "18px sans-serif";
      ctx.fillText(`•  ${line}`, 372, 540 + i * 32);
    });
  }

  _drawHazards(ctx, assets) {
    this._heading(ctx, "Studio hazards");
    ctx.fillStyle = "#f87171";
    ctx.font = "16px sans-serif";
    ctx.fillText("Contact with an active hazard deals damage. Treat marked areas as live.", 372, 186);
    enabledHazards().forEach((hz, i) => {
      const col = i % 3;
      const r = Math.floor(i / 3);
      const x = 372 + col * 490;
      const y = 210 + r * 360;
      const copy = HAZARD_COPY[hz.id] || { name: hz.id, avoid: "Stay out of the hit box." };
      drawPanel(ctx, x, y, 468, 330, "#ef4444");
      drawFramed(ctx, x + 24, y + 24, 120, 120, () =>
        drawSheetFrame(ctx, assets?.sheet("hazards"), HAZARD_FRAMES[hz.id] ?? hz.sprite_frame, x + 32, y + 32, 104, 104)
      );
      ctx.textAlign = "left";
      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(copy.name.toUpperCase(), x + 160, y + 64);
      ctx.fillStyle = "#f87171";
      ctx.font = "14px sans-serif";
      ctx.fillText("CONTACT DAMAGE", x + 160, y + 92);
      this._body(ctx, copy.avoid, x + 24, y + 170, 420);
    });
  }

  _drawHud(ctx, assets) {
    this._heading(ctx, "What the HUD shows");
    const items = [
      ["Health", HUD_FRAMES.health, "Current and maximum hit points."],
      ["Energy", HUD_FRAMES.energy, "Special-power resource. Regenerates over time."],
      ["Score", HUD_FRAMES.score, "Points from combat, tokens and bonuses."],
      ["Ammo", HUD_FRAMES.ammo, "Weapon ammunition remaining."],
      ["Objective", HUD_FRAMES.objective, "Current studio goal and wave counts."],
      ["Special", HUD_FRAMES.energy, "Power name and cooldown when it is not ready."],
    ];
    items.forEach((item, i) => {
      const col = i % 2;
      const r = Math.floor(i / 2);
      const x = 372 + col * 740;
      const y = 190 + r * 230;
      drawPanel(ctx, x, y, 700, 200, "#22d3ee");
      drawFramed(ctx, x + 24, y + 36, 72, 72, () =>
        drawSheetFrame(ctx, assets?.sheet("hud"), item[1], x + 32, y + 44, 56, 56)
      );
      ctx.textAlign = "left";
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(`${i + 1}.  ${item[0]}`, x + 120, y + 70);
      this._body(ctx, item[2], x + 120, y + 110, 540);
    });
    ctx.fillStyle = "#94a3b8";
    ctx.font = "16px sans-serif";
    ctx.fillText("During a boss fight a separate health bar shows Essam Salama’s remaining health and phase.", 372, 920);
  }

  _drawCheckpoints(ctx, assets) {
    this._heading(ctx, "Checkpoints and death");
    this._drawSpec(ctx, assets, GUIDE_IMAGES.checkpoint, 372, 180, 180, "checkpoint");
    const lines = [
      "Checkpoints save your restart position, character, ammo, keys, score and collected pickups.",
      "There is no lives counter. After you die, choose Resume from Checkpoint or Restart Level.",
      "Resume restores health to the checkpoint value (at least 1) and reapplies wave progress from that snapshot.",
      "At the boss checkpoint the introduction normally does not replay after death.",
      "A full level restart begins from the start and resets encounters, pickups and the boss fight.",
      "Character selection is kept. Music follows the restored studio or boss state.",
    ];
    lines.forEach((line, i) => this._body(ctx, line, 580, 210 + i * 70, 1200));
  }

  _drawWinning(ctx, assets) {
    this._heading(ctx, "Studio 01 flow");
    const steps = [
      ["Enter the studio.", GUIDE_IMAGES.editor],
      ["Clear all enemy waves.", GUIDE_IMAGES.post_producer],
      ["Collect the access key.", GUIDE_IMAGES.key],
      ["Open the studio gate.", GUIDE_IMAGES.door],
      ["Reach the boss arena.", GUIDE_IMAGES.checkpoint],
      ["Watch or skip the boss introduction.", GUIDE_IMAGES.boss01],
      ["Defeat Essam Salama.", GUIDE_IMAGES.boss01],
      ["Reach the exit.", GUIDE_IMAGES.exit],
      ["View results and unlock progression.", GUIDE_IMAGES.bonus],
    ];
    steps.forEach((step, i) => {
      const col = i % 3;
      const r = Math.floor(i / 3);
      const x = 372 + col * 490;
      const y = 176 + r * 260;
      drawPanel(ctx, x, y, 468, 236, "#e8b84a");
      this._drawSpec(ctx, assets, step[1], x + 16, y + 40, 96, `win${i}`);
      ctx.textAlign = "left";
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 18px sans-serif";
      ctx.fillText(`${i + 1}`, x + 132, y + 48);
      this._body(ctx, step[0], x + 132, y + 80, 300);
    });
  }
}
