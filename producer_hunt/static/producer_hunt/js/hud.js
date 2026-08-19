import { HUD_FRAMES, drawSheetFrame } from "./asset-catalog.js";

export class HUD {
  draw(ctx, { player, score, assets }) {
    const ready = player.ability.ready;
    const sheet = assets?.sheet("hud");
    ctx.fillStyle = "rgba(5, 7, 12, 0.62)";
    ctx.fillRect(24, 24, 560, 132);

    const kit = assets?.characterKit(player.character.id);
    const portrait = kit?.portraitImage;
    if (portrait) {
      ctx.drawImage(portrait, 40, 40, 56, 88);
    } else {
      ctx.fillStyle = player.character.color;
      ctx.fillRect(40, 40, 56, 88);
      ctx.fillStyle = "#071018";
      ctx.font = "bold 16px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(player.character.initials, 68, 92);
    }

    ctx.textAlign = "left";
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 18px sans-serif";
    ctx.fillText(player.character.name, 112, 56);

    const smooth = ctx.imageSmoothingEnabled;
    ctx.imageSmoothingEnabled = false;
    drawSheetFrame(ctx, sheet, HUD_FRAMES.health, 112, 62, 22, 22);
    drawSheetFrame(ctx, sheet, HUD_FRAMES.ammo, 250, 92, 22, 22);
    drawSheetFrame(ctx, sheet, HUD_FRAMES.score, 112, 92, 22, 22);
    drawSheetFrame(ctx, sheet, HUD_FRAMES.energy, 112, 114, 22, 22);
    ctx.imageSmoothingEnabled = smooth;

    const ratio = player.maxHealth ? player.health / player.maxHealth : 0;
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(140, 68, 214, 14);
    ctx.fillStyle = ratio > 0.3 ? "#4ade80" : "#f87171";
    ctx.fillRect(140, 68, 214 * Math.max(0, ratio), 14);
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "13px sans-serif";
    ctx.fillText(`${Math.ceil(player.health)} / ${player.maxHealth}`, 370, 80);

    ctx.fillStyle = "#f4f1ea";
    ctx.fillText(`${score}`, 140, 110);
    ctx.fillText(`${player.weapon.name}  ${player.weapon.ammo}`, 278, 110);

    const spec = player.ability;
    ctx.fillText(spec.name, 140, 132);
    ctx.fillStyle = ready ? "#e8b84a" : "#64748b";
    ctx.fillText(ready ? "READY" : `CD ${Math.max(0, spec.cool).toFixed(1)}s`, 300, 132);
  }
}
