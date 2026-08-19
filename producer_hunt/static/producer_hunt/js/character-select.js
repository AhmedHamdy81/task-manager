import { CHARACTERS, DEFAULT_CHARACTER_ID, characterById } from "./characters.js";
import { DESIGN_H, DESIGN_W } from "./config.js";
import { loadSettings, saveSettings } from "./settings.js";
import { drawButtons, hitButton } from "./ui.js";

function drawContainedImage(ctx, img, x, y, w, h) {
  const scale = Math.min(w / img.width, h / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
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
  }

  get selected() {
    return this.list[this.focusIndex] || characterById(this.selectedId);
  }

  move(dir) {
    const n = this.list.length;
    this.focusIndex = (this.focusIndex + dir + n) % n;
  }

  setFocus(i) {
    if (i < 0 || i >= this.list.length) return;
    this.focusIndex = i;
    this.selectedId = this.list[i].id;
  }

  persist() {
    this.selectedId = this.selected.id;
    saveSettings({ characterId: this.selectedId });
  }

  cards() {
    const n = this.list.length;
    const margin = 80;
    const gap = 28;
    const cardW = Math.min(380, (DESIGN_W - margin * 2 - gap * (n - 1)) / n);
    const cardH = Math.min(620, DESIGN_H - 280);
    const total = n * cardW + (n - 1) * gap;
    const startX = (DESIGN_W - total) / 2;
    const y = 168;
    return this.list.map((ch, i) => ({
      i,
      ch,
      x: startX + i * (cardW + gap),
      y,
      w: cardW,
      h: cardH,
    }));
  }

  confirmButton() {
    return { id: "CONFIRM", label: "CONFIRM", x: DESIGN_W / 2 + 16, y: DESIGN_H - 108, w: 280, h: 56 };
  }

  backButton() {
    return { id: "BACK", label: "BACK", x: DESIGN_W / 2 - 296, y: DESIGN_H - 108, w: 280, h: 56 };
  }

  handleClick(x, y) {
    const cards = this.cards();
    const hit = cards.find((c) => x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h);
    if (hit) {
      const same = hit.i === this.focusIndex && this.selectedId === hit.ch.id;
      this.setFocus(hit.i);
      return same ? "confirm" : "focus";
    }
    if (hitButton(this.confirmButton(), x, y)) return "confirm";
    if (hitButton(this.backButton(), x, y)) return "back";
    return null;
  }

  draw(ctx, assets) {
    ctx.fillStyle = "#f4f1ea";
    ctx.font = "bold 42px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("SELECT CHARACTER", DESIGN_W / 2, 78);
    ctx.font = "18px sans-serif";
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("← →  navigate   ·   ENTER confirm   ·   ESC back", DESIGN_W / 2, 122);

    for (const card of this.cards()) {
      const focused = card.i === this.focusIndex;
      const chosen = card.ch.id === this.selectedId;
      const ch = card.ch;
      ctx.fillStyle = focused ? "#172033" : "#0f1624";
      ctx.fillRect(card.x, card.y, card.w, card.h);
      ctx.lineWidth = focused ? 4 : chosen ? 3 : 1;
      ctx.strokeStyle = focused ? "#e8b84a" : chosen ? ch.color : "#334155";
      ctx.strokeRect(card.x + 2, card.y + 2, card.w - 4, card.h - 4);

      const pad = 28;
      const portraitBox = Math.min(card.w - pad * 2, card.h - 160);
      const px = card.x + (card.w - portraitBox) / 2;
      const py = card.y + 36;
      ctx.fillStyle = "#0b1220";
      ctx.fillRect(px, py, portraitBox, portraitBox);

      const kit = assets?.characterKit(ch.id);
      const portrait = kit?.portraitImage;
      if (portrait) {
        drawContainedImage(ctx, portrait, px + 8, py + 8, portraitBox - 16, portraitBox - 16);
      } else {
        ctx.fillStyle = ch.color;
        ctx.fillRect(px + portraitBox * 0.25, py + portraitBox * 0.2, portraitBox * 0.5, portraitBox * 0.6);
        ctx.fillStyle = "#071018";
        ctx.font = "bold 36px sans-serif";
        ctx.fillText(ch.initials, card.x + card.w / 2, py + portraitBox * 0.55);
      }

      ctx.fillStyle = "#f4f1ea";
      ctx.font = "bold 22px sans-serif";
      ctx.fillText(ch.displayName || ch.name, card.x + card.w / 2, py + portraitBox + 48);

      if (chosen) {
        ctx.fillStyle = "#e8b84a";
        ctx.font = "bold 14px sans-serif";
        ctx.fillText("SELECTED", card.x + card.w / 2, py + portraitBox + 78);
      } else if (focused) {
        ctx.fillStyle = "#94a3b8";
        ctx.font = "14px sans-serif";
        ctx.fillText("FOCUSED", card.x + card.w / 2, py + portraitBox + 78);
      }
    }

    drawButtons(ctx, [this.backButton(), this.confirmButton()]);
  }
}
