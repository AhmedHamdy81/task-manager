/**
 * Notification threads — fold notifications about the same task into one card
 * with a live progress bar and a step track (used by the bell panel and Tasks page).
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function createdMs(n) {
    var t = n && n.created_at ? Date.parse(n.created_at) : NaN;
    return Number.isNaN(t) ? Number(n && n.id) || 0 : t;
  }

  function timeLabel(n) {
    if (window.tmDateTime && window.tmDateTime.formatLocalTime && n.created_at) {
      return window.tmDateTime.formatLocalTime(n.created_at);
    }
    return n.created_ago || "";
  }

  function isOngoingCopy(copy) {
    var s = String((copy && copy.status) || "").trim().toLowerCase();
    return s === "open" || s === "in_progress";
  }

  function copyTaskLiveHtml(copy) {
    if (!copy || copy.id == null) return "";
    return (
      '<div class="task-copy-live notif-copy-task-live" data-task-id="' +
      esc(String(copy.id)) +
      '" data-status="' +
      esc(copy.status || "open") +
      '" data-est-min="' +
      esc(copy.copy_estimated_minutes != null ? String(copy.copy_estimated_minutes) : "") +
      '" data-started-ms="' +
      esc(copy.started_ms != null ? String(copy.started_ms) : "0") +
      '" data-finished-ms="' +
      esc(copy.finished_ms != null ? String(copy.finished_ms) : "0") +
      '" data-duration-label="' +
      esc(copy.duration_label || "") +
      '">' +
      '<div class="task-progress">' +
      '<div class="task-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">' +
      '<div class="task-progress-fill" style="width: 0%;"></div>' +
      '<span class="task-progress-pct" aria-hidden="true"></span>' +
      "</div>" +
      '<div class="task-progress-meta" aria-live="polite"></div>' +
      "</div>" +
      "</div>"
    );
  }

  // Workflow notifications are titled "<project · days>: <step>"; copy tasks link via copy_task.
  function threadInfo(n) {
    var title = String(n.title || "");
    var pid = n.project_id != null ? String(n.project_id) : "";
    var sep = title.indexOf(": ");
    if (sep > 0) {
      var subject = title.slice(0, sep);
      return { key: "s:" + pid + ":" + subject, subject: subject, label: title.slice(sep + 2) };
    }
    var copy = n.copy_task;
    if (copy && copy.id != null) {
      var parts = title.split(" · ");
      var verb = copy.title === "Convert" ? "Converting" : "Copying";
      var unit = copy.copy_unit_number != null ? " · Unit " + copy.copy_unit_number : "";
      return {
        key: "t:" + copy.id,
        subject: (n.project_name ? n.project_name + " · " : "") + verb + " " + (copy.copy_day_name || "—") + unit,
        label: parts.length > 1 ? parts[parts.length - 1] : title,
      };
    }
    return null;
  }

  function group(list) {
    var entries = [];
    var byKey = {};
    (list || []).forEach(function (n) {
      if (!n || n.id == null) return;
      var info = threadInfo(n);
      if (!info) {
        entries.push({ kind: "single", n: n });
        return;
      }
      var entry = byKey[info.key];
      if (!entry) {
        entry = { kind: "thread", key: info.key, subject: info.subject, steps: [] };
        byKey[info.key] = entry;
        entries.push(entry);
      }
      entry.steps.push({ n: n, label: info.label });
    });
    return entries.map(function (entry) {
      if (entry.kind !== "thread") return entry;
      if (entry.steps.length === 1) return { kind: "single", n: entry.steps[0].n };
      entry.steps.sort(function (a, b) {
        return createdMs(a.n) - createdMs(b.n) || Number(a.n.id) - Number(b.n.id);
      });
      entry.latest = entry.steps[entry.steps.length - 1];
      entry.copyTask = null;
      for (var i = entry.steps.length - 1; i >= 0; i--) {
        if (entry.steps[i].n.copy_task) {
          entry.copyTask = entry.steps[i].n.copy_task;
          break;
        }
      }
      entry.ongoing = isOngoingCopy(entry.copyTask);
      entry.unread = entry.steps.filter(function (s) {
        return !s.n.is_read && !s.n.is_acknowledged && !s.n.is_resolved;
      }).length;
      entry.ids = entry.steps.map(function (s) {
        return s.n.id;
      });
      return entry;
    });
  }

  function detailHtml(step) {
    var n = step.n;
    var link =
      n.action_label && n.action_href
        ? ' <a class="notif-action-link" href="' + esc(n.action_href) + '">' + esc(n.action_label) + "</a>"
        : "";
    return (
      '<p class="notif-thread__detail-head"><strong>' + esc(step.label) + "</strong> · " + esc(timeLabel(n)) + "</p>" +
      "<p>" + esc(n.message) + link + "</p>"
    );
  }

  /**
   * opts: { ackLabel, removeLabel, onAck(ids), onResolve(ids), onRead(ids) }
   */
  function renderThread(thread, opts) {
    opts = opts || {};
    var latest = thread.latest;
    var el = document.createElement("div");
    el.className =
      "notif-item notif-thread " + esc(latest.n.severity || "info") + (thread.unread ? " is-unread" : "");
    el.dataset.threadKey = thread.key;

    var track = thread.steps
      .map(function (s, i) {
        var cls = "notif-thread__step";
        if (s === latest) cls += " is-latest";
        if (!s.n.is_read) cls += " is-unread";
        return (
          '<li class="' + cls + '">' +
          '<button type="button" data-step="' + i + '" aria-pressed="' + (s === latest ? "true" : "false") + '" title="' +
          esc(s.label + " · " + timeLabel(s.n) + " — " + s.n.message) + '">' +
          '<span class="notif-thread__dot" aria-hidden="true"></span>' +
          '<span class="notif-thread__label">' + esc(s.label) + "</span>" +
          '<span class="notif-thread__time">' + esc(timeLabel(s.n)) + "</span>" +
          "</button></li>"
        );
      })
      .join("");

    el.innerHTML =
      '<div class="notif-main">' +
      '<div class="notif-thread__head">' +
      "<strong>" + esc(thread.subject) + "</strong>" +
      '<span class="notif-thread__status">' + esc(latest.label) + "</span>" +
      '<span class="notif-thread__count">' + thread.steps.length + " updates" +
      (thread.unread ? " · " + thread.unread + " new" : "") + "</span>" +
      "</div>" +
      copyTaskLiveHtml(thread.copyTask) +
      '<ol class="notif-thread__track">' + track + "</ol>" +
      '<div class="notif-thread__detail">' + detailHtml(latest) + "</div>" +
      "</div>" +
      '<div class="notif-actions">' +
      '<button type="button" class="btn btn--small btn--ghost js-thread-ack">' + esc(opts.ackLabel || "Ack all") + "</button>" +
      '<button type="button" class="btn btn--small btn--ghost js-thread-resolve">' + esc(opts.removeLabel || "Remove all") + "</button>" +
      "</div>";

    var detail = el.querySelector(".notif-thread__detail");
    el.querySelectorAll(".notif-thread__step button").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var step = thread.steps[Number(btn.getAttribute("data-step"))];
        el.querySelectorAll(".notif-thread__step button").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        detail.innerHTML = detailHtml(step);
      });
    });
    el.querySelector(".js-thread-ack").addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (opts.onAck) opts.onAck(thread.ids.slice());
    });
    el.querySelector(".js-thread-resolve").addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (opts.onResolve) opts.onResolve(thread.ids.slice());
    });
    el.addEventListener("click", function (ev) {
      if (ev.target && ev.target.closest(".notif-actions, a")) return;
      var unreadIds = thread.steps
        .filter(function (s) {
          return !s.n.is_read;
        })
        .map(function (s) {
          return s.n.id;
        });
      if (unreadIds.length && opts.onRead) opts.onRead(unreadIds);
    });
    return el;
  }

  window.TmNotifThreads = {
    group: group,
    renderThread: renderThread,
    copyTaskLiveHtml: copyTaskLiveHtml,
  };
})();
