/**
 * Chat DOM rendering: bubble rows live in global-chat.js as appendOneMessageRow / renderMessagesTo
 * for now (avoids duplicate 200+ lines). Next step: move those functions here behind tmChat.render.*
 */
(function (global) {
  "use strict";
  global.tmChat = global.tmChat || {};
  global.tmChat.render = global.tmChat.render || { _note: "see global-chat.js appendOneMessageRow" };
})(typeof window !== "undefined" ? window : global);
