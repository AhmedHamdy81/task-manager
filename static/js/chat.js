(function () {
  "use strict";

  var RECORDING_MAX_MS = 120000;
  var GROUP_MS = 5 * 60 * 1000;

  function formatTime(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, {
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch (e) {
      return iso;
    }
  }

  function parseTime(iso) {
    try {
      var d = new Date(iso);
      return isNaN(d.getTime()) ? 0 : d.getTime();
    } catch (e) {
      return 0;
    }
  }

  function initialFromMessage(m) {
    if (m.avatar_initial) return m.avatar_initial;
    var name = (m.username || "").trim();
    for (var i = 0; i < name.length; i++) {
      var ch = name.charAt(i);
      if (/[a-zA-Z0-9]/.test(ch)) return ch.toUpperCase();
    }
    return "?";
  }

  function extForAudioBlob(blob) {
    var t = (blob.type || "").toLowerCase();
    if (t.indexOf("ogg") !== -1 || t.indexOf("opus") !== -1) return ".ogg";
    if (t.indexOf("mp4") !== -1 || t.indexOf("m4a") !== -1 || t.indexOf("aac") !== -1)
      return ".m4a";
    if (t.indexOf("mpeg") !== -1 || t.indexOf("mp3") !== -1) return ".mp3";
    if (t.indexOf("wav") !== -1) return ".wav";
    return ".webm";
  }

  function appendMessageTextWithMentions(container, text, team) {
    if (!text) return;
    if (!team || !team.length) {
      container.textContent = text;
      return;
    }
    var named = [];
    for (var i = 0; i < team.length; i++) {
      var nm = (team[i].name || "").trim();
      if (nm) named.push({ id: team[i].id, name: nm });
    }
    named.sort(function (a, b) {
      return b.name.length - a.name.length;
    });

    var pos = 0;
    var n = text.length;
    while (pos < n) {
      var at = text.indexOf("@", pos);
      if (at < 0) {
        container.appendChild(document.createTextNode(text.slice(pos)));
        break;
      }
      if (at > pos) {
        container.appendChild(document.createTextNode(text.slice(pos, at)));
      }
      var rest = text.slice(at + 1);
      var hit = null;
      for (var j = 0; j < named.length; j++) {
        var name = named[j].name;
        if (rest.length >= name.length && rest.slice(0, name.length) === name) {
          var boundary = rest.charAt(name.length);
          if (boundary && /[0-9A-Za-z]/.test(boundary)) continue;
          hit = named[j];
          break;
        }
      }
      if (hit) {
        var span = document.createElement("span");
        span.className = "project-chat-mention";
        var inner = document.createElement("a");
        inner.href = "#project-chat";
        inner.className = "project-chat-mention-link";
        inner.textContent = "@" + hit.name;
        inner.addEventListener("click", function (e) {
          e.preventDefault();
        });
        span.appendChild(inner);
        container.appendChild(span);
        pos = at + 1 + hit.name.length;
      } else {
        container.appendChild(document.createTextNode("@"));
        pos = at + 1;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var dock = document.getElementById("project-chat");
    if (!dock || dock.getAttribute("data-chat-allowed") !== "true") return;

    var messagesUrl = dock.getAttribute("data-messages-url");
    var unreadUrl = dock.getAttribute("data-unread-url");
    var markReadUrl = dock.getAttribute("data-mark-read-url");
    if (!messagesUrl || !unreadUrl || !markReadUrl) return;

    var projectId = parseInt(dock.getAttribute("data-project-id"), 10);
    var soundUrl = dock.getAttribute("data-notify-sound-url") || "";
    var myDirectoryUserId = parseInt(dock.getAttribute("data-directory-user-id"), 10);
    if (isNaN(myDirectoryUserId)) myDirectoryUserId = null;

    var CHAT_SOUND_PREF_KEY = "tm-chat-notify-sound";
    var knownChatMessageIds = new Set();
    var notifyAudioEl = null;

    function chatSoundPrefEnabled() {
      try {
        var v = localStorage.getItem(CHAT_SOUND_PREF_KEY);
        if (v === null || v === "") return true;
        return v !== "0";
      } catch (e) {
        return true;
      }
    }

    function setChatSoundPref(enabled) {
      try {
        localStorage.setItem(CHAT_SOUND_PREF_KEY, enabled ? "1" : "0");
      } catch (e) {
        /* ignore */
      }
    }

    function syncSoundToggleUI() {
      var btn = document.getElementById("project-chat-sound-toggle");
      if (!btn) return;
      var on = chatSoundPrefEnabled();
      btn.classList.toggle("is-sound-muted", !on);
      btn.setAttribute("aria-pressed", on ? "false" : "true");
      btn.title = on ? "Mute notification sound" : "Unmute notification sound";
      btn.setAttribute(
        "aria-label",
        on ? "Mute chat notification sound" : "Unmute chat notification sound"
      );
    }

    function notifyVolumeForContext() {
      if (typeof document.hidden !== "undefined" && document.hidden) {
        return 0.58;
      }
      if (isCollapsed()) {
        return 0.52;
      }
      return 0.14;
    }

    function playChatNotifySound() {
      if (!soundUrl || !chatSoundPrefEnabled()) return;
      try {
        if (!notifyAudioEl) {
          notifyAudioEl = new Audio(soundUrl);
          notifyAudioEl.preload = "auto";
        }
        notifyAudioEl.volume = Math.min(1, Math.max(0, notifyVolumeForContext()));
        notifyAudioEl.currentTime = 0;
        var p = notifyAudioEl.play();
        if (p && typeof p.catch === "function") {
          p.catch(function () {});
        }
      } catch (e) {
        /* ignore */
      }
    }

    function maybeNotifyIncomingChat(payload) {
      if (!payload || payload.message_id == null || payload.user_id == null) return;
      var mid = payload.message_id;
      var sid = payload.user_id;
      if (myDirectoryUserId != null && sid === myDirectoryUserId) return;
      if (knownChatMessageIds.has(mid)) return;
      knownChatMessageIds.add(mid);
      playChatNotifySound();
    }

    function rememberLoadedMessageIds(items) {
      if (!items || !items.length) return;
      for (var i = 0; i < items.length; i++) {
        var id = items[i].id;
        if (id != null) knownChatMessageIds.add(id);
      }
    }

    var storageKey = "tm-chat-expanded-" + projectId;
    var heightStorageKey = "tm-chat-panel-height-" + projectId;
    var DEFAULT_CHAT_PANEL_PX = 400;
    var MIN_CHAT_PANEL_PX = 300;
    var STREAM_BOTTOM_PIN_PX = 80;

    var toggleBtn = document.getElementById("project-chat-toggle");
    var panelBody = document.getElementById("project-chat-panel-body");
    var listEl = document.getElementById("project-chat-messages");
    var form = document.getElementById("project-chat-form");
    var input = document.getElementById("project-chat-input");
    var errEl = document.getElementById("project-chat-error");
    var statusEl = document.getElementById("project-chat-status");
    var badgeEl = document.getElementById("project-chat-unread-badge");
    var btnGallery = document.getElementById("project-chat-btn-gallery");
    var btnCamera = document.getElementById("project-chat-btn-camera");
    var btnMic = document.getElementById("project-chat-btn-mic");
    var fileGallery = document.getElementById("project-chat-file-gallery");
    var fileCamera = document.getElementById("project-chat-file-camera");
    var mentionList = document.getElementById("project-chat-mention-list");
    var dockInner = document.getElementById("project-chat-dock-inner");
    var resizeHandle = document.getElementById("project-chat-resize-handle");

    if (!listEl || !form || !input) return;

    function maxChatPanelPx() {
      var vv = window.visualViewport;
      var vh = vv && vv.height ? vv.height : window.innerHeight;
      var topReserve = 20;
      var bottomReserve = 24;
      var cap = Math.floor(vh * 0.88);
      var byViewport = vh - topReserve - bottomReserve;
      return Math.max(MIN_CHAT_PANEL_PX, Math.min(cap, byViewport));
    }

    function clampChatPanelPx(h) {
      var max = maxChatPanelPx();
      if (h < MIN_CHAT_PANEL_PX) return MIN_CHAT_PANEL_PX;
      if (h > max) return max;
      return h;
    }

    function readStoredChatPanelPx() {
      try {
        var raw = localStorage.getItem(heightStorageKey);
        if (raw == null) return DEFAULT_CHAT_PANEL_PX;
        var n = parseInt(raw, 10);
        return isNaN(n) ? DEFAULT_CHAT_PANEL_PX : n;
      } catch (e) {
        return DEFAULT_CHAT_PANEL_PX;
      }
    }

    function applyStoredChatPanelHeight() {
      if (!dockInner) return;
      var h = clampChatPanelPx(readStoredChatPanelPx());
      dockInner.style.height = h + "px";
    }

    function clearChatPanelInlineHeight() {
      if (!dockInner) return;
      dockInner.style.height = "";
    }

    function persistChatPanelHeight() {
      if (!dockInner) return;
      try {
        localStorage.setItem(heightStorageKey, String(clampChatPanelPx(dockInner.offsetHeight)));
      } catch (e) {
        /* ignore */
      }
    }

    function syncStreamScrollAfterResize() {
      var gap = listEl.scrollHeight - listEl.clientHeight - listEl.scrollTop;
      var pinToBottom = gap <= STREAM_BOTTOM_PIN_PX;
      return function () {
        if (pinToBottom) {
          listEl.scrollTop = Math.max(0, listEl.scrollHeight - listEl.clientHeight);
        } else {
          var g = Math.max(0, listEl.scrollHeight - listEl.clientHeight - gap);
          listEl.scrollTop = g;
        }
      };
    }

    function clampChatPanelToViewport() {
      if (!dockInner || dock.classList.contains("project-chat-dock--collapsed")) return;
      var c = clampChatPanelPx(dockInner.offsetHeight);
      dockInner.style.height = c + "px";
      try {
        localStorage.setItem(heightStorageKey, String(c));
      } catch (e) {
        /* ignore */
      }
    }

    window.addEventListener("resize", function () {
      clampChatPanelToViewport();
    });
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", function () {
        clampChatPanelToViewport();
      });
    }

    if (resizeHandle && dockInner) {
      resizeHandle.addEventListener("pointerdown", function (e) {
        if (e.button !== 0 || isCollapsed()) return;
        e.preventDefault();
        var startY = e.clientY;
        var startH = dockInner.offsetHeight;
        dockInner.classList.add("is-resizing-chat");
        try {
          resizeHandle.setPointerCapture(e.pointerId);
        } catch (err) {
          /* ignore */
        }

        function move(ev) {
          var sync = syncStreamScrollAfterResize();
          var nh = clampChatPanelPx(startH + (startY - ev.clientY));
          dockInner.style.height = nh + "px";
          requestAnimationFrame(sync);
        }

        function up(ev) {
          dockInner.classList.remove("is-resizing-chat");
          try {
            resizeHandle.releasePointerCapture(ev.pointerId);
          } catch (err2) {
            /* ignore */
          }
          persistChatPanelHeight();
          resizeHandle.removeEventListener("pointermove", move);
          resizeHandle.removeEventListener("pointerup", done);
          resizeHandle.removeEventListener("pointercancel", done);
        }

        function done(ev) {
          up(ev);
        }

        resizeHandle.addEventListener("pointermove", move);
        resizeHandle.addEventListener("pointerup", done);
        resizeHandle.addEventListener("pointercancel", done);
      });

      resizeHandle.addEventListener("keydown", function (e) {
        if (isCollapsed()) return;
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        e.preventDefault();
        var step = 28;
        var h = dockInner.offsetHeight;
        var nh = e.key === "ArrowUp" ? h + step : h - step;
        var sync = syncStreamScrollAfterResize();
        dockInner.style.height = clampChatPanelPx(nh) + "px";
        requestAnimationFrame(sync);
        persistChatPanelHeight();
      });
    }

    var teamMentionList = [];
    (function loadTeamJson() {
      var tel = document.getElementById("project-chat-team-json");
      if (!tel) return;
      try {
        teamMentionList = JSON.parse(tel.textContent || "[]");
      } catch (e) {
        teamMentionList = [];
      }
    })();

    var mentionState = { start: -1, highlight: 0, filtered: [] };

    function hideMentionList() {
      if (!mentionList) return;
      mentionList.hidden = true;
      mentionList.innerHTML = "";
      mentionState.start = -1;
      mentionState.filtered = [];
    }

    function filterTeamForMention(query) {
      var q = (query || "").toLowerCase();
      if (!teamMentionList.length) return [];
      var out = [];
      for (var i = 0; i < teamMentionList.length; i++) {
        var t = teamMentionList[i];
        var n = (t.name || "").toLowerCase();
        if (!q || n.indexOf(q) === 0) out.push(t);
        if (out.length >= 8) break;
      }
      return out;
    }

    function renderMentionSuggestions(items) {
      if (!mentionList) return;
      mentionList.innerHTML = "";
      for (var i = 0; i < items.length; i++) {
        (function (t, idx) {
          var li = document.createElement("li");
          li.setAttribute("role", "option");
          li.className = "project-chat-mention-suggestion";
          if (idx === mentionState.highlight) li.classList.add("is-active");
          li.textContent = t.name;
          li.addEventListener("mousedown", function (e) {
            e.preventDefault();
            insertMention(t.name);
          });
          mentionList.appendChild(li);
        })(items[i], i);
      }
      mentionList.hidden = items.length === 0;
    }

    function insertMention(name) {
      if (mentionState.start < 0 || !input) return;
      var v = input.value;
      var cur = input.selectionStart;
      var end = typeof cur === "number" ? cur : v.length;
      var before = v.slice(0, mentionState.start);
      var after = v.slice(end);
      var insert = "@" + name + " ";
      input.value = before + insert + after;
      var caret = before.length + insert.length;
      input.setSelectionRange(caret, caret);
      hideMentionList();
      input.focus();
    }

    function updateMentionUI() {
      if (!input || !mentionList) return;
      var v = input.value;
      var cur = input.selectionStart;
      if (typeof cur !== "number") {
        hideMentionList();
        return;
      }
      var before = v.slice(0, cur);
      var at = before.lastIndexOf("@");
      if (at < 0) {
        hideMentionList();
        return;
      }
      var prevCh = at > 0 ? before.charAt(at - 1) : " ";
      if (prevCh && !/\s/.test(prevCh)) {
        hideMentionList();
        return;
      }
      var query = before.slice(at + 1, cur);
      if (query.indexOf("\n") >= 0 || query.indexOf("@") >= 0) {
        hideMentionList();
        return;
      }
      var filtered = filterTeamForMention(query);
      if (!filtered.length) {
        hideMentionList();
        return;
      }
      mentionState.start = at;
      mentionState.filtered = filtered;
      mentionState.highlight = 0;
      renderMentionSuggestions(filtered);
    }

    input.addEventListener("input", updateMentionUI);
    input.addEventListener("keyup", updateMentionUI);
    input.addEventListener("blur", function () {
      window.setTimeout(hideMentionList, 180);
    });
    input.addEventListener("keydown", function (e) {
      if (!mentionList || mentionList.hidden || !mentionState.filtered.length) return;
      var n = mentionState.filtered.length;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        mentionState.highlight = (mentionState.highlight + 1) % n;
        renderMentionSuggestions(mentionState.filtered);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        mentionState.highlight = (mentionState.highlight - 1 + n) % n;
        renderMentionSuggestions(mentionState.filtered);
      } else if (e.key === "Enter") {
        e.preventDefault();
        insertMention(mentionState.filtered[mentionState.highlight].name);
      } else if (e.key === "Escape") {
        e.preventDefault();
        hideMentionList();
      }
    });

    var mediaRecorder = null;
    var recordChunks = [];
    var recordStream = null;
    var voiceShouldSend = false;
    var voiceMaxTimer = null;

    function isCollapsed() {
      return dock.classList.contains("project-chat-dock--collapsed");
    }

    function setError(msg) {
      if (!errEl) return;
      if (msg) {
        errEl.textContent = msg;
        errEl.hidden = false;
      } else {
        errEl.textContent = "";
        errEl.hidden = true;
      }
    }

    function announce(msg) {
      if (statusEl) statusEl.textContent = msg || "";
    }

    function scrollStreamBottom() {
      requestAnimationFrame(function () {
        listEl.scrollTop = listEl.scrollHeight;
      });
    }

    function syncBadge(count) {
      if (!badgeEl) return;
      if (count > 0 && isCollapsed()) {
        badgeEl.textContent = count > 99 ? "99+" : String(count);
        badgeEl.hidden = false;
      } else {
        badgeEl.hidden = true;
      }
    }

    function fetchUnread() {
      return fetch(unreadUrl, { credentials: "same-origin" })
        .then(function (res) {
          if (!res.ok) return;
          return res.json();
        })
        .then(function (data) {
          if (data && typeof data.count === "number") syncBadge(data.count);
        })
        .catch(function () {
          /* ignore */
        });
    }

    function markRead() {
      return fetch(markReadUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
        .then(function () {
          syncBadge(0);
        })
        .catch(function () {
          /* ignore */
        });
    }

    function setExpanded(open) {
      if (open) {
        dock.classList.remove("project-chat-dock--collapsed");
        applyStoredChatPanelHeight();
        if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
        syncBadge(0);
        loadMessages()
          .then(function () {
            return markRead();
          })
          .then(function () {
            scrollStreamBottom();
          });
      } else {
        dock.classList.add("project-chat-dock--collapsed");
        clearChatPanelInlineHeight();
        if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
        fetchUnread();
      }
      try {
        localStorage.setItem(storageKey, open ? "1" : "0");
      } catch (e) {
        /* ignore */
      }
    }

    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        var next = isCollapsed();
        setExpanded(next);
      });
    }

    var soundToggle = document.getElementById("project-chat-sound-toggle");
    if (soundToggle) {
      if (!soundUrl) {
        soundToggle.hidden = true;
      } else {
        syncSoundToggleUI();
        soundToggle.addEventListener("click", function () {
          setChatSoundPref(!chatSoundPrefEnabled());
          syncSoundToggleUI();
        });
      }
    }

    try {
      if (localStorage.getItem(storageKey) === "1") setExpanded(true);
      else fetchUnread();
    } catch (e) {
      fetchUnread();
    }

    function setSending(on) {
      dock.classList.toggle("is-sending", on);
      var controls = [input, btnGallery, btnCamera, btnMic, form.querySelector("#project-chat-send")];
      controls.forEach(function (el) {
        if (el) el.disabled = !!on;
      });
    }

    function renderMessages(items) {
      listEl.innerHTML = "";
      if (!items || !items.length) {
        var empty = document.createElement("p");
        empty.className = "project-chat-empty muted";
        empty.textContent = "No messages yet. Say hello or share a photo.";
        listEl.appendChild(empty);
        scrollStreamBottom();
        return;
      }
      var prev = null;
      items.forEach(function (m) {
        var grouped = false;
        if (prev) {
          var sameSide = !!prev.is_me === !!m.is_me;
          var sameUser = (prev.username || "") === (m.username || "");
          var dt = parseTime(m.created_at) - parseTime(prev.created_at);
          grouped = sameSide && sameUser && dt >= 0 && dt < GROUP_MS;
        }

        var row = document.createElement("div");
        row.className =
          "project-chat-bubble-row " +
          (m.is_me ? "project-chat-bubble-row--me" : "project-chat-bubble-row--them");
        if (grouped) row.classList.add("project-chat-bubble-row--grouped");
        row.setAttribute("data-msg-id", String(m.id));

        var av = document.createElement("div");
        av.className = "project-chat-avatar";
        av.textContent = initialFromMessage(m);
        av.setAttribute("aria-hidden", "true");

        var stack = document.createElement("div");
        stack.className = "project-chat-bubble-stack";
        if (grouped) stack.classList.add("project-chat-bubble-stack--indented");

        var meta = document.createElement("div");
        meta.className = "project-chat-bubble-meta";
        var nameEl = document.createElement("span");
        nameEl.className = "project-chat-bubble-name";
        nameEl.textContent = m.username || "Unknown";
        var timeEl = document.createElement("time");
        timeEl.className = "project-chat-bubble-time";
        timeEl.dateTime = m.created_at || "";
        timeEl.textContent = formatTime(m.created_at);
        meta.appendChild(nameEl);
        meta.appendChild(timeEl);

        var bubble = document.createElement("div");
        bubble.className = "project-chat-bubble";

        if (m.message) {
          var text = document.createElement("div");
          text.className = "project-chat-text";
          appendMessageTextWithMentions(text, m.message, teamMentionList);
          bubble.appendChild(text);
        }

        if (m.image_url) {
          var mw = document.createElement("div");
          mw.className = "project-chat-bubble-media";
          var img = document.createElement("img");
          img.src = m.image_url;
          img.alt = "Photo";
          img.loading = "lazy";
          mw.appendChild(img);
          bubble.appendChild(mw);
        }

        if (m.audio_url) {
          var aw = document.createElement("div");
          aw.className = "project-chat-bubble-media project-chat-bubble-media--audio";
          var aud = document.createElement("audio");
          aud.controls = true;
          aud.preload = "metadata";
          aud.src = m.audio_url;
          aud.setAttribute("aria-label", "Voice note");
          aw.appendChild(aud);
          bubble.appendChild(aw);
        }

        if (!grouped) stack.appendChild(meta);
        stack.appendChild(bubble);
        if (!grouped) row.appendChild(av);
        row.appendChild(stack);
        listEl.appendChild(row);
        prev = m;
      });
      scrollStreamBottom();
      rememberLoadedMessageIds(items);
    }

    function loadMessages() {
      setError("");
      return fetch(messagesUrl, { credentials: "same-origin" })
        .then(function (res) {
          if (res.status === 403) throw new Error("You cannot view this chat.");
          if (!res.ok) throw new Error("Could not load messages.");
          return res.json();
        })
        .then(function (data) {
          renderMessages(data.messages || []);
          announce("");
        })
        .catch(function (e) {
          setError(e.message || "Could not load messages.");
          announce("Error loading chat.");
        });
    }

    function postFormData(fd) {
      setSending(true);
      announce("Sending…");
      return fetch(messagesUrl, {
        method: "POST",
        body: fd,
        credentials: "same-origin",
      })
        .then(function (res) {
          var ct = res.headers.get("content-type") || "";
          if (ct.indexOf("application/json") === -1) {
            if (!res.ok) throw new Error("Could not send message.");
            return {};
          }
          return res.json().then(function (data) {
            if (!res.ok) {
              var detail = (data && data.detail) || data.error || "Send failed.";
              throw new Error(detail);
            }
            return data;
          });
        })
        .then(function () {
          input.value = "";
          if (fileGallery) fileGallery.value = "";
          if (fileCamera) fileCamera.value = "";
          announce("");
          return loadMessages().then(function () {
            if (!isCollapsed()) return markRead();
            return fetchUnread();
          });
        })
        .catch(function (e) {
          announce("");
          setError(e.message || "Send failed.");
        })
        .finally(function () {
          setSending(false);
        });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = (input.value || "").trim();
      if (!text) {
        setError("Type a message, or attach a photo or voice note.");
        return;
      }
      setError("");
      var fd = new FormData();
      fd.append("message", text);
      postFormData(fd);
    });

    if (fileGallery) {
      fileGallery.addEventListener("change", function () {
        if (!fileGallery.files || !fileGallery.files.length) return;
        setError("");
        var fd = new FormData();
        var t = (input.value || "").trim();
        if (t) fd.append("message", t);
        fd.append("image", fileGallery.files[0]);
        postFormData(fd);
      });
    }

    if (btnGallery && fileGallery) {
      btnGallery.addEventListener("click", function () {
        fileGallery.click();
      });
    }

    if (fileCamera) {
      fileCamera.addEventListener("change", function () {
        if (!fileCamera.files || !fileCamera.files.length) return;
        setError("");
        var fd = new FormData();
        var t = (input.value || "").trim();
        if (t) fd.append("message", t);
        fd.append("image", fileCamera.files[0]);
        postFormData(fd);
      });
    }

    function closeCameraModal(stream, root) {
      if (stream) {
        stream.getTracks().forEach(function (t) {
          t.stop();
        });
      }
      if (root && root.parentNode) root.parentNode.removeChild(root);
    }

    if (btnCamera && fileCamera) {
      btnCamera.addEventListener("click", function () {
        setError("");
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          fileCamera.click();
          return;
        }
        navigator.mediaDevices
          .getUserMedia({ video: { facingMode: "environment" }, audio: false })
          .then(function (stream) {
            var root = document.createElement("div");
            root.className = "project-chat-camera-modal";
            root.setAttribute("role", "dialog");
            root.setAttribute("aria-modal", "true");
            root.setAttribute("aria-label", "Camera");
            var inner = document.createElement("div");
            inner.className = "project-chat-camera-modal-inner";
            var video = document.createElement("video");
            video.autoplay = true;
            video.playsInline = true;
            video.muted = true;
            video.srcObject = stream;
            var actions = document.createElement("div");
            actions.className = "project-chat-camera-modal-actions";
            var btnCap = document.createElement("button");
            btnCap.type = "button";
            btnCap.className = "btn btn--primary";
            btnCap.textContent = "Capture";
            var btnCancel = document.createElement("button");
            btnCancel.type = "button";
            btnCancel.className = "btn btn--ghost";
            btnCancel.textContent = "Cancel";
            actions.appendChild(btnCancel);
            actions.appendChild(btnCap);
            inner.appendChild(video);
            inner.appendChild(actions);
            root.appendChild(inner);
            document.body.appendChild(root);

            function cleanup() {
              closeCameraModal(stream, root);
            }

            btnCancel.addEventListener("click", cleanup);
            root.addEventListener("click", function (ev) {
              if (ev.target === root) cleanup();
            });

            btnCap.addEventListener("click", function () {
              try {
                var w = video.videoWidth;
                var h = video.videoHeight;
                if (!w || !h) {
                  setError("Camera not ready. Try again.");
                  cleanup();
                  return;
                }
                var canvas = document.createElement("canvas");
                canvas.width = w;
                canvas.height = h;
                var ctx = canvas.getContext("2d");
                ctx.drawImage(video, 0, 0);
                canvas.toBlob(
                  function (blob) {
                    cleanup();
                    if (!blob) {
                      setError("Could not capture photo.");
                      return;
                    }
                    var file = new File([blob], "camera.jpg", { type: "image/jpeg" });
                    var fd = new FormData();
                    var t = (input.value || "").trim();
                    if (t) fd.append("message", t);
                    fd.append("image", file);
                    postFormData(fd);
                  },
                  "image/jpeg",
                  0.88
                );
              } catch (err) {
                setError("Could not capture photo.");
                cleanup();
              }
            });
          })
          .catch(function () {
            setError("Camera unavailable — try the file picker.");
            fileCamera.click();
          });
      });
    }

    function clearVoiceTimers() {
      if (voiceMaxTimer) {
        clearTimeout(voiceMaxTimer);
        voiceMaxTimer = null;
      }
    }

    function finishRecordingUI() {
      clearVoiceTimers();
      if (btnMic) btnMic.classList.remove("is-recording");
    }

    function stopVoiceRecording(send) {
      voiceShouldSend = !!send;
      if (mediaRecorder && mediaRecorder.state === "recording") {
        try {
          mediaRecorder.stop();
        } catch (e) {
          /* ignore */
        }
      } else {
        recordChunks = [];
        if (recordStream) {
          recordStream.getTracks().forEach(function (t) {
            t.stop();
          });
          recordStream = null;
        }
        mediaRecorder = null;
        finishRecordingUI();
      }
    }

    function pickMime() {
      if (typeof MediaRecorder === "undefined") return "";
      var types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
      for (var i = 0; i < types.length; i++) {
        if (MediaRecorder.isTypeSupported(types[i])) return types[i];
      }
      return "";
    }

    if (btnMic) {
      btnMic.addEventListener("click", function () {
        setError("");
        if (mediaRecorder && mediaRecorder.state === "recording") {
          stopVoiceRecording(true);
          return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          setError("Voice notes are not supported in this browser.");
          return;
        }
        navigator.mediaDevices
          .getUserMedia({ audio: true })
          .then(function (stream) {
            recordStream = stream;
            recordChunks = [];
            var mime = pickMime();
            try {
              mediaRecorder = mime
                ? new MediaRecorder(stream, { mimeType: mime })
                : new MediaRecorder(stream);
            } catch (e) {
              mediaRecorder = new MediaRecorder(stream);
            }
            mediaRecorder.ondataavailable = function (ev) {
              if (ev.data && ev.data.size) recordChunks.push(ev.data);
            };
            mediaRecorder.onstop = function () {
              var mimeType = (mediaRecorder && mediaRecorder.mimeType) || "audio/webm";
              var blob = new Blob(recordChunks, { type: mimeType });
              recordChunks = [];
              if (recordStream) {
                recordStream.getTracks().forEach(function (t) {
                  t.stop();
                });
                recordStream = null;
              }
              mediaRecorder = null;
              finishRecordingUI();
              if (voiceShouldSend) {
                if (blob.size > 0) {
                  var ext = extForAudioBlob(blob);
                  var file = new File([blob], "voice" + ext, {
                    type: blob.type || "audio/webm",
                  });
                  var fd = new FormData();
                  var t = (input.value || "").trim();
                  if (t) fd.append("message", t);
                  fd.append("audio", file);
                  postFormData(fd);
                } else {
                  setError("Recording was empty.");
                }
              }
              voiceShouldSend = false;
            };
            mediaRecorder.start(200);
            if (btnMic) btnMic.classList.add("is-recording");
            voiceMaxTimer = window.setTimeout(function () {
              if (mediaRecorder && mediaRecorder.state === "recording") {
                stopVoiceRecording(true);
              }
            }, RECORDING_MAX_MS);
          })
          .catch(function (err) {
            var msg = "Microphone unavailable.";
            if (err && err.name === "NotAllowedError") msg = "Microphone access was denied.";
            setError(msg);
          });
      });
    }

    if (!isNaN(projectId)) {
      function bindChatSocket() {
        var s = window.__tmSocket;
        if (!s) return;

        function joinProjectRoom() {
          s.emit("join_project", { project_id: projectId });
        }

        s.on("connect", joinProjectRoom);
        if (s.connected) joinProjectRoom();

        s.on("chat_updated", function (payload) {
          if (!payload || payload.project_id !== projectId) return;
          maybeNotifyIncomingChat(payload);
          if (isCollapsed()) {
            fetchUnread();
          } else {
            loadMessages().then(function () {
              return markRead();
            });
          }
        });

        window.addEventListener("beforeunload", function () {
          try {
            s.emit("leave_project", { project_id: projectId });
          } catch (err) {
            /* ignore */
          }
        });
      }

      bindChatSocket();
    }
  });
})();
