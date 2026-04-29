/**
 * App shell: sidebar toggle (mobile), inspector slide-in.
 */
(function () {
  "use strict";

  var inspector;
  var inspectorContent;
  var inspectorTitle;
  var backdrop;
  var sidebar;
  var sidebarToggle;
  var currentParking = null;

  function qs(id) {
    return document.getElementById(id);
  }

  function closeInspectorSync() {
    if (!inspectorContent) return;
    if (typeof window.__tmInspectorBeforeClose === "function") {
      try {
        window.__tmInspectorBeforeClose();
      } catch (e) {
        /* ignore */
      }
    }
    var park = currentParking;
    while (inspectorContent.firstChild) {
      var n = inspectorContent.firstChild;
      if (park) park.appendChild(n);
      else inspectorContent.removeChild(n);
    }
    currentParking = null;
    if (inspector) {
      inspector.classList.remove("is-open");
      inspector.hidden = true;
    }
    if (backdrop) {
      backdrop.classList.remove("is-open");
      backdrop.hidden = true;
    }
    document.body.classList.remove("app--inspector-open");
  }

  function closeInspector() {
    if (!inspector || !inspector.classList.contains("is-open")) {
      closeInspectorSync();
      return;
    }
    inspector.classList.remove("is-open");
    if (backdrop) backdrop.classList.remove("is-open");
    document.body.classList.remove("app--inspector-open");
    setTimeout(closeInspectorSync, 200);
  }

  function openInspector(opts) {
    opts = opts || {};
    if (!inspector || !inspectorContent) return;
    closeInspectorSync();
    currentParking = opts.parking || null;
    if (inspectorTitle) {
      inspectorTitle.textContent = opts.title || "Details";
    }
    if (opts.el) {
      inspectorContent.appendChild(opts.el);
    }
    inspector.hidden = false;
    if (backdrop) backdrop.hidden = false;
    requestAnimationFrame(function () {
      inspector.classList.add("is-open");
      if (backdrop) backdrop.classList.add("is-open");
      document.body.classList.add("app--inspector-open");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    inspector = qs("app-inspector");
    inspectorContent = qs("app-inspector-content");
    inspectorTitle = qs("app-inspector-title");
    backdrop = qs("app-inspector-backdrop");
    sidebar = qs("app-sidebar");
    sidebarToggle = qs("app-sidebar-toggle");

    var closeBtn = qs("app-inspector-close");
    if (closeBtn) closeBtn.addEventListener("click", closeInspector);
    if (backdrop) backdrop.addEventListener("click", closeInspector);

    if (sidebarToggle && sidebar) {
      sidebarToggle.addEventListener("click", function () {
        sidebar.classList.toggle("is-open");
        document.body.classList.toggle("app--sidebar-open");
      });
    }
  });

  window.tmShell = {
    openInspector: openInspector,
    closeInspector: closeInspector,
    closeInspectorSync: closeInspectorSync,
  };
})();
