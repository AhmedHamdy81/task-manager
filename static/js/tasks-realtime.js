/**
 * After task mutations (Socket.IO `tasks_changed`), refresh in-page task HTML without a full reload.
 */
(function () {
  "use strict";

  var debounceTimer = null;
  var DEBOUNCE_MS = 280;

  function debouncedSchedule(payload) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      runRefresh(payload || {});
    }, DEBOUNCE_MS);
  }

  function fetchText(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.text();
    });
  }

  function projectPanelShouldRefresh(payload, panel) {
    var ids = payload.project_ids;
    if (!ids || !ids.length) return true;
    var raw = panel.getAttribute("data-project-id");
    var pid = parseInt(raw, 10);
    if (!pid) return false;
    for (var i = 0; i < ids.length; i++) {
      if (Number(ids[i]) === pid) return true;
    }
    return false;
  }

  function runRefresh(payload) {
    var urls = window.__tmTaskFragmentUrls || {};
    var chain = Promise.resolve();

    var dash = document.getElementById("dashboard-machine-room-tasks");
    if (dash && urls.dashboardMrTasks) {
      chain = chain.then(function () {
        return fetchText(urls.dashboardMrTasks);
      }).then(function (html) {
        var wrap = document.createElement("div");
        wrap.innerHTML = html.trim();
        var next = wrap.firstElementChild;
        if (next && next.id === "dashboard-machine-room-tasks") {
          dash.replaceWith(next);
        }
        if (window.__tmDashboardMrPostcopyReinit) window.__tmDashboardMrPostcopyReinit();
        if (window.__tmTaskCopyLiveRefresh) window.__tmTaskCopyLiveRefresh();
      });
    }

    var mrZone = document.getElementById("mr-tasks-refresh-zone");
    var tasksRoot = document.getElementById("tasks-page-root");
    var mrFragUrl =
      tasksRoot && tasksRoot.getAttribute("data-tm-tasks-fragment-url");
    if (mrZone && (mrFragUrl || urls.machineRoomTasksZone)) {
      chain = chain.then(function () {
        var u = mrFragUrl || urls.machineRoomTasksZone;
        u += (typeof window.location !== "undefined" && window.location.search) || "";
        return fetchText(u);
      }).then(function (html) {
        mrZone.innerHTML = html.trim();
        if (window.__tmTasksPageRefreshStream) window.__tmTasksPageRefreshStream();
        if (window.__tmDashboardMrPostcopyReinit) window.__tmDashboardMrPostcopyReinit();
        if (window.__tmTaskCopyLiveRefresh) window.__tmTaskCopyLiveRefresh();
      });
    }

    var root = document.getElementById("tasks-page-root");
    var slot = document.getElementById("tm-tasks-my-stream-slot");
    if (root && slot && urls.tasksMyStream) {
      chain = chain.then(function () {
        return fetchText(urls.tasksMyStream);
      }).then(function (html) {
        slot.innerHTML = html.trim();
        if (window.__tmTasksPageRefreshStream) window.__tmTasksPageRefreshStream();
        if (window.__tmTaskCopyLiveRefresh) window.__tmTaskCopyLiveRefresh();
      });
    }

    var panel = document.getElementById("project-tasks-panel");
    var body = document.getElementById("project-tasks-panel-body");
    var purl =
      panel &&
      panel.getAttribute("data-tm-project-tasks-fragment-url");
    if (panel && body && purl && projectPanelShouldRefresh(payload, panel)) {
      chain = chain.then(function () {
        return fetchText(purl);
      }).then(function (html) {
        body.innerHTML = html.trim();
        if (window.__tmTaskCopyLiveRefresh) window.__tmTaskCopyLiveRefresh();
      });
    }

    chain.catch(function () {
      /* silent: network or session edge cases */
    });
  }

  function attachSocket(socket) {
    if (!socket || socket.__tmTasksChangedAttached) return;
    socket.__tmTasksChangedAttached = true;
    socket.on("tasks_changed", function (payload) {
      debouncedSchedule(payload);
    });
  }

  function boot() {
    var s = window.__tmSocket;
    if (s) attachSocket(s);
    else {
      var n = 0;
      var t = setInterval(function () {
        n += 1;
        if (window.__tmSocket) {
          clearInterval(t);
          attachSocket(window.__tmSocket);
        } else if (n > 200) {
          clearInterval(t);
        }
      }, 50);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
