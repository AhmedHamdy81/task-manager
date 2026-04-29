/**
 * Live progress for machine "Copy Material" tasks — DOM bar + meta (capped at 100%).
 */
(function () {
  "use strict";

  var FILL_CLASS_PREFIX = "task-progress-fill--";

  function pad2(n) {
    var x = Math.floor(Number(n)) || 0;
    return x < 10 ? "0" + x : String(x);
  }

  function fmtEtaFromUtcMs(ms) {
    var iso = new Date(ms).toISOString();
    if (typeof window.tmDateTime !== "undefined" && window.tmDateTime.formatTimeCairo) {
      return window.tmDateTime.formatTimeCairo(iso);
    }
    var d = new Date(ms);
    return pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes());
  }

  function clearFillTier(fillEl) {
    var cl = fillEl.classList;
    ["low", "mid", "high", "over", "done"].forEach(function (suffix) {
      cl.remove(FILL_CLASS_PREFIX + suffix);
    });
  }

  function setFillTier(fillEl, tier) {
    clearFillTier(fillEl);
    if (tier) fillEl.classList.add(FILL_CLASS_PREFIX + tier);
  }

  function updateNode(root) {
    var status = (root.getAttribute("data-status") || "").trim();
    var estRaw = root.getAttribute("data-est-min");
    var est = parseInt(estRaw, 10);
    var startedMs = parseInt(root.getAttribute("data-started-ms"), 10) || 0;
    var barEl = root.querySelector(".task-progress-bar");
    var fillEl = root.querySelector(".task-progress-fill");
    var metaEl = root.querySelector(".task-progress-meta");
    if (!fillEl || !metaEl) return;

    function aria(pct) {
      if (barEl) {
        barEl.setAttribute("aria-valuenow", String(Math.round(pct)));
      }
    }

    if (status === "done") {
      fillEl.style.width = "100%";
      setFillTier(fillEl, "done");
      metaEl.textContent = "100% · Finished";
      aria(100);
      return;
    }

    if (!startedMs || !isFinite(est) || est < 1) {
      fillEl.style.width = "0%";
      clearFillTier(fillEl);
      metaEl.textContent = "—";
      aria(0);
      return;
    }

    var now = Date.now();
    var elapsedMin = (now - startedMs) / 60000;
    var calculatedPercent = Math.floor((elapsedMin / est) * 100);
    var displayPercent = Math.max(0, Math.min(100, calculatedPercent));

    if (elapsedMin >= est) {
      fillEl.style.width = "100%";
      setFillTier(fillEl, "over");
      metaEl.textContent = "100% · ⏱ In progress";
      aria(100);
      if (root.getAttribute("data-offer-convert") === "1" && root.dataset.tmEstimateCompleteFired !== "1") {
        root.dataset.tmEstimateCompleteFired = "1";
        try {
          root.dispatchEvent(new CustomEvent("tm:mr-copy-estimate-elapsed", { bubbles: true }));
        } catch (e) {
          /* ignore */
        }
      }
      return;
    }

    fillEl.style.width = displayPercent + "%";
    if (displayPercent < 70) {
      setFillTier(fillEl, "low");
    } else if (displayPercent <= 90) {
      setFillTier(fillEl, "mid");
    } else {
      setFillTier(fillEl, "high");
    }

    var remaining = Math.max(0, Math.ceil(est - elapsedMin));
    var etaMs = startedMs + est * 60000;
    metaEl.textContent =
      displayPercent + "% · ⏱ " + remaining + "m left · ETA " + fmtEtaFromUtcMs(etaMs);
    aria(displayPercent);
  }

  function updateTaskUI() {
    document.querySelectorAll(".task-copy-live").forEach(updateNode);
  }

  function hasActiveCopy() {
    var roots = document.querySelectorAll(".task-copy-live");
    for (var i = 0; i < roots.length; i++) {
      if ((roots[i].getAttribute("data-status") || "").trim() !== "done") return true;
    }
    return false;
  }

  function boot() {
    updateTaskUI();
    if (hasActiveCopy()) {
      setInterval(updateTaskUI, 10000);
    }
  }

  window.__tmTaskCopyLiveRefresh = function () {
    updateTaskUI();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
