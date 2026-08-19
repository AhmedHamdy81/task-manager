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

export function drawDecorSheet(ctx, assets, key, items, camera, dest = 96) {
  const sheet = assets.sheet(key);
  if (!sheet?.image || !items?.length) return false;
  for (const item of items) {
    const s = camera.worldToScreen(item.x, item.y);
    drawSheetFrame(ctx, sheet, item.frame || 0, s.x, s.y, item.w || dest, item.h || dest);
  }
  return true;
}

export function drawPickups(ctx, assets, pickups, camera) {
  const sheet = assets.sheet("pickups");
  for (const p of pickups) {
    if (p.taken) continue;
    const vis = p.vis || 64;
    const cx = p.x + p.w / 2;
    const cy = p.y + p.h / 2;
    const s = camera.worldToScreen(cx - vis / 2, cy - vis / 2);
    const frame = p.frame ?? PICKUP_FRAMES[p.kind] ?? 0;
    if (!drawSheetFrame(ctx, sheet, frame, s.x, s.y, vis, vis)) {
      ctx.fillStyle = p.kind === "health" ? "#4ade80" : "#fbbf24";
      ctx.fillRect(s.x + vis * 0.2, s.y + vis * 0.2, vis * 0.6, vis * 0.6);
    }
  }
}

export function drawProgression(ctx, assets, world, camera) {
  const sheet = assets.sheet("progression");
  const end = world.end;
  const s = camera.worldToScreen(end.x - 80, end.y - 80);
  if (!drawSheetFrame(ctx, sheet, 5, s.x, s.y, 220, 220)) {
    const e = camera.worldToScreen(end.x, end.y);
    ctx.fillStyle = "#e8b84a";
    ctx.fillRect(e.x, e.y, end.w, end.h);
    ctx.fillStyle = "#071018";
    ctx.font = "14px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("WRAP", e.x + end.w / 2, e.y + 36);
  }
  for (const cp of world.checkpoints || []) {
    const c = camera.worldToScreen(cp.x - 40, cp.y - 40);
    drawSheetFrame(ctx, sheet, 3, c.x, c.y, 160, 160);
  }
}

export { EFFECT_FRAMES, HUD_FRAMES, PICKUP_FRAMES, PROJECTILE_FRAMES, drawSheetFrame };
