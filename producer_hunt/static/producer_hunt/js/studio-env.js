/** Studio 01 ambient activity, cycling hazards, and movers. Extends progression hazards. */

import { DESIGN_H, DESIGN_W, DEBUG_COMBAT, HITSTOP_LIGHT_SEC, SHAKE_LIGHT } from "./config.js";
import { aabb, clamp } from "./collision.js";
import { syncDoorSolids } from "./progression.js";
import { drawSheetFrame } from "./asset-catalog.js";

const CYCLE = new Set(["steam_vent", "electrical_floor", "falling_light", "rolling_cart"]);
const MISSING = new Set();

export const EXPECTED_ENV_ASSETS = [
  "environment/studio_01/foreground_silhouettes.png",
  "assets/hazards/steam_vent.png",
  "assets/audio/sfx/environment/studio_ambience.mp3",
];

export function warnMissingEnvAsset(rel) {
  if (MISSING.has(rel)) return;
  MISSING.add(rel);
  console.warn(`[Producer Hunt] Missing environment asset: ${rel}. Using a labeled placeholder.`);
}

export function isHazardDamaging(h) {
  if (!h?.enabled || !(h.damage > 0)) return false;
  if (h.kind === "camera_rig") return false;
  if (h.kind === "falling_light") return h.phase === "impact";
  if (h.kind === "rolling_cart") return h.phase === "active" && h.visible !== false;
  if (CYCLE.has(h.kind)) return h.phase === "active";
  return true;
}

export function snapshotHazards(world) {
  return (world?.hazards || []).map((h) => ({
    id: h.id,
    phase: h.phase || "idle",
    phaseAge: h.phaseAge || 0,
    fired: Boolean(h.fired),
    dropX: h.dropX,
    dropY: h.dropY,
    fixtureY: h.fixtureY,
    cartX: h.cartX,
    dir: h.dir,
    pause: h.pause || 0,
    moverX: h.moverX,
  }));
}

export function applyHazardSnapshot(world, rows) {
  if (!world || !rows) return;
  const map = Object.fromEntries(rows.map((r) => [r.id, r]));
  for (const h of world.hazards || []) {
    const rec = map[h.id];
    if (!rec) continue;
    h.phase = rec.phase || "idle";
    h.phaseAge = rec.phaseAge || 0;
    h.fired = Boolean(rec.fired);
    if (Number.isFinite(rec.dropX)) h.dropX = rec.dropX;
    if (Number.isFinite(rec.dropY)) h.dropY = rec.dropY;
    if (Number.isFinite(rec.fixtureY)) h.fixtureY = rec.fixtureY;
    if (Number.isFinite(rec.cartX)) h.cartX = rec.cartX;
    if (rec.dir) h.dir = rec.dir;
    h.pause = rec.pause || 0;
    if (Number.isFinite(rec.moverX)) {
      h.moverX = rec.moverX;
      h.x = rec.moverX;
    }
  }
}

export function resetHazardVfx(game) {
  game.dangerZones = [];
  game._envLoops = new Set();
  game.audio?.stopSound?.("env_steam");
  game.audio?.stopSound?.("env_electric");
  game.audio?.stopSound?.("env_alarm");
}

function freezeEnv(game) {
  return Boolean(
    game._cinematicActive ||
      game.bossEncounter?.phase === "intro" ||
      game.bossEncounter?.phase === "dying" ||
      game.bossEncounter?.phase === "defeat_cinematic" ||
      game.bossEncounter?.boss?.deathStarted
  );
}

function onCam(game, x, margin = 220) {
  const cam = game.camera;
  if (!cam) return true;
  return x > cam.x - margin && x < cam.x + cam.w + margin;
}

function symbols(game) {
  return game.settings?.hazardSymbols !== false;
}

function flashMul(game) {
  let m = game.settings?.reducedFlashes || game.settings?.reducedMotion ? 0.45 : 1;
  const boss = game.bossEncounter?.boss;
  if (boss?.state === "phase_transition") m *= 1.55;
  else if ((boss?.phase || 1) >= 2 && game.bossEncounter?.arenaLocked) m *= 1.2;
  return m;
}

function particleMul(game) {
  if (game.settings?.reducedMotion || game.settings?.reducedFlashes) return 0.35;
  return 1;
}

function hitBox(h) {
  if (h.kind === "rolling_cart") {
    return { x: h.cartX, y: h.y, w: h.w, h: h.h };
  }
  if (h.kind === "falling_light" && h.phase === "impact") {
    const r = h.impactRadius || 65;
    return { x: (h.dropX || h.x) - r, y: (h.impactY || h.y) - r * 0.35, w: r * 2, h: r * 0.7 };
  }
  return { x: h.x, y: h.y, w: h.w, h: h.h };
}

function clipAgainstSolids(world, box) {
  const next = { ...box };
  for (const s of world.solids || []) {
    if (s.moverId || s.arenaWall) continue;
    if (!aabb(next, s)) continue;
    if (s.y + 8 < next.y + next.h && s.y + s.h > next.y) {
      const left = s.x + s.w - next.x;
      const right = next.x + next.w - s.x;
      if (left > 0 && left < right && left < next.w) {
        next.x += left;
        next.w -= left;
      } else if (right > 0 && right < next.w) {
        next.w -= right;
      }
    }
  }
  return next.w > 8 ? next : { ...box, w: 0, h: 0 };
}

function enterPhase(h, name) {
  h.phase = name;
  h.phaseAge = 0;
}

function dealHazard(game, h, box, knock = 0) {
  if (!game.player?.alive || freezeEnv(game)) return;
  if (h.cool > 0) return;
  const mounted = Boolean(game.player.mounted && game.vehicle);
  const targetBox = mounted ? { x: game.vehicle.x, y: game.vehicle.y, w: game.vehicle.w, h: game.vehicle.h } : game.player.bounds();
  if (!aabb(targetBox, box)) return;
  const dir = Math.sign((mounted ? game.vehicle.footX : game.player.footX) - (box.x + box.w / 2)) || -1;
  const dealt = mounted
    ? game.hurtVehicle?.(h.damage, { knockbackX: dir * (knock || h.knockback || 220) })
    : game.player.takeDamage(h.damage, { knockbackX: dir * (knock || h.knockback || 220) });
  if (!dealt) return;
  h.cool = h.hitCooldown || h.cooldown || 0.75;
  if (!mounted) game._applyPlayerKnockback?.(dir * 24);
  if (game.shakeEnabled() && !freezeEnv(game)) game.camera.addShake(SHAKE_LIGHT);
  game.beginHitStop(HITSTOP_LIGHT_SEC);
  game.hud?.invalidate();
  if (game.player.alive && !mounted) game.sfx("player_hit");
}

function sfxOnce(game, h, key, id) {
  if (h[key]) return;
  h[key] = true;
  if (onCam(game, h.x)) game.sfx(id, { x: h.x + (h.w || 0) / 2 });
}

export function tickMovers(game, dt) {
  if (!game.world || freezeEnv(game)) {
    injectMoverSolids(game.world);
    return;
  }
  const player = game.player;
  for (const h of game.world.hazards || []) {
    if (h.kind !== "camera_rig" || !h.enabled) continue;
    const left = h.pathLeft ?? h.x;
    const right = h.pathRight ?? h.x + 200;
    const speed = h.speed || 70;
    if (h.pause > 0) {
      h.pause -= dt;
    } else {
      const prev = h.moverX ?? h.x;
      h.dir = h.dir || 1;
      let next = prev + h.dir * speed * dt;
      if (next <= left) {
        next = left;
        h.dir = 1;
        h.pause = h.endPause ?? 0.55;
      } else if (next >= right) {
        next = right;
        h.dir = -1;
        h.pause = h.endPause ?? 0.55;
      }
      const dx = next - prev;
      if (player?.alive && player.onGround) {
        const ride = {
          x: prev,
          y: h.y,
          w: h.w,
          h: h.h,
        };
        const feet = { x: player.x, y: player.y + player.h - 6, w: player.w, h: 10 };
        if (aabb(feet, ride)) {
          const crushed = {
            x: player.x + dx,
            y: player.y,
            w: player.w,
            h: player.h,
          };
          const wall = (game.world.solids || []).some((s) => !s.moverId && aabb(crushed, s) && s.y + 12 < player.footY);
          if (!wall) {
            player.x += dx;
            player._syncFeet?.();
          } else {
            next = prev;
            h.dir *= -1;
            h.pause = 0.4;
          }
        }
      }
      h.moverX = next;
      h.x = next;
    }
  }
  injectMoverSolids(game.world);
}

function injectMoverSolids(world) {
  if (!world) return;
  world.moverSolids = (world.hazards || [])
    .filter((h) => h.kind === "camera_rig" && h.enabled)
    .map((h) => ({
      x: h.moverX ?? h.x,
      y: h.y,
      w: h.w,
      h: h.h,
      moverId: h.id,
    }));
  syncDoorSolids(world);
}

export function tickHazards(game, dt) {
  if (!game.world) return;
  const freeze = freezeEnv(game);
  const quietX = game.world.hazardQuietX;
  const px = game.player?.footX ?? 0;
  for (const h of game.world.hazards || []) {
    if (h.cool > 0) h.cool -= dt;
    if (!h.enabled) continue;
    if (Number.isFinite(quietX) && (h.x > quietX || (h.cartX || 0) > quietX)) {
      if (CYCLE.has(h.kind) && h.kind !== "falling_light") enterPhase(h, "idle");
      continue;
    }
    if (freeze) continue;
    if (!CYCLE.has(h.kind) && h.kind !== "camera_rig") {
      if (!game.player?.alive) continue;
      if (h.cool > 0 || !isHazardDamaging(h)) continue;
      dealHazard(game, h, hitBox(h), h.knockback);
      continue;
    }
    if (h.kind === "camera_rig") continue;
    if (h.kind === "steam_vent" || h.kind === "electrical_floor") tickCycle(game, h, dt);
    else if (h.kind === "falling_light") tickFalling(game, h, dt);
    else if (h.kind === "rolling_cart") tickCart(game, h, dt);
  }
  tickAmbienceAudio(game);
}

function tickCycle(game, h, dt) {
  h.phase = h.phase || "idle";
  h.phaseAge = (h.phaseAge || 0) + dt;
  const tel = h.telegraphDuration ?? 0.8;
  const act = h.activeDuration ?? 1.2;
  const cd = h.inactiveDuration ?? h.cooldown ?? 2.2;
  if (h.phase === "idle") {
    h._sfxTel = false;
    if (h.phaseAge > 0.45) enterPhase(h, "telegraph");
  } else if (h.phase === "telegraph") {
    sfxOnce(game, h, "_sfxTel", h.kind === "steam_vent" ? "env_steam" : "env_electric");
    if (h.phaseAge >= tel) {
      h._sfxTel = false;
      enterPhase(h, "active");
    }
  } else if (h.phase === "active") {
    if (h.damage > 0 && game.player?.alive) {
      const box = h.kind === "steam_vent" ? clipAgainstSolids(game.world, hitBox(h)) : hitBox(h);
      dealHazard(game, h, box, h.knockback);
    }
    if (h.phaseAge >= act) enterPhase(h, "cooldown");
  } else if (h.phase === "cooldown" && h.phaseAge >= cd) {
    enterPhase(h, "idle");
  }
}

function tickFalling(game, h, dt) {
  h.phase = h.phase || "idle";
  if (h.phase === "spent") return;
  h.phaseAge = (h.phaseAge || 0) + dt;
  const trig = h.trigger || { x: h.x - 80, y: 0, w: 220, h: DESIGN_H };
  if (h.phase === "idle") {
    if (game.player?.alive && aabb(game.player.bounds(), trig)) {
      h.dropX = h.impactX ?? h.x + h.w / 2;
      h.dropY = h.ceilingY ?? 80;
      h.impactY = h.impactY ?? game.world.ground?.y ?? 960;
      h.fixtureY = h.dropY;
      enterPhase(h, "telegraph");
      if (onCam(game, h.dropX)) game.sfx("env_alarm", { x: h.dropX });
      game.dangerZones.push({
        x: h.dropX - (h.impactRadius || 65),
        y: h.impactY - 16,
        w: (h.impactRadius || 65) * 2,
        h: 20,
        life: h.telegraphDuration ?? 1.2,
        delay: 0,
        damage: 0,
        owner: "env",
        kind: "fall_mark",
        hit: true,
        age: 0,
      });
    }
    return;
  }
  if (h.phase === "telegraph") {
    h.fixtureY = (h.ceilingY ?? 80) + Math.sin(h.phaseAge * 28) * 5;
    if (h.phaseAge >= (h.telegraphDuration ?? 1.2)) {
      enterPhase(h, "fall");
      h.dropY = h.fixtureY;
    }
    return;
  }
  if (h.phase === "fall") {
    h.dropY += 920 * dt;
    if (h.dropY >= (h.impactY || 960) - 20) {
      enterPhase(h, "impact");
      if (game.shakeEnabled()) game.camera.addShake(0.28);
      game.sfx("env_impact", { x: h.dropX });
    }
    return;
  }
  if (h.phase === "impact") {
    if (h.damage > 0 && h.phaseAge < 0.18) dealHazard(game, h, hitBox(h), 200);
    if (h.phaseAge > 0.25) enterPhase(h, h.reset ? "idle" : "spent");
  }
}

function tickCart(game, h, dt) {
  if (game.player?.mounted) return;
  h.phase = h.phase || "idle";
  h.phaseAge = (h.phaseAge || 0) + dt;
  const left = h.pathLeft ?? h.x;
  const right = h.pathRight ?? h.x + 400;
  if (h.phase === "idle") {
    const ready = !h.triggerX || (game.player?.footX ?? 0) >= h.triggerX;
    if (ready && h.phaseAge > (h.idleWait || 1.2)) {
      enterPhase(h, "telegraph");
      if (onCam(game, h.triggerX || h.x)) game.sfx("env_alarm", { x: h.triggerX || h.x });
    }
    return;
  }
  if (h.phase === "telegraph") {
    if (h.phaseAge >= (h.telegraphDuration ?? 0.9)) {
      const start = h.dir < 0 ? right : left;
      const spawn = { x: start, y: h.y, w: h.w, h: h.h };
      if (game.player?.alive && aabb(game.player.bounds(), spawn)) {
        h.phaseAge = (h.telegraphDuration ?? 0.9) - 0.25;
        return;
      }
      h.cartX = start;
      h.visible = true;
      enterPhase(h, "active");
      if (onCam(game, start)) game.sfx("env_cart", { x: start });
    }
    return;
  }
  if (h.phase === "active") {
    const dir = h.dir || 1;
    h.cartX += dir * (h.speed || 380) * dt;
    if (h.damage > 0) dealHazard(game, h, hitBox(h), h.knockback || 340);
    const gone = dir > 0 ? h.cartX > right + 40 : h.cartX < left - 40;
    if (gone) {
      h.visible = false;
      enterPhase(h, h.reset === false ? "spent" : "cooldown");
    }
    return;
  }
  if (h.phase === "cooldown" && h.phaseAge >= (h.inactiveDuration ?? 7)) enterPhase(h, "idle");
}

function tickAmbienceAudio(game) {
  if (game.world?.id !== "studio_01") return;
  if (freezeEnv(game) || game.state?.get?.() !== "PLAYING") {
    game.audio?.stopSound?.("env_ambience");
    return;
  }
  game.audio?.ensureLoop?.("env_ambience", { x: (game.camera?.x || 0) + 400 });
}

export function drawAmbients(ctx, game, layer) {
  const list = (game.world?.ambients || []).filter((a) => (a.layer || "back") === layer);
  const t = game._worldTime || 0;
  const cam = game.camera;
  const density = particleMul(game);
  const p = game.player;
  for (const a of list) {
    if (!onCam(game, a.x, 160)) continue;
    const s = cam.worldToScreen(a.x, a.y);
    const overlap =
      layer === "front" &&
      p &&
      aabb(p.bounds(), { x: a.x, y: a.y, w: a.w || 90, h: a.h || 220 });
    ctx.save();
    ctx.globalAlpha = overlap ? 0.28 : a.alpha ?? 0.85;
    drawAmbientKind(ctx, a, s, t, density, flashMul(game));
    ctx.restore();
  }
}

function drawAmbientKind(ctx, a, s, t, density, flash) {
  const kind = a.kind;
  if (kind === "monitor") {
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(s.x, s.y, 54, 36);
    ctx.fillStyle = `rgba(34, 211, 238, ${0.25 + 0.2 * Math.sin(t * 7 + a.x) * flash})`;
    ctx.fillRect(s.x + 4, s.y + 4, 46, 22);
  } else if (kind === "reel") {
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(s.x + 18, s.y + 18, 16, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(s.x + 18, s.y + 18, 6, t * 2.2, t * 2.2 + 1.2);
    ctx.stroke();
  } else if (kind === "fan") {
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = 2;
    for (let i = 0; i < 3; i += 1) {
      const ang = t * 4 + (i * Math.PI * 2) / 3;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(s.x + Math.cos(ang) * 22, s.y + Math.sin(ang) * 22);
      ctx.stroke();
    }
  } else if (kind === "warning" || kind === "tally") {
    const on = (Math.sin(t * (kind === "tally" ? 10 : 4) + a.x) * 0.5 + 0.5) * flash;
    ctx.fillStyle = kind === "tally" ? `rgba(248,113,113,${0.3 + on * 0.6})` : `rgba(250,204,21,${0.25 + on * 0.5})`;
    ctx.beginPath();
    ctx.arc(s.x, s.y, kind === "tally" ? 6 : 8, 0, Math.PI * 2);
    ctx.fill();
  } else if (kind === "spark" && density > 0.2) {
    if ((t * 9 + a.x) % 1.6 < 0.12 * flash) {
      ctx.fillStyle = "#e0f2fe";
      ctx.fillRect(s.x, s.y, 3, 10);
    }
  } else if (kind === "steam_puff") {
    ctx.fillStyle = `rgba(226,232,240,${0.12 + 0.08 * Math.sin(t * 3 + a.x)})`;
    ctx.beginPath();
    ctx.ellipse(s.x, s.y - (t * 18) % 30, 10, 16, 0, 0, Math.PI * 2);
    ctx.fill();
  } else if (kind === "cable") {
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.quadraticCurveTo(s.x + 20, s.y + 40 + Math.sin(t * 1.4 + a.x) * 6, s.x + 8, s.y + 90);
    ctx.stroke();
  } else if (kind === "dust" && density > 0.3) {
    ctx.fillStyle = "rgba(253, 230, 138, 0.18)";
    for (let i = 0; i < Math.round(5 * density); i += 1) {
      const px = s.x + ((Math.sin(t * 0.6 + i + a.x) * 0.5 + 0.5) * (a.w || 80));
      const py = s.y + ((t * 12 + i * 17 + a.x) % (a.h || 120));
      ctx.fillRect(px, py, 2, 2);
    }
  } else if (kind === "silhouette") {
    ctx.fillStyle = "rgba(15, 23, 42, 0.55)";
    ctx.fillRect(s.x, s.y, 28, 70);
    ctx.beginPath();
    ctx.arc(s.x + 14, s.y - 6, 10, 0, Math.PI * 2);
    ctx.fill();
  } else if (kind === "elevator") {
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(s.x, s.y, 70, 110);
    ctx.fillStyle = "#334155";
    const lift = (Math.sin(t * 0.7) * 0.5 + 0.5) * 40;
    ctx.fillRect(s.x + 8, s.y + 8 + lift, 54, 28);
  } else if (kind === "barber_light") {
    ctx.fillStyle = `rgba(248, 250, 252, ${0.35 + 0.25 * Math.sin(t * 5 + a.x) * flash})`;
    ctx.fillRect(s.x, s.y, 16, 48);
    ctx.fillStyle = "#ef4444";
    ctx.fillRect(s.x + 4, s.y + 6, 8, 8);
  } else {
    ctx.fillStyle = "#475569";
    ctx.fillRect(s.x, s.y, 24, 24);
  }
}

export function drawHazardFx(ctx, game) {
  const sheet = game.assets?.sheet("hazards");
  const t = game._worldTime || 0;
  const flash = flashMul(game);
  for (const h of game.world?.hazards || []) {
    if (!h.enabled && h.kind !== "falling_light") continue;
    if (!onCam(game, h.drawX ?? h.x, 200)) continue;
    const vis = h.vis || 128;
    const s = game.camera.worldToScreen(h.drawX ?? h.x, h.drawY ?? h.y);
    if (h.kind === "camera_rig") {
      const p = game.camera.worldToScreen(h.moverX ?? h.x, h.y);
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(p.x, p.y, h.w, h.h);
      ctx.fillStyle = "#22d3ee";
      ctx.fillRect(p.x + 8, p.y + 4, 28, 16);
      ctx.fillStyle = `rgba(248,113,113,${0.4 + 0.4 * Math.sin(t * 8)})`;
      ctx.beginPath();
      ctx.arc(p.x + 18, p.y + 8, 4, 0, Math.PI * 2);
      ctx.fill();
      continue;
    }
    if (h.kind === "rolling_cart" && h.phase === "active" && h.visible !== false) {
      const p = game.camera.worldToScreen(h.cartX, h.y);
      ctx.fillStyle = "#334155";
      ctx.fillRect(p.x, p.y, h.w, h.h);
      ctx.fillStyle = "#0f172a";
      ctx.beginPath();
      ctx.arc(p.x + 18, p.y + h.h, 10, 0, Math.PI * 2);
      ctx.arc(p.x + h.w - 18, p.y + h.h, 10, 0, Math.PI * 2);
      ctx.fill();
      continue;
    }
    if (h.kind === "falling_light") {
      const mark = game.camera.worldToScreen((h.dropX || h.x) - (h.impactRadius || 65), (h.impactY || h.y) - 12);
      if (h.phase === "telegraph" || h.phase === "fall") {
        ctx.fillStyle = `rgba(250, 204, 21, ${0.25 * flash})`;
        ctx.fillRect(mark.x, mark.y, (h.impactRadius || 65) * 2, 16);
        if (symbols(game)) {
          ctx.fillStyle = "#f8fafc";
          ctx.font = "bold 22px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText("!", mark.x + (h.impactRadius || 65), mark.y - 8);
        }
      }
      if (h.phase === "telegraph" || h.phase === "fall" || h.phase === "impact" || h.phase === "spent") {
        const fy = h.phase === "spent" || h.phase === "impact" ? (h.impactY || h.y) - 40 : h.dropY ?? h.fixtureY ?? 80;
        const fp = game.camera.worldToScreen((h.dropX || h.x) - 24, fy);
        if (!drawSheetFrame(ctx, sheet, 2, fp.x - 40, fp.y - 40, vis, vis)) {
          ctx.fillStyle = h.phase === "spent" ? "#475569" : "#fbbf24";
          ctx.fillRect(fp.x, fp.y, 48, 28);
        }
      }
      continue;
    }
    drawSheetFrame(ctx, sheet, h.frame || 0, s.x, s.y, vis, vis);
    if (h.kind === "steam_vent") {
      const box = hitBox(h);
      const p = game.camera.worldToScreen(box.x, box.y);
      if (h.phase === "telegraph") {
        ctx.fillStyle = `rgba(226,232,240,${0.2 * flash})`;
        ctx.fillRect(p.x, p.y + box.h - 28, box.w, 24);
        if (symbols(game)) {
          ctx.fillStyle = "#f8fafc";
          ctx.font = "bold 18px sans-serif";
          ctx.fillText("!", p.x + box.w / 2, p.y + box.h - 36);
        }
      } else if (h.phase === "active") {
        ctx.fillStyle = "rgba(241,245,249,0.45)";
        ctx.fillRect(p.x, p.y, box.w, box.h);
      }
    }
    if (h.kind === "electrical_floor") {
      const box = hitBox(h);
      const p = game.camera.worldToScreen(box.x, box.y);
      if (h.phase === "telegraph") {
        ctx.fillStyle = `rgba(165,243,252,${0.25 * flash})`;
        ctx.fillRect(p.x, p.y, box.w, box.h);
        if (symbols(game)) {
          ctx.fillStyle = "#f8fafc";
          ctx.font = "bold 18px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText("!", p.x + box.w / 2, p.y - 8);
        }
      } else if (h.phase === "active") {
        ctx.fillStyle = "rgba(224,242,254,0.7)";
        ctx.fillRect(p.x, p.y, box.w, box.h);
        ctx.fillStyle = "#22d3ee";
        for (let i = 0; i < 4; i += 1) ctx.fillRect(p.x + 8 + i * (box.w / 4), p.y - 10, 2, 14);
      }
    }
    if ((h.phase === "telegraph" || h.phase === "active") && h.kind === "rolling_cart" && symbols(game)) {
      const p = game.camera.worldToScreen(h.triggerX || h.pathLeft || h.x, h.y - 40);
      ctx.fillStyle = "#f8fafc";
      ctx.font = "bold 20px sans-serif";
      ctx.fillText("!", p.x, p.y);
    }
  }
}

export function drawForegroundSilhouettes(ctx, game) {
  warnMissingEnvAsset("environment/studio_01/foreground_silhouettes.png");
  const cam = game.camera;
  const shift = (cam.x * 1.18) % 640;
  const p = game.player;
  ctx.save();
  for (let x = -shift - 80; x < DESIGN_W + 80; x += 640) {
    const worldX = cam.x + x;
    const overlap = p && Math.abs(p.footX - worldX - 40) < 90;
    ctx.globalAlpha = overlap ? 0.18 : 0.32;
    ctx.fillStyle = "#020617";
    ctx.fillRect(x, DESIGN_H - 220, 70, 220);
    ctx.fillRect(x + 200, DESIGN_H - 160, 40, 160);
  }
  ctx.restore();
}

export function drawEnvDebug(ctx, game) {
  if (!game.debug && !DEBUG_COMBAT) return;
  const cam = game.camera;
  ctx.save();
  ctx.lineWidth = 1;
  for (const h of game.world?.hazards || []) {
    const box = hitBox(h);
    const s = cam.worldToScreen(box.x, box.y);
    ctx.strokeStyle = isHazardDamaging(h) ? "#ef4444" : "#fbbf24";
    ctx.strokeRect(s.x, s.y, box.w, box.h);
    if (h.trigger) {
      const t = cam.worldToScreen(h.trigger.x, h.trigger.y);
      ctx.strokeStyle = "#38bdf8";
      ctx.strokeRect(t.x, t.y, h.trigger.w, h.trigger.h);
    }
    ctx.fillStyle = "#e2e8f0";
    ctx.font = "11px monospace";
    ctx.fillText(`${h.kind} ${h.phase || "on"} ${(h.phaseAge || 0).toFixed(1)}`, s.x, s.y - 4);
  }
  for (const m of game.world?.moverSolids || []) {
    const s = cam.worldToScreen(m.x, m.y);
    ctx.strokeStyle = "#22d3ee";
    ctx.strokeRect(s.x, s.y, m.w, m.h);
  }
  for (const cp of game.world?.checkpoints || []) {
    const s = cam.worldToScreen(cp.x, cp.y);
    ctx.strokeStyle = "#2dd4bf";
    ctx.strokeRect(s.x, s.y, cp.w, cp.h);
  }
  const boss = (game.world?.encounters || []).find((e) => e.boss);
  if (boss) {
    const s = cam.worldToScreen(boss.activateX, 40);
    ctx.strokeStyle = "#f59e0b";
    ctx.beginPath();
    ctx.moveTo(s.x, 40);
    ctx.lineTo(s.x, DESIGN_H - 40);
    ctx.stroke();
    ctx.fillText("boss video", s.x + 6, 56);
  }
  if (game.player) {
    const safe = { x: game.player.footX - 40, y: game.player.footY - 170, w: 80, h: 170 };
    const s = cam.worldToScreen(safe.x, safe.y);
    ctx.strokeStyle = "#86efac";
    ctx.strokeRect(s.x, s.y, safe.w, safe.h);
  }
  ctx.restore();
}

export function lockedArena(game) {
  const be = game.bossEncounter;
  if (be?.arenaLocked) {
    const box = be.arenaBox?.();
    if (box) return { left: box.left, right: box.right, lookScale: 1.15, focusX: 0.46 };
  }
  const enc = (game.world?.encounters || []).find((e) => e.scripted && e.locked && !e.cleared);
  if (!enc) return null;
  return { left: enc.arenaLeft, right: enc.arenaRight };
}

export { CYCLE, clamp };
