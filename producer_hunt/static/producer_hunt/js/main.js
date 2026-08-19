import { DEBUG_ASSETS, DEBUG_QUERY } from "./config.js";
import { Game } from "./game.js";

const canvas = document.getElementById("ph-canvas");
const body = document.body;

function preventScroll(e) {
  const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"];
  if (keys.includes(e.code)) e.preventDefault();
}

window.addEventListener("keydown", preventScroll, { passive: false });

const params = new URLSearchParams(window.location.search);
const debug =
  DEBUG_ASSETS ||
  params.get(DEBUG_QUERY) === "1" ||
  params.get(DEBUG_QUERY) === "true";

const game = new Game(canvas, {
  exitUrl: body.dataset.exitUrl || "/",
  assetBase: body.dataset.assetBase || "",
  debug,
});
game.start();
window.__producerHunt = game;
