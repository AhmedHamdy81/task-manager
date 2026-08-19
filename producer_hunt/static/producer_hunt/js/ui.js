import { DESIGN_H, DESIGN_W } from "./config.js";

export function menuButtons(items, y0 = DESIGN_H / 2 - 20) {
  return items.map((label, i) => ({
    id: label,
    label,
    x: DESIGN_W / 2 - 220,
    y: y0 + i * 70,
    w: 440,
    h: 56,
  }));
}

export function hitButton(btn, x, y) {
  return x >= btn.x && x <= btn.x + btn.w && y >= btn.y && y <= btn.y + btn.h;
}

export function hitMenu(buttons, x, y) {
  return buttons.find((b) => hitButton(b, x, y)) || null;
}

export function drawButtons(ctx, buttons) {
  ctx.textAlign = "center";
  for (const b of buttons) {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.strokeStyle = "#e8b84a";
    ctx.strokeRect(b.x, b.y, b.w, b.h);
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText(b.label, b.x + b.w / 2, b.y + 36);
  }
}

export function drawMenu(ctx, title, subtitle, buttons) {
  ctx.fillStyle = "rgba(5, 7, 12, 0.72)";
  ctx.fillRect(0, 0, DESIGN_W, DESIGN_H);
  ctx.textAlign = "center";
  ctx.fillStyle = "#f4f1ea";
  ctx.font = "bold 56px sans-serif";
  ctx.fillText(title, DESIGN_W / 2, 220);
  if (subtitle) {
    ctx.font = "22px sans-serif";
    ctx.fillStyle = "#e8b84a";
    ctx.fillText(subtitle, DESIGN_W / 2, 270);
  }
  drawButtons(ctx, buttons);
}
