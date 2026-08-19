import { DESIGN_H, DESIGN_W } from "./config.js";
import {
  EFFECT_FRAMES,
  HUD_FRAMES,
  PICKUP_FRAMES,
  PROJECTILE_FRAMES,
  TILE,
  drawParallaxLayer,
  drawSheetFrame,
  PARALLAX,
} from "./asset-catalog.js";

export function drawStudioParallax(ctx, assets, camX) {
  let any = false;
  for (const layer of PARALLAX) {
    const sheet = assets.sheet(layer.key);
    if (!sheet?.image) continue;
    drawParallaxLayer(ctx, sheet.image, camX, layer.factor, DESIGN_W, DESIGN_H);
    any = true;
  }
  return any;
}

export function drawTiledPlatforms(ctx, assets, solids, camera) {
  const sheet = assets.sheet("tiles");
  if (!sheet?.image) return false;
  const TILE_W = sheet.frameWidth;
  for (const solid of solids) {
    let row = 0;
    for (let y = solid.y; y < solid.y + solid.h - 0.5; y += TILE_W) {
      const th = Math.min(TILE_W, solid.y + solid.h - y);
      let i = 0;
      for (let x = solid.x; x < solid.x + solid.w - 0.5; x += TILE_W) {
        const remaining = solid.x + solid.w - x;
        const tw = Math.min(TILE_W, remaining);
        let frame = TILE.mid;
        if (row === 0 && i === 0) frame = TILE.left;
        else if (row === 0 && remaining <= TILE_W && i > 0) frame = TILE.right;
        else if (row > 0) frame = TILE.mid;
        else if (i > 0 && remaining > TILE_W && i % 3 === 2) frame = TILE.midAlt;
        const screen = camera.worldToScreen(x, y);
        drawSheetFrame(ctx, sheet, frame, screen.x, screen.y, tw, th);
        i += 1;
      }
      row += 1;
    }
  }
  return true;
}

export function drawDecorSheet(ctx, assets, key, items, camera, dest = 96, layer = null) {
  const sheet = assets.sheet(key);
  if (!sheet?.image || !items?.length) return false;
  const list = layer ? items.filter((item) => (item.layer || "back") === layer) : items;
  for (const item of list) {
    const s = camera.worldToScreen(item.x, item.y);
    drawSheetFrame(ctx, sheet, item.frame || 0, s.x, s.y, item.w || dest, item.h || dest);
  }
  return true;
}

export function drawHints(ctx, hints, camera) {
  if (!hints?.length) return;
  ctx.save();
  ctx.font = "bold 20px sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  for (const hint of hints) {
    const s = camera.worldToScreen(hint.x, hint.y);
    if (s.x < -80 || s.x > DESIGN_W + 40) continue;
    ctx.fillStyle = "rgba(5,7,12,0.55)";
    ctx.fillRect(s.x - 8, s.y - 16, 200, 28);
    ctx.fillStyle = "#f4f1ea";
    ctx.fillText(hint.text, s.x, s.y);
  }
  ctx.restore();
}

export function drawPickups(ctx, assets, pickups, camera, now = 0) {
  const sheet = assets.sheet("pickups");
  for (const p of pickups) {
    if (p.taken || p.reserved) continue;
    const vis = p.vis || 64;
    const cx = p.x + p.w / 2;
    const cy = p.y + p.h / 2 + Math.sin(now / 420 + p.x * 0.01) * 5;
    const s = camera.worldToScreen(cx - vis / 2, cy - vis / 2);
    const frame = p.frame ?? 0;
    if (!drawSheetFrame(ctx, sheet, frame, s.x, s.y, vis, vis)) {
      ctx.fillStyle = p.kind === "health" ? "#4ade80" : "#fbbf24";
      ctx.fillRect(s.x + vis * 0.2, s.y + vis * 0.2, vis * 0.6, vis * 0.6);
    }
  }
}

export function drawHazards(ctx, assets, hazards, camera) {
  const sheet = assets.sheet("hazards");
  for (const h of hazards || []) {
    const vis = h.vis || 128;
    const s = camera.worldToScreen(h.drawX, h.drawY);
    if (!drawSheetFrame(ctx, sheet, h.frame || 0, s.x, s.y, vis, vis)) {
      if (!h.enabled) continue;
      ctx.fillStyle = "rgba(250, 204, 21, 0.55)";
      const hit = camera.worldToScreen(h.x, h.y);
      ctx.fillRect(hit.x, hit.y, h.w, h.h);
    }
  }
}

export function drawProgression(ctx, assets, world, camera) {
  const sheet = assets.sheet("progression");
  for (const door of world.doors || []) {
    const vis = door.vis || 256;
    const s = camera.worldToScreen(door.drawX, door.drawY);
    const frame = door.state === "open" || door.state === "opening" ? door.openFrame : door.closedFrame;
    if (!drawSheetFrame(ctx, sheet, frame, s.x, s.y, vis, vis)) {
      const b = camera.worldToScreen(door.x, door.y);
      ctx.fillStyle = door.state === "open" ? "#334155" : "#7f1d1d";
      ctx.fillRect(b.x, b.y, door.w, door.h);
    }
  }
  for (const cp of world.checkpoints || []) {
    const vis = cp.vis || 256;
    const s = camera.worldToScreen(cp.drawX, cp.drawY);
    const frame = cp.activated ? 3 : 2;
    drawSheetFrame(ctx, sheet, frame, s.x, s.y, vis, vis);
  }
}

export { EFFECT_FRAMES, HUD_FRAMES, PICKUP_FRAMES, PROJECTILE_FRAMES, drawSheetFrame };
