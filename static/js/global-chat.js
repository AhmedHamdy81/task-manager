(function () {
  "use strict";

  var OPEN_KEY = "tm-global-chat-open-ids";
  var MAX_WINDOWS = 5;
  var CHAT_W = 300;
  var CHAT_H = 400;
  var GAP = 10;
  var LAUNCHER_R = 16;
  var LAUNCHER_W = 52;
  var RECORDING_MAX_MS = 120000;
  var GROUP_MS = 5 * 60 * 1000;
  var CHAT_SOUND_PREF_KEY = "tm-chat-notify-sound";
  var CHAT_QUICK_REACTIONS = ["👍", "❤️", "😂", "😮"];

  function postChatReaction(projectId, messageId, emoji) {
    if (window.tmChat && window.tmChat.api && window.tmChat.api.postReaction) {
      return window.tmChat.api.postReaction(projectId, messageId, emoji);
    }
    return Promise.reject(new Error("Chat API not loaded"));
  }

  function fillChatReactionRow(rowEl, summaries, messageId, msgCtx) {
    if (!rowEl || !msgCtx) return;
    rowEl.innerHTML = "";
    var map = {};
    (summaries || []).forEach(function (s) {
      map[s.emoji] = s;
    });
    CHAT_QUICK_REACTIONS.forEach(function (em) {
      var s = map[em];
      var n = s ? s.count : 0;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "project-chat-reaction-pill";
      if (s && s.me) btn.classList.add("is-mine");
      btn.setAttribute("aria-label", "React " + em);
      btn.textContent = em + (n > 0 ? " " + n : "");
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        postChatReaction(msgCtx.projectId, messageId, em)
          .then(function (data) {
            fillChatReactionRow(rowEl, data.reactions, messageId, msgCtx);
          })
          .catch(function () {});
      });
      rowEl.appendChild(btn);
    });
  }

  function formatTime(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
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
      if (at > pos) container.appendChild(document.createTextNode(text.slice(pos, at)));
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
        inner.href = "#";
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

  /** Append one bubble row; returns m for use as next `prev`. */
  function appendOneMessageRow(listEl, m, prev, teamMentionList, msgCtx) {
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
      var isDel = !!m.is_deleted;
      if (isDel) {
        bubble.classList.add("project-chat-bubble--deleted");
        var delText = document.createElement("div");
        delText.className = "project-chat-text project-chat-text--deleted";
        delText.textContent = "This message was deleted";
        bubble.appendChild(delText);
      } else {
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
      }

      var wrap = document.createElement("div");
      wrap.className = "project-chat-bubble-wrap";
      wrap.appendChild(bubble);

      if (!isDel && msgCtx && msgCtx.projectId != null && msgCtx.reloadMessages) {
        var reactRow = document.createElement("div");
        reactRow.className = "project-chat-reactions";
        fillChatReactionRow(reactRow, m.reactions || [], m.id, msgCtx);

        var toolbar = document.createElement("div");
        toolbar.className = "project-chat-msg-toolbar";
        var menuBtn = document.createElement("button");
        menuBtn.type = "button";
        menuBtn.className = "project-chat-msg-menu-btn";
        menuBtn.setAttribute("aria-label", "Message options");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.innerHTML = "&#8942;";
        var pop = document.createElement("div");
        pop.className = "project-chat-msg-popover";
        pop.hidden = true;
        pop.setAttribute("role", "menu");
        if (m.is_me) {
          var delAct = document.createElement("button");
          delAct.type = "button";
          delAct.className = "project-chat-msg-popover-action";
          delAct.setAttribute("role", "menuitem");
          delAct.textContent = "Delete for everyone";
          delAct.addEventListener("click", function (e) {
            e.stopPropagation();
            pop.hidden = true;
            menuBtn.setAttribute("aria-expanded", "false");
            fetch("/projects/" + msgCtx.projectId + "/chat/messages/" + m.id, {
              method: "DELETE",
              credentials: "same-origin",
            })
              .then(function (res) {
                if (!res.ok) throw new Error("delete");
                return msgCtx.reloadMessages();
              })
              .catch(function () {});
          });
          pop.appendChild(delAct);
        }
        var reactLbl = document.createElement("div");
        reactLbl.className = "project-chat-msg-popover-label";
        reactLbl.textContent = "React";
        pop.appendChild(reactLbl);
        var reactGrid = document.createElement("div");
        reactGrid.className = "project-chat-msg-popover-reacts";
        CHAT_QUICK_REACTIONS.forEach(function (em) {
          var eb = document.createElement("button");
          eb.type = "button";
          eb.className = "project-chat-msg-popover-emoji";
          eb.textContent = em;
          eb.addEventListener("click", function (e) {
            e.stopPropagation();
            pop.hidden = true;
            menuBtn.setAttribute("aria-expanded", "false");
            postChatReaction(msgCtx.projectId, m.id, em)
              .then(function (data) {
                fillChatReactionRow(reactRow, data.reactions, m.id, msgCtx);
              })
              .catch(function () {});
          });
          reactGrid.appendChild(eb);
        });
        pop.appendChild(reactGrid);
        menuBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          var willOpen = pop.hidden;
          listEl.querySelectorAll(".project-chat-msg-popover").forEach(function (p) {
            p.hidden = true;
          });
          listEl.querySelectorAll(".project-chat-msg-menu-btn").forEach(function (b) {
            b.setAttribute("aria-expanded", "false");
          });
          pop.hidden = !willOpen;
          menuBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
        });
        toolbar.appendChild(menuBtn);
        toolbar.appendChild(pop);
        wrap.appendChild(toolbar);
        wrap.appendChild(reactRow);
      }

      if (!grouped) stack.appendChild(meta);
      stack.appendChild(wrap);
      if (!grouped) row.appendChild(av);
      row.appendChild(stack);
      listEl.appendChild(row);
      return m;
  }

  /**
   * If nextItems extends prevItems with the same prefix, append only new rows (keeps scroll stable).
   * @returns {{ applied: boolean, added: number }}
   */
  function tryAppendNewMessagesOnly(listEl, prevItems, nextItems, teamMentionList, msgCtx) {
    if (!prevItems || !prevItems.length || !nextItems || !nextItems.length) {
      return { applied: false, added: 0 };
    }
    if (nextItems.length < prevItems.length) {
      return { applied: false, added: 0 };
    }
    for (var i = 0; i < prevItems.length; i++) {
      if ((prevItems[i].id || 0) !== (nextItems[i].id || 0)) {
        return { applied: false, added: 0 };
      }
    }
    var newSlice = nextItems.slice(prevItems.length);
    if (!newSlice.length) {
      return { applied: true, added: 0 };
    }
    var emptyEl = listEl.querySelector(".project-chat-empty");
    if (emptyEl) {
      emptyEl.remove();
    }
    var last = prevItems[prevItems.length - 1];
    for (var j = 0; j < newSlice.length; j++) {
      last = appendOneMessageRow(listEl, newSlice[j], last, teamMentionList, msgCtx);
    }
    return { applied: true, added: newSlice.length };
  }

  function renderMessagesTo(listEl, items, teamMentionList, msgCtx) {
    listEl.innerHTML = "";
    if (!items || !items.length) {
      var empty = document.createElement("p");
      empty.className = "project-chat-empty muted";
      empty.textContent = "No messages yet.";
      listEl.appendChild(empty);
      return;
    }
    var prev = null;
    for (var k = 0; k < items.length; k++) {
      prev = appendOneMessageRow(listEl, items[k], prev, teamMentionList, msgCtx);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var shell = document.getElementById("global-chat-container");
    if (!shell || !shell.getAttribute("data-threads-url")) return;

    document.addEventListener("click", function (e) {
      if (!shell.contains(e.target)) return;
      if (e.target.closest(".project-chat-msg-menu-btn")) return;
      if (e.target.closest(".project-chat-msg-popover")) return;
      shell.querySelectorAll(".project-chat-msg-popover").forEach(function (p) {
        p.hidden = true;
      });
      shell.querySelectorAll(".project-chat-msg-menu-btn").forEach(function (b) {
        b.setAttribute("aria-expanded", "false");
      });
    });

    var threadsUrl = shell.getAttribute("data-threads-url");
    var soundUrl = shell.getAttribute("data-notify-sound-url") || "";
    var rawV = shell.getAttribute("data-viewer-id");
    var myDirectoryUserId = rawV && rawV !== "" ? parseInt(rawV, 10) : null;
    if (isNaN(myDirectoryUserId)) myDirectoryUserId = null;

    var threadsMap = {};
    var openOrder = [];
    var windows = {};
    var dragMove = null;
    var WIN_Z_MIN = 1100;
    var WIN_Z_MAX = 9980;
    var winZCounter = WIN_Z_MIN;
    var knownChatMessageIds = new Set();
    var notifyAudioEl = null;
    var listPanelHidden = true;

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
      } catch (e) {}
    }

    function playChatNotifySound() {
      if (!soundUrl || !chatSoundPrefEnabled()) return;
      try {
        if (!notifyAudioEl) {
          notifyAudioEl = new Audio(soundUrl);
          notifyAudioEl.preload = "auto";
        }
        notifyAudioEl.volume = 0.35;
        notifyAudioEl.currentTime = 0;
        var p = notifyAudioEl.play();
        if (p && typeof p.catch === "function") p.catch(function () {});
      } catch (e) {}
    }

    function maybeNotifyIncomingChat(payload) {
      if (!payload || payload.message_id == null || payload.user_id == null) return;
      if (myDirectoryUserId != null && payload.user_id === myDirectoryUserId) return;
      var mid = payload.message_id;
      if (knownChatMessageIds.has(mid)) return;
      knownChatMessageIds.add(mid);
      playChatNotifySound();
    }

    function rememberLoadedMessageIds(items) {
      if (!items || !items.length) return;
      for (var i = 0; i < items.length; i++) {
        if (items[i].id != null) knownChatMessageIds.add(items[i].id);
      }
    }

    function loadPersistedOpen() {
      try {
        var raw = localStorage.getItem(OPEN_KEY);
        if (!raw) return [];
        var arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr.map(function (x) { return parseInt(x, 10); }).filter(function (n) { return !isNaN(n); }) : [];
      } catch (e) {
        return [];
      }
    }

    function persistOpen() {
      try {
        localStorage.setItem(OPEN_KEY, JSON.stringify(openOrder));
      } catch (e) {}
    }

    function launcherTotalWidth() {
      return LAUNCHER_R + LAUNCHER_W + GAP;
    }

    function bumpWindowZ() {
      winZCounter += 1;
      if (winZCounter >= WIN_Z_MAX) winZCounter = WIN_Z_MIN + 1;
      return winZCounter;
    }

    function bringFloatingChatToFront(chatWin) {
      if (!chatWin || !chatWin.root) return;
      chatWin.root.style.zIndex = String(bumpWindowZ());
      Object.keys(windows).forEach(function (k) {
        var o = windows[parseInt(k, 10)];
        if (o && o.root) o.root.classList.remove("global-chat-window--active");
      });
      chatWin.root.classList.add("global-chat-window--active");
    }

    document.addEventListener("mousemove", function (e) {
      if (!dragMove) return;
      var dx = e.clientX - dragMove.startX;
      var dy = e.clientY - dragMove.startY;
      var w = dragMove.win;
      w.root.style.right = "auto";
      w.root.style.left = dragMove.origLeft + dx + "px";
      w.root.style.bottom = dragMove.origBottom - dy + "px";
      w.userPlaced = true;
      w.root.classList.add("global-chat-window--placed");
    });
    document.addEventListener("mouseup", function () {
      dragMove = null;
    });

    function relayoutWindows() {
      var base = launcherTotalWidth();
      openOrder.forEach(function (pid, i) {
        var w = windows[pid];
        if (w && w.root && !w.userPlaced) {
          w.root.style.right = base + i * (CHAT_W + GAP) + "px";
          w.root.style.left = "auto";
        }
      });
    }

    function totalUnreadAcrossThreads() {
      var n = 0;
      Object.keys(threadsMap).forEach(function (k) {
        n += threadsMap[k].unread || 0;
      });
      return n;
    }

    function makeOnClose(pid) {
      return function () {
        delete windows[pid];
        var j = openOrder.indexOf(pid);
        if (j >= 0) openOrder.splice(j, 1);
        persistOpen();
        relayoutWindows();
      };
    }

    function attachChatWindow(pid) {
      if (!threadsMap[pid] || windows[pid]) return;
      windows[pid] = new ChatWindow(pid, threadsMap[pid], {
        bringToFront: function (selfWin) {
          bringFloatingChatToFront(selfWin);
        },
        soundUrl: soundUrl,
        myDirectoryUserId: myDirectoryUserId,
        knownIds: knownChatMessageIds,
        onClose: makeOnClose(pid),
        afterSend: function () {
          return fetchThreads();
        },
      });
      shell.appendChild(windows[pid].root);
    }

    function syncLauncherBadge() {
      var n = totalUnreadAcrossThreads();
      if (!launcherBadge) return;
      if (n > 0) {
        launcherBadge.textContent = n > 99 ? "99+" : String(n);
        launcherBadge.hidden = false;
      } else {
        launcherBadge.hidden = true;
      }
    }

    function refreshPanelList() {
      panelList.innerHTML = "";
      var ids = Object.keys(threadsMap).map(Number);
      if (!ids.length) {
        var p = document.createElement("p");
        p.className = "muted";
        p.style.padding = "0.75rem";
        p.textContent = "No project chats. Join a project team first.";
        panelList.appendChild(p);
        return;
      }
      ids.sort(function (a, b) {
        var ta = threadsMap[a];
        var tb = threadsMap[b];
        var sa = ta.last_sort || 0;
        var sb = tb.last_sort || 0;
        if (sb !== sa) return sb - sa;
        return (ta.name || "").localeCompare(tb.name || "");
      });
      ids.forEach(function (pid) {
        var t = threadsMap[pid];
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "global-chat-panel-row";
        var nm = document.createElement("div");
        nm.className = "global-chat-panel-row-name";
        nm.textContent = t.name;
        var pr = document.createElement("div");
        pr.className = "global-chat-panel-row-preview";
        pr.textContent = t.last_preview || "";
        var meta = document.createElement("div");
        meta.className = "global-chat-panel-row-meta";
        var tm = document.createElement("span");
        tm.textContent = t.last_at ? formatTime(t.last_at) : "";
        var ub = document.createElement("span");
        ub.className = "global-chat-panel-unread";
        if (t.unread > 0) ub.textContent = "(" + (t.unread > 99 ? "99+" : t.unread) + ")";
        else ub.textContent = "";
        meta.appendChild(tm);
        meta.appendChild(ub);
        btn.appendChild(nm);
        btn.appendChild(pr);
        btn.appendChild(meta);
        btn.addEventListener("click", function () {
          openOrFocusChat(pid);
          listPanel.hidden = true;
          listPanelHidden = true;
        });
        panelList.appendChild(btn);
      });
    }

    function updateThreadSortFields() {
      Object.keys(threadsMap).forEach(function (k) {
        var t = threadsMap[k];
        var ts = 0;
        if (t.last_at) {
          var d = new Date(t.last_at);
          ts = isNaN(d.getTime()) ? 0 : d.getTime();
        }
        t.last_sort = ts;
      });
    }

    function fetchThreads() {
      return fetch(threadsUrl, { credentials: "same-origin" })
        .then(function (res) {
          if (!res.ok) return;
          return res.json();
        })
        .then(function (data) {
          if (!data || !Array.isArray(data.threads)) return;
          threadsMap = {};
          data.threads.forEach(function (t) {
            var ta = new Date(t.last_at || 0).getTime();
            t.last_sort = isNaN(ta) ? 0 : ta;
            threadsMap[t.project_id] = t;
          });
          updateThreadSortFields();
          refreshPanelList();
          Object.keys(windows).forEach(function (pidStr) {
            var pid = parseInt(pidStr, 10);
            if (!threadsMap[pid]) {
              if (windows[pid]) {
                windows[pid].destroy();
                delete windows[pid];
              }
              var ix = openOrder.indexOf(pid);
              if (ix >= 0) openOrder.splice(ix, 1);
            } else if (windows[pid]) {
              windows[pid].syncThread(threadsMap[pid]);
            }
          });
          syncLauncherBadge();
          openOrder = openOrder.filter(function (pid) {
            return threadsMap[pid];
          });
          persistOpen();
          relayoutWindows();
          bindAllSocketRooms();
        })
        .catch(function () {});
    }

    function bindAllSocketRooms() {
      var s = window.__tmSocket;
      if (!s || !s.connected) return;
      var ids = Object.keys(threadsMap).map(Number);
      s.emit("sync_chat_rooms", { project_ids: ids });
    }

    function openOrFocusChat(pid) {
      if (!threadsMap[pid]) return;
      if (windows[pid]) {
        var idx = openOrder.indexOf(pid);
        if (idx >= 0) openOrder.splice(idx, 1);
        openOrder.unshift(pid);
        persistOpen();
        relayoutWindows();
        windows[pid].focus();
        return;
      }
      if (openOrder.length >= MAX_WINDOWS) {
        var drop = openOrder.pop();
        if (windows[drop]) {
          windows[drop].destroy();
          delete windows[drop];
        }
        persistOpen();
      }
      openOrder.unshift(pid);
      persistOpen();
      attachChatWindow(pid);
      relayoutWindows();
      windows[pid].boot();
    }

    function applyHash() {
      var h = (location.hash || "").replace(/^#/, "");
      var m = /^gchat-(\d+)$/.exec(h);
      if (m) {
        var id = parseInt(m[1], 10);
        fetchThreads().then(function () {
          if (threadsMap[id]) openOrFocusChat(id);
        });
      }
    }

    /* ——— ChatWindow ——— */
    function ChatWindow(projectId, thread, opts) {
      this.projectId = projectId;
      this.thread = thread;
      this.opts = opts;
      this.teamMentionList = [];
      /** @type {Array|null} last messages array from API (for incremental DOM updates) */
      this.lastMessageSnapshot = null;
      this.markReadUrl = thread.mark_read_url;
      this.messagesUrl = thread.messages_url;
      this.userPlaced = false;
      var self = this;

      this.root = document.createElement("div");
      this.root.className = "global-chat-window";
      this.root.style.width = CHAT_W + "px";
      this.root.style.height = CHAT_H + "px";
      this._topResizeListeners = null;

      var resizeHandle = document.createElement("div");
      resizeHandle.className = "chat-resize-handle";
      resizeHandle.id = "chat-top-resize-" + projectId;
      resizeHandle.setAttribute("aria-label", "Resize chat height");
      resizeHandle.addEventListener("mousedown", function (e) {
        if (self.root.classList.contains("global-chat-window--collapsed")) return;
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        self.bringToFront();
        var startY = e.clientY;
        var startH = self.root.offsetHeight;
        var minH = 250;
        function maxH() {
          return Math.floor(window.innerHeight * 0.8);
        }
        function onMove(ev) {
          var delta = ev.clientY - startY;
          var newH = startH - delta;
          if (newH < minH) newH = minH;
          var cap = maxH();
          if (newH > cap) newH = cap;
          self.root.style.height = newH + "px";
        }
        function onUp() {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          document.body.style.userSelect = "";
          document.body.style.webkitUserSelect = "";
          self.root.classList.remove("is-resizing-top");
          self._topResizeListeners = null;
        }
        document.body.style.userSelect = "none";
        document.body.style.webkitUserSelect = "none";
        self.root.classList.add("is-resizing-top");
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        self._topResizeListeners = { move: onMove, up: onUp };
      });

      var head = document.createElement("div");
      head.className = "global-chat-window-head";
      this.titleEl = document.createElement("h3");
      this.titleEl.className = "global-chat-window-title";
      this.titleEl.textContent = thread.name || "Chat";
      this.headBadge = document.createElement("span");
      this.headBadge.className = "global-chat-window-head-badge";
      this.updateHeaderUnread(thread.unread || 0);
      var minBtn = document.createElement("button");
      minBtn.type = "button";
      minBtn.className = "global-chat-window-min";
      minBtn.setAttribute("aria-label", "Minimize chat");
      minBtn.setAttribute("aria-expanded", "true");
      minBtn.textContent = "\u2212";
      var closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "global-chat-window-close";
      closeBtn.setAttribute("aria-label", "Close chat");
      closeBtn.innerHTML = "&times;";
      minBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        self.root.classList.toggle("global-chat-window--collapsed");
        var collapsed = self.root.classList.contains("global-chat-window--collapsed");
        minBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      });
      closeBtn.addEventListener("click", function () {
        self.destroy();
        opts.onClose();
      });
      head.addEventListener("click", function (e) {
        if (!self.root.classList.contains("global-chat-window--collapsed")) return;
        if (e.target.closest("button")) return;
        self.root.classList.remove("global-chat-window--collapsed");
        minBtn.setAttribute("aria-expanded", "true");
        self.bringToFront();
      });
      head.addEventListener("mousedown", function (e) {
        if (self.root.classList.contains("global-chat-window--collapsed")) return;
        if (e.button !== 0) return;
        if (e.target.closest("button")) return;
        var r = self.root.getBoundingClientRect();
        dragMove = {
          win: self,
          startX: e.clientX,
          startY: e.clientY,
          origLeft: r.left,
          origBottom: window.innerHeight - r.bottom,
        };
        self.bringToFront();
        e.preventDefault();
      });
      head.appendChild(this.titleEl);
      head.appendChild(this.headBadge);
      head.appendChild(minBtn);
      head.appendChild(closeBtn);
      this.root.appendChild(resizeHandle);
      this.root.appendChild(head);
      this.root.addEventListener("mousedown", function () {
        self.bringToFront();
      });

      this.listEl = document.createElement("div");
      this.listEl.className = "global-chat-window-stream project-chat-stream";
      this.listEl.setAttribute("role", "log");
      this.root.appendChild(this.listEl);

      var foot = document.createElement("div");
      foot.className = "global-chat-window-foot";
      this.form = document.createElement("form");
      this.form.className = "project-chat-composer global-chat-window-form";
      this.form.action = "#";
      var field = document.createElement("div");
      field.className = "project-chat-composer-field";
      this.input = document.createElement("input");
      this.input.type = "text";
      this.input.className = "project-chat-composer-input";
      this.input.id = "gchat-in-" + projectId;
      this.input.placeholder = "Message…";
      this.input.maxLength = 8000;
      this.input.autocomplete = "off";
      this.mentionList = document.createElement("ul");
      this.mentionList.className = "project-chat-mention-suggestions";
      this.mentionList.hidden = true;
      this.mentionList.setAttribute("role", "listbox");
      field.appendChild(this.input);
      field.appendChild(this.mentionList);
      var actions = document.createElement("div");
      actions.className = "project-chat-composer-actions";
      this.btnGal = document.createElement("button");
      this.btnGal.type = "button";
      this.btnGal.className = "project-chat-icon-btn";
      this.btnGal.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';
      this.btnCam = document.createElement("button");
      this.btnCam.type = "button";
      this.btnCam.className = "project-chat-icon-btn";
      this.btnCam.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>';
      this.btnMic = document.createElement("button");
      this.btnMic.type = "button";
      this.btnMic.className = "project-chat-icon-btn";
      this.btnMic.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>';
      this.btnSend = document.createElement("button");
      this.btnSend.type = "submit";
      this.btnSend.className = "btn btn--primary";
      this.btnSend.textContent = "Send";
      actions.appendChild(this.btnGal);
      actions.appendChild(this.btnCam);
      actions.appendChild(this.btnMic);
      actions.appendChild(this.btnSend);
      this.fileGal = document.createElement("input");
      this.fileGal.type = "file";
      this.fileGal.className = "sr-only";
      this.fileGal.accept = "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp";
      this.fileCam = document.createElement("input");
      this.fileCam.type = "file";
      this.fileCam.className = "sr-only";
      this.fileCam.accept = "image/*";
      this.fileCam.setAttribute("capture", "environment");
      this.form.appendChild(field);
      this.form.appendChild(actions);
      this.form.appendChild(this.fileGal);
      this.form.appendChild(this.fileCam);
      foot.appendChild(this.form);
      this.errEl = document.createElement("p");
      this.errEl.className = "project-chat-error";
      this.errEl.hidden = true;
      foot.appendChild(this.errEl);
      this.root.appendChild(foot);

      this._bindForm();
      this._bindMention();
      this._bindMedia();
    }

    ChatWindow.prototype.bringToFront = function () {
      if (this.opts && this.opts.bringToFront) this.opts.bringToFront(this);
    };

    ChatWindow.prototype.updateHeaderUnread = function (n) {
      if (n > 0) {
        this.headBadge.textContent = "(" + (n > 99 ? "99+" : n) + ")";
        this.headBadge.hidden = false;
      } else {
        this.headBadge.textContent = "";
        this.headBadge.hidden = true;
      }
    };

    ChatWindow.prototype.syncThread = function (t) {
      this.thread = t;
      this.markReadUrl = t.mark_read_url;
      this.messagesUrl = t.messages_url;
      this.titleEl.textContent = t.name || "Chat";
      this.updateHeaderUnread(t.unread || 0);
    };

    ChatWindow.prototype.focusComposer = function () {
      if (!this.input) return;
      if (this.root.classList.contains("global-chat-window--collapsed")) return;
      try {
        this.input.focus();
        var len = (this.input.value || "").length;
        if (typeof this.input.setSelectionRange === "function") {
          this.input.setSelectionRange(len, len);
        }
      } catch (e) {}
    };

    ChatWindow.prototype.focus = function () {
      this.bringToFront();
      this.focusComposer();
    };

    ChatWindow.prototype.setError = function (msg) {
      if (msg) {
        this.errEl.textContent = msg;
        this.errEl.hidden = false;
      } else {
        this.errEl.textContent = "";
        this.errEl.hidden = true;
      }
    };

    ChatWindow.prototype.markRead = function () {
      if (!this.markReadUrl) return Promise.resolve();
      return fetch(this.markReadUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }).catch(function () {});
    };

    ChatWindow.prototype.loadTeam = function () {
      var self = this;
      return fetch("/projects/" + this.projectId + "/chat/team", { credentials: "same-origin" })
        .then(function (res) {
          return res.ok ? res.json() : { team: [] };
        })
        .then(function (data) {
          self.teamMentionList = (data && data.team) || [];
        })
        .catch(function () {
          self.teamMentionList = [];
        });
    };

    ChatWindow.prototype.loadMessages = function () {
      var self = this;
      if (!this.messagesUrl) return Promise.resolve();
      return fetch(this.messagesUrl, { credentials: "same-origin" })
        .then(function (res) {
          if (res.status === 403) throw new Error("No access");
          if (!res.ok) throw new Error("Load failed");
          return res.json();
        })
        .then(function (data) {
          var items = data.messages || [];
          var msgCtx = {
            projectId: self.projectId,
            reloadMessages: function () {
              return self.loadMessages();
            },
          };
          var nearBottom =
            self.listEl.scrollHeight - self.listEl.scrollTop - self.listEl.clientHeight < 80;
          var inc = tryAppendNewMessagesOnly(
            self.listEl,
            self.lastMessageSnapshot,
            items,
            self.teamMentionList,
            msgCtx
          );
          if (!inc.applied) {
            renderMessagesTo(self.listEl, items, self.teamMentionList, msgCtx);
          }
          self.lastMessageSnapshot = items.slice();
          rememberLoadedMessageIds(items);
          requestAnimationFrame(function () {
            if (!inc.applied || nearBottom) {
              self.listEl.scrollTop = self.listEl.scrollHeight;
            }
          });
        })
        .catch(function (e) {
          self.setError(e.message || "Could not load");
        });
    };

    ChatWindow.prototype.postFormData = function (fd) {
      var self = this;
      if (!this.messagesUrl) return;
      var sendSucceeded = false;
      this.root.classList.add("is-sending");
      this.input.disabled = true;
      this.btnSend.disabled = true;
      this.btnGal.disabled = true;
      this.btnCam.disabled = true;
      this.btnMic.disabled = true;
      return fetch(this.messagesUrl, { method: "POST", body: fd, credentials: "same-origin" })
        .then(function (res) {
          var ct = res.headers.get("content-type") || "";
          if (ct.indexOf("application/json") === -1) {
            if (!res.ok) throw new Error("Send failed");
            return {};
          }
          return res.json().then(function (data) {
            if (!res.ok) throw new Error((data && data.detail) || data.error || "Send failed");
            return data;
          });
        })
        .then(function () {
          sendSucceeded = true;
          self.input.value = "";
          self.fileGal.value = "";
          self.fileCam.value = "";
          self.setError("");
          return self.loadMessages().then(function () {
            return self.markRead();
          });
        })
        .then(function () {
          if (self.opts.afterSend) return self.opts.afterSend();
        })
        .catch(function (e) {
          self.setError(e.message || "Send failed");
        })
        .finally(function () {
          self.root.classList.remove("is-sending");
          self.input.disabled = false;
          self.btnSend.disabled = false;
          self.btnGal.disabled = false;
          self.btnCam.disabled = false;
          self.btnMic.disabled = false;
          if (sendSucceeded) {
            requestAnimationFrame(function () {
              self.focusComposer();
            });
          }
        });
    };

    ChatWindow.prototype._bindForm = function () {
      var self = this;
      this.form.addEventListener("submit", function (e) {
        e.preventDefault();
        var text = (self.input.value || "").trim();
        if (!text) {
          self.setError("Type a message or attach media.");
          return;
        }
        self.setError("");
        var fd = new FormData();
        fd.append("message", text);
        self.postFormData(fd);
      });
    };

    ChatWindow.prototype._bindMention = function () {
      var self = this;
      var mentionState = { start: -1, highlight: 0, filtered: [] };
      function hide() {
        self.mentionList.hidden = true;
        self.mentionList.innerHTML = "";
        mentionState.start = -1;
        mentionState.filtered = [];
      }
      function filterTeam(q) {
        var qq = (q || "").toLowerCase();
        var out = [];
        for (var i = 0; i < self.teamMentionList.length; i++) {
          var t = self.teamMentionList[i];
          var n = (t.name || "").toLowerCase();
          if (!qq || n.indexOf(qq) === 0) out.push(t);
          if (out.length >= 8) break;
        }
        return out;
      }
      function render(items) {
        self.mentionList.innerHTML = "";
        items.forEach(function (t, idx) {
          var li = document.createElement("li");
          li.setAttribute("role", "option");
          li.className = "project-chat-mention-suggestion";
          if (idx === mentionState.highlight) li.classList.add("is-active");
          li.textContent = t.name;
          li.addEventListener("mousedown", function (e) {
            e.preventDefault();
            insert(t.name);
          });
          self.mentionList.appendChild(li);
        });
        self.mentionList.hidden = items.length === 0;
      }
      function insert(name) {
        if (mentionState.start < 0) return;
        var v = self.input.value;
        var cur = self.input.selectionStart;
        var end = typeof cur === "number" ? cur : v.length;
        var before = v.slice(0, mentionState.start);
        var after = v.slice(end);
        var ins = "@" + name + " ";
        self.input.value = before + ins + after;
        self.input.setSelectionRange(before.length + ins.length, before.length + ins.length);
        hide();
        self.input.focus();
      }
      function updateMentionUI() {
        var v = self.input.value;
        var cur = self.input.selectionStart;
        if (typeof cur !== "number") {
          hide();
          return;
        }
        var before = v.slice(0, cur);
        var at = before.lastIndexOf("@");
        if (at < 0) {
          hide();
          return;
        }
        var prevCh = at > 0 ? before.charAt(at - 1) : " ";
        if (prevCh && !/\s/.test(prevCh)) {
          hide();
          return;
        }
        var query = before.slice(at + 1, cur);
        if (query.indexOf("\n") >= 0 || query.indexOf("@") >= 0) {
          hide();
          return;
        }
        var filtered = filterTeam(query);
        if (!filtered.length) {
          hide();
          return;
        }
        mentionState.start = at;
        mentionState.filtered = filtered;
        mentionState.highlight = 0;
        render(filtered);
      }
      this.input.addEventListener("input", updateMentionUI);
      this.input.addEventListener("keyup", updateMentionUI);
      this.input.addEventListener("blur", function () {
        setTimeout(hide, 160);
      });
      this.input.addEventListener("keydown", function (e) {
        if (self.mentionList.hidden || !mentionState.filtered.length) return;
        var n = mentionState.filtered.length;
        if (e.key === "ArrowDown") {
          e.preventDefault();
          mentionState.highlight = (mentionState.highlight + 1) % n;
          render(mentionState.filtered);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          mentionState.highlight = (mentionState.highlight - 1 + n) % n;
          render(mentionState.filtered);
        } else if (e.key === "Enter") {
          e.preventDefault();
          insert(mentionState.filtered[mentionState.highlight].name);
        } else if (e.key === "Escape") {
          e.preventDefault();
          hide();
        }
      });
    };

    ChatWindow.prototype._bindMedia = function () {
      var self = this;
      this.btnGal.addEventListener("click", function () {
        self.fileGal.click();
      });
      this.fileGal.addEventListener("change", function () {
        if (!self.fileGal.files || !self.fileGal.files.length) return;
        var fd = new FormData();
        var t = (self.input.value || "").trim();
        if (t) fd.append("message", t);
        fd.append("image", self.fileGal.files[0]);
        self.postFormData(fd);
      });
      this.btnCam.addEventListener("click", function () {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          self.fileCam.click();
          return;
        }
        navigator.mediaDevices
          .getUserMedia({ video: { facingMode: "environment" }, audio: false })
          .then(function (stream) {
            var root = document.createElement("div");
            root.className = "project-chat-camera-modal";
            root.setAttribute("role", "dialog");
            root.setAttribute("aria-modal", "true");
            var inner = document.createElement("div");
            inner.className = "project-chat-camera-modal-inner";
            var video = document.createElement("video");
            video.autoplay = true;
            video.playsInline = true;
            video.muted = true;
            video.srcObject = stream;
            var actions = document.createElement("div");
            actions.className = "project-chat-camera-modal-actions";
            var cap = document.createElement("button");
            cap.type = "button";
            cap.className = "btn btn--primary";
            cap.textContent = "Capture";
            var cancel = document.createElement("button");
            cancel.type = "button";
            cancel.className = "btn btn--ghost";
            cancel.textContent = "Cancel";
            actions.appendChild(cancel);
            actions.appendChild(cap);
            inner.appendChild(video);
            inner.appendChild(actions);
            root.appendChild(inner);
            document.body.appendChild(root);
            function cleanup() {
              stream.getTracks().forEach(function (t) {
                t.stop();
              });
              if (root.parentNode) root.parentNode.removeChild(root);
            }
            cancel.addEventListener("click", cleanup);
            cap.addEventListener("click", function () {
              try {
                var w = video.videoWidth;
                var h = video.videoHeight;
                if (!w || !h) {
                  cleanup();
                  return;
                }
                var canvas = document.createElement("canvas");
                canvas.width = w;
                canvas.height = h;
                canvas.getContext("2d").drawImage(video, 0, 0);
                canvas.toBlob(function (blob) {
                  cleanup();
                  if (!blob) return;
                  var file = new File([blob], "camera.jpg", { type: "image/jpeg" });
                  var fd = new FormData();
                  var tx = (self.input.value || "").trim();
                  if (tx) fd.append("message", tx);
                  fd.append("image", file);
                  self.postFormData(fd);
                }, "image/jpeg", 0.88);
              } catch (e) {
                cleanup();
              }
            });
          })
          .catch(function () {
            self.fileCam.click();
          });
      });
      this.fileCam.addEventListener("change", function () {
        if (!self.fileCam.files || !self.fileCam.files.length) return;
        var fd = new FormData();
        var t = (self.input.value || "").trim();
        if (t) fd.append("message", t);
        fd.append("image", self.fileCam.files[0]);
        self.postFormData(fd);
      });

      var mediaRecorder = null;
      var recordChunks = [];
      var recordStream = null;
      var voiceShouldSend = false;
      var voiceMaxTimer = null;
      this.btnMic.addEventListener("click", function () {
        if (mediaRecorder && mediaRecorder.state === "recording") {
          voiceShouldSend = true;
          try {
            mediaRecorder.stop();
          } catch (e) {}
          return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
          recordStream = stream;
          recordChunks = [];
          try {
            mediaRecorder = new MediaRecorder(stream);
          } catch (e) {
            return;
          }
          mediaRecorder.ondataavailable = function (ev) {
            if (ev.data && ev.data.size) recordChunks.push(ev.data);
          };
          mediaRecorder.onstop = function () {
            var blob = new Blob(recordChunks, { type: mediaRecorder.mimeType || "audio/webm" });
            recordChunks = [];
            if (recordStream) {
              recordStream.getTracks().forEach(function (t) {
                t.stop();
              });
              recordStream = null;
            }
            mediaRecorder = null;
            self.btnMic.classList.remove("is-recording");
            if (voiceMaxTimer) {
              clearTimeout(voiceMaxTimer);
              voiceMaxTimer = null;
            }
            if (voiceShouldSend && blob.size > 0) {
              var ext = extForAudioBlob(blob);
              var file = new File([blob], "voice" + ext, { type: blob.type || "audio/webm" });
              var fd = new FormData();
              var tx = (self.input.value || "").trim();
              if (tx) fd.append("message", tx);
              fd.append("audio", file);
              self.postFormData(fd);
            }
            voiceShouldSend = false;
          };
          mediaRecorder.start(200);
          self.btnMic.classList.add("is-recording");
          voiceMaxTimer = setTimeout(function () {
            if (mediaRecorder && mediaRecorder.state === "recording") {
              voiceShouldSend = true;
              try {
                mediaRecorder.stop();
              } catch (e2) {}
            }
          }, RECORDING_MAX_MS);
        });
      });
    };

    ChatWindow.prototype.boot = function () {
      var self = this;
      this.loadTeam().then(function () {
        return self.loadMessages();
      }).then(function () {
        return self.markRead();
      }).then(function () {
        if (threadsMap[self.projectId]) {
          threadsMap[self.projectId].unread = 0;
          self.updateHeaderUnread(0);
          syncLauncherBadge();
        }
        self.focusComposer();
      });
      fetchThreads();
    };

    ChatWindow.prototype.destroy = function () {
      this.lastMessageSnapshot = null;
      if (dragMove && dragMove.win === this) dragMove = null;
      if (this._topResizeListeners) {
        document.removeEventListener("mousemove", this._topResizeListeners.move);
        document.removeEventListener("mouseup", this._topResizeListeners.up);
        document.body.style.userSelect = "";
        document.body.style.webkitUserSelect = "";
        this.root.classList.remove("is-resizing-top");
        this._topResizeListeners = null;
      }
      if (this.root && this.root.parentNode) {
        this.root.parentNode.removeChild(this.root);
      }
    };

    /* ——— Build chrome ——— */
    var launcher = document.createElement("button");
    launcher.type = "button";
    launcher.className = "global-chat-launcher";
    launcher.setAttribute("aria-label", "Messages");
    launcher.innerHTML = '<span aria-hidden="true">&#128172;</span>';
    var launcherBadge = document.createElement("span");
    launcherBadge.className = "global-chat-launcher-badge";
    launcherBadge.hidden = true;
    launcher.appendChild(launcherBadge);
    shell.appendChild(launcher);

    var listPanel = document.createElement("div");
    listPanel.className = "global-chat-panel";
    listPanel.hidden = true;
    var panelHead = document.createElement("div");
    panelHead.className = "global-chat-panel-head";
    var panelTitle = document.createElement("span");
    panelTitle.textContent = "Chats";
    var soundBtn = document.createElement("button");
    soundBtn.type = "button";
    soundBtn.className = "global-chat-window-close";
    soundBtn.title = "Sound";
    soundBtn.textContent = "\u266b";
    soundBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      setChatSoundPref(!chatSoundPrefEnabled());
      soundBtn.style.opacity = chatSoundPrefEnabled() ? "1" : "0.45";
    });
    soundBtn.style.opacity = chatSoundPrefEnabled() ? "1" : "0.45";
    panelHead.appendChild(panelTitle);
    panelHead.appendChild(soundBtn);
    listPanel.appendChild(panelHead);
    var panelList = document.createElement("div");
    panelList.className = "global-chat-panel-list";
    listPanel.appendChild(panelList);
    shell.appendChild(listPanel);

    launcher.addEventListener("click", function () {
      listPanelHidden = !listPanelHidden;
      listPanel.hidden = listPanelHidden;
      if (!listPanelHidden) {
        fetchThreads();
      }
    });

    fetchThreads().then(function () {
      var saved = loadPersistedOpen()
        .filter(function (pid) {
          return threadsMap[pid];
        })
        .slice(0, MAX_WINDOWS);
      openOrder = saved.slice();
      saved.forEach(function (pid) {
        attachChatWindow(pid);
        windows[pid].boot();
      });
      relayoutWindows();
      persistOpen();
      applyHash();
    });

    window.addEventListener("hashchange", applyHash);

    window.setInterval(fetchThreads, 45000);

    function wireSocket() {
      var s = window.__tmSocket;
      if (!s) return;
      function onChat(payload) {
        if (!payload || payload.project_id == null) return;
        maybeNotifyIncomingChat(payload);
        var pid = payload.project_id;
        if (windows[pid]) {
          windows[pid].loadTeam().then(function () {
            return windows[pid].loadMessages();
          }).then(function () {
            return windows[pid].markRead();
          });
        }
        fetchThreads();
      }
      s.on("connect", bindAllSocketRooms);
      s.on("chat_updated", onChat);
      if (s.connected) bindAllSocketRooms();
    }

    if (window.__tmSocket) {
      wireSocket();
    } else {
      var tries = 0;
      var iv = setInterval(function () {
        tries++;
        if (window.__tmSocket) {
          clearInterval(iv);
          wireSocket();
        } else if (tries > 50) clearInterval(iv);
      }, 200);
    }
  });
})();
