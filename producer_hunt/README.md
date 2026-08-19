# Producer Hunt 2.0

Isolated full-screen run-and-gun foundation for BigBangAdmin.

This package is **not** part of production workflows (projects, tasks, machine room, chat, and so on).

## Play

Signed-in users: sidebar **Entertainment → Producer Hunt**, or `/producer-hunt`.

Internal resolution: **1920 × 1080** (letterboxed in the browser). Physics uses this coordinate system, not CSS pixels.

Debug overlays (`?debug=1` or **F1**) work only when `APP_ENV` is not production.

## Game flow

```text
BOOT → START_SCREEN → CHARACTER_SELECT → PLAYING
PLAYING → PAUSED | PLAYER_DEAD → RESPAWNING → PLAYING
PLAYING → LEVEL_COMPLETE
```

Pause freezes gameplay simulation (including decorative world motion). Death waits for the death animation, then offers checkpoint respawn. Restart Level and Return to Main Menu ask for confirmation. Settings persist in `localStorage` under `bigbangadmin.producer_hunt` only (legacy `producerHunt.settings` is migrated once). Restart disposes the in-memory level; it does not reload BigBangAdmin.

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

Characters live in `js/characters.js`. Shared movement, jump, health, damage, and collision apply to all four. Select one after the title screen; the id is stored in `localStorage` (`bigbangadmin.producer_hunt`). Unknown saved ids fall back to **The Editor**.

| Id | Name | Special |
|---|---|---|
| `editor` | The Editor | CUT! — freeze nearby enemies |
| `assistant` | The Assistant | Turbo Sync — speed boost |
| `vfx_supervisor` | The VFX Supervisor | FINAL RENDER — short-range burst |
| `colorist` | The Colorist | GRADE SHIFT — damage boost |

## Enemies

Register a type on `ENEMY_TYPES` in `js/enemy.js`, then spawn it from a level’s `enemySpawns`. Level 1 spawns **Post Producer** (`post_producer`). Legacy `assistant_producer` ids are migrated to Post Producer.

## Weapons

Weapon fields: `id`, `name`, `damage`, `fireRate`, `projectileSpeed`, `ammo`, `maxAmmo`, `spread`, `projectileType`. The `Weapon` class owns firing; the player does not compute shots.

## Levels

Add `js/levels/level-02.js` with the same shape as `LEVEL_01`, then load it from `game.js` `beginLevel`. Fields: `worldWidth`, `worldHeight`, `platforms`, `playerSpawn`, `enemySpawns`, `pickups`, `checkpoints`, `levelEnd`, `zones`.

## Placeholder assets

Development strips (exact production sizes) live under `static/producer_hunt/assets/`. See `ASSET_SPEC.md`. Regenerate with `python producer_hunt/tools/generate_placeholder_sheets.py`.

Replace a PNG in place; update `sprite-spec.js` only if frame count/FPS changes.

## Flask

Blueprint `producer_hunt` serves `/producer-hunt` and `/producer-hunt/static/…`. The game page does not extend BigBangAdmin `base.html`.
