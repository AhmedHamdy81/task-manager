(function () {
  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function extractNotifications(payload) {
    if (!payload || typeof payload !== "object") return [];
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload.notifications)) return payload.notifications;
    if (Array.isArray(payload.items)) return payload.items;
    return [];
  }

  function normalizeNotification(n) {
    if (!n || typeof n !== "object") return null;
    return {
      id: n.id != null ? Number(n.id) : 0,
      title: n.title != null ? String(n.title) : "",
      message: n.message != null ? String(n.message) : "",
      severity: (n.severity && String(n.severity).toLowerCase()) || "info",
      type: (n.type && String(n.type).toLowerCase()) || "activity",
      entity_type: n.entity_type != null ? String(n.entity_type) : "",
      entity_id: n.entity_id != null ? Number(n.entity_id) : 0,
      project_id: n.project_id != null ? n.project_id : null,
      is_read: !!n.is_read,
      is_acknowledged: !!n.is_acknowledged,
      is_resolved: !!n.is_resolved,
      created_at: n.created_at != null ? String(n.created_at) : "",
      created_ago: n.created_ago != null ? String(n.created_ago) : "",
    };
  }

  ready(function () {
    var panel = document.getElementById("notif-panel");
    if (!panel) {
      console.warn("[notifications] panel #notif-panel not found (signed out or layout)");
      return;
    }
    var listEl =
      document.getElementById("notif-list") || panel.querySelector("#notif-list");
    if (!listEl) {
      console.error("[notifications] #notif-list not found inside panel");
      return;
    }
    var markAllBtn = document.getElementById("mark-all-read");
    var notifBtn = document.getElementById("notif-btn");
    var notifBadge = document.getElementById("notif-badge");
    var muteBtn = document.getElementById("notif-mute");
    var closeBtn = document.getElementById("notif-close");

    var listUrl = panel.getAttribute("data-list-url") || "/notifications";
    var readBase = panel.getAttribute("data-read-url-base") || "/notifications/read/";
    var ackBase = panel.getAttribute("data-ack-url-base") || "/notifications/ack/";
    var resolveBase = panel.getAttribute("data-resolve-url-base") || "/notifications/resolve/";
    var readAllUrl = panel.getAttribute("data-read-all-url") || "/notifications/read-all";
    var filter = "all";
    var muteStorageKey = "notif_muted";
    var lastUnreadCount = null;
    var notificationSound = null;

    function resolveSoundUrl() {
      var chat = document.getElementById("global-chat-container");
      var fromChat = chat ? chat.getAttribute("data-notify-sound-url") : "";
      return fromChat || "/static/sounds/notify.mp3";
    }

    function ensureSound() {
      if (notificationSound) return notificationSound;
      try {
        notificationSound = new Audio(resolveSoundUrl());
        notificationSound.preload = "auto";
      } catch (_err) {
        notificationSound = null;
      }
      return notificationSound;
    }

    function isMuted() {
      try {
        return window.localStorage.getItem(muteStorageKey) === "1";
      } catch (_err) {
        return false;
      }
    }

    function updateMuteIcon() {
      if (!muteBtn) return;
      muteBtn.textContent = isMuted() ? "🔇" : "🔊";
      muteBtn.setAttribute(
        "aria-label",
        isMuted() ? "Unmute notification sound" : "Mute notification sound"
      );
      muteBtn.setAttribute("title", isMuted() ? "Sound muted" : "Sound on");
    }

    function toggleMute() {
      try {
        window.localStorage.setItem(muteStorageKey, isMuted() ? "0" : "1");
      } catch (_err) {}
      updateMuteIcon();
    }

    function updateBadge(count) {
      if (!notifBadge) return;
      var c = Number(count) || 0;
      if (c > 0) {
        notifBadge.style.display = "inline-block";
        notifBadge.textContent = String(c);
      } else {
        notifBadge.style.display = "none";
        notifBadge.textContent = "0";
      }
    }

    function playNewNotificationSound() {
      if (isMuted()) return;
      var snd = ensureSound();
      if (!snd) return;
      try {
        snd.currentTime = 0;
        var p = snd.play();
        if (p && typeof p.catch === "function") p.catch(function () {});
      } catch (_err) {}
    }

    function setPanelOpen(open) {
      panel.classList.toggle("open", !!open);
      if (notifBtn) {
        notifBtn.setAttribute("aria-expanded", open ? "true" : "false");
      }
    }

    function handleOutsideClick(e) {
      if (panel.contains(e.target)) return;
      if (notifBtn && notifBtn.contains(e.target)) return;
      setPanelOpen(false);
    }

    function post(url) {
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      }).then(function (r) {
        if (!r.ok) throw new Error("request_failed");
        return r.json().catch(function () {
          return { ok: false };
        });
      });
    }

    function openEntity(n) {
      var type = String(n.entity_type || "").toLowerCase();
      var entityId = n.entity_id != null ? Number(n.entity_id) : 0;
      var projectId = n.project_id != null ? n.project_id : null;

      if (type === "shooting_day" && projectId != null) {
        var hash =
          entityId && !Number.isNaN(entityId) ? "#day-" + String(entityId) : "";
        window.location.href =
          "/projects/" + String(projectId) + "/production" + hash;
        return;
      }
      if (type === "hdd" && projectId != null) {
        window.location.href = "/machine/project/" + String(projectId);
        return;
      }
      if (type === "booking") {
        window.location.href = "/booking";
        return;
      }
      if (type === "vfx" && projectId != null) {
        window.location.href = "/projects/" + String(projectId) + "/vfx";
        return;
      }
      if (type === "task") {
        window.location.href = "/tasks";
        return;
      }
      if (type === "project" && projectId != null) {
        window.location.href = "/projects/" + String(projectId);
        return;
      }
      window.location.href = "/";
    }

    function render(list) {
      if (!Array.isArray(list) || !list.length) {
        listEl.innerHTML = '<p class="notif-empty">No notifications.</p>';
        return;
      }
      listEl.innerHTML = "";
      list.forEach(function (raw) {
        var n = normalizeNotification(raw);
        if (!n || raw.id == null || Number.isNaN(Number(raw.id))) return;
        var item = document.createElement("div");
        item.className = "notif-item " + esc(n.severity || "info");
        if (!n.is_read) item.className += " is-unread";
        if (n.is_acknowledged) item.className += " is-ack";
        var timeLine = "";
        if (
          typeof window.tmDateTime !== "undefined" &&
          window.tmDateTime.formatLocalTime &&
          n.created_at
        ) {
          timeLine = window.tmDateTime.formatLocalTime(n.created_at);
        }
        if (!timeLine && n.created_ago) timeLine = n.created_ago;
        item.innerHTML =
          '<div class="notif-main">' +
          "<strong>" +
          esc(n.title) +
          "</strong>" +
          "<p>" +
          esc(n.message) +
          "</p>" +
          "</div>" +
          '<div class="notif-meta">' +
          (timeLine
            ? '<div class="notif-time">' + esc(timeLine) + "</div>"
            : "") +
          "</div>" +
          '<div class="notif-actions">' +
          '<button type="button" class="btn btn--small btn--ghost js-open">Open</button>' +
          '<button type="button" class="btn btn--small btn--ghost js-ack">Ack</button>' +
          '<button type="button" class="btn btn--small btn--ghost js-resolve">Remove</button>' +
          "</div>";
        var btnOpen = item.querySelector(".js-open");
        var btnAck = item.querySelector(".js-ack");
        var btnResolve = item.querySelector(".js-resolve");
        if (btnOpen) {
          btnOpen.addEventListener("click", function () {
            openEntity(n);
          });
        }
        if (btnAck) {
          btnAck.addEventListener("click", function () {
            post(ackBase + String(n.id)).then(loadNotifications).catch(function () {});
          });
        }
        if (btnResolve) {
          btnResolve.addEventListener("click", function () {
            post(resolveBase + String(n.id)).then(loadNotifications).catch(function () {});
          });
        }
        item.addEventListener("click", function (e) {
          if (e.target && e.target.closest(".notif-actions")) return;
          if (!n.is_read) {
            post(readBase + String(n.id))
              .then(loadNotifications)
              .catch(function () {});
          }
        });
        listEl.appendChild(item);
      });
    }

    function loadNotifications() {
      var url = listUrl + "?limit=50&type=" + encodeURIComponent(filter);
      fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then(function (r) {
          if (!r.ok) {
            console.warn("[notifications] HTTP", r.status, url);
            throw new Error("request_failed");
          }
          return r.json();
        })
        .then(function (payload) {
          var list = extractNotifications(payload);
          render(list);
          var unreadCount = list.reduce(function (acc, raw) {
            var n = normalizeNotification(raw);
            return n && !n.is_read ? acc + 1 : acc;
          }, 0);
          updateBadge(unreadCount);
          if (lastUnreadCount !== null && unreadCount > lastUnreadCount) {
            playNewNotificationSound();
          }
          lastUnreadCount = unreadCount;
        })
        .catch(function (err) {
          console.warn("[notifications] fetch failed", err && err.message ? err.message : err);
        });
    }

    panel.querySelectorAll(".notif-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        filter = btn.getAttribute("data-filter") || "all";
        panel.querySelectorAll(".notif-filter").forEach(function (x) {
          x.classList.remove("is-active");
        });
        btn.classList.add("is-active");
        loadNotifications();
      });
    });

    if (markAllBtn) {
      markAllBtn.addEventListener("click", function () {
        post(readAllUrl).then(loadNotifications).catch(function () {});
      });
    }

    if (muteBtn) {
      muteBtn.addEventListener("click", function (e) {
        e.preventDefault();
        toggleMute();
      });
      updateMuteIcon();
    }

    if (notifBtn) {
      notifBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var opening = !panel.classList.contains("open");
        setPanelOpen(opening);
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", function (e) {
        e.preventDefault();
        setPanelOpen(false);
      });
    }

    document.addEventListener("click", handleOutsideClick);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setPanelOpen(false);
    });
    setPanelOpen(false);

    loadNotifications();
    window.tmReloadNotifications = loadNotifications;
    window.setInterval(loadNotifications, 15000);
  });
})();
