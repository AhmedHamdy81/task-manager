#!/usr/bin/env python3
"""Generate development-only placeholder sprite strips (exact production dimensions)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "static" / "producer_hunt" / "assets"
FRAME = 256
BASELINE = 248  # feet sit 8px above the bottom of every frame

PLAYER_ANIMS = {
    "idle": 6,
    "run": 8,
    "jump": 4,
    "fall": 2,
    "crouch": 2,
    "shoot": 4,
    "crouch_shoot": 4,
    "hit": 3,
    "death": 8,
}

ENEMY_ANIMS = {
    "idle": 6,
    "walk": 8,
    "run": 8,
    "attack": 6,
    "hit": 3,
    "death": 8,
}

CHARACTERS = {
    "editor": ("EDITOR", (74, 222, 128), (22, 101, 52)),
    "assistant": ("ASSISTANT", (56, 189, 248), (7, 89, 133)),
    "vfx_supervisor": ("VFX SUP", (192, 132, 252), (107, 33, 168)),
    "colorist": ("COLORIST", (251, 113, 133), (159, 18, 57)),
}

ENEMIES = {
    "assistant_producer": ("A. PROD", (245, 158, 11), (120, 53, 15)),
}


def _font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_body(draw: ImageDraw.ImageDraw, fill, accent, crouch: bool, frame_i: int, frames: int):
    bob = int((frame_i % 3) - 1) * 2
    height = 96 if crouch else 160
    top = BASELINE - height - bob
    left = 92
    width = 72
    draw.rectangle([left, top, left + width, BASELINE], fill=fill)
    draw.rectangle([left, BASELINE - 18, left + width, BASELINE], fill=accent)
    # head
    cx, cy = left + width // 2, top + 22
    draw.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=accent)
    # right-facing cue
    draw.polygon([(left + width, top + 70), (left + width + 28, top + 82), (left + width, top + 94)], fill=accent)
    # baseline tick
    draw.line([(40, BASELINE), (216, BASELINE)], fill=(255, 255, 255, 40), width=1)


def write_strip(path: Path, label: str, anim: str, frames: int, fill, accent, crouch: bool):
    img = Image.new("RGBA", (FRAME * frames, FRAME), (0, 0, 0, 0))
    font_s = _font(18)
    font_t = _font(14)
    for i in range(frames):
        frame = Image.new("RGBA", (FRAME, FRAME), (0, 0, 0, 0))
        d = ImageDraw.Draw(frame)
        _draw_body(d, fill, accent, crouch, i, frames)
        d.text((16, 12), label, fill=(255, 255, 255, 220), font=font_s)
        d.text((16, 36), f"{anim.upper().replace('_', ' ')} {i + 1}", fill=(255, 255, 255, 180), font=font_t)
        img.paste(frame, (i * FRAME, 0), frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print("wrote", path, img.size)


def write_portrait(path: Path, label: str, fill, accent):
    img = Image.new("RGBA", (FRAME, FRAME), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([48, 40, 208, 240], fill=fill)
    d.ellipse([88, 56, 168, 136], fill=accent)
    d.text((128, 180), label, fill=(7, 16, 24, 255), font=_font(16), anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print("wrote", path, img.size)


def main() -> None:
    for cid, (label, fill, accent) in CHARACTERS.items():
        write_portrait(ROOT / "characters" / cid / "portrait.png", label, fill, accent)
        for anim, frames in PLAYER_ANIMS.items():
            write_strip(
                ROOT / "characters" / cid / "sprites" / f"{cid}_{anim}.png",
                label,
                anim,
                frames,
                fill,
                accent,
                crouch=anim.startswith("crouch"),
            )
    for eid, (label, fill, accent) in ENEMIES.items():
        for anim, frames in ENEMY_ANIMS.items():
            write_strip(
                ROOT / "enemies" / eid / f"{eid}_{anim}.png",
                label,
                anim,
                frames,
                fill,
                accent,
                crouch=False,
            )


if __name__ == "__main__":
    main()
