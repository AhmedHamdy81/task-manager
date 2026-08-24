(function () {
  "use strict";

  var STORAGE_KEY = "tm-admin-control-section";
  var VALID = {
    "post-scopes": true,
    "all-tasks": true,
    "task-groups": true,
    "task-titles": true,
  };
  var LEGACY_SECTION = {
    "task-groups": "post-scopes",
    "task-titles": "post-scopes",
  };

  document.addEventListener("DOMContentLoaded", function () {
    var nav = document.querySelectorAll("[data-admin-nav]");
    var panels = document.querySelectorAll("[data-admin-panel]");
    if (!nav.length || !panels.length) return;

    var sidebar = document.getElementById("admin-sidebar");
    var sideToggle = document.getElementById("admin-sidebar-toggle");
    var sideBackdrop = document.getElementById("admin-sidebar-backdrop");

    function mqSidebar() {
      return window.matchMedia("(max-width: 767px)").matches;
    }

    function closeAdminSidebar() {
      if (!sidebar) return;
      sidebar.classList.remove("is-open");
      document.body.classList.remove("admin-sidebar-open");
      if (sideToggle) sideToggle.setAttribute("aria-expanded", "false");
      if (sideBackdrop) {
        sideBackdrop.setAttribute("hidden", "");
        sideBackdrop.setAttribute("aria-hidden", "true");
      }
    }

    function openAdminSidebar() {
      if (!sidebar) return;
      sidebar.classList.add("is-open");
      document.body.classList.add("admin-sidebar-open");
      if (sideToggle) sideToggle.setAttribute("aria-expanded", "true");
      if (sideBackdrop) {
        sideBackdrop.removeAttribute("hidden");
        sideBackdrop.setAttribute("aria-hidden", "false");
      }
    }

    if (sideToggle && sidebar) {
      sideToggle.addEventListener("click", function () {
        if (sidebar.classList.contains("is-open")) closeAdminSidebar();
        else openAdminSidebar();
      });
    }
    if (sideBackdrop) {
      sideBackdrop.addEventListener("click", closeAdminSidebar);
    }
    window.addEventListener("resize", function () {
      if (!mqSidebar()) closeAdminSidebar();
    });

    function normalizeSection(sectionId) {
      if (LEGACY_SECTION[sectionId]) return LEGACY_SECTION[sectionId];
      if (!VALID[sectionId]) return "post-scopes";
      if (sectionId === "task-groups" || sectionId === "task-titles") return "post-scopes";
      return sectionId;
    }

    function show(sectionId) {
      sectionId = normalizeSection(sectionId);
      panels.forEach(function (p) {
        var id = p.getAttribute("data-admin-panel");
        var on = id === sectionId;
        p.hidden = !on;
        if (on) p.removeAttribute("aria-hidden");
        else p.setAttribute("aria-hidden", "true");
      });
      nav.forEach(function (btn) {
        var id = btn.getAttribute("data-admin-nav");
        var active = id === sectionId;
        btn.classList.toggle("is-active", active);
        if (btn.tagName === "BUTTON") {
          if (active) btn.setAttribute("aria-current", "page");
          else btn.removeAttribute("aria-current");
        }
      });
      try {
        sessionStorage.setItem(STORAGE_KEY, sectionId);
      } catch (e) {
        /* ignore */
      }
    }

    nav.forEach(function (el) {
      if (el.tagName !== "BUTTON") return;
      el.addEventListener("click", function () {
        show(el.getAttribute("data-admin-nav") || "post-scopes");
        if (mqSidebar()) closeAdminSidebar();
      });
    });

    document.querySelectorAll(".admin-shell form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        var msg = form.getAttribute("data-confirm");
        if (msg && !window.confirm(msg)) {
          e.preventDefault();
        }
      });
    });

    var initial = "post-scopes";
    var forced = "";
    try {
      var params = new URLSearchParams(window.location.search || "");
      forced = (params.get("section") || "").trim();
    } catch (e0) {
      forced = "";
    }
    if (forced && VALID[forced]) {
      initial = normalizeSection(forced);
    } else {
      try {
        initial = normalizeSection(sessionStorage.getItem(STORAGE_KEY) || "post-scopes");
      } catch (e2) {
        initial = "post-scopes";
      }
    }
    show(initial);

    var addDlg = document.getElementById("control-add-task-dialog");
    var addForm = document.getElementById("control-add-task-form");
    var addKey = document.getElementById("control-add-task-scope-key");
    var addScopeLabel = document.getElementById("control-add-task-dialog-scope");
    var addTitle = document.getElementById("control-add-task-title");
    var addDesc = document.getElementById("control-add-task-description");

    function closeAddTaskDialog() {
      if (addDlg && addDlg.open) addDlg.close();
    }

    function openAddTaskDialog(btn) {
      if (!addDlg || !addForm || !addKey) return;
      var key = btn.getAttribute("data-scope-key") || "";
      var label = btn.getAttribute("data-scope-label") || "";
      addForm.reset();
      addKey.value = key;
      if (addDesc) addDesc.value = "";
      if (addScopeLabel) addScopeLabel.textContent = label ? "Scope: " + label : "";
      if (typeof addDlg.showModal === "function") addDlg.showModal();
      else addDlg.setAttribute("open", "open");
      if (addTitle) addTitle.focus();
    }

    document.querySelectorAll("[data-add-task-title]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openAddTaskDialog(btn);
      });
    });
    var addCancel = document.getElementById("control-add-task-cancel");
    if (addCancel) addCancel.addEventListener("click", closeAddTaskDialog);
    if (addDlg) {
      addDlg.addEventListener("click", function (evt) {
        if (evt.target === addDlg) closeAddTaskDialog();
      });
    }

    var statusDlg = document.getElementById("control-title-status-dialog");
    var statusScope = document.getElementById("control-title-status-scope");

    function closeTitleStatusDialog() {
      if (statusDlg && statusDlg.open) statusDlg.close();
    }

    function fillStatusList(col, items) {
      var ul = col.querySelector("ul");
      var countEl = col.querySelector("[data-count]");
      if (!ul) return;
      ul.textContent = "";
      var list = Array.isArray(items) ? items : [];
      if (countEl) countEl.textContent = String(list.length);
      if (!list.length) {
        var empty = document.createElement("li");
        empty.className = "is-empty";
        empty.textContent = "None";
        ul.appendChild(empty);
        return;
      }
      list.forEach(function (title) {
        var li = document.createElement("li");
        li.textContent = String(title || "");
        ul.appendChild(li);
      });
    }

    function openTitleStatusDialog(btn) {
      if (!statusDlg) return;
      var payload = {};
      try {
        payload = JSON.parse(btn.getAttribute("data-status") || "{}") || {};
      } catch (err) {
        payload = {};
      }
      var label = btn.getAttribute("data-scope-label") || "";
      if (statusScope) statusScope.textContent = label ? "Scope: " + label : "";
      statusDlg.querySelectorAll("[data-status-kind]").forEach(function (col) {
        var kind = col.getAttribute("data-status-kind") || "";
        fillStatusList(col, payload[kind]);
      });
      if (typeof statusDlg.showModal === "function") statusDlg.showModal();
      else statusDlg.setAttribute("open", "open");
    }

    document.querySelectorAll("[data-title-status]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openTitleStatusDialog(btn);
      });
    });
    var statusClose = document.getElementById("control-title-status-close");
    if (statusClose) statusClose.addEventListener("click", closeTitleStatusDialog);
    if (statusDlg) {
      statusDlg.addEventListener("click", function (evt) {
        if (evt.target === statusDlg) closeTitleStatusDialog();
      });
    }

    document.querySelectorAll(".admin-date-input").forEach(function (input) {
      input.addEventListener("click", function () {
        if (typeof input.showPicker === "function") {
          try {
            input.showPicker();
          } catch (err) {
            /* Already open or not allowed. */
          }
        }
      });
    });
  });
})();
