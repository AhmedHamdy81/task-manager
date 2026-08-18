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
  });
})();
