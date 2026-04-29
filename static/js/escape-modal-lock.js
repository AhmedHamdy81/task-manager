/**
 * Disable Escape from closing modals / overlays app-wide.
 * - Window capture stops keydown before other document listeners run.
 * - HTMLDialogElement: block the "cancel" event (Escape) so <dialog> stays open.
 * Exceptions: global chat (mention UI), HDD inline rename field, and plain inputs
 * outside modal-like shells so typing UX stays intact.
 */
(function () {
  "use strict";

  function allowEscapeDefault(e) {
    var t = e.target;
    if (!t || typeof t.closest !== "function") return false;
    if (t.closest("#global-chat-container")) return true;
    if (t.classList && t.classList.contains("hdd-name-input")) return true;
    var tag = (t.tagName || "").toLowerCase();
    var inModalLike = t.closest(
      ".modal, dialog, #app-inspector, #avatar-modal, .avatar-modal"
    );
    if (!inModalLike && (tag === "input" || tag === "textarea" || tag === "select")) {
      return true;
    }
    return false;
  }

  window.addEventListener(
    "keydown",
    function (e) {
      if (e.key !== "Escape") return;
      if (allowEscapeDefault(e)) return;
      e.preventDefault();
      e.stopPropagation();
    },
    true
  );

  document.addEventListener(
    "cancel",
    function (e) {
      if (e.target instanceof HTMLDialogElement) {
        e.preventDefault();
      }
    },
    true
  );
})();
