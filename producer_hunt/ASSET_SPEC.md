# Producer Hunt — Sprite & Animation Asset Spec

Art is drop-in. Gameplay talks only to the animation system (`SpriteAnimator` + `sprite-spec.js`).

## Player Sprites

```text
256 × 256 px per frame
horizontal sprite strip
transparent PNG
right-facing
bottom-center gameplay origin (feet)
```

The engine **mirrors** the sheet when the character faces left. Do not export left-facing sheets.

## Required Animations

| Animation | Default frames | Default FPS | Loop | File |
|---|---:|---:|---|---|
| idle | 6 | 8 | yes | `{id}_idle.png` |
| run | 8 | 14 | yes | `{id}_run.png` |
| jump | 4 | 10 | no | `{id}_jump.png` |
| fall | 2 | 8 | yes | `{id}_fall.png` |
| crouch | 2 | 6 | no | `{id}_crouch.png` |
| shoot | 4 | 16 | no | `{id}_shoot.png` |
| crouch_shoot | 4 | 16 | no | `{id}_crouch_shoot.png` |
| hit | 3 | 14 | no | `{id}_hit.png` |
| death | 8 | 10 | no | `{id}_death.png` |

Frame counts and FPS live in `static/producer_hunt/js/sprite-spec.js` (`PLAYER_ANIMATIONS`). Do not hardcode them in the renderer.

Strip width = `frames × 256`. Height = `256`.

Examples:

- idle 6 frames → **1536 × 256**
- run 8 frames → **2048 × 256**

## Naming Rules

Folder:

```text
assets/characters/{id}/sprites/{id}_{animation}.png
assets/characters/{id}/portrait.png
```

`{id}` matches the character config id (`editor`, `assistant`, `vfx_supervisor`, `colorist`).

Portraits are **not** cropped from gameplay sheets.

## Ground Alignment

Every frame of every animation for a character must share the **same foot baseline** (near the bottom of the 256 canvas). Jump, crouch, and death must not slide the feet horizontally or vertically relative to that line except for intended motion.

## Transparency

Backgrounds must be true alpha transparency. No matte color, no baked checkerboard.

## Character Consistency

Across all sheets for one character, keep:

- scale
- clothing
- weapon
- proportions
- colors

## Left Facing

Export **right-facing** only. The engine flips on X around the bottom-center origin.

## Collision vs sprite

The 256×256 frame is **render only**. Collision is a smaller box (default 80×170) attached to the feet. Transparent padding must not become a hit box.

## Muzzle

Projectile spawn uses `muzzleOffset` from the feet (default `{ x: 78, y: -105 }`). X is mirrored when facing left.

## Sprite Validation

On load the game checks:

- image loaded
- width === frameWidth × frames
- height === frameHeight

Mismatch logs:

```text
[Producer Hunt Asset Validation]

Asset:
editor_idle.png

Expected:
1536 × 256
6 frames

Actual:
1536 × 300

Using placeholder fallback.
```

Missing files log an error and the game continues with a fallback draw.

## Enemies

Same 256×256 horizontal strips.

```text
assets/enemies/post_producer/sprites/post_producer_{anim}.png
assets/enemies/post_producer/effects/post_producer_attack_impact.png
```

Active enemy: `post_producer` (Post Producer).

| Animation | Frames | Size |
|---|---:|---|
| idle | 6 | 1536 × 256 |
| walk | 8 | 2048 × 256 |
| attack | 4 | 1024 × 256 |
| hit | 3 | 768 × 256 |
| death | 6 | 1536 × 256 |
| attack impact | 4 × 128 | 512 × 128 |

Config: `ENEMY_ANIMATIONS` in `sprite-spec.js`. Legacy spawn id `assistant_producer` is aliased to `post_producer` once at load.

## How to replace a sheet

1. Export PNG strip at the exact size.
2. Overwrite the file in the folder above.
3. Change frame count / FPS in `sprite-spec.js` only if the sheet differs from defaults.
4. Reload Producer Hunt. No gameplay rewrite.

Regenerate development placeholders:

```text
python producer_hunt/tools/generate_placeholder_sheets.py
```

## Production checklist

Before accepting a final sprite sheet:

```text
[ ] Correct character
[ ] Correct animation
[ ] Correct frame count
[ ] Exactly 256 × 256 per frame
[ ] Correct total image width
[ ] Transparent background
[ ] No text
[ ] No logos
[ ] No frame numbers
[ ] No borders
[ ] No shadows extending outside intended frame
[ ] Same scale across frames
[ ] Same costume
[ ] Same weapon
[ ] Same character proportions
[ ] Feet aligned to baseline
[ ] Facing right
[ ] No cropped body parts
```
