import { DESIGN_H, DESIGN_W } from "./config.js";
import { PARTICLE_CYCLE, SHAKE_CYCLE } from "./presentation.js";

export function menuButtons(items, y0 = DESIGN_H / 2 - 20, opts = {}) {
  const w = opts.w || 520;
  const h = opts.h || 56;
  const gap = opts.gap || 66;
  return items.map((label, i) => ({
    id: label,
    label,
    x: DESIGN_W / 2 - w / 2,
    y: y0 + i * gap,
    w,
    h,
  }));
}

export function hitButton(btn, x, y) {
  return x >= btn.x && x <= btn.x + btn.w && y >= btn.y && y <= btn.y + btn.h;
}

export function hitMenu(buttons, x, y) {
  return buttons.find((b) => hitButton(b, x, y)) || null;
}

export function moveMenuIndex(index, dir, count) {
  if (!count) return 0;
  return (index + dir + count) % count;
}

export function drawButtons(ctx, buttons, opts = {}) {
  const focus = opts.focus ?? -1;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  buttons.forEach((b, i) => {
    const on = i === focus;
    ctx.fillStyle = on ? "#243044" : "#1e293b";
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.lineWidth = on ? 4 : 1;
    ctx.strokeStyle = on ? "#f4f1ea" : "#e8b84a";
    ctx.strokeRect(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1);
    if (on) {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 20px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("▸", b.x + 16, b.y + b.h / 2);
      ctx.textAlign = "center";
    }
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText(b.label, b.x + b.w / 2, b.y + b.h / 2 + 1);
  });
  ctx.textBaseline = "alphabetic";
}

export function drawMenu(ctx, title, subtitle, buttons, opts = {}) {
  ctx.fillStyle = "rgba(5, 7, 12, 0.78)";
  ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
  ctx.textAlign = "center";
  ctx.fillStyle = "#f4f1ea";
  ctx.font = "bold 56px sans-serif";
  ctx.fillText(title, DESIGN_W / 2, opts.titleY || 168);
  if (subtitle) {
    ctx.font = "22px sans-serif";
    ctx.fillStyle = "#e8b84a";
    ctx.fillText(subtitle, DESIGN_W / 2, (opts.titleY || 168) + 48);
  }
  drawButtons(ctx, buttons, opts);
}

export function drawConfirm(ctx, title, body, focus = 0) {
  ctx.fillStyle = "rgba(5, 7, 12, 0.82)";
  ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
  const box = { x: DESIGN_W / 2 - 420, y: 280, w: 840, h: 420 };
  ctx.fillStyle = "#121a28";
  ctx.fillRect(box.x, box.y, box.w, box.h);
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#f4f1ea";
  ctx.strokeRect(box.x + 1, box.y + 1, box.w - 2, box.h - 2);
  ctx.textAlign = "center";
  ctx.fillStyle = "#f4f1ea";
  ctx.font = "bold 32px sans-serif";
  ctx.fillText(title, DESIGN_W / 2, 360);
  ctx.fillStyle = "#cbd5e1";
  ctx.font = "20px sans-serif";
  wrapText(ctx, body, DESIGN_W / 2, 420, 720, 30);
  const buttons = confirmButtons();
  drawButtons(ctx, buttons, { focus });
  return buttons;
}

export function confirmButtons() {
  return [
    { id: "CONFIRM", label: "CONFIRM", x: DESIGN_W / 2 - 280, y: 560, w: 250, h: 56 },
    { id: "CANCEL", label: "CANCEL", x: DESIGN_W / 2 + 30, y: 560, w: 250, h: 56 },
  ];
}

export function settingsRows() {
  return [
    { id: "masterVolume", label: "Master volume", kind: "slider" },
    { id: "musicVolume", label: "Music volume", kind: "slider" },
    { id: "effectsVolume", label: "Effects volume", kind: "slider" },
    { id: "voiceVolume", label: "Voice / video volume", kind: "slider" },
    { id: "ambienceVolume", label: "Ambience volume", kind: "slider" },
    { id: "muted", label: "Mute", kind: "toggle" },
    { id: "fullscreen", label: "Fullscreen", kind: "toggle" },
    { id: "screenShake", label: "Screen shake", kind: "cycle", values: SHAKE_CYCLE },
    { id: "reducedFlashes", label: "Flashes", kind: "toggle", invertLabel: true },
    { id: "particleDensity", label: "Particle density", kind: "cycle", values: PARTICLE_CYCLE },
    { id: "hazardSymbols", label: "Warning symbols", kind: "toggle" },
    { id: "captions", label: "Subtitles", kind: "toggle" },
    { id: "reducedMotion", label: "Reduced motion", kind: "toggle" },
    { id: "difficulty", label: "Difficulty", kind: "cycle" },
    { id: "BACK", label: "Back", kind: "action" },
  ];
}

export function drawSettings(ctx, settings, focus, extras = {}) {
  ctx.fillStyle = "rgba(5, 7, 12, 0.82)";
  ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
  ctx.textAlign = "center";
  ctx.fillStyle = "#f4f1ea";
  ctx.font = "bold 48px sans-serif";
  ctx.fillText("SETTINGS", DESIGN_W / 2, 120);
  ctx.font = "18px sans-serif";
  ctx.fillStyle = "#94a3b8";
  ctx.fillText("← → adjust   ·   ENTER toggle   ·   ESC back", DESIGN_W / 2, 164);

  const rows = settingsRows();
  const x = DESIGN_W / 2 - 380;
  const rowH = 42;
  rows.forEach((row, i) => {
    const y = 148 + i * rowH;
    const on = i === focus;
    ctx.fillStyle = on ? "#243044" : "#152033";
    ctx.fillRect(x, y, 760, 38);
    ctx.lineWidth = on ? 3 : 1;
    ctx.strokeStyle = on ? "#f4f1ea" : "#e8b84a";
    ctx.strokeRect(x + 0.5, y + 0.5, 759, 37);
    if (on) {
      ctx.fillStyle = "#e8b84a";
      ctx.font = "bold 18px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("▸", x + 16, y + 26);
    }
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 18px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(row.label, x + 48, y + 26);
    ctx.textAlign = "right";
    ctx.fillStyle = "#e8b84a";
    if (row.kind === "slider") {
      const v = Math.round((settings[row.id] ?? 0) * 100);
      drawMeter(ctx, x + 400, y + 10, 280, 16, settings[row.id] ?? 0, on);
      ctx.fillText(`${v}%`, x + 736, y + 26);
    } else if (row.kind === "toggle") {
      let onVal = row.id === "fullscreen" ? Boolean(extras.fullscreen) : Boolean(settings[row.id]);
      if (row.id === "reducedFlashes") onVal = !settings.reducedFlashes;
      const label = row.id === "reducedFlashes" ? (onVal ? "FULL" : "REDUCED") : onVal ? "ON" : "OFF";
      ctx.fillText(label, x + 736, y + 26);
    } else if (row.kind === "cycle") {
      ctx.fillText(String(settings[row.id] || "normal").toUpperCase(), x + 736, y + 26);
    }
  });

  ctx.textAlign = "center";
  ctx.fillStyle = "#64748b";
  ctx.font = "16px sans-serif";
  ctx.fillText("Volumes apply immediately and persist in Producer Hunt settings.", DESIGN_W / 2, 860);
}

function drawMeter(ctx, x, y, w, h, value, focused) {
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = focused ? "#e8b84a" : "#64748b";
  ctx.fillRect(x, y, Math.max(0, w * value), h);
  ctx.strokeStyle = "#f4f1ea";
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
}

function wrapText(ctx, text, x, y, maxW, lineH) {
  const words = String(text || "").split(" ");
  let line = "";
  let yy = y;
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxW) {
      ctx.fillText(line, x, yy);
      line = word;
      yy += lineH;
    } else line = test;
  }
  if (line) ctx.fillText(line, x, yy);
}
