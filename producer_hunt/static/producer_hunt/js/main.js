import { ASSET_CACHE_KEY, DEBUG_ASSETS, DEBUG_QUERY } from "./config.js";
import { Game } from "./game.js";

const canvas = document.getElementById("ph-canvas");
const body = document.body;

const allowDebug = body.dataset.allowDebug === "1";
const params = new URLSearchParams(window.location.search);
const debug =
  allowDebug &&
  (DEBUG_ASSETS || params.get(DEBUG_QUERY) === "1" || params.get(DEBUG_QUERY) === "true");

let game = null;

try {
  if (!canvas) throw new Error("Missing #ph-canvas");
  game = new Game(canvas, {
    exitUrl: body.dataset.exitUrl || "/",
    assetBase: body.dataset.assetBase || "",
    cacheKey: body.dataset.assetVersion || ASSET_CACHE_KEY,
    debug,
    allowDebug,
    levelId: params.get("level") || "studio_01",
  });
  game.start();
  if (allowDebug) window.__producerHunt = game;
} catch (err) {
  console.error("Producer Hunt failed to initialize", err);
}

window.addEventListener("pagehide", () => {
  if (game) game.stop();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && game) game.start();
});
