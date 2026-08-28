(function () {
  "use strict";

  function flashModals() {
    return Array.prototype.slice.call(document.querySelectorAll("[data-flash-modal]"));
  }

  function showFlashModal(modal) {
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("flash-modal-open");
    var btn = modal.querySelector("[data-flash-dismiss].btn");
    if (btn) btn.focus();
  }

  function dismissFlashModal(modal) {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    modal.remove();
    var next = flashModals().find(function (item) {
      return !item.classList.contains("hidden");
    });
    if (next) {
      showFlashModal(next);
      return;
    }
    document.body.classList.remove("flash-modal-open");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var modals = flashModals();
    if (modals.length) showFlashModal(modals[0]);
  });

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-flash-dismiss]");
    if (!btn) return;
    var modal = btn.closest("[data-flash-modal]");
    if (!modal) return;
    ev.preventDefault();
    dismissFlashModal(modal);
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    var open = document.querySelector("[data-flash-modal]:not(.hidden)");
    if (open) dismissFlashModal(open);
  });
})();
