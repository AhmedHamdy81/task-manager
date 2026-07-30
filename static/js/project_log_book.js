(function () {
  "use strict";

  var root = document.getElementById("project-log-book-root");
  if (!root) return;

  var tmpl = root.getAttribute("data-detail-url-tmpl") || "";
  var dialog = document.getElementById("project-log-book-dialog");
  var body = document.getElementById("project-log-book-dialog-body");
  var titleEl = document.getElementById("project-log-book-dialog-title");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function humanKey(k) {
    return String(k || "")
      .replace(/_/g, " ")
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function fmtVal(v) {
    if (v == null || v === "") return "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "object") {
      try {
        return JSON.stringify(v);
      } catch (e) {
        return String(v);
      }
    }
    return String(v);
  }

  function renderChanges(changes) {
    var keys = Object.keys(changes || {});
    if (!keys.length) return "";
    var html = '<div class="project-log-book-changes"><h3>Field changes</h3>';
    keys.forEach(function (k) {
      var c = changes[k] || {};
      html +=
        '<div class="project-log-book-change-row">' +
        '<div class="project-log-book-change-row__field">' +
        esc(humanKey(k)) +
        "</div>" +
        "<div>" +
        esc(fmtVal(c.old)) +
        " → " +
        esc(fmtVal(c.new)) +
        "</div></div>";
    });
    html += "</div>";
    return html;
  }

  function renderMeta(meta) {
    var keys = Object.keys(meta || {});
    if (!keys.length) return "";
    var html = '<div class="project-log-book-meta-block"><h3>Details</h3><ul class="project-log-book-meta-list">';
    keys.forEach(function (k) {
      if (k === "error" || k === "error_message") return;
      html +=
        "<li><span>" +
        esc(humanKey(k)) +
        "</span><span>" +
        esc(fmtVal(meta[k])) +
        "</span></li>";
    });
    html += "</ul></div>";
    return html;
  }

  function renderDetail(log) {
    var err = (log.metadata && (log.metadata.error || log.metadata.error_message)) || "";
    var html =
      '<dl class="project-log-book-detail-grid">' +
      "<dt>When</dt><dd>" +
      esc(log.occurred_at || "—") +
      "</dd>" +
      "<dt>Actor</dt><dd>" +
      esc(log.actor_name || "System") +
      "</dd>" +
      "<dt>Event</dt><dd>" +
      esc(log.event_type || "") +
      "</dd>" +
      "<dt>Module</dt><dd>" +
      esc(log.module_label || log.module || "") +
      "</dd>" +
      "<dt>Action</dt><dd>" +
      esc(log.action || "") +
      "</dd>" +
      "<dt>Entity</dt><dd>" +
      esc((log.entity_type || "") + (log.entity_label ? " · " + log.entity_label : "")) +
      "</dd>" +
      "<dt>Status</dt><dd>" +
      esc(log.status || "") +
      "</dd>" +
      "<dt>Duration</dt><dd>" +
      esc(log.duration_label || "—") +
      "</dd>" +
      "<dt>Operation ID</dt><dd>" +
      esc(log.operation_id || "—") +
      "</dd>" +
      "<dt>Summary</dt><dd>" +
      esc(log.summary || "") +
      "</dd>";
    if (err) {
      html += "<dt>Error</dt><dd>" + esc(String(err).slice(0, 500)) + "</dd>";
    }
    if (log.ip_address) {
      html += "<dt>IP</dt><dd>" + esc(log.ip_address) + "</dd>";
    }
    html += "</dl>";
    html += renderChanges(log.changes || {});
    html += renderMeta(log.metadata || {});
    return html;
  }

  function openDetail(id) {
    if (!dialog || !body || !tmpl) return;
    var url = tmpl.replace("__ID__", String(id));
    body.innerHTML = '<p class="muted">Loading…</p>';
    if (titleEl) titleEl.textContent = "Activity details";
    if (typeof dialog.showModal === "function") dialog.showModal();
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, j: j };
        });
      })
      .then(function (x) {
        if (!x.ok || !x.j || !x.j.log) {
          body.innerHTML = '<p class="form-error">Could not load activity details.</p>';
          return;
        }
        if (titleEl) titleEl.textContent = x.j.log.summary || "Activity details";
        body.innerHTML = renderDetail(x.j.log);
      })
      .catch(function () {
        body.innerHTML = '<p class="form-error">Network error loading details.</p>';
      });
  }

  root.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-log-detail]");
    if (!btn || !root.contains(btn)) return;
    e.preventDefault();
    openDetail(btn.getAttribute("data-log-detail"));
  });
})();
