/**
 * Reserved for shared chat UI state (incremental refactor).
 */
(function (global) {
  "use strict";
  global.tmChat = global.tmChat || {};
  global.tmChat.state = {
    version: 1,
  };
})(typeof window !== "undefined" ? window : global);
