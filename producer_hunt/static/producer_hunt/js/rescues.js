/** Studio 01 trapped crew. Rewards go through grantReward once per stable rescue ID. */

import { aabb } from "./collision.js";
import { SpriteAnimator } from "./animation.js";
import { DEBUG_COMBAT } from "./config.js";
import { RESCUE_ANIMATIONS, SPRITE_FRAME_HEIGHT as FH, SPRITE_FRAME_WIDTH as FW } from "./sprite-spec.js";

export const ALL_RESCUES_BONUS = 2000;
export const RESCUE_TOTAL = 4;

const MISSING = new Set();
const KITS = new Map();

export const EXPECTED_RESCUE_ASSETS = [
  "characters/rescues/camera_operator/sprites/rescue_idle.png",
  "characters/rescues/camera_operator/sprites/rescue_release.png",
  "characters/rescues/camera_operator/sprites/rescue_celebrate.png",
  "characters/rescues/camera_operator/sprites/rescue_run.png",
  "characters/rescues/sound_engineer/sprites/rescue_idle.png",
  "characters/rescues/sound_engineer/sprites/rescue_release.png",
  "characters/rescues/sound_engineer/sprites/rescue_celebrate.png",
  "characters/rescues/sound_engineer/sprites/rescue_run.png",
  "characters/rescues/stunt_performer/sprites/rescue_idle.png",
  "characters/rescues/stunt_performer/sprites/rescue_release.png",
  "characters/rescues/stunt_performer/sprites/rescue_celebrate.png",
  "characters/rescues/stunt_performer/sprites/rescue_run.png",
  "characters/rescues/production_intern/sprites/rescue_idle.png",
  "characters/rescues/production_intern/sprites/rescue_release.png",
  "characters/rescues/production_intern/sprites/rescue_celebrate.png",
  "characters/rescues/production_intern/sprites/rescue_run.png",
];

export function warnMissingRescueAsset(rel) {
  if (MISSING.has(rel)) return;
  MISSING.add(rel);
  console.warn(`[Producer Hunt] Missing rescue asset: ${rel}. Using a labeled placeholder.`);
}

export const RESCUE_DEFS = {
  camera_operator: {
    id: "camera_operator",
    displayName: "Camera Operator",
    color: "#ea580c",
    accessory: "headset",
    w: 52,
    h: 148,
    interactW: 110,
    interactH: 170,
    requireClear: true,
    clearRadius: 240,
    autoTouch: false,
    message: "CAMERA OPERATOR RESCUED — MACHINE-GUN AMMO",
    caption: "Thanks — take the spare magazines.",
    score: 500,
    reward: { kind: "ammo", weaponId: "machine_gun", amount: 48 },
    fallback: [{ kind: "score", amount: 250 }],
  },
  sound_engineer: {
    id: "sound_engineer",
    displayName: "Sound Engineer",
    color: "#2563eb",
    accessory: "headphones",
    w: 52,
    h: 148,
    interactW: 110,
    interactH: 170,
    requireClear: false,
    autoTouch: true,
    message: "SOUND ENGINEER RESCUED — HEALTH RESTORED",
    caption: "You saved the mix. Patch yourself up.",
    score: 500,
    reward: { kind: "health", amount: 25 },
    fallback: [{ kind: "score", amount: 250 }],
  },
  stunt_performer: {
    id: "stunt_performer",
    displayName: "Stunt Performer",
    color: "#dc2626",
    accessory: "pads",
    w: 52,
    h: 148,
    interactW: 110,
    interactH: 170,
    requireClear: false,
    autoTouch: false,
    message: "STUNT PERFORMER RESCUED — DEFENSE BOOST",
    caption: "Walk it off — I'll cover you.",
    score: 750,
    reward: { kind: "temporaryBuff", buff: "defense", mul: 0.75, duration: 15 },
    fallback: [],
  },
  production_intern: {
    id: "production_intern",
    displayName: "Production Intern",
    color: "#ca8a04",
    accessory: "clipboard",
    w: 52,
    h: 148,
    interactW: 110,
    interactH: 170,
    requireClear: false,
    autoTouch: false,
    message: "PRODUCTION INTERN RESCUED — POWER ENERGY",
    caption: "Call sheet's yours. Charge up.",
    score: 750,
    reward: { kind: "specialPowerEnergy", amount: 40 },
    fallback: [
      { kind: "ammo", amount: 30 },
      { kind: "score", amount: 250 },
    ],
  },
};

export function rescueDef(kind) {
  return RESCUE_DEFS[kind] || RESCUE_DEFS.sound_engineer;
}

function kitConfig(kind) {
  const def = rescueDef(kind);
  const animations = {};
  for (const [name, clip] of Object.entries(RESCUE_ANIMATIONS)) {
    animations[name] = {
      ...clip,
      src: `characters/rescues/${def.id}/sprites/${clip.file}.png`,
    };
  }
  return {
    id: def.id,
    frameWidth: FW || SPRITE_FRAME_WIDTH || 256,
    frameHeight: FH || SPRITE_FRAME_HEIGHT || 256,
    renderWidth: 168,
    renderHeight: 168,
    animations,
  };
}

export async function preloadRescueKits(assets) {
  for (const kind of Object.keys(RESCUE_DEFS)) {
    const cfg = kitConfig(kind);
    const kit = { ...cfg, animations: {} };
    for (const [name, clip] of Object.entries(cfg.animations)) {
      const img = await assets.loadOptionalImage(clip.src, clip.src);
      if (!img) warnMissingRescueAsset(clip.src);
      kit.animations[name] = {
        ...clip,
        image: img || null,
        frameWidth: cfg.frameWidth,
        frameHeight: cfg.frameHeight,
        renderWidth: cfg.renderWidth,
        renderHeight: cfg.renderHeight,
      };
    }
    KITS.set(kind, kit);
  }
}

export function instantiateRescue(raw, index, levelId) {
  const def = rescueDef(raw.kind);
  const h = raw.h || def.h;
  return {
    id: raw.id || `${levelId || "lvl"}_rescue_${index}`,
    kind: def.id,
    displayName: def.displayName,
    x: raw.x,
    y: raw.y - h,
    w: raw.w || def.w,
    h,
    footX: raw.x + (raw.w || def.w) / 2,
    footY: raw.y,
    facing: raw.facing === 1 ? 1 : -1,
    state: "trapped",
    timer: 0,
    hold: 0,
    rewarded: false,
    saved: false,
    prompt: false,
    fade: 1,
    containerId: raw.containerId || "",
    escapeX: Number.isFinite(raw.escapeX) ? raw.escapeX : raw.x - 420,
    requireClear: raw.requireClear != null ? Boolean(raw.requireClear) : def.requireClear,
    autoTouch: raw.autoTouch != null ? Boolean(raw.autoTouch) : def.autoTouch,
    anim: new SpriteAnimator(KITS.get(def.id) || kitConfig(def.id)),
    def,
  };
}

function containerOpen(world, rescue) {
  if (!rescue.containerId) return true;
  const d = (world.destructibles || []).find((row) => row.id === rescue.containerId);
  if (!d) return true;
  return d.state === "gone" || d.state === "rubble";
}

function zoneBox(r) {
  const w = r.def.interactW || 110;
  const h = r.def.interactH || 170;
  return { x: r.footX - w / 2, y: r.footY - h, w, h };
}

function areaClear(game, r) {
  if (!r.requireClear) return true;
  const rad = r.def.clearRadius || 220;
  return !(game.enemies || []).some((e) => {
    if (!e.alive || e.hitboxEnabled === false) return false;
    return Math.hypot(e.footX - r.footX, (e.footY || 0) - r.footY) < rad;
  });
}

function cinematic(game) {
  return Boolean(
    game._cinematicActive ||
      game.bossEncounter?.phase === "intro" ||
      game.bossEncounter?.phase === "dying" ||
      game.bossEncounter?.phase === "defeat_cinematic"
  );
}

export function grantReward(game, spec) {
  if (!game?.player || !spec) return { granted: [], usedFallback: false };
  const granted = [];
  const tryOne = (reward) => {
    if (!reward?.kind) return false;
    const p = game.player;
    if (reward.kind === "health") {
      if (p.isHealthFull?.()) return false;
      const n = p.heal(reward.amount || 25);
      if (n > 0) granted.push("health");
      return n > 0;
    }
    if (reward.kind === "ammo") {
      const n = reward.weaponId
        ? p.loadout?.addAmmo?.(reward.weaponId, reward.amount || 40) || 0
        : p.loadout?.addGenericAmmo?.(reward.amount || 40) || 0;
      if (n > 0) {
        p._syncWeaponRef?.();
        granted.push("ammo");
      }
      return n > 0;
    }
    if (reward.kind === "weapon") {
      if (!reward.weaponId || !p.loadout) return false;
      p.loadout.collectWeapon(reward.weaponId);
      p._syncWeaponRef?.();
      granted.push("weapon");
      return true;
    }
    if (reward.kind === "specialPowerEnergy") {
      if (p.isEnergyFull?.()) return false;
      const n = p.addEnergy(reward.amount || 40);
      if (n > 0) granted.push("energy");
      return n > 0;
    }
    if (reward.kind === "temporaryBuff") {
      p.rescueBuff = {
        defenseMul: reward.mul || 0.75,
        remain: reward.duration || 15,
        label: "DEFENSE",
      };
      granted.push("buff");
      return true;
    }
    if (reward.kind === "score") {
      const amt = Math.max(0, Number(reward.amount) || 0);
      game.scoreboard?.award(`rescue-fallback:${spec.id}`, amt, { source: "rescue_fallback", bucket: "rescue" });
      game.scoreboard?.sync(game);
      granted.push("score");
      return amt > 0;
    }
    return false;
  };

  let usedFallback = false;
  if (!tryOne(spec.reward)) {
    usedFallback = true;
    for (const row of spec.fallback || []) {
      if (tryOne(row)) break;
    }
  }
  return { granted, usedFallback };
}

function showMessage(game, rescue) {
  const text = rescue.def.message;
  game.combatHint = { text, until: (game._worldTime || 0) + 2.4 };
  game.rescueToast = { text, age: 0, life: 1.6 };
  if (game.settings?.captions && rescue.def.caption) {
    game.rescueCaption = { text: rescue.def.caption, until: (game._worldTime || 0) + 3.2 };
  }
}

function awardAllBonus(game) {
  const hud = rescueHud(game.world);
  game.stats.rescuesFound = hud.found;
  game.stats.totalRescues = hud.total;
  game.scoreboard?.awardAllRescues(hud.found, hud.total);
  game.scoreboard?.sync(game);
  game.stats.allRescuesAwarded = Boolean(game.stats.allRescuesAwarded);
}

function beginRescue(game, r) {
  if (r.state !== "available") return;
  if (cinematic(game)) return;
  r.state = "rescuing";
  r.timer = 0.42;
  r.anim.play("release", { restart: true });
  game.sfx("rescue_celebrate", { x: r.footX });
  if (game.player?.alive) game.player.invuln = Math.max(game.player.invuln || 0, 0.55);
}

function finishReward(game, r) {
  if (r.rewarded) return;
  r.rewarded = true;
  grantReward(game, r.def);
  game.scoreboard?.awardRescue(r.kind, r.id);
  game.scoreboard?.sync(game);
  showMessage(game, r);
  game.sfx("rescue_reward", { x: r.footX });
  const hud = rescueHud(game.world);
  game.stats.rescuesFound = hud.found;
  game.stats.totalRescues = hud.total;
  awardAllBonus(game);
  game.hud?.invalidate?.();
}

export function tickRescues(game, dt) {
  if (!game.world) return;
  const p = game.player;
  if (p?.rescueBuff) {
    p.rescueBuff.remain -= dt;
    if (p.rescueBuff.remain <= 0) p.rescueBuff = null;
  }
  if (game.rescueToast) {
    game.rescueToast.age += dt;
    if (game.rescueToast.age >= game.rescueToast.life) game.rescueToast = null;
  }
  if (cinematic(game)) return;

  for (const r of game.world.rescues || []) {
    if (r.anim?.kit !== KITS.get(r.kind) && KITS.get(r.kind)) r.anim.setKit(KITS.get(r.kind));
    r.prompt = false;
    if (r.state === "completed") continue;

    const open = containerOpen(game.world, r);
    if (r.state === "trapped" && open) {
      r.state = "available";
      game.sfx("rescue_open", { x: r.footX });
    }

    if (r.state === "available") {
      r.anim.play("idle");
      r.anim.update(dt);
      if (!p?.alive || p.mounted) continue;
      const inside = aabb(p.bounds(), zoneBox(r));
      const clear = areaClear(game, r);
      if (inside && !clear) {
        r.prompt = "clear";
        continue;
      }
      if (inside && clear) {
        r.prompt = "rescue";
        r.hold += dt;
        if (r.hold <= dt + 0.001) game.sfx("rescue_prompt", { x: r.footX });
        const pressed = game.input.consume("interact") || game.input.consume("confirm");
        if (pressed || (r.autoTouch && r.hold > 0.18)) beginRescue(game, r);
      } else r.hold = 0;
      continue;
    }

    if (r.state === "rescuing") {
      r.anim.update(dt);
      r.timer -= dt;
      if (r.timer <= 0 || r.anim.finished) {
        r.state = "celebrating";
        r.timer = 0.7;
        r.anim.play("celebrate", { restart: true });
        finishReward(game, r);
      }
      continue;
    }

    if (r.state === "celebrating") {
      r.anim.update(dt);
      r.timer -= dt;
      if (r.timer <= 0) {
        r.state = "escaping";
        r.anim.play("run", { restart: true });
        game.sfx("rescue_escape", { x: r.footX });
      }
      continue;
    }

    if (r.state === "escaping") {
      const dest = r.escapeX;
      const dir = Math.sign(dest - r.footX) || -1;
      r.facing = dir;
      r.footX += dir * 210 * dt;
      r.x = r.footX - r.w / 2;
      r.anim.flip = dir > 0;
      r.anim.update(dt);
      r.fade = Math.max(0, r.fade - dt * 0.45);
      const done = (dir < 0 && r.footX <= dest) || (dir > 0 && r.footX >= dest) || r.fade <= 0;
      if (done) {
        r.state = "completed";
        r.saved = true;
        r.fade = 0;
        awardAllBonus(game);
        game.hud?.invalidate?.();
      }
    }
  }
}

export function snapshotRescues(world) {
  return (world?.rescues || []).map((r) => ({
    id: r.id,
    state: r.state === "rescuing" || r.state === "celebrating" || r.state === "escaping" ? "completed" : r.state,
    rewarded: Boolean(r.rewarded || r.state === "completed" || r.saved),
    saved: Boolean(r.saved || r.state === "completed"),
  }));
}

export function applyRescueSnapshot(world, rows) {
  if (!world || !rows) return;
  const map = Object.fromEntries(rows.map((r) => [r.id, r]));
  for (const r of world.rescues || []) {
    const rec = map[r.id];
    if (!rec) {
      r.state = "trapped";
      r.rewarded = false;
      r.saved = false;
      r.timer = 0;
      r.fade = 1;
      continue;
    }
    r.rewarded = Boolean(rec.rewarded || rec.saved);
    r.saved = Boolean(rec.saved || rec.state === "completed");
    if (r.saved || rec.state === "completed") {
      r.state = "completed";
      r.fade = 0;
    } else {
      r.state = rec.state === "available" ? "available" : "trapped";
      r.fade = 1;
    }
    r.timer = 0;
    r.hold = 0;
  }
}

export function rescueHud(world) {
  const rows = world?.rescues || [];
  const total = rows.length;
  const found = rows.filter((r) => r.state === "completed" || r.saved || r.rewarded).length;
  return { found, total, label: `CREW ${found}/${total || RESCUE_TOTAL}` };
}

function drawNpcFallback(ctx, r, rw, rh) {
  ctx.fillStyle = r.def.color;
  ctx.fillRect(-22, -rh + 28, 44, rh - 36);
  ctx.fillStyle = "#f8fafc";
  ctx.beginPath();
  ctx.arc(0, -rh + 22, 14, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#0f172a";
  ctx.font = "bold 11px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(r.def.accessory.slice(0, 4).toUpperCase(), 0, -rh + 80);
}

export function drawRescues(ctx, game, layer) {
  for (const r of game.world?.rescues || []) {
    if (r.state === "completed") continue;
    const trapped = r.state === "trapped";
    if (layer === "back" && !trapped) continue;
    if (layer === "front" && trapped) continue;
    const origin = game.camera.worldToScreen(r.footX, r.footY);
    ctx.save();
    ctx.globalAlpha = r.state === "escaping" ? Math.max(0.15, r.fade) : trapped ? 0.9 : 1;
    r.anim.flip = r.facing > 0;
    r.anim.draw(ctx, origin.x, origin.y, (g, rw, rh) => drawNpcFallback(g, r, rw, rh));
    ctx.restore();
    if (r.prompt && layer === "front") {
      const label = r.prompt === "clear" ? "CLEAR THE AREA" : "F / ENTER  RESCUE";
      ctx.save();
      ctx.fillStyle = "rgba(15,23,42,0.86)";
      ctx.fillRect(origin.x - 110, origin.y - r.h - 48, 220, 36);
      ctx.strokeStyle = "#fbbf24";
      ctx.lineWidth = 2;
      ctx.strokeRect(origin.x - 110, origin.y - r.h - 48, 220, 36);
      ctx.fillStyle = "#fbbf24";
      ctx.beginPath();
      ctx.moveTo(origin.x, origin.y - r.h - 56);
      ctx.lineTo(origin.x - 8, origin.y - r.h - 48);
      ctx.lineTo(origin.x + 8, origin.y - r.h - 48);
      ctx.fill();
      ctx.fillStyle = "#f8fafc";
      ctx.font = "bold 14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, origin.x, origin.y - r.h - 24);
      ctx.restore();
    }
  }
}

export function drawRescueHud(ctx, game) {
  if (!game.world?.rescues?.length) return;
  if (game._cinematicActive) return;
  const hud = rescueHud(game.world);
  const x = 24;
  const y = 300;
  ctx.save();
  ctx.fillStyle = "rgba(5, 7, 12, 0.62)";
  ctx.fillRect(x, y, 168, 40);
  ctx.strokeStyle = "#e8b84a";
  ctx.strokeRect(x + 0.5, y + 0.5, 167, 39);
  ctx.fillStyle = "#e8b84a";
  ctx.font = "bold 16px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(hud.label, x + 14, y + 26);
  const toast = game.rescueToast;
  if (toast && !game.settings?.reducedFlashes) {
    ctx.globalAlpha = 1 - toast.age / toast.life;
    ctx.fillStyle = "#fde68a";
    ctx.fillRect(x, y, 168, 40);
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#0f172a";
    ctx.fillText(hud.label, x + 14, y + 26);
  }
  ctx.restore();
  if (game.rescueCaption && (game._worldTime || 0) < game.rescueCaption.until) {
    ctx.save();
    ctx.fillStyle = "rgba(5,7,12,0.72)";
    ctx.fillRect(DESIGN_SAFE_X, 980, 1200, 44);
    ctx.fillStyle = "#f8fafc";
    ctx.font = "18px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(game.rescueCaption.text, DESIGN_SAFE_X + 16, 1008);
    ctx.restore();
  }
}

const DESIGN_SAFE_X = 360;

export function drawRescueDebug(ctx, game) {
  if (!game.debug && !DEBUG_COMBAT) return;
  const cam = game.camera;
  ctx.save();
  ctx.font = "11px monospace";
  for (const r of game.world?.rescues || []) {
    const z = zoneBox(r);
    const s = cam.worldToScreen(z.x, z.y);
    ctx.strokeStyle = "#22d3ee";
    ctx.strokeRect(s.x, s.y, z.w, z.h);
    const p = cam.worldToScreen(r.footX, r.footY);
    ctx.fillStyle = "#e0f2fe";
    ctx.fillText(`${r.id} ${r.state} ${r.rewarded ? "paid" : "open"}`, p.x - 40, p.y - r.h - 8);
    ctx.strokeStyle = "rgba(74,222,128,0.7)";
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    const e = cam.worldToScreen(r.escapeX, r.footY);
    ctx.lineTo(e.x, e.y);
    ctx.stroke();
  }
  ctx.restore();
}

export { ALL_RESCUES_BONUS as RESCUE_ALL_BONUS };
