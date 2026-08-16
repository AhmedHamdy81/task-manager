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
  var inspectorHomeParent = null;
  var inspectorHomeNext = null;
  var backdropHomeParent = null;
  var backdropHomeNext = null;
  var inspectorModal = false;

  function qs(id) {
    return document.getElementById(id);
  }

  function pinInspectorToBody() {
    if (!inspector || inspector.parentNode === document.body) return;
    inspectorHomeParent = inspector.parentNode;
    inspectorHomeNext = inspector.nextSibling;
    if (backdrop && backdrop.parentNode !== document.body) {
      backdropHomeParent = backdrop.parentNode;
      backdropHomeNext = backdrop.nextSibling;
      document.body.appendChild(backdrop);
    }
    document.body.appendChild(inspector);
  }

  function restoreInspectorHome() {
    if (inspector && inspectorHomeParent) {
      var anchor = inspectorHomeNext;
      while (anchor && (anchor === inspector || anchor === backdrop)) {
        anchor = anchor.nextSibling;
      }
      if (anchor && anchor.parentNode !== inspectorHomeParent) anchor = null;
      inspectorHomeParent.insertBefore(inspector, anchor);
    }
    if (backdrop && backdropHomeParent) {
      if (inspector && inspector.parentNode === backdropHomeParent) {
        backdropHomeParent.insertBefore(backdrop, inspector.nextSibling);
      } else {
        var bAnchor = backdropHomeNext;
        if (bAnchor && bAnchor.parentNode !== backdropHomeParent) bAnchor = null;
        backdropHomeParent.insertBefore(backdrop, bAnchor);
      }
    }
    inspectorHomeParent = null;
    inspectorHomeNext = null;
    backdropHomeParent = null;
    backdropHomeNext = null;
  }

  function clearInspectorModalUi() {
    inspectorModal = false;
    if (inspector) {
      inspector.classList.remove("app-inspector--modal");
      inspector.removeAttribute("role");
      inspector.removeAttribute("aria-modal");
      inspector.setAttribute("aria-hidden", "true");
      inspector.setAttribute("aria-label", "Details");
    }
    if (backdrop) backdrop.classList.remove("app-inspector-backdrop--modal");
    document.body.classList.remove("booking-edit-inspector-modal");
    restoreInspectorHome();
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
      backdrop.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("app--inspector-open");
    clearInspectorModalUi();
  }

  function closeInspector() {
    if (!inspector || !inspector.classList.contains("is-open")) {
      closeInspectorSync();
      return;
    }
    if (inspectorModal) {
      closeInspectorSync();
      return;
    }
    inspector.classList.remove("is-open");
    if (backdrop) backdrop.classList.remove("is-open");
    document.body.classList.remove("app--inspector-open");
    setTimeout(closeInspectorSync, 200);
  }

  function revealInspector() {
    if (!inspector) return;
    inspector.classList.add("is-open");
    if (backdrop) backdrop.classList.add("is-open");
    document.body.classList.add("app--inspector-open");
  }

  function openInspector(opts) {
    opts = opts || {};
    if (!inspector || !inspectorContent) return;
    closeInspectorSync();
    currentParking = opts.parking || null;
    inspectorModal = !!(opts.modal || opts.bodyClass === "booking-edit-inspector-modal");
    if (inspectorTitle) {
      inspectorTitle.textContent = opts.title || "Details";
    }
    if (opts.el) {
      inspectorContent.appendChild(opts.el);
    }
    if (opts.bodyClass) {
      try {
        document.body.classList.add(opts.bodyClass);
      } catch (e) {
        /* ignore */
      }
    }
    if (inspectorModal) {
      inspector.classList.add("app-inspector--modal");
      inspector.setAttribute("role", "dialog");
      inspector.setAttribute("aria-modal", "true");
      inspector.setAttribute("aria-label", opts.title || "Details");
      if (backdrop) backdrop.classList.add("app-inspector-backdrop--modal");
      pinInspectorToBody();
    }
    inspector.hidden = false;
    inspector.setAttribute("aria-hidden", "false");
    if (backdrop) {
      backdrop.hidden = false;
      backdrop.setAttribute("aria-hidden", "false");
    }
    if (inspectorModal) {
      revealInspector();
    } else {
      requestAnimationFrame(revealInspector);
    }
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
