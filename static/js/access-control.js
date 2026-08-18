(function () {
  "use strict";

  var boot = window.ACCESS_CONTROL_BOOT || {};
  var apiBase = boot.apiBase || "/admin/api/permissions";
  var MATRIX_ACTIONS = [
    "view",
    "create",
    "edit",
    "edit_own",
    "edit_all",
    "delete",
    "delete_own",
    "upload",
    "upload_version",
    "approve",
    "assign",
    "export",
    "manage_permissions",
    "manage_users",
    "start_copy",
    "manage_hdd",
  ];
  var state = {
    catalog: null,
    dirty: false,
    pendingRole: {},
    pendingJobTitle: {},
  };

  function $(sel) {
    return document.querySelector(sel);
  }

  function fetchJson(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    opts.credentials = "same-origin";
    return fetch(url, opts).then(function (r) {
      var ct = (r.headers.get("content-type") || "").toLowerCase();
      if (ct.indexOf("application/json") < 0) {
        throw new Error(r.status === 403 ? "forbidden" : "invalid_response");
      }
      return r.json().then(function (j) {
        if (!r.ok) throw new Error((j && j.error) || "request_failed");
        return j;
      });
    });
  }

  function setLoadError(msg) {
    var el = $("#ac-load-error");
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = msg;
  }

  function matrixActions() {
    if (!state.catalog || !state.catalog.actions) return [];
    var keys = {};
    MATRIX_ACTIONS.forEach(function (k) {
      keys[k] = true;
    });
    return state.catalog.actions.filter(function (a) {
      return keys[a.key];
    });
  }

  function showPanel(panelId) {
    document.querySelectorAll("[data-ac-panel]").forEach(function (p) {
      var on = p.getAttribute("data-ac-panel") === panelId;
      p.hidden = !on;
      if (on) p.removeAttribute("aria-hidden");
      else p.setAttribute("aria-hidden", "true");
    });
    document.querySelectorAll("[data-ac-nav]").forEach(function (btn) {
      var on = btn.getAttribute("data-ac-nav") === panelId;
      btn.classList.toggle("is-active", on);
      if (btn.tagName === "BUTTON") {
        if (on) btn.setAttribute("aria-current", "page");
        else btn.removeAttribute("aria-current");
      }
    });
    var saveBtn = $("#ac-save-btn");
    if (saveBtn) {
      saveBtn.hidden = panelId !== "roles" && panelId !== "job-titles";
    }
    var unsaved = $("#ac-unsaved");
    if (unsaved && saveBtn && saveBtn.hidden) unsaved.hidden = true;
  }

  function setDirty(on) {
    state.dirty = !!on;
    var el = $("#ac-unsaved");
    var btn = $("#ac-save-btn");
    if (el) el.hidden = !state.dirty;
    if (btn) btn.disabled = !state.dirty;
  }

  function groupByModule(pages) {
    var map = {};
    (pages || []).forEach(function (p) {
      var m = p.module || "other";
      if (!map[m]) map[m] = [];
      map[m].push(p);
    });
    return map;
  }

  function moduleBadgeClass(module) {
    var raw = String(module || "other").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    return "access-control-badge access-control-badge--mod-" + (raw || "other");
  }

  function renderPages() {
    var host = $("#ac-pages-list");
    if (!host || !state.catalog) return;
    var pages = state.catalog.pages || [];
    var q = (($("#ac-pages-search") || {}).value || "").trim().toLowerCase();
    host.textContent = "";
    var shown = 0;
    pages.forEach(function (p) {
      var hay = (p.name + " " + p.key + " " + p.module).toLowerCase();
      if (q && hay.indexOf(q) < 0) return;
      var card = document.createElement("article");
      card.className = "access-control-page-card panel admin-card";
      card.innerHTML =
        '<div class="access-control-page-card-head">' +
        '<h3 class="access-control-page-card-title">' +
        escapeHtml(p.name) +
        "</h3>" +
        '<span class="' +
        moduleBadgeClass(p.module) +
        '">' +
        escapeHtml(p.module) +
        "</span>" +
        (p.is_active ? "" : '<span class="access-control-badge access-control-badge--muted">Inactive</span>') +
        "</div>" +
        '<p class="muted access-control-page-key"><code>' +
        escapeHtml(p.key) +
        "</code></p>" +
        '<p class="access-control-page-route muted">' +
        escapeHtml(p.route_pattern || "—") +
        "</p>" +
        (p.description ? '<p class="access-control-page-desc">' + escapeHtml(p.description) + "</p>" : "");
      host.appendChild(card);
      shown += 1;
    });
    if (!shown) {
      var empty = document.createElement("p");
      empty.className = "muted access-control-matrix-empty";
      empty.textContent = pages.length
        ? "No pages match your search."
        : "No permission pages are registered yet. Restart the app so seed_permissions can populate the catalog.";
      host.appendChild(empty);
    }
  }

  function renderActions() {
    var host = $("#ac-actions-list");
    if (!host || !state.catalog) return;
    host.textContent = "";
    (state.catalog.actions || []).forEach(function (a) {
      var card = document.createElement("article");
      card.className = "access-control-action-card panel admin-card";
      card.innerHTML =
        "<h3>" +
        escapeHtml(a.name) +
        '</h3><p class="muted"><code>' +
        escapeHtml(a.key) +
        "</code></p>" +
        (a.description ? "<p>" + escapeHtml(a.description) + "</p>" : "");
      host.appendChild(card);
    });
  }

  function permKey(pageKey, actionKey) {
    return pageKey + "||" + actionKey;
  }

  function roleAllowed(roleName, pageKey, actionKey) {
    var pk = permKey(pageKey, actionKey);
    if (state.pendingRole[roleName] && pk in state.pendingRole[roleName]) {
      return state.pendingRole[roleName][pk];
    }
    var row = (state.catalog.role_permissions || []).find(function (r) {
      return r.role_name === roleName && r.page_key === pageKey && r.action_key === actionKey;
    });
    return row ? !!row.is_allowed : false;
  }

  function jtAllowed(jtId, pageKey, actionKey) {
    var pk = permKey(pageKey, actionKey);
    if (state.pendingJobTitle[jtId] && pk in state.pendingJobTitle[jtId]) {
      return state.pendingJobTitle[jtId][pk];
    }
    var row = (state.catalog.job_title_permissions || []).find(function (r) {
      return String(r.job_title_id) === String(jtId) && r.page_key === pageKey && r.action_key === actionKey;
    });
    return row ? !!row.is_allowed : false;
  }

  function renderMatrix(containerSel, selectSel, searchSel, mode) {
    var host = $(containerSel);
    var sel = $(selectSel);
    if (!host || !sel || !state.catalog) return;
    var targetId = sel.value;
    if (!targetId) {
      host.innerHTML = '<p class="muted access-control-matrix-empty">Select a ' + (mode === "role" ? "role" : "job title") + " above.</p>";
      return;
    }
    var actions = matrixActions();
    var q = (($(searchSel) || {}).value || "").trim().toLowerCase();
    var grouped = groupByModule(state.catalog.pages);
    host.textContent = "";
    Object.keys(grouped)
      .sort()
      .forEach(function (mod) {
        var pages = grouped[mod].filter(function (p) {
          if (!q) return true;
          return (p.name + " " + p.key + " " + mod).toLowerCase().indexOf(q) >= 0;
        });
        if (!pages.length) return;
        var details = document.createElement("details");
        details.className = "access-control-module";
        details.open = true;
        details.innerHTML = '<summary class="access-control-module-title">' + escapeHtml(mod) + "</summary>";
        pages.forEach(function (page) {
          var block = document.createElement("div");
          block.className = "access-control-page-block";
          block.innerHTML = '<h4 class="access-control-page-block-title">' + escapeHtml(page.name) + "</h4>";
          var chips = document.createElement("div");
          chips.className = "access-control-action-chips";
          actions.forEach(function (act) {
            var checked =
              mode === "role"
                ? roleAllowed(targetId, page.key, act.key)
                : jtAllowed(targetId, page.key, act.key);
            var label = document.createElement("label");
            label.className = "access-control-chip" + (checked ? " is-on" : "");
            var inp = document.createElement("input");
            inp.type = "checkbox";
            inp.checked = checked;
            inp.dataset.pageKey = page.key;
            inp.dataset.actionKey = act.key;
            inp.addEventListener("change", function () {
              var pk = permKey(page.key, act.key);
              if (mode === "role") {
                if (!state.pendingRole[targetId]) state.pendingRole[targetId] = {};
                state.pendingRole[targetId][pk] = inp.checked;
              } else {
                if (!state.pendingJobTitle[targetId]) state.pendingJobTitle[targetId] = {};
                state.pendingJobTitle[targetId][pk] = inp.checked;
              }
              label.classList.toggle("is-on", inp.checked);
              setDirty(true);
            });
            label.appendChild(inp);
            label.appendChild(document.createTextNode(act.key));
            chips.appendChild(label);
          });
          block.appendChild(chips);
          details.appendChild(block);
        });
        host.appendChild(details);
      });
  }

  function fillSelect(selOrSelector, items, getVal, getLabel, placeholder) {
    var sel = typeof selOrSelector === "string" ? $(selOrSelector) : selOrSelector;
    if (!sel) return;
    sel.textContent = "";
    if (placeholder) {
      var ph = document.createElement("option");
      ph.value = "";
      ph.textContent = placeholder;
      sel.appendChild(ph);
    }
    items.forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = String(getVal(it));
      opt.textContent = getLabel(it);
      sel.appendChild(opt);
    });
    if (!placeholder && sel.options.length) sel.selectedIndex = 0;
  }

  function roleOptions() {
    return (boot.roles || [])
      .filter(function (r) {
        return r !== "guest";
      })
      .map(function (r) {
        return { key: r, label: (boot.roleLabels || {})[r] || r };
      });
  }

  function renderOverrideList() {
    var host = $("#ac-override-list");
    if (!host || !state.catalog) return;
    host.textContent = "";
    (state.catalog.user_overrides || []).forEach(function (o) {
      var li = document.createElement("li");
      li.className = "access-control-override-item";
      var user = (state.catalog.users || []).find(function (u) {
        return String(u.id) === String(o.user_id);
      });
      li.innerHTML =
        "<span><strong>" +
        escapeHtml(user ? user.name : "User #" + o.user_id) +
        "</strong> · " +
        escapeHtml(o.page_key) +
        "/" +
        escapeHtml(o.action_key) +
        " → " +
        (o.is_allowed ? "Allow" : "Deny") +
        (o.note ? ' <span class="muted">(' + escapeHtml(o.note) + ")</span>" : "") +
        "</span>" +
        '<button type="button" class="btn btn--small btn--danger" data-del-override="' +
        o.id +
        '">Remove</button>';
      host.appendChild(li);
    });
    host.querySelectorAll("[data-del-override]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-del-override");
        fetchJson(apiBase + "/user-override/" + encodeURIComponent(id), { method: "DELETE" }).then(loadCatalog);
      });
    });
  }

  function renderPreview() {
    var host = $("#ac-preview-result");
    var sel = $("#ac-preview-user");
    if (!host || !sel || !sel.value) return;
    fetchJson(apiBase + "/preview/" + encodeURIComponent(sel.value)).then(function (j) {
      host.textContent = "";
      var head = document.createElement("div");
      head.className = "access-control-preview-head panel admin-card";
      head.innerHTML =
        "<h3>" +
        escapeHtml(j.user_name || "User") +
        "</h3>" +
        '<p class="muted">Role: <code>' +
        escapeHtml(j.role || "—") +
        "</code> · Job title: " +
        escapeHtml(j.job_title || "—") +
        "</p>";
      host.appendChild(head);
      (j.pages || []).forEach(function (p) {
        var card = document.createElement("article");
        card.className = "access-control-preview-page panel admin-card";
        var acts = (p.actions || [])
          .map(function (a) {
            return (
              '<span class="access-control-badge" title="' +
              escapeHtml(a.source + (a.detail ? ": " + a.detail : "")) +
              '">' +
              escapeHtml(a.action) +
              "</span>"
            );
          })
          .join("");
        card.innerHTML =
          "<h4>" +
          escapeHtml(p.page_name) +
          (p.can_view
            ? ' <span class="access-control-badge access-control-badge--ok">view</span>'
            : ' <span class="access-control-badge access-control-badge--muted">no view</span>') +
          "</h4>" +
          '<p class="muted">Source: ' +
          escapeHtml(p.view_source || "—") +
          "</p>" +
          '<div class="access-control-preview-actions">' +
          acts +
          "</div>";
        host.appendChild(card);
      });
    });
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function applyCatalog(j) {
    state.catalog = j || {};
    if (!Array.isArray(state.catalog.pages)) state.catalog.pages = [];
    if (!Array.isArray(state.catalog.actions)) state.catalog.actions = [];
    try {
      renderPages();
      renderActions();
    } catch (err) {
      setLoadError("Could not render the permissions catalog. Try refreshing the page.");
      throw err;
    }
    fillSelect(
      "#ac-role-select",
      roleOptions(),
      function (x) {
        return x.key;
      },
      function (x) {
        return x.label;
      }
    );
    fillSelect(
      "#ac-job-title-select",
      j.job_titles || [],
      function (x) {
        return x.id;
      },
      function (x) {
        return x.name;
      },
      (j.job_titles || []).length ? null : "No job titles yet"
    );
    fillSelect("#ac-override-user", j.users || [], function (x) {
      return x.id;
    }, function (x) {
      return x.name;
    });
    fillSelect("#ac-preview-user", j.users || [], function (x) {
      return x.id;
    }, function (x) {
      return x.name;
    });
    fillSelect("#ac-override-page", j.pages || [], function (x) {
      return x.key;
    }, function (x) {
      return x.name;
    });
    fillSelect("#ac-override-action", j.actions || [], function (x) {
      return x.key;
    }, function (x) {
      return x.name;
    });
    renderMatrix("#ac-role-matrix", "#ac-role-select", "#ac-roles-search", "role");
    renderMatrix("#ac-jt-matrix", "#ac-job-title-select", "#ac-jt-search", "job_title");
    renderOverrideList();
    setDirty(false);
    state.pendingRole = {};
    state.pendingJobTitle = {};
  }

  function loadCatalog() {
    setLoadError("");
    if (boot.initialCatalog && boot.initialCatalog.pages) {
      applyCatalog(boot.initialCatalog);
      boot.initialCatalog = null;
      return Promise.resolve();
    }
    return fetchJson(apiBase)
      .then(function (j) {
        applyCatalog(j);
      })
      .catch(function (err) {
        var msg = "Could not load permissions.";
        if (err && err.message === "forbidden") {
          msg =
            "Your account cannot manage access control. Sign out, then sign in with an Administrator account (Users → set role to Administrator).";
        } else if (err && err.message === "invalid_response") {
          msg = "Your session may have expired. Sign in again, then reopen Access Control.";
        }
        setLoadError(msg);
        throw err;
      });
  }

  function savePending() {
    var reqs = [];
    Object.keys(state.pendingRole).forEach(function (roleName) {
      Object.keys(state.pendingRole[roleName]).forEach(function (pk) {
        var parts = pk.split("||");
        reqs.push(
          fetchJson(apiBase + "/role", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              role_name: roleName,
              page_key: parts[0],
              action_key: parts[1],
              is_allowed: !!state.pendingRole[roleName][pk],
            }),
          })
        );
      });
    });
    Object.keys(state.pendingJobTitle).forEach(function (jtId) {
      Object.keys(state.pendingJobTitle[jtId]).forEach(function (pk) {
        var parts = pk.split("||");
        reqs.push(
          fetchJson(apiBase + "/job-title", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_title_id: parseInt(jtId, 10),
              page_key: parts[0],
              action_key: parts[1],
              is_allowed: !!state.pendingJobTitle[jtId][pk],
            }),
          })
        );
      });
    });
    return Promise.all(reqs).then(loadCatalog);
  }

  var closeAccessSidebar = function () {};

  function wireAccessSidebar() {
    var sidebar = document.getElementById("admin-sidebar");
    var toggle = document.getElementById("admin-sidebar-toggle");
    var backdrop = document.getElementById("admin-sidebar-backdrop");
    if (!sidebar) return;

    closeAccessSidebar = function () {
      sidebar.classList.remove("is-open");
      document.body.classList.remove("admin-sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
      if (backdrop) {
        backdrop.setAttribute("hidden", "");
        backdrop.setAttribute("aria-hidden", "true");
      }
    };

    function openAccessSidebar() {
      sidebar.classList.add("is-open");
      document.body.classList.add("admin-sidebar-open");
      if (toggle) toggle.setAttribute("aria-expanded", "true");
      if (backdrop) {
        backdrop.removeAttribute("hidden");
        backdrop.setAttribute("aria-hidden", "false");
      }
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        if (sidebar.classList.contains("is-open")) closeAccessSidebar();
        else openAccessSidebar();
      });
    }
    if (backdrop) {
      backdrop.addEventListener("click", closeAccessSidebar);
    }
    window.addEventListener("resize", function () {
      if (!window.matchMedia("(max-width: 767px)").matches) closeAccessSidebar();
    });
  }

  function wireNav() {
    document.querySelectorAll("[data-ac-nav]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-ac-nav");
        showPanel(id);
        if (id === "pages") {
          renderPages();
        }
        if (id === "actions") {
          renderActions();
        }
        if (id === "roles") {
          renderMatrix("#ac-role-matrix", "#ac-role-select", "#ac-roles-search", "role");
        }
        if (id === "job-titles") {
          renderMatrix("#ac-jt-matrix", "#ac-job-title-select", "#ac-jt-search", "job_title");
        }
        if (window.matchMedia("(max-width: 767px)").matches) {
          closeAccessSidebar();
        }
      });
    });
  }

  function bootApp() {
    wireAccessSidebar();
    wireNav();
    var initial = "pages";
    try {
      var section = (new URLSearchParams(window.location.search || "").get("section") || "").trim();
      var valid = {
        pages: true,
        actions: true,
        roles: true,
        "job-titles": true,
        overrides: true,
        preview: true,
      };
      if (valid[section]) initial = section;
    } catch (e) {
      initial = "pages";
    }
    showPanel(initial);
    loadCatalog()
      .then(function () {
        if (initial === "preview") renderPreview();
      })
      .catch(function () {});
    var pagesSearch = $("#ac-pages-search");
    if (pagesSearch) pagesSearch.addEventListener("input", renderPages);
    ["#ac-role-select", "#ac-roles-search"].forEach(function (sel) {
      var el = $(sel);
      if (el) el.addEventListener("input", function () {
        renderMatrix("#ac-role-matrix", "#ac-role-select", "#ac-roles-search", "role");
      });
      if (el) el.addEventListener("change", function () {
        renderMatrix("#ac-role-matrix", "#ac-role-select", "#ac-roles-search", "role");
      });
    });
    ["#ac-job-title-select", "#ac-jt-search"].forEach(function (sel) {
      var el = $(sel);
      if (el) el.addEventListener("input", function () {
        renderMatrix("#ac-jt-matrix", "#ac-job-title-select", "#ac-jt-search", "job_title");
      });
      if (el) el.addEventListener("change", function () {
        renderMatrix("#ac-jt-matrix", "#ac-job-title-select", "#ac-jt-search", "job_title");
      });
    });
    var saveBtn = $("#ac-save-btn");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        saveBtn.disabled = true;
        savePending()
          .catch(function () {})
          .finally(function () {
            saveBtn.disabled = !state.dirty;
          });
      });
    }
    var addOv = $("#ac-override-add");
    if (addOv) {
      addOv.addEventListener("click", function () {
        var uid = ($("#ac-override-user") || {}).value;
        var page = ($("#ac-override-page") || {}).value;
        var act = ($("#ac-override-action") || {}).value;
        var allow = ($("#ac-override-allow") || {}).value === "1";
        var note = ($("#ac-override-note") || {}).value || "";
        if (!uid || !page || !act) return;
        fetchJson(apiBase + "/user-override", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: parseInt(uid, 10),
            page_key: page,
            action_key: act,
            is_allowed: allow,
            note: note,
          }),
        }).then(loadCatalog);
      });
    }
    var previewBtn = $("#ac-preview-run");
    if (previewBtn) previewBtn.addEventListener("click", renderPreview);
    var previewUser = $("#ac-preview-user");
    if (previewUser) previewUser.addEventListener("change", renderPreview);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootApp);
  } else {
    bootApp();
  }
})();
