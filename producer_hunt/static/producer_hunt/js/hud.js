import { HUD_FRAMES, drawSheetFrame } from "./asset-catalog.js";

const MARGIN = 24;
const PORTRAIT = 72;

function drawContained(ctx, img, x, y, w, h) {
  const scale = Math.min(w / img.width, h / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

function icon(ctx, sheet, frame, x, y, size = 22) {
  const smooth = ctx.imageSmoothingEnabled;
  ctx.imageSmoothingEnabled = false;
  drawSheetFrame(ctx, sheet, frame, x, y, size, size);
  ctx.imageSmoothingEnabled = smooth;
}

export class HUD {
  constructor() {
    this._layer = document.createElement("canvas");
    this._layer.width = 640;
    this._layer.height = 300;
    this._sig = "";
  }

  invalidate() {
    this._sig = "";
  }

  signature({ player, score, assets, objective = "", wave = null, crew = null }) {
    const w = player.weapon;
    const ab = player.ability;
    const kit = assets?.characterKit(player.character.id);
    const portrait = kit?.portraitImage ? player.character.id : "placeholder";
    const cd = ab && !ab.ready ? Math.ceil(Math.max(0, ab.cool) * 10) : 0;
    return [
      player.character.id,
      portrait,
      Math.ceil(player.health),
      player.maxHealth,
      Math.ceil(player.energy || 0),
      player.energyMax || 0,
      w.id,
      w.ammo,
      w.maxAmmo,
      player.loadout?.currentId || "",
      player.notice?.text || "",
      score,
      player.keys || 0,
      ab?.ready ? 1 : 0,
      cd,
      player.alive ? 1 : 0,
      objective,
      wave?.index ?? 0,
      wave?.total ?? 0,
      wave?.living ?? 0,
      crew?.found ?? 0,
      crew?.total ?? 0,
    ].join("|");
  }

  draw(ctx, view) {
    const sig = this.signature(view);
    if (sig !== this._sig) {
      this._sig = sig;
      this._compose(this._layer.getContext("2d"), view);
    }
    ctx.drawImage(this._layer, 0, 0);
  }

  _compose(ctx, { player, score, assets, objective = "", wave = null, crew = null }) {
    ctx.clearRect(0, 0, this._layer.width, this._layer.height);

    const keys = player.keys || 0;
    const panelH = 268;
    ctx.fillStyle = "rgba(5, 7, 12, 0.62)";
    ctx.fillRect(MARGIN, MARGIN, 560, panelH);

    const kit = assets?.characterKit(player.character.id);
    const portrait = kit?.portraitImage;
    const px = MARGIN + 16;
    const py = MARGIN + 16;
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(px, py, PORTRAIT, PORTRAIT);
    if (portrait) {
      drawContained(ctx, portrait, px + 4, py + 4, PORTRAIT - 8, PORTRAIT - 8);
    } else {
      ctx.fillStyle = player.character.color;
      ctx.fillRect(px + 10, py + 10, PORTRAIT - 20, PORTRAIT - 20);
      ctx.fillStyle = "#071018";
      ctx.font = "bold 18px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(player.character.initials, px + PORTRAIT / 2, py + PORTRAIT / 2 + 6);
    }

    const sheet = assets?.sheet("hud");
    const textX = px + PORTRAIT + 16;
    ctx.textAlign = "left";
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 18px sans-serif";
    ctx.fillText(player.character.displayName || player.character.name, textX, MARGIN + 28);

    icon(ctx, sheet, HUD_FRAMES.health, textX, MARGIN + 38);
    const ratio = player.maxHealth ? Math.max(0, Math.min(1, player.health / player.maxHealth)) : 0;
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(textX + 28, MARGIN + 42, 214, 14);
    ctx.fillStyle = ratio > 0.3 ? "#4ade80" : "#f87171";
    ctx.fillRect(textX + 28, MARGIN + 42, 214 * ratio, 14);
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "13px sans-serif";
    ctx.fillText(`${Math.max(0, Math.ceil(player.health))} / ${player.maxHealth}`, textX + 250, MARGIN + 54);

    ctx.fillStyle = "#94a3b8";
    ctx.font = "13px sans-serif";
    ctx.fillText("EN", textX, MARGIN + 72);
    const eRatio = player.energyMax ? Math.max(0, Math.min(1, (player.energy || 0) / player.energyMax)) : 0;
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(textX + 28, MARGIN + 62, 214, 12);
    ctx.fillStyle = "#38bdf8";
    ctx.fillRect(textX + 28, MARGIN + 62, 214 * eRatio, 12);
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(`${Math.max(0, Math.ceil(player.energy || 0))} / ${player.energyMax || 0}`, textX + 250, MARGIN + 73);

    icon(ctx, sheet, HUD_FRAMES.score, textX, MARGIN + 84);
    ctx.fillStyle = "#f4f1ea";
    ctx.fillText(`${score}`, textX + 28, MARGIN + 102);

    icon(ctx, sheet, HUD_FRAMES.ammo, textX + 140, MARGIN + 84);
    const ammoLabel = player.weapon.ammo < 0 ? "∞" : `${player.weapon.ammo} / ${player.weapon.maxAmmo}`;
    ctx.fillText(ammoLabel, textX + 168, MARGIN + 102);

    const weapons = assets?.sheet("player_weapons");
    const wdef = player.loadout?.def?.() || {};
    drawSheetFrame(ctx, weapons, wdef.hudIcon ?? player.weapon.weaponFrame ?? 0, textX, MARGIN + 108, 28, 28);
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 13px sans-serif";
    ctx.fillText((wdef.displayName || player.weapon.name || "Pistol").toUpperCase(), textX + 34, MARGIN + 128);
    if (player.notice?.text) {
      ctx.fillStyle = player.notice.text === "EMPTY" ? "#f87171" : "#e8b84a";
      ctx.fillText(player.notice.text, textX + 250, MARGIN + 128);
    }

    const spec = player.ability;
    ctx.fillStyle = "#94a3b8";
    ctx.fillText(spec.name, textX, MARGIN + 152);
    ctx.fillStyle = spec.ready ? "#e8b84a" : "#64748b";
    ctx.fillText(spec.ready ? "READY" : `CD ${Math.max(0, spec.cool).toFixed(1)}s`, textX + 160, MARGIN + 152);

    icon(ctx, sheet, HUD_FRAMES.objective, textX, MARGIN + 162);
    ctx.fillStyle = "#f4f1ea";
    const obj = objective || (keys > 0 ? `KEY ${keys}` : "");
    ctx.fillText(obj, textX + 28, MARGIN + 180);
    if (wave && wave.total > 0) {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 13px sans-serif";
      ctx.fillText(`WAVE ${wave.index} / ${wave.total}`, textX, MARGIN + 204);
      ctx.fillText(`ENEMIES ${wave.living}`, textX + 168, MARGIN + 204);
    }
    if (keys > 0) ctx.fillText(`KEY ${keys}`, textX + 300, MARGIN + 180);
    if (crew && crew.total > 0) {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 13px sans-serif";
      ctx.fillText(`CREW ${crew.found}/${crew.total}`, textX + 300, MARGIN + 204);
    }
  }
}
