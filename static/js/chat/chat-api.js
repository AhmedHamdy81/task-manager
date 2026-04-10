/**
 * Chat HTTP helpers (JSON-safe; avoids HTML error pages breaking JSON.parse).
 */
(function (global) {
  "use strict";

  global.tmChat = global.tmChat || {};

  global.tmChat.api = {
    postReaction: function (projectId, messageId, emoji) {
      return fetch(
        "/projects/" + projectId + "/chat/messages/" + messageId + "/reaction",
        {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ emoji: emoji }),
        }
      ).then(function (res) {
        return res.text().then(function (text) {
          var body = {};
          var raw = (text || "").trim();
          if (raw.charAt(0) === "{") {
            try {
              body = JSON.parse(raw);
            } catch (ignore) {
              /* ignore */
            }
          }
          if (!res.ok) {
            throw new Error(
              (body && (body.detail || body.error)) || raw.slice(0, 120) || "Reaction failed"
            );
          }
          return body;
        });
      });
    },
  };
})(typeof window !== "undefined" ? window : global);
