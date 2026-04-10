/**
 * Global chat event delegation remains in global-chat.js (DOMContentLoaded bootstrap).
 * Reserved for future extraction.
 */
(function (global) {
  "use strict";
  global.tmChat = global.tmChat || {};
  global.tmChat.events = global.tmChat.events || { _note: "see global-chat.js" };
})(typeof window !== "undefined" ? window : global);
