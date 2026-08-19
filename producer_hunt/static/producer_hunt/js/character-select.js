import { CHARACTERS } from "./characters.js";
import { DESIGN_H, DESIGN_W } from "./config.js";
import { hitButton } from "./ui.js";

export class CharacterSelect {
  constructor() {
    this.index = 0;
    this.list = CHARACTERS;
  }

  get selected() {
    return this.list[this.index];
  }

  move(dir) {
    const n = this.list.length;
    this.index = (this.index + dir + n) % n;
  }

  cards() {
    const cardW = 300;
    const gap = 28;
    const total = this.list.length * cardW + (this.list.length - 1) * gap;
    const startX = (DESIGN_W - total) / 2;
    return this.list.map((ch, i) => ({
      i,
      ch,
      x: startX + i * (cardW + gap),
      y: 210,
      w: cardW,
      h: 560,
    }));
  }

  selectButton() {
    return { x: DESIGN_W / 2 - 140, y: DESIGN_H - 110, w: 280, h: 56, label: "SELECT" };
  }

  handleClick(x, y) {
    const cards = this.cards();
    const hit = cards.find((c) => x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h);
    if (hit) {
      const same = hit.i === this.index;
      this.index = hit.i;
      return same;
    }
    return hitButton(this.selectButton(), x, y);
  }

  draw(ctx, assets) {
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 42px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("CHARACTER SELECT", DESIGN_W / 2, 90);
    ctx.font = "18px sans-serif";
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("← →  or click a card   ·   ENTER / SELECT to confirm", DESIGN_W / 2, 140);

    for (const card of this.cards()) {
      const on = card.i === this.index;
      const ch = card.ch;
      ctx.fillStyle = on ? "#172033" : "#0f1624";
      ctx.fillRect(card.x, card.y, card.w, card.h);
      ctx.strokeStyle = on ? ch.color : "#334155";
      ctx.lineWidth = on ? 4 : 1;
      ctx.strokeRect(card.x + 2, card.y + 2, card.w - 4, card.h - 4);

      const kit = assets?.characterKit(ch.id);
      const portrait = kit?.portraitImage;
      if (portrait) {
        ctx.drawImage(portrait, card.x + 90, card.y + 36, 120, 150);
      } else {
        ctx.fillStyle = ch.color;
        ctx.fillRect(card.x + 90, card.y + 36, 120, 150);
        ctx.fillStyle = "#071018";
        ctx.font = "bold 32px sans-serif";
        ctx.fillText(ch.initials, card.x + card.w / 2, card.y + 124);
      }

      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 20px sans-serif";
      ctx.fillText(ch.name, card.x + card.w / 2, card.y + 220);
      ctx.font = "16px sans-serif";
      ctx.fillStyle = "#e8b84a";
      ctx.fillText(ch.role, card.x + card.w / 2, card.y + 250);

      ctx.fillStyle = "#cbd5e1";
      ctx.font = "15px sans-serif";
      const lines = [
        `HEALTH  ${ch.health}`,
        `SPEED  ${ch.speed}`,
        `DAMAGE  ${ch.damageLabel}`,
        `JUMP  ${ch.jumpStrength}`,
        `WEAPON  ${ch.weapon.name}`,
        `SPECIAL  ${ch.specialAbility.name}`,
      ];
      lines.forEach((line, n) => ctx.fillText(line, card.x + card.w / 2, card.y + 300 + n * 28));
    }

    const btn = this.selectButton();
    ctx.fillStyle = "#e8b84a";
    ctx.fillRect(btn.x, btn.y, btn.w, btn.h);
    ctx.fillStyle = "#071018";
    ctx.font = "bold 22px sans-serif";
    ctx.fillText(btn.label, DESIGN_W / 2, btn.y + 38);
  }
}
