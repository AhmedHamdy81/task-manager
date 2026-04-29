/**
 * Machine Room dashboard: "Finish now" or elapsed copy time reveals the
 * Convert choice panel; then POST with synced hidden fields.
 * Finish-now clicks are delegated from document so the dashboard panel can be replaced in place.
 */
(function () {
  "use strict";

  function parseInt10(v) {
    var n = parseInt(String(v || "").trim(), 10);
    return isNaN(n) ? 0 : n;
  }

  function syncPostcopyForm(form) {
    var startHidden = form.querySelector('input[name="start_convert"]');
    var minsHidden = form.querySelector('input[name="convert_minutes"]');
    var radios = form.querySelectorAll('input[type="radio"][name^="mr-start-convert-"]');
    var estInput = form.querySelector(".mr-convert-est-input");
    var wrapEst = estInput && estInput.closest(".task-item-mr-postcopy-est");
    var on = false;
    radios.forEach(function (r) {
      if (r.checked && String(r.value) === "1") on = true;
    });
    if (startHidden) startHidden.value = on ? "1" : "0";
    if (minsHidden) minsHidden.value = on && estInput ? String(parseInt10(estInput.value) || 0) : "";
    if (estInput) {
      estInput.disabled = !on;
      if (wrapEst) wrapEst.classList.toggle("is-muted", !on);
    }
  }

  function revealPostcopyPanel(form) {
    var wrap = form.closest(".task-item-mr-postcopy-wrap");
    if (wrap) {
      wrap.hidden = false;
      wrap.removeAttribute("hidden");
    }
    var panel = form.querySelector(".task-item-mr-postcopy");
    if (!panel) return;
    try {
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (e) {
      panel.scrollIntoView(false);
    }
    panel.classList.add("task-item-mr-postcopy--pulse");
    window.setTimeout(function () {
      panel.classList.remove("task-item-mr-postcopy--pulse");
    }, 2400);
    syncPostcopyForm(form);
  }

  function wireForm(form) {
    if (!form || form.getAttribute("data-mr-postcopy-wired") === "1") return;
    form.setAttribute("data-mr-postcopy-wired", "1");
    var radios = form.querySelectorAll('input[type="radio"][name^="mr-start-convert-"]');
    var estInput = form.querySelector(".mr-convert-est-input");

    radios.forEach(function (r) {
      r.addEventListener("change", function () {
        syncPostcopyForm(form);
      });
    });
    if (estInput) {
      estInput.addEventListener("input", function () {
        syncPostcopyForm(form);
      });
    }

    form.addEventListener("submit", function (e) {
      syncPostcopyForm(form);
      var startHidden = form.querySelector('input[name="start_convert"]');
      var minsHidden = form.querySelector('input[name="convert_minutes"]');
      var on = startHidden && String(startHidden.value) === "1";
      var mins = parseInt10(minsHidden && minsHidden.value);
      if (on && mins < 1) {
        e.preventDefault();
        window.alert("Enter an estimate of at least 1 minute for Convert, or choose No.");
        return;
      }
      var msg =
        "Mark this copy as finished and notify the project team?" +
        (on ? " A Convert task (~" + mins + "m) will be started." : " You chose not to start a Convert task (team will be notified).");
      if (!window.confirm(msg)) {
        e.preventDefault();
      }
    });

    syncPostcopyForm(form);
  }

  function mrMachineRoomTaskStreamPanel() {
    return document.getElementById("mr-machine-room-task-stream-panel");
  }

  function mrStreamZoneContaining(node) {
    var dash = document.getElementById("dashboard-machine-room-tasks");
    var mrPanel = mrMachineRoomTaskStreamPanel();
    if (dash && node && dash.contains(node)) return dash;
    if (mrPanel && node && mrPanel.contains(node)) return mrPanel;
    return null;
  }

  function onEstimateElapsed(ev) {
    var live = ev.target && ev.target.closest ? ev.target.closest(".task-copy-live") : null;
    if (!live) return;
    var zone = mrStreamZoneContaining(live);
    if (!zone) return;
    var tid = live.getAttribute("data-task-id") || "";
    var form = zone.querySelector('form[data-mr-postcopy-form][data-task-id="' + tid + '"]');
    if (!form) return;
    revealPostcopyPanel(form);
  }

  document.addEventListener("tm:mr-copy-estimate-elapsed", onEstimateElapsed);

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".mr-finish-now");
    if (!btn) return;
    var zone = mrStreamZoneContaining(btn);
    if (!zone) return;
    var article = btn.closest(".task-item");
    if (!article) return;
    var form = article.querySelector("form[data-mr-postcopy-form]");
    if (!form) return;
    revealPostcopyPanel(form);
  });

  function boot() {
    document.querySelectorAll("form[data-mr-postcopy-form]").forEach(wireForm);
  }

  window.__tmDashboardMrPostcopyReinit = boot;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
