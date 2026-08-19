# Producer Hunt 2.0

Isolated full-screen run-and-gun foundation for BigBangAdmin.

This package is **not** part of production workflows (projects, tasks, machine room, chat, and so on).

## Play

Signed-in users: sidebar **Entertainment → Producer Hunt**, or `/producer-hunt`.

Internal resolution: **1920 × 1080** (letterboxed in the browser). Physics uses this coordinate system, not CSS pixels.

Debug overlays: `/producer-hunt?debug=1` or **F1**.

## Game flow

```text
BOOT → START SCREEN → CHARACTER SELECT → LEVEL 1 (PLAYING)
PLAYING → PAUSED | PLAYER_DEAD → GAME OVER | LEVEL COMPLETE
```

Restart resets the level in memory. It does not reload BigBangAdmin.

## Controls

| Input | Action |
|---|---|
| A / Left | Move left |
| D / Right | Move right |
| W / Up | Jump |
| S / Down | Crouch |
| Space | Shoot |
| Shift | Special ability |
| Esc | Pause |
| Enter | Confirm / restart |

Keys are remappable in `js/input.js` (`Input.remap`).

## Architecture

| Module | Role |
|---|---|
| `game-state.js` | Explicit states (`BOOT`, `START_SCREEN`, …) |
| `input.js` | Keyboard, simultaneous actions |
| `physics.js` | Gravity, arcade accel/decel |
| `collision.js` | AABB vs solids / world bounds |
| `camera.js` | World-space follow + look-ahead |
| `player.js` | Movement, facing, health, animation states |
| `weapon.js` | Data-driven fire / ammo |
| `projectile.js` | Shots, lifetime, cleanup |
| `enemy.js` | Shared enemy class + type config |
| `abilities.js` | Specials: duration / cooldown |
| `hud.js` | Screen-space HUD |
| `asset-loader.js` | Load + validate sprite strips; never crash on missing art |
| `sprite-spec.js` | Frame size, default frame counts / FPS, path helpers |
| `animation.js` | `SpriteAnimator` (play / update / draw, loop, flip, pause) |
| `levels/level-01.js` | BigBang Studios world data |

## Characters

Add a character by appending an object in `js/characters.js` (stats, weapon, special, asset paths). No engine branching per id except ability handlers in `js/abilities.js`.

| Id | Name | Special |
|---|---|---|
| `editor` | THE EDITOR | CUT! — freeze nearby enemies |
| `assistant` | THE ASSISTANT | Turbo Sync — speed boost |
| `vfx_supervisor` | VFX SUPERVISOR | FINAL RENDER — short-range burst |
| `colorist` | THE COLORIST | GRADE SHIFT — damage boost |

## Enemies

Register a type on `ENEMY_TYPES` in `js/enemy.js`, then spawn it from a level’s `enemySpawns`. Only **Assistant Producer** is implemented.

## Weapons

Weapon fields: `id`, `name`, `damage`, `fireRate`, `projectileSpeed`, `ammo`, `maxAmmo`, `spread`, `projectileType`. The `Weapon` class owns firing; the player does not compute shots.

## Levels

Add `js/levels/level-02.js` with the same shape as `LEVEL_01`, then load it from `game.js` `beginLevel`. Fields: `worldWidth`, `worldHeight`, `platforms`, `playerSpawn`, `enemySpawns`, `pickups`, `checkpoints`, `levelEnd`, `zones`.

## Placeholder assets

Development strips (exact production sizes) live under `static/producer_hunt/assets/`. See `ASSET_SPEC.md`. Regenerate with `python producer_hunt/tools/generate_placeholder_sheets.py`.

Replace a PNG in place; update `sprite-spec.js` only if frame count/FPS changes.

## Flask

Blueprint `producer_hunt` serves `/producer-hunt` and `/producer-hunt/static/…`. The game page does not extend BigBangAdmin `base.html`.
