/**
 * Global appearance mode + accent (localStorage).
 * Early flash-prevention lives in base.html; this keeps system preference in sync
 * and exposes helpers for Profile controls.
 */
(function () {
  "use strict";

  var MODE_KEY = "appearanceMode";
  var ACCENT_KEY = "appearanceAccent";

  function applyMode(mode) {
    var root = document.documentElement;
    if (mode === "light") {
      root.setAttribute("data-theme", "light");
      return;
    }
    if (mode === "system") {
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        root.setAttribute("data-theme", "light");
      } else {
        root.removeAttribute("data-theme");
      }
      return;
    }
    root.removeAttribute("data-theme");
  }

  function applyAccent(accent) {
    var root = document.documentElement;
    if (accent && accent !== "default") {
      root.setAttribute("data-accent-theme", accent);
    } else {
      root.removeAttribute("data-accent-theme");
    }
  }

  function readMode() {
    try {
      return window.localStorage.getItem(MODE_KEY) || "dark";
    } catch (e) {
      return "dark";
    }
  }

  function readAccent() {
    try {
      return window.localStorage.getItem(ACCENT_KEY) || "default";
    } catch (e) {
      return "default";
    }
  }

  function syncFromStorage() {
    applyMode(readMode());
    applyAccent(readAccent());
  }

  window.TmAppearance = {
    applyMode: applyMode,
    applyAccent: applyAccent,
    readMode: readMode,
    readAccent: readAccent,
    syncFromStorage: syncFromStorage,
    MODE_KEY: MODE_KEY,
    ACCENT_KEY: ACCENT_KEY,
  };

  if (window.matchMedia) {
    var media = window.matchMedia("(prefers-color-scheme: light)");
    var onChange = function () {
      if (readMode() === "system") applyMode("system");
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
    } else if (typeof media.addListener === "function") {
      media.addListener(onChange);
    }
  }
})();
