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

  function checkedValue(name) {
    var input = document.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : "";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var root = document.getElementById("profile-appearance");
    if (!root) return;

    var savedMode = "dark";
    var savedAccent = "default";
    try {
      savedMode = window.localStorage.getItem(MODE_KEY) || "dark";
      savedAccent = window.localStorage.getItem(ACCENT_KEY) || "default";
    } catch (e) {}

    var modeInput = root.querySelector('input[name="appearance-mode"][value="' + savedMode + '"]');
    var accentInput = root.querySelector('input[name="appearance-accent"][value="' + savedAccent + '"]');
    if (modeInput) modeInput.checked = true;
    if (accentInput) accentInput.checked = true;

    applyMode(savedMode);
    applyAccent(savedAccent);

    root.querySelectorAll('input[name="appearance-mode"]').forEach(function (input) {
      input.addEventListener("change", function () {
        var mode = checkedValue("appearance-mode") || "dark";
        applyMode(mode);
        try {
          window.localStorage.setItem(MODE_KEY, mode);
        } catch (e) {}
      });
    });

    root.querySelectorAll('input[name="appearance-accent"]').forEach(function (input) {
      input.addEventListener("change", function () {
        var accent = checkedValue("appearance-accent") || "default";
        applyAccent(accent);
        try {
          window.localStorage.setItem(ACCENT_KEY, accent);
        } catch (e) {}
      });
    });

    if (window.matchMedia) {
      var media = window.matchMedia("(prefers-color-scheme: light)");
      var syncSystemMode = function () {
        var mode = "dark";
        try {
          mode = window.localStorage.getItem(MODE_KEY) || "dark";
        } catch (e) {}
        if (mode === "system") applyMode(mode);
      };
      if (typeof media.addEventListener === "function") {
        media.addEventListener("change", syncSystemMode);
      } else if (typeof media.addListener === "function") {
        media.addListener(syncSystemMode);
      }
    }
  });
})();
