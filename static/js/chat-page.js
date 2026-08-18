/**
 * Full-page chat workspace (/chat) — WhatsApp Web style project threads.
 * Reuses existing REST + Socket.IO; does not replace global-chat.js.
 */
(function () {
  "use strict";

  var GROUP_MS = 5 * 60 * 1000;
  var RECORDING_MAX_MS = 120000;
  var POLL_MS = 45000;
  var CHAT_QUICK_REACTIONS = ["👍", "❤️", "😂", "😮"];

  var ChatPageState = {
    root: null,
    threadsUrl: "",
    myDirectoryUserId: null,
    threadsMap: {},
    threadsList: [],
    directThreads: [],
    groupThreads: [],
    departmentThreads: [],
    projectThreads: [],
    membersByThread: {},
    selectedProjectId: null,
    selectedThreadKey: null,
    teamByProject: {},
    messagesByProject: {},
    pageStateByProject: {},
    pendingByProject: {},
    lastSnapshotByProject: {},
    threadSearchQuery: "",
    globalSearchQuery: "",
    messageSearchQuery: "",
    serverSearchResults: [],
    serverSearchMode: false,
    pinnedByProject: {},
    newMessagesPending: false,
    replyTo: null,
    typingByProject: {},
    typingStopTimer: null,
    typingActive: false,
    pollTimer: null,
    mediaRecorder: null,
    recordChunks: [],
    recordStream: null,
    voiceShouldSend: false,
    voiceMaxTimer: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function fillAvatarEl(el, opts) {
    if (window.tmChat && window.tmChat.render && window.tmChat.render.fillAvatarEl) {
      window.tmChat.render.fillAvatarEl(el, opts);
      return;
    }
    if (!el) return;
    opts = opts || {};
    el.textContent =
      opts.avatar_initial || (opts.name ? String(opts.name).charAt(0).toUpperCase() : "?");
  }

  function threadStorageKey(t) {
    if (!t) return "";
    if (t.id) return String(t.id);
    if (t.thread_type === "direct") return "direct:" + t.thread_id;
    if (t.thread_type === "group") return "group:" + t.thread_id;
    if (t.thread_type === "department") return "department:" + t.thread_id;
    return "project:" + (t.project_id != null ? t.project_id : t.thread_id);
  }

  function isDirectThread(t) {
    return !!(t && t.thread_type === "direct");
  }

  function isGroupThread(t) {
    return !!(t && t.thread_type === "group");
  }

  function isDepartmentThread(t) {
    return !!(t && t.thread_type === "department");
  }

  function isProjectThread(t) {
    return !!(t && (!t.thread_type || t.thread_type === "project"));
  }

  function activeThread() {
    var key = ChatPageState.selectedThreadKey;
    return key ? ChatPageState.threadsMap[key] : null;
  }

  function activeStorageKey() {
    return ChatPageState.selectedThreadKey;
  }

  function activeProjectId() {
    var t = activeThread();
    if (t && isProjectThread(t)) return t.project_id;
    return ChatPageState.selectedProjectId;
  }

  function storageKeyForProjectId(projectId) {
    var key = "project:" + projectId;
    if (ChatPageState.threadsMap[key]) return key;
    if (ChatPageState.threadsMap[projectId]) return projectId;
    return key;
  }

  function findKeyForThreadId(threadId) {
    var key = "direct:" + threadId;
    if (ChatPageState.threadsMap[key]) return key;
    for (var i = 0; i < ChatPageState.threadsList.length; i++) {
      var t = ChatPageState.threadsList[i];
      if (t.thread_id === threadId) return threadStorageKey(t);
    }
    return key;
  }

  function findKeyForSocketPayload(payload) {
    if (!payload) return null;
    if (payload.thread_id != null) return findKeyForThreadId(payload.thread_id);
    if (payload.project_id != null) return storageKeyForProjectId(payload.project_id);
    return null;
  }

  function teamForKey(storageKey) {
    var thread = ChatPageState.threadsMap[storageKey];
    if (!thread) return [];
    if (isProjectThread(thread) && thread.project_id != null) {
      return ChatPageState.teamByProject[thread.project_id] || [];
    }
    if (isDirectThread(thread)) return [];
    return ChatPageState.membersByThread[storageKey] || [];
  }

  function loadThreadMembers(storageKey) {
    var thread = ChatPageState.threadsMap[storageKey];
    var api = fetchChatApi();
    if (!thread || !api || thread.thread_id == null || isProjectThread(thread)) {
      return Promise.resolve([]);
    }
    return api.fetchThreadMembers(thread.thread_id).then(function (data) {
      var members = (data && data.members) || [];
      ChatPageState.membersByThread[storageKey] = members.map(function (m) {
        return {
          id: m.user_id,
          account_id: m.account_id,
          name: m.name,
          job_title: m.job_title,
        };
      });
      return ChatPageState.membersByThread[storageKey];
    });
  }

  function deleteMessageUrl(storageKey, messageId) {
    var thread = ChatPageState.threadsMap[storageKey];
    if (thread && thread.thread_id != null) {
      return "/chat/threads/" + thread.thread_id + "/messages/" + messageId;
    }
    var pid = thread && thread.project_id != null ? thread.project_id : storageKey;
    return "/projects/" + pid + "/chat/messages/" + messageId;
  }

  function fetchMessagesForKey(storageKey, params) {
    var thread = ChatPageState.threadsMap[storageKey];
    var api = fetchChatApi();
    if (!thread) return Promise.reject(new Error("No thread"));
    if (api && thread.thread_id != null) {
      return api.fetchThreadMessages(thread.thread_id, params);
    }
    if (api && thread.project_id != null) {
      return api.fetchMessages(thread.project_id, params);
    }
    var url = thread.messages_url;
    if (!url) return Promise.reject(new Error("No messages URL"));
    params = params || {};
    var qs = [];
    if (params.limit != null) qs.push("limit=" + encodeURIComponent(params.limit));
    if (params.before_id != null) qs.push("before_id=" + encodeURIComponent(params.before_id));
    if (params.after_id != null) qs.push("after_id=" + encodeURIComponent(params.after_id));
    if (params.direction) qs.push("direction=" + encodeURIComponent(params.direction));
    if (qs.length) url += (url.indexOf("?") >= 0 ? "&" : "?") + qs.join("&");
    return fetch(url, { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) throw new Error("Could not load messages");
      return res.json();
    });
  }

  function fetchMessagesAroundForKey(storageKey, messageId, limit) {
    var thread = ChatPageState.threadsMap[storageKey];
    var api = fetchChatApi();
    if (!thread) return Promise.reject(new Error("No thread"));
    limit = limit || 50;
    if (isProjectThread(thread) && thread.project_id != null && api) {
      return api.fetchMessagesAround(thread.project_id, messageId, limit);
    }
    if (!api || thread.thread_id == null) {
      return Promise.reject(new Error("Chat API not loaded"));
    }
    var half = Math.max(Math.floor(limit / 2), 1);
    return Promise.all([
      api.fetchThreadMessages(thread.thread_id, {
        before_id: messageId + 1,
        limit: half,
        direction: "older",
      }),
      api.fetchThreadMessages(thread.thread_id, {
        after_id: messageId - 1,
        limit: limit - half,
        direction: "newer",
      }),
    ]).then(function (parts) {
      var map = {};
      (parts[0].messages || []).concat(parts[1].messages || []).forEach(function (m) {
        if (m && m.id != null) map[m.id] = m;
      });
      var messages = Object.keys(map)
        .map(function (k) {
          return map[k];
        })
        .sort(function (a, b) {
          return (a.id || 0) - (b.id || 0);
        });
      return {
        messages: messages,
        has_older: !!(parts[0] && parts[0].has_older),
        has_newer: !!(parts[1] && parts[1].has_newer),
        oldest_id: messages.length ? messages[0].id : null,
        newest_id: messages.length ? messages[messages.length - 1].id : null,
        last_read_message_id: parts[1].last_read_message_id != null ? parts[1].last_read_message_id : parts[0].last_read_message_id,
        first_unread_message_id:
          parts[1].first_unread_message_id != null ? parts[1].first_unread_message_id : parts[0].first_unread_message_id,
      };
    });
  }

  function updateProjectOnlyTools(thread) {
    var project = isProjectThread(thread);
    var pinned = $("chat-page-pinned-btn");
    var attach = $("chat-page-attachments-btn");
    var teamBtn = $("chat-page-team-btn");
    var openProj = $("chat-page-open-project");
    if (pinned) pinned.hidden = !project;
    if (attach) attach.hidden = !project;
    if (teamBtn) {
      teamBtn.hidden = !project && !isGroupThread(thread) && !isDepartmentThread(thread);
      teamBtn.textContent = project ? "Team" : "Members";
    }
    if (openProj) openProj.hidden = !project;
    if (window.ChatConferenceUI && window.ChatConferenceUI.updateForThread) {
      window.ChatConferenceUI.updateForThread(thread);
    }
  }

  function postChatReaction(storageKey, messageId, emoji) {
    var api = fetchChatApi();
    if (!api) return Promise.reject(new Error("Chat API not loaded"));
    var thread = ChatPageState.threadsMap[storageKey];
    if (thread && thread.thread_id != null) {
      return api.postThreadReaction(thread.thread_id, messageId, emoji);
    }
    var pid = thread && thread.project_id != null ? thread.project_id : storageKey;
    return api.postReaction(pid, messageId, emoji);
  }

  function formatTime(iso) {
    if (!iso) return "";
    try {
      if (window.tmDateTime && window.tmDateTime.formatDateTimeCairo) {
        return window.tmDateTime.formatDateTimeCairo(iso);
      }
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
    } catch (e) {
      return String(iso);
    }
  }

  function formatThreadTime(iso) {
    if (!iso) return "";
    try {
      var ms =
        window.tmDateTime && window.tmDateTime.instantMs
          ? window.tmDateTime.instantMs(iso)
          : new Date(iso).getTime();
      if (isNaN(ms)) return "";
      var now = Date.now();
      var diff = now - ms;
      if (diff < 86400000) {
        var d = new Date(ms);
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      }
      if (diff < 604800000) {
        return new Date(ms).toLocaleDateString(undefined, { weekday: "short" });
      }
      return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch (e) {
      return "";
    }
  }

  function parseTime(iso) {
    try {
      if (window.tmDateTime && window.tmDateTime.instantMs) {
        return window.tmDateTime.instantMs(iso);
      }
      var d = new Date(iso);
      return isNaN(d.getTime()) ? 0 : d.getTime();
    } catch (e) {
      return 0;
    }
  }

  function dayKey(iso) {
    var ms = parseTime(iso);
    if (!ms) return "";
    var d = new Date(ms);
    return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
  }

  function formatDateSeparator(iso) {
    var ms = parseTime(iso);
    if (!ms) return "";
    var d = new Date(ms);
    var today = new Date();
    var yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (dayKey(iso) === dayKey(today.toISOString())) return "Today";
    if (dayKey(iso) === dayKey(yesterday.toISOString())) return "Yesterday";
    return d.toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined,
    });
  }

  function extForAudioBlob(blob) {
    var t = (blob.type || "").toLowerCase();
    if (t.indexOf("ogg") !== -1 || t.indexOf("opus") !== -1) return ".ogg";
    if (t.indexOf("mp4") !== -1 || t.indexOf("m4a") !== -1 || t.indexOf("aac") !== -1) return ".m4a";
    if (t.indexOf("mpeg") !== -1 || t.indexOf("mp3") !== -1) return ".mp3";
    if (t.indexOf("wav") !== -1) return ".wav";
    return ".webm";
  }

  function threadSortKey(t) {
    var lastSort =
      typeof window.tmDateTime !== "undefined" && window.tmDateTime.instantMs
        ? window.tmDateTime.instantMs(t.last_at || "")
        : parseTime(t.last_at);
    return {
      unread: t.unread || 0,
      lastSort: isNaN(lastSort) ? 0 : lastSort,
      name: (t.name || "").toLowerCase(),
    };
  }

  function sortThreads(list) {
    return list.slice().sort(function (a, b) {
      var ka = threadSortKey(a);
      var kb = threadSortKey(b);
      if (ka.unread !== kb.unread) return kb.unread - ka.unread;
      if (ka.lastSort !== kb.lastSort) return kb.lastSort - ka.lastSort;
      return ka.name.localeCompare(kb.name);
    });
  }

  function syncComposerInputHeight(input) {
    if (!input) return;
    input.style.height = "auto";
    var maxPx = 160;
    var minPx = 72;
    input.style.height = Math.min(Math.max(input.scrollHeight, minPx), maxPx) + "px";
  }

  function resetComposerInput(input) {
    if (!input) return;
    input.value = "";
    input.style.height = "";
  }

  function setComposerError(msg) {
    var el = $("chat-page-composer-error");
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  function jumpToReplyTarget(messageId) {
    var key = activeStorageKey();
    if (key == null || messageId == null) return;
    if (scrollToMessage(messageId)) return;
    jumpToMessage(key, messageId).catch(function () {
      setComposerError("Original message is not loaded.");
    });
  }

  function startReply(m) {
    if (!m || m.is_deleted) return;
    var preview = (m.message || "").trim();
    if (!preview) {
      if (m.image_url) preview = "Photo";
      else if (m.audio_url) preview = "Voice message";
    }
    ChatPageState.replyTo = {
      id: m.id,
      username: m.username || "Unknown",
      message: preview.slice(0, 120),
    };
    var bar = $("chat-page-reply-preview");
    var label = $("chat-page-reply-preview-label");
    var text = $("chat-page-reply-preview-text");
    if (label) label.textContent = "Replying to " + (ChatPageState.replyTo.username || "");
    if (text) text.textContent = ChatPageState.replyTo.message || "";
    if (bar) bar.hidden = false;
    var input = $("chat-page-composer-input");
    if (input) input.focus();
  }

  function cancelReply() {
    ChatPageState.replyTo = null;
    var bar = $("chat-page-reply-preview");
    if (bar) bar.hidden = true;
  }

  function formatTypingLabel(names) {
    if (!names || !names.length) return "";
    if (names.length === 1) return names[0] + " is typing…";
    if (names.length === 2) return names[0] + " and " + names[1] + " are typing…";
    return "Several people are typing…";
  }

  function updateTypingIndicator(projectId) {
    var el = $("chat-page-typing-indicator");
    if (!el) return;
    if (ChatPageState.selectedProjectId !== projectId) {
      el.hidden = true;
      return;
    }
    var map = ChatPageState.typingByProject[projectId] || {};
    var names = Object.keys(map).filter(function (k) {
      return map[k];
    });
    if (!names.length) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.textContent = formatTypingLabel(names);
    el.hidden = false;
  }

  function stopTypingEmit(projectId) {
    if (!ChatPageState.typingActive) return;
    ChatPageState.typingActive = false;
    var s = window.__tmSocket;
    if (s && s.connected && projectId != null) {
      s.emit("chat_typing_stop", { project_id: projectId });
    }
    if (ChatPageState.typingStopTimer) {
      clearTimeout(ChatPageState.typingStopTimer);
      ChatPageState.typingStopTimer = null;
    }
  }

  function wireTypingInput(input) {
    if (!input) return;
    var debounceTimer = null;
    input.addEventListener("input", function () {
      var pid = activeProjectId();
      if (pid == null) return;
      var s = window.__tmSocket;
      if (!s || !s.connected) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        if (!ChatPageState.typingActive) {
          ChatPageState.typingActive = true;
          s.emit("chat_typing_start", { project_id: pid });
        }
        if (ChatPageState.typingStopTimer) clearTimeout(ChatPageState.typingStopTimer);
        ChatPageState.typingStopTimer = setTimeout(function () {
          stopTypingEmit(pid);
        }, 3000);
      }, 350);
    });
    input.addEventListener("blur", function () {
      var pid = activeProjectId();
      if (pid != null) stopTypingEmit(pid);
    });
  }

  function handleChatTyping(payload) {
    if (!payload || payload.project_id == null) return;
    var pid = payload.project_id;
    if (!ChatPageState.typingByProject[pid]) ChatPageState.typingByProject[pid] = {};
    var name = payload.display_name || "Someone";
    if (payload.is_typing) {
      ChatPageState.typingByProject[pid][name] = true;
    } else {
      delete ChatPageState.typingByProject[pid][name];
    }
    updateTypingIndicator(pid);
  }

  function deliveryStatusClass(m) {
    if (m.delivery_status === "failed") return "failed";
    if (m.delivery_status === "sending") return "sending";
    if (m.delivery_state === "read") return "read";
    if (m.delivery_state === "sent" || m.delivery_status === "sent") return "sent";
    return "";
  }

  function deliveryStatusText(m) {
    if (window.tmChat && window.tmChat.render && window.tmChat.render.deliveryLabel) {
      return window.tmChat.render.deliveryLabel(m);
    }
    if (m.delivery_status === "sending") return "Sending…";
    if (m.delivery_status === "failed") return "Failed";
    if (m.delivery_state === "read") return "Read";
    if (m.delivery_state === "sent" || m.delivery_status === "sent") return "Sent";
    return "";
  }

  function fetchChatApi() {
    return window.tmChat && window.tmChat.api ? window.tmChat.api : null;
  }

  function getPageState(projectId) {
    if (!ChatPageState.pageStateByProject[projectId]) {
      ChatPageState.pageStateByProject[projectId] = {
        hasOlder: false,
        hasNewer: false,
        oldestId: null,
        newestId: null,
        loadingOlder: false,
        lastReadMessageId: null,
        firstUnreadMessageId: null,
        showUnreadDivider: false,
      };
    }
    return ChatPageState.pageStateByProject[projectId];
  }

  function isNearBottom(listEl, threshold) {
    if (!listEl) return true;
    threshold = threshold == null ? 80 : threshold;
    return listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight < threshold;
  }

  function mergeMessageLists(existing, incoming, mode) {
    var map = {};
    (existing || []).forEach(function (m) {
      if (m && m.id != null) map[m.id] = m;
    });
    (incoming || []).forEach(function (m) {
      if (m && m.id != null) map[m.id] = m;
    });
    var merged = Object.keys(map)
      .map(function (k) {
        return map[k];
      })
      .sort(function (a, b) {
        return (a.id || 0) - (b.id || 0);
      });
    if (mode === "replace") return incoming || [];
    return merged;
  }

  function applyMessagesResponse(projectId, data, mode) {
    var items = (data && data.messages) || [];
    var ps = getPageState(projectId);
    ps.hasOlder = !!data.has_older;
    ps.hasNewer = !!data.has_newer;
    ps.oldestId = data.oldest_id != null ? data.oldest_id : ps.oldestId;
    ps.newestId = data.newest_id != null ? data.newest_id : ps.newestId;
    if (data.last_read_message_id != null) ps.lastReadMessageId = data.last_read_message_id;
    if (data.first_unread_message_id != null) {
      ps.firstUnreadMessageId = data.first_unread_message_id;
      ps.showUnreadDivider = !!data.first_unread_message_id;
    }
    if (mode === "prepend") {
      ChatPageState.messagesByProject[projectId] = mergeMessageLists(
        items,
        ChatPageState.messagesByProject[projectId] || [],
        "append"
      );
    } else if (mode === "append") {
      ChatPageState.messagesByProject[projectId] = mergeMessageLists(
        ChatPageState.messagesByProject[projectId] || [],
        items,
        "append"
      );
    } else {
      ChatPageState.messagesByProject[projectId] = items.slice();
      if (items.length) {
        ps.oldestId = items[0].id;
        ps.newestId = items[items.length - 1].id;
      }
    }
    return items;
  }

  function showOlderLoader(show) {
    var el = $("chat-page-older-loader");
    if (el) el.hidden = !show;
  }

  function showNewMessagesJump(show) {
    var el = $("chat-page-new-msgs-btn");
    if (el) el.hidden = !show;
  }

  function updateUnreadHeaderButton(storageKey) {
    var btn = $("chat-page-jump-unread-btn");
    if (!btn) return;
    var ps = getPageState(storageKey);
    var show = !!ps.firstUnreadMessageId && ChatPageState.selectedThreadKey === storageKey;
    btn.hidden = !show;
  }

  function scrollToMessage(messageId) {
    var listEl = $("chat-page-messages");
    if (!listEl || messageId == null) return;
    var row = listEl.querySelector('[data-message-id="' + messageId + '"]');
    if (row) {
      row.scrollIntoView({ block: "center", behavior: "smooth" });
      row.classList.add("chat-page-msg-highlight");
      setTimeout(function () {
        row.classList.remove("chat-page-msg-highlight");
      }, 2000);
      return true;
    }
    return false;
  }

  function jumpToFirstUnread() {
    var key = activeStorageKey();
    if (key == null) return;
    var ps = getPageState(key);
    if (!ps.firstUnreadMessageId) return;
    if (scrollToMessage(ps.firstUnreadMessageId)) return;
    fetchMessagesAroundForKey(key, ps.firstUnreadMessageId, 50).then(function (data) {
      applyMessagesResponse(key, data, "replace");
      renderMessages(key, ChatPageState.messagesByProject[key], {
        scroll: "message",
        messageId: ps.firstUnreadMessageId,
      });
    });
  }

  function jumpToMessage(storageKey, messageId) {
    if (scrollToMessage(messageId)) return Promise.resolve();
    return fetchMessagesAroundForKey(storageKey, messageId, 50).then(function (data) {
      applyMessagesResponse(storageKey, data, "replace");
      if (ChatPageState.selectedThreadKey === storageKey) {
        renderMessages(storageKey, ChatPageState.messagesByProject[storageKey], {
          scroll: "message",
          messageId: messageId,
        });
      }
    });
  }

  function bindAllSocketRooms() {
    var s = window.__tmSocket;
    if (!s || !s.connected) return;
    var projectIds = [];
    var threadIds = [];
    ChatPageState.threadsList.forEach(function (t) {
      if (t.thread_id != null) threadIds.push(t.thread_id);
      if (isProjectThread(t) && t.project_id != null) projectIds.push(t.project_id);
    });
    s.emit("sync_chat_rooms", { project_ids: projectIds });
    s.emit("sync_chat_threads", { thread_ids: threadIds });
  }

  function loadThreads() {
    return fetch(ChatPageState.threadsUrl, { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("Could not load threads");
        return res.json();
      })
      .then(function (data) {
        var threads = (data && data.threads) || [];
        ChatPageState.threadsMap = {};
        threads.forEach(function (t) {
          var key = threadStorageKey(t);
          ChatPageState.threadsMap[key] = t;
          if (isProjectThread(t) && t.project_id != null) {
            ChatPageState.threadsMap[t.project_id] = t;
          }
        });
        ChatPageState.directThreads = (data && data.direct) || threads.filter(isDirectThread);
        ChatPageState.groupThreads = (data && data.group) || threads.filter(isGroupThread);
        ChatPageState.departmentThreads =
          (data && data.department) || threads.filter(isDepartmentThread);
        ChatPageState.projectThreads = (data && data.project) || threads.filter(isProjectThread);
        ChatPageState.threadsList = sortThreads(threads);
        renderThreadList();
        bindAllSocketRooms();
        return ChatPageState.threadsList;
      });
  }

  function filteredThreads() {
    var q = (ChatPageState.threadSearchQuery || "").trim().toLowerCase();
    if (!q) return ChatPageState.threadsList;
    return ChatPageState.threadsList.filter(function (t) {
      var name = (t.title || t.name || "").toLowerCase();
      var preview = (t.last_preview || t.last_message || "").toLowerCase();
      var type = (t.project_type_label || t.subtitle || "").toLowerCase();
      return name.indexOf(q) >= 0 || preview.indexOf(q) >= 0 || type.indexOf(q) >= 0;
    });
  }

  function renderThreadRow(t, listEl) {
    var key = threadStorageKey(t);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-page-thread";
    btn.setAttribute("role", "option");
    if (t.project_id != null) btn.dataset.projectId = String(t.project_id);
    btn.dataset.threadKey = key;
    if (ChatPageState.selectedThreadKey === key) btn.classList.add("is-active");

    var av = document.createElement("div");
    av.className = "chat-page-thread-avatar";
    fillAvatarEl(av, {
      avatar_url: t.avatar_url,
      avatar_initial: t.avatar_initial,
      name: t.title || t.name,
    });

    var body = document.createElement("div");
    body.className = "chat-page-thread-body";

    var top = document.createElement("div");
    top.className = "chat-page-thread-top";
    var nameEl = document.createElement("span");
    nameEl.className = "chat-page-thread-name";
    nameEl.textContent = t.title || t.name || (isDirectThread(t) ? "Direct message" : "Project");
    var timeWrap = document.createElement("span");
    timeWrap.style.display = "inline-flex";
    timeWrap.style.alignItems = "center";
    timeWrap.style.gap = "0.35rem";
    var timeEl = document.createElement("span");
    timeEl.className = "chat-page-thread-time";
    timeEl.textContent = formatThreadTime(t.last_at || t.last_message_at);
    timeWrap.appendChild(timeEl);
    var unreadN = t.unread_count != null ? t.unread_count : t.unread;
    if (unreadN > 0) {
      var unread = document.createElement("span");
      unread.className = "chat-page-thread-unread";
      unread.textContent = unreadN > 99 ? "99+" : String(unreadN);
      timeWrap.appendChild(unread);
    }
    if (t.live_conference_id) {
      var liveIco = document.createElement("span");
      liveIco.className = "chat-page-thread-live-call";
      liveIco.title = "Live call in progress";
      liveIco.setAttribute("aria-hidden", "true");
      liveIco.textContent = "\u{1F4DE}";
      timeWrap.insertBefore(liveIco, timeWrap.firstChild);
    }
    top.appendChild(nameEl);
    if (isProjectThread(t) && t.project_id != null) {
      var teamBtn = document.createElement("button");
      teamBtn.type = "button";
      teamBtn.className = "chat-page-thread-team-btn";
      teamBtn.setAttribute("aria-label", "View project team for " + (t.name || "project"));
      teamBtn.title = "View team";
      teamBtn.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>';
      teamBtn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openTeamModal(t.project_id);
      });
      top.appendChild(teamBtn);
    }
    top.appendChild(timeWrap);

    var bottom = document.createElement("div");
    bottom.className = "chat-page-thread-bottom";
    var preview = document.createElement("span");
    preview.className = "chat-page-thread-preview";
    preview.textContent = t.last_preview || t.last_message || "No messages yet";
    bottom.appendChild(preview);
    if (isDirectThread(t) && t.subtitle) {
      var sub = document.createElement("span");
      sub.className = "chat-page-thread-badge";
      sub.textContent = t.subtitle;
      bottom.appendChild(sub);
    } else if (t.subtitle) {
      var subBadge = document.createElement("span");
      subBadge.className = "chat-page-thread-badge";
      subBadge.textContent = t.subtitle;
      bottom.appendChild(subBadge);
    } else if (t.project_type_label) {
      var badge = document.createElement("span");
      badge.className = "chat-page-thread-badge";
      badge.textContent = t.project_type_label;
      bottom.appendChild(badge);
    }

    body.appendChild(top);
    body.appendChild(bottom);
    btn.appendChild(av);
    btn.appendChild(body);
    btn.addEventListener("click", function () {
      selectThreadKey(key);
    });
    listEl.appendChild(btn);
  }

  function renderThreadList() {
    var listEl = $("chat-page-thread-list");
    var emptyEl = $("chat-page-threads-empty");
    if (!listEl) return;
    var threads = filteredThreads();
    function appendSection(label, items) {
      if (!items.length) return;
      var head = document.createElement("h3");
      head.className = "chat-page-thread-section-label";
      head.textContent = label;
      listEl.appendChild(head);
      items.forEach(function (t) {
        renderThreadRow(t, listEl);
      });
    }
    listEl.innerHTML = "";
    if (!ChatPageState.threadsList.length) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = threads.length > 0;
    appendSection("Direct Messages", threads.filter(isDirectThread));
    appendSection("Groups", threads.filter(isGroupThread));
    appendSection("Departments", threads.filter(isDepartmentThread));
    appendSection("Project Chats", threads.filter(isProjectThread));
  }

  function updateConversationHeader(thread) {
    var title = $("chat-page-conv-title");
    var meta = $("chat-page-conv-meta");
    var av = $("chat-page-conv-avatar");
    var link = $("chat-page-open-project");
    var teamBtn = $("chat-page-team-btn");
    if (!thread) return;
    if (title) title.textContent = thread.title || thread.name || "Chat";
    if (av) {
      fillAvatarEl(av, {
        avatar_url: thread.avatar_url,
        avatar_initial: thread.avatar_initial,
        name: thread.title || thread.name,
      });
    }
    if (link) {
      link.hidden = !isProjectThread(thread);
      if (isProjectThread(thread)) link.href = thread.detail_url || "#";
    }
    if (teamBtn) {
      teamBtn.hidden =
        !isProjectThread(thread) && !isGroupThread(thread) && !isDepartmentThread(thread);
      teamBtn.textContent = isProjectThread(thread) ? "Team" : "Members";
    }
    if (meta) {
      if (isDirectThread(thread)) {
        var dparts = [];
        if (thread.job_title) dparts.push(thread.job_title);
        if (thread.email) dparts.push(thread.email);
        if (!dparts.length && thread.subtitle) dparts.push(thread.subtitle);
        meta.textContent = dparts.join(" · ") || "Direct message";
        meta.classList.remove("chat-page-conv-meta--clickable");
        meta.dataset.projectId = "";
        meta.dataset.threadKey = "";
      } else if (isGroupThread(thread) || isDepartmentThread(thread)) {
        meta.textContent = thread.subtitle || "Members";
        meta.classList.add("chat-page-conv-meta--clickable");
        meta.dataset.projectId = "";
        meta.dataset.threadKey = threadStorageKey(thread);
      } else {
        var parts = [];
        if (thread.project_type_label) parts.push(thread.project_type_label);
        if (thread.director) parts.push(thread.director);
        if (thread.production_house) parts.push(thread.production_house);
        if (thread.team_count) {
          parts.push(thread.team_count + " member" + (thread.team_count === 1 ? "" : "s"));
        }
        meta.textContent = parts.join(" · ");
        meta.classList.toggle("chat-page-conv-meta--clickable", !!thread.team_count);
        meta.dataset.projectId = thread.team_count ? String(thread.project_id) : "";
        meta.dataset.threadKey = "";
      }
    }
  }

  function showConversation(open) {
    var ph = $("chat-page-placeholder");
    var conv = $("chat-page-conversation");
    var main = $("chat-page-main");
    if (ph) ph.hidden = !!open;
    if (conv) conv.hidden = !open;
    if (main) main.classList.toggle("chat-page-main--open", !!open);
    if (ChatPageState.root) {
      ChatPageState.root.classList.toggle("chat-page-root--conversation-open", !!open);
    }
  }

  function selectThreadKey(key) {
    var thread = ChatPageState.threadsMap[key];
    if (!thread) return;
    var prevKey = ChatPageState.selectedThreadKey;
    var prevPid = activeProjectId();
    if (prevPid != null && prevKey !== key) stopTypingEmit(prevPid);
    ChatPageState.selectedThreadKey = key;
    ChatPageState.selectedProjectId = isProjectThread(thread) ? thread.project_id : null;
    ChatPageState.messageSearchQuery = "";
    ChatPageState.serverSearchMode = false;
    ChatPageState.serverSearchResults = [];
    cancelReply();
    var msgSearch = $("chat-page-msg-search");
    if (msgSearch) msgSearch.value = "";
    delete ChatPageState.pageStateByProject[key];
    delete ChatPageState.lastSnapshotByProject[key];
    renderThreadList();
    updateConversationHeader(thread);
    updateProjectOnlyTools(thread);
    showConversation(true);
    setComposerError("");
    var prepPromise = isProjectThread(thread)
      ? loadTeam(thread.project_id)
      : loadThreadMembers(key);
    prepPromise
      .then(function () {
        return loadMessages(key, { reset: true });
      })
      .then(function () {
        return markCurrentThreadRead();
      });
    if (history.replaceState) {
      var url = new URL(window.location.href);
      url.searchParams.delete("project_id");
      url.searchParams.delete("thread_id");
      url.searchParams.delete("direct_thread_id");
      if (thread.thread_id != null && !isProjectThread(thread)) {
        url.searchParams.set("thread_id", String(thread.thread_id));
      } else if (thread.project_id != null) {
        url.searchParams.set("project_id", String(thread.project_id));
      }
      url.hash = "";
      history.replaceState(null, "", url.pathname + url.search);
    }
  }

  function selectThread(projectId) {
    selectThreadKey(storageKeyForProjectId(projectId));
  }

  function loadTeam(projectId) {
    return fetch("/projects/" + projectId + "/chat/team", { credentials: "same-origin" })
      .then(function (res) {
        return res.ok ? res.json() : { team: [] };
      })
      .then(function (data) {
        ChatPageState.teamByProject[projectId] = ((data && data.team) || []).map(function (m) {
          return {
            id: m.id,
            account_id: m.account_id,
            name: m.name,
            job_title: m.job_title,
          };
        });
      })
      .catch(function () {
        ChatPageState.teamByProject[projectId] = [];
      });
  }

  function renderTeamModal(projectId) {
    var listEl = $("chat-page-team-list");
    var emptyEl = $("chat-page-team-empty");
    var metaEl = $("chat-page-team-dialog-meta");
    var titleEl = $("chat-page-team-dialog-title");
    var thread = ChatPageState.threadsMap[projectId];
    var team = ChatPageState.teamByProject[projectId] || [];
    if (titleEl) {
      titleEl.textContent = thread && thread.name ? thread.name + " — Team" : "Project team";
    }
    if (metaEl) {
      metaEl.textContent =
        team.length + " member" + (team.length === 1 ? "" : "s") + " on this project.";
    }
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!team.length) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    team.forEach(function (member) {
      var li = document.createElement("li");
      li.className = "project-team-row";
      var av = document.createElement("div");
      av.className = "chat-page-team-avatar chat-avatar";
      fillAvatarEl(av, {
        avatar_url: member.avatar_url,
        avatar_initial: member.avatar_initial,
        name: member.name,
      });
      li.appendChild(av);
      var text = document.createElement("div");
      text.className = "project-team-member-text";
      var nameEl = document.createElement("strong");
      nameEl.className = "project-team-name";
      nameEl.textContent = member.name || "Member";
      text.appendChild(nameEl);
      var role = (member.job_title || "").trim();
      if (role) {
        var roleEl = document.createElement("span");
        roleEl.className = "project-team-role";
        roleEl.textContent = role;
        text.appendChild(roleEl);
      }
      li.appendChild(text);
      listEl.appendChild(li);
    });
  }

  function closeTeamModal() {
    var dlg = $("chat-page-team-dialog");
    if (!dlg) return;
    try {
      if (typeof dlg.close === "function") dlg.close();
      else dlg.removeAttribute("open");
    } catch (e) {
      dlg.removeAttribute("open");
    }
  }

  function openTeamModal(projectId) {
    var dlg = $("chat-page-team-dialog");
    if (!dlg || projectId == null) return;
    loadTeam(projectId).then(function () {
      renderTeamModal(projectId);
      if (typeof dlg.showModal === "function") dlg.showModal();
      else dlg.setAttribute("open", "");
    });
  }

  function renderMembersModal(storageKey) {
    var listEl = $("chat-page-team-list");
    var emptyEl = $("chat-page-team-empty");
    var metaEl = $("chat-page-team-dialog-meta");
    var titleEl = $("chat-page-team-dialog-title");
    var thread = ChatPageState.threadsMap[storageKey];
    var members = ChatPageState.membersByThread[storageKey] || [];
    if (titleEl) {
      titleEl.textContent = (thread && thread.title ? thread.title : "Chat") + " — Members";
    }
    if (metaEl) {
      metaEl.textContent =
        members.length + " member" + (members.length === 1 ? "" : "s") + " in this chat.";
    }
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!members.length) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    members.forEach(function (member) {
      var li = document.createElement("li");
      li.className = "project-team-row";
      var av = document.createElement("div");
      av.className = "chat-page-team-avatar chat-avatar";
      fillAvatarEl(av, {
        avatar_url: member.avatar_url,
        avatar_initial: member.avatar_initial,
        name: member.name,
      });
      li.appendChild(av);
      var text = document.createElement("div");
      text.className = "project-team-member-text";
      var nameEl = document.createElement("strong");
      nameEl.className = "project-team-name";
      nameEl.textContent = member.name || "Member";
      text.appendChild(nameEl);
      var role = (member.job_title || "").trim();
      if (role) {
        var roleEl = document.createElement("span");
        roleEl.className = "project-team-role muted";
        roleEl.textContent = role;
        text.appendChild(roleEl);
      }
      li.appendChild(text);
      listEl.appendChild(li);
    });
  }

  function openMembersModal(storageKey) {
    var dlg = $("chat-page-team-dialog");
    if (!dlg || !storageKey) return;
    loadThreadMembers(storageKey).then(function () {
      renderMembersModal(storageKey);
      if (typeof dlg.showModal === "function") dlg.showModal();
      else dlg.setAttribute("open", "");
    });
  }

  function markCurrentThreadRead() {
    var thread = activeThread();
    if (!thread || !thread.mark_read_url) return Promise.resolve();
    return fetch(thread.mark_read_url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(function () {
        thread.unread = 0;
        thread.unread_count = 0;
        renderThreadList();
      })
      .catch(function () {});
  }

  function appendMessageTextWithMentions(container, text, team) {
    if (window.tmChat && window.tmChat.render && window.tmChat.render.appendMessageText) {
      window.tmChat.render.appendMessageText(container, text, team);
      return;
    }
    if (!text) return;
    container.textContent = text;
  }

  function fillChatReactionRow(rowEl, summaries, messageId, projectId, reloadFn) {
    if (!rowEl) return;
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
        postChatReaction(projectId, messageId, em)
          .then(function (data) {
            fillChatReactionRow(rowEl, data.reactions, messageId, projectId, reloadFn);
          })
          .catch(function () {});
      });
      rowEl.appendChild(btn);
    });
  }

  function openLightbox(src) {
    var lb = $("chat-page-lightbox");
    var img = $("chat-page-lightbox-img");
    if (!lb || !img) return;
    img.src = src;
    lb.hidden = false;
  }

  function closeLightbox() {
    var lb = $("chat-page-lightbox");
    var img = $("chat-page-lightbox-img");
    if (lb) lb.hidden = true;
    if (img) img.src = "";
  }

  function appendOneMessageRow(listEl, m, prev, team, projectId, reloadFn) {
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
    row.dataset.messageId = String(m.id);
    if (m.temp_id) row.dataset.tempId = m.temp_id;

    if (
      (m.message_type === "conference" || m.conference) &&
      window.tmChat &&
      window.tmChat.render &&
      window.tmChat.render.appendConferenceCard
    ) {
      row.classList.add("project-chat-bubble-row--conference");
      window.tmChat.render.appendConferenceCard(row, m, { reload: reloadFn });
      listEl.appendChild(row);
      return m;
    }

    var av = document.createElement("div");
    av.className = "project-chat-avatar";
    fillAvatarEl(av, {
      avatar_url: m.avatar_url,
      avatar_initial: m.avatar_initial,
      name: m.username,
    });

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
    timeEl.dateTime =
      window.tmDateTime && window.tmDateTime.utcIsoForAttr
        ? window.tmDateTime.utcIsoForAttr(m.created_at)
        : m.created_at || "";
    timeEl.textContent = formatTime(m.created_at);
    meta.appendChild(nameEl);
    meta.appendChild(timeEl);
    if (m.delivery_status || m.delivery_state) {
      var statusEl = document.createElement("span");
      var dClass = deliveryStatusClass(m);
      statusEl.className = "chat-page-delivery-status chat-page-delivery-status--" + dClass;
      statusEl.textContent = deliveryStatusText(m);
      meta.appendChild(statusEl);
    }

    var bubble = document.createElement("div");
    bubble.className = "project-chat-bubble";
    var isDel = !!m.is_deleted;
    if (isDel) {
      bubble.classList.add("project-chat-bubble--deleted");
      var delText = document.createElement("div");
      delText.className = "project-chat-text project-chat-text--deleted";
      delText.textContent = "Message deleted";
      bubble.appendChild(delText);
    } else {
      if (m.reply_to && window.tmChat && window.tmChat.render) {
        window.tmChat.render.appendReplyQuote(bubble, m.reply_to, function (mid) {
          jumpToReplyTarget(mid);
        });
      }
      if (m.message) {
        var text = document.createElement("div");
        text.className = "project-chat-text";
        appendMessageTextWithMentions(text, m.message, team);
        bubble.appendChild(text);
      }
      if (m.entity_links && m.entity_links.length) {
        var linksWrap = document.createElement("div");
        linksWrap.className = "chat-page-msg-links";
        m.entity_links.forEach(function (lk) {
          var badge = document.createElement("span");
          badge.className = "chat-page-msg-link-badge";
          badge.textContent = lk.label || lk.entity_type;
          linksWrap.appendChild(badge);
        });
        bubble.appendChild(linksWrap);
      }
      if (m.is_pinned) {
        var pinBadge = document.createElement("span");
        pinBadge.className = "chat-page-msg-pin-badge";
        pinBadge.textContent = "Pinned";
        bubble.appendChild(pinBadge);
      }
      if (m.image_url) {
        var mw = document.createElement("div");
        mw.className = "project-chat-bubble-media chat-page-bubble-media";
        var img = document.createElement("img");
        img.src = m.image_url;
        img.alt = "Photo";
        img.loading = "lazy";
        img.addEventListener("click", function () {
          openLightbox(m.image_url);
        });
        mw.appendChild(img);
        bubble.appendChild(mw);
      }
      if (m.audio_url) {
        bubble.classList.add("project-chat-bubble--voice");
        var aw = document.createElement("div");
        aw.className = "project-chat-bubble-media project-chat-bubble-media--audio";
        if (window.tmChat && window.tmChat.createVoiceNotePlayer) {
          aw.appendChild(window.tmChat.createVoiceNotePlayer(m.audio_url));
        } else {
          var aud = document.createElement("audio");
          aud.controls = true;
          aud.preload = "metadata";
          aud.src = m.audio_url;
          aud.setAttribute("aria-label", "Voice note");
          aw.appendChild(aud);
        }
        bubble.appendChild(aw);
      }
    }

    var wrap = document.createElement("div");
    wrap.className = "project-chat-bubble-wrap";
    wrap.appendChild(bubble);

    if (!isDel) {
      var reactRow = document.createElement("div");
      reactRow.className = "project-chat-reactions";
      fillChatReactionRow(reactRow, m.reactions || [], m.id, projectId, reloadFn);

      var toolbar = document.createElement("div");
      toolbar.className = "project-chat-msg-toolbar";
      var menuBtn = document.createElement("button");
      menuBtn.type = "button";
      menuBtn.className = "project-chat-msg-menu-btn";
      menuBtn.setAttribute("aria-label", "Message options");
      menuBtn.innerHTML = "&#8942;";
      var pop = document.createElement("div");
      pop.className = "project-chat-msg-popover";
      pop.hidden = true;
      pop.setAttribute("role", "menu");

      if (m.message) {
        var copyAct = document.createElement("button");
        copyAct.type = "button";
        copyAct.className = "project-chat-msg-popover-action";
        copyAct.textContent = "Copy text";
        copyAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(m.message || "").catch(function () {});
          }
        });
        pop.appendChild(copyAct);
      }

      var replyAct = document.createElement("button");
      replyAct.type = "button";
      replyAct.className = "project-chat-msg-popover-action";
      replyAct.textContent = "Reply";
      replyAct.addEventListener("click", function (e) {
        e.stopPropagation();
        pop.hidden = true;
        startReply(m);
      });
      pop.appendChild(replyAct);

      if (isProjectThread(activeThread())) {
        var pinAct = document.createElement("button");
        pinAct.type = "button";
        pinAct.className = "project-chat-msg-popover-action";
        pinAct.textContent = m.is_pinned ? "Unpin" : "Pin";
        pinAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          var api = fetchChatApi();
          if (!api) return;
          var fn = m.is_pinned ? api.unpinMessage : api.pinMessage;
          var thread = ChatPageState.threadsMap[projectId];
          var pid = thread && thread.project_id != null ? thread.project_id : projectId;
          fn(pid, m.id)
            .then(function () {
              return loadMessages(projectId, { reset: true });
            })
            .catch(function () {});
        });
        pop.appendChild(pinAct);

        var actionAct = document.createElement("button");
        actionAct.type = "button";
        actionAct.className = "project-chat-msg-popover-action";
        actionAct.textContent = "Create Action Item";
        actionAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          var api = fetchChatApi();
          if (!api) return;
          var thread = ChatPageState.threadsMap[projectId];
          var pid = thread && thread.project_id != null ? thread.project_id : projectId;
          api
            .createActionFromMessage(pid, m.id, {
              title: (m.message || "").slice(0, 80) || "Chat follow-up",
            })
            .then(function (data) {
              if (data && data.url) window.open(data.url, "_blank");
            })
            .catch(function () {});
        });
        pop.appendChild(actionAct);
      }

      if (m.delivery_status === "failed" && m.temp_id) {
        var retryAct = document.createElement("button");
        retryAct.type = "button";
        retryAct.className = "project-chat-msg-popover-action";
        retryAct.textContent = "Retry send";
        retryAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          retryPendingMessage(projectId, m.temp_id);
        });
        pop.appendChild(retryAct);
        var dropAct = document.createElement("button");
        dropAct.type = "button";
        dropAct.className = "project-chat-msg-popover-action";
        dropAct.textContent = "Remove draft";
        dropAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          removePendingMessage(projectId, m.temp_id);
        });
        pop.appendChild(dropAct);
      }

      if (m.is_me) {
        var delAct = document.createElement("button");
        delAct.type = "button";
        delAct.className = "project-chat-msg-popover-action";
        delAct.textContent = "Delete for everyone";
        delAct.addEventListener("click", function (e) {
          e.stopPropagation();
          pop.hidden = true;
          fetch(deleteMessageUrl(projectId, m.id), {
            method: "DELETE",
            credentials: "same-origin",
          })
            .then(function (res) {
              if (!res.ok) throw new Error("delete");
              return reloadFn();
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
          postChatReaction(projectId, m.id, em)
            .then(function (data) {
              fillChatReactionRow(reactRow, data.reactions, m.id, projectId, reloadFn);
            })
            .catch(function () {});
        });
        reactGrid.appendChild(eb);
      });
      pop.appendChild(reactGrid);

      menuBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        var willOpen = pop.hidden;
        document.querySelectorAll(".project-chat-msg-popover").forEach(function (p) {
          p.hidden = true;
        });
        pop.hidden = !willOpen;
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

  function filterMessagesForSearch(items) {
    var q = (ChatPageState.messageSearchQuery || "").trim().toLowerCase();
    if (!q) return items;
    return items.filter(function (m) {
      if (m.is_deleted) return false;
      return ((m.message || "") + " " + (m.username || "")).toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderMessages(storageKey, items, opts) {
    opts = opts || {};
    var listEl = $("chat-page-messages");
    if (!listEl) return;
    var team = teamForKey(storageKey);
    var filtered = ChatPageState.serverSearchMode
      ? items || []
      : filterMessagesForSearch(items || []);
    listEl.innerHTML = "";

    var ps = getPageState(storageKey);
    if (ps.hasOlder) {
      var loader = document.createElement("div");
      loader.id = "chat-page-older-loader";
      loader.className = "chat-page-older-loader muted";
      loader.textContent = ps.loadingOlder ? "Loading older messages…" : "Scroll up for older messages";
      loader.hidden = !!ps.loadingOlder;
      listEl.appendChild(loader);
    }

    if (!filtered.length) {
      var empty = document.createElement("p");
      empty.className = "project-chat-empty muted";
      empty.textContent = ChatPageState.serverSearchMode || ChatPageState.messageSearchQuery
        ? "No messages match your search."
        : isDirectThread(activeThread())
          ? "No messages yet. Say hello."
          : "No messages yet. Say hello to your team.";
      listEl.appendChild(empty);
      updateUnreadHeaderButton(storageKey);
      return;
    }

    var reloadFn = function () {
      return loadMessages(storageKey, { reset: true });
    };
    var prev = null;
    var lastDay = "";
    var unreadInserted = false;
    var unreadTarget = ps.showUnreadDivider ? ps.firstUnreadMessageId : null;
    for (var k = 0; k < filtered.length; k++) {
      var m = filtered[k];
      if (!unreadInserted && unreadTarget && m.id >= unreadTarget) {
        unreadInserted = true;
        var unreadSep = document.createElement("div");
        unreadSep.className = "chat-page-unread-sep";
        unreadSep.textContent = "Unread messages";
        listEl.appendChild(unreadSep);
        prev = null;
      }
      var dk = dayKey(m.created_at);
      if (dk && dk !== lastDay) {
        lastDay = dk;
        var sep = document.createElement("div");
        sep.className = "chat-page-date-sep";
        var span = document.createElement("span");
        span.textContent = formatDateSeparator(m.created_at);
        sep.appendChild(span);
        listEl.appendChild(sep);
        prev = null;
      }
      prev = appendOneMessageRow(listEl, m, prev, team, storageKey, reloadFn);
    }
    updateUnreadHeaderButton(storageKey);
    if (opts.scroll === "bottom" || opts.scroll == null) {
      requestAnimationFrame(function () {
        listEl.scrollTop = listEl.scrollHeight;
      });
    } else if (opts.scroll === "message" && opts.messageId) {
      requestAnimationFrame(function () {
        scrollToMessage(opts.messageId);
      });
    } else if (opts.preserveScroll && opts.prevHeight != null) {
      requestAnimationFrame(function () {
        listEl.scrollTop = listEl.scrollHeight - opts.prevHeight;
      });
    }
  }

  function appendTailMessages(listEl, newSlice, storageKey, prevMsg) {
    var team = teamForKey(storageKey);
    var reloadFn = function () {
      return loadMessages(storageKey, { reset: true });
    };
    var prev = prevMsg;
    var emptyEl = listEl.querySelector(".project-chat-empty");
    if (emptyEl) emptyEl.remove();
    for (var j = 0; j < newSlice.length; j++) {
      prev = appendOneMessageRow(listEl, newSlice[j], prev, team, storageKey, reloadFn);
    }
    return prev;
  }

  function tryAppendNewMessagesOnly(listEl, prevItems, nextItems, projectId) {
    if (!prevItems || !prevItems.length || !nextItems || !nextItems.length) {
      return { applied: false, added: 0 };
    }
    var prevNewest = prevItems[prevItems.length - 1].id;
    var nextNewest = nextItems[nextItems.length - 1].id;
    if (nextNewest <= prevNewest) return { applied: true, added: 0 };
    var newSlice = nextItems.filter(function (m) {
      return m.id > prevNewest;
    });
    if (!newSlice.length) return { applied: true, added: 0 };
    var nearBottom = isNearBottom(listEl);
    var prev = prevItems[prevItems.length - 1];
    appendTailMessages(listEl, newSlice, projectId, prev);
    if (nearBottom) {
      requestAnimationFrame(function () {
        listEl.scrollTop = listEl.scrollHeight;
      });
      showNewMessagesJump(false);
      ChatPageState.newMessagesPending = false;
    } else {
      showNewMessagesJump(true);
      ChatPageState.newMessagesPending = true;
    }
    return { applied: true, added: newSlice.length };
  }

  function loadMessages(storageKey, opts) {
    opts = opts || {};
    var listEl = $("chat-page-messages");
    var nearBottom = isNearBottom(listEl);
    return fetchMessagesForKey(storageKey, { limit: 50, direction: "latest" })
      .then(function (data) {
        applyMessagesResponse(storageKey, data, opts.reset ? "replace" : "replace");
        var items = ChatPageState.messagesByProject[storageKey] || [];
        var prevSnap = ChatPageState.lastSnapshotByProject[storageKey];
        var inc =
          !opts.reset && listEl && prevSnap
            ? tryAppendNewMessagesOnly(listEl, prevSnap, items, storageKey)
            : { applied: false };
        if (!inc.applied) {
          renderMessages(storageKey, items, {
            scroll: nearBottom || opts.reset ? "bottom" : undefined,
          });
        }
        ChatPageState.lastSnapshotByProject[storageKey] = items.slice();
        showOlderLoader(false);
        getPageState(storageKey).loadingOlder = false;
      })
      .catch(function (e) {
        if (listEl) {
          listEl.innerHTML = "";
          var err = document.createElement("p");
          err.className = "project-chat-empty muted";
          err.textContent = e.message || "Could not load messages";
          listEl.appendChild(err);
        }
      });
  }

  function loadOlderMessages(storageKey) {
    var ps = getPageState(storageKey);
    if (!ps.hasOlder || ps.loadingOlder) return Promise.resolve();
    var listEl = $("chat-page-messages");
    var prevHeight = listEl ? listEl.scrollHeight : 0;
    ps.loadingOlder = true;
    showOlderLoader(true);
    if (ps.oldestId == null) {
      ps.loadingOlder = false;
      showOlderLoader(false);
      return Promise.resolve();
    }
    return fetchMessagesForKey(storageKey, { before_id: ps.oldestId, limit: 50, direction: "older" })
      .then(function (data) {
        applyMessagesResponse(storageKey, data, "prepend");
        ps.loadingOlder = false;
        showOlderLoader(false);
        renderMessages(storageKey, ChatPageState.messagesByProject[storageKey], {
          preserveScroll: true,
          prevHeight: prevHeight,
        });
      })
      .catch(function () {
        ps.loadingOlder = false;
        showOlderLoader(false);
      });
  }

  function removePendingMessage(projectId, tempId) {
    var pending = ChatPageState.pendingByProject[projectId] || {};
    delete pending[tempId];
    ChatPageState.pendingByProject[projectId] = pending;
    var items = (ChatPageState.messagesByProject[projectId] || []).filter(function (m) {
      return m.temp_id !== tempId;
    });
    ChatPageState.messagesByProject[projectId] = items;
    renderMessages(projectId, items, { scroll: "preserve" });
  }

  function retryPendingMessage(projectId, tempId) {
    var pending = (ChatPageState.pendingByProject[projectId] || {})[tempId];
    if (!pending || !pending.formData) return;
    postFormData(pending.formData, { tempId: tempId, retry: true });
  }

  function postFormData(fd, opts) {
    opts = opts || {};
    var key = activeStorageKey();
    if (key == null) return Promise.reject(new Error("No thread selected"));
    var thread = ChatPageState.threadsMap[key];
    if (!thread || !thread.messages_url) return Promise.reject(new Error("No thread"));
    var tempId = opts.tempId || "tmp_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
    if (!opts.retry) {
      fd.append("temp_id", tempId);
      if (ChatPageState.replyTo && ChatPageState.replyTo.id) {
        fd.append("reply_to_message_id", String(ChatPageState.replyTo.id));
      }
      var text = fd.get("message") || fd.get("text") || "";
      var optimistic = {
        id: tempId,
        temp_id: tempId,
        username: "You",
        message: String(text || "").trim(),
        avatar_initial: "?",
        created_at: new Date().toISOString(),
        is_me: true,
        is_deleted: false,
        reactions: [],
        delivery_status: "sending",
      };
      if (!ChatPageState.pendingByProject[key]) ChatPageState.pendingByProject[key] = {};
      ChatPageState.pendingByProject[key][tempId] = { formData: fd, optimistic: optimistic };
      var items = (ChatPageState.messagesByProject[key] || []).slice();
      items.push(optimistic);
      ChatPageState.messagesByProject[key] = items;
      renderMessages(key, items, { scroll: "bottom" });
    }
    ChatPageState.root.classList.add("is-sending");
    var typingPid = activeProjectId();
    if (typingPid != null) stopTypingEmit(typingPid);
    return fetch(thread.messages_url, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (res) {
        return res.text().then(function (text) {
          var body = {};
          try {
            if (text && text.charAt(0) === "{") body = JSON.parse(text);
          } catch (ignore) {}
          if (!res.ok) {
            throw new Error((body && (body.detail || body.error)) || "Send failed");
          }
          return body;
        });
      })
      .then(function (body) {
        var input = $("chat-page-composer-input");
        resetComposerInput(input);
        var file = $("chat-page-file-image");
        if (file) file.value = "";
        setComposerError("");
        cancelReply();
        if (ChatPageState.pendingByProject[key]) delete ChatPageState.pendingByProject[key][tempId];
        var serverMsg = body.message;
        if (serverMsg) {
          var list = (ChatPageState.messagesByProject[key] || []).filter(function (m) {
            return m.temp_id !== tempId;
          });
          serverMsg.delivery_status = "sent";
          list.push(serverMsg);
          list.sort(function (a, b) {
            return (a.id || 0) - (b.id || 0);
          });
          ChatPageState.messagesByProject[key] = list;
          ChatPageState.lastSnapshotByProject[key] = list.slice();
          renderMessages(key, list, { scroll: "bottom" });
        } else {
          return loadMessages(key, { reset: true });
        }
        return markCurrentThreadRead();
      })
      .catch(function (e) {
        var list = ChatPageState.messagesByProject[key] || [];
        list.forEach(function (m) {
          if (m.temp_id === tempId) m.delivery_status = "failed";
        });
        renderMessages(key, list, { scroll: "bottom" });
        if (!opts.retry) setComposerError(e.message || "Send failed");
        throw e;
      })
      .finally(function () {
        ChatPageState.root.classList.remove("is-sending");
      });
  }

  function sendMessage() {
    var input = $("chat-page-composer-input");
    var text = input ? (input.value || "").trim() : "";
    if (!text) {
      setComposerError("Type a message or attach media.");
      return;
    }
    setComposerError("");
    var fd = new FormData();
    fd.append("message", text);
    postFormData(fd).catch(function (e) {
      setComposerError(e.message || "Send failed");
    });
  }

  function uploadAttachment(file) {
    if (!file) return;
    var fd = new FormData();
    var input = $("chat-page-composer-input");
    var text = input ? (input.value || "").trim() : "";
    if (text) fd.append("message", text);
    fd.append("image", file);
    postFormData(fd).catch(function (e) {
      setComposerError(e.message || "Upload failed");
    });
  }

  function stopVoiceRecording(send) {
    ChatPageState.voiceShouldSend = !!send;
    if (ChatPageState.mediaRecorder && ChatPageState.mediaRecorder.state === "recording") {
      try {
        ChatPageState.mediaRecorder.stop();
      } catch (e) {}
    }
  }

  function startVoiceRecording() {
    if (ChatPageState.mediaRecorder && ChatPageState.mediaRecorder.state === "recording") {
      stopVoiceRecording(true);
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setComposerError("Voice notes are not supported in this browser.");
      return;
    }
    var btn = $("chat-page-btn-voice");
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then(function (stream) {
        ChatPageState.recordStream = stream;
        ChatPageState.recordChunks = [];
        try {
          ChatPageState.mediaRecorder = new MediaRecorder(stream);
        } catch (e) {
          setComposerError("Could not start recording.");
          return;
        }
        ChatPageState.mediaRecorder.ondataavailable = function (ev) {
          if (ev.data && ev.data.size) ChatPageState.recordChunks.push(ev.data);
        };
        ChatPageState.mediaRecorder.onstop = function () {
          var blob = new Blob(ChatPageState.recordChunks, {
            type: ChatPageState.mediaRecorder.mimeType || "audio/webm",
          });
          ChatPageState.recordChunks = [];
          if (ChatPageState.recordStream) {
            ChatPageState.recordStream.getTracks().forEach(function (t) {
              t.stop();
            });
            ChatPageState.recordStream = null;
          }
          ChatPageState.mediaRecorder = null;
          if (btn) btn.classList.remove("is-recording");
          if (ChatPageState.voiceMaxTimer) {
            clearTimeout(ChatPageState.voiceMaxTimer);
            ChatPageState.voiceMaxTimer = null;
          }
          if (ChatPageState.voiceShouldSend && blob.size > 0) {
            var ext = extForAudioBlob(blob);
            var file = new File([blob], "voice" + ext, { type: blob.type || "audio/webm" });
            var fd = new FormData();
            var input = $("chat-page-composer-input");
            var tx = input ? (input.value || "").trim() : "";
            if (tx) fd.append("message", tx);
            fd.append("audio", file);
            postFormData(fd).catch(function (e) {
              setComposerError(e.message || "Voice upload failed");
            });
          }
          ChatPageState.voiceShouldSend = false;
        };
        ChatPageState.mediaRecorder.start(200);
        if (btn) btn.classList.add("is-recording");
        ChatPageState.voiceMaxTimer = setTimeout(function () {
          stopVoiceRecording(true);
        }, RECORDING_MAX_MS);
      })
      .catch(function () {
        setComposerError("Microphone access denied.");
      });
  }

  function updateThreadPreview(storageKey) {
    loadThreads().then(function () {
      if (ChatPageState.selectedThreadKey === storageKey) {
        updateConversationHeader(activeThread());
      }
    });
  }

  function handleConferenceUpdated(payload) {
    if (!payload) return;
    var key = findKeyForSocketPayload(payload);
    loadThreads().then(function () {
      if (ChatPageState.selectedThreadKey === key) {
        return loadMessages(key, { reset: true }).then(function () {
          if (window.ChatConferenceUI && window.ChatConferenceUI.updateForThread) {
            window.ChatConferenceUI.updateForThread(activeThread());
          }
        });
      }
    });
  }

  function handleSocketChatUpdated(payload) {
    var key = findKeyForSocketPayload(payload);
    if (!key) return;
    if (ChatPageState.selectedThreadKey === key) {
      var ps = getPageState(key);
      var kind = payload.kind || "message";
      if (kind === "pin" || kind === "unpin" || kind === "link" || kind === "delete") {
        loadMessages(key, { reset: true }).then(function () {
          if (isNearBottom($("chat-page-messages"))) markCurrentThreadRead();
        });
      } else if (ps.newestId && kind !== "reaction") {
        fetchMessagesForKey(key, { after_id: ps.newestId, limit: 50, direction: "newer" })
          .then(function (data) {
            if (!data.messages || !data.messages.length) return;
            applyMessagesResponse(key, data, "append");
            var items = ChatPageState.messagesByProject[key] || [];
            var listEl = $("chat-page-messages");
            var prevSnap = ChatPageState.lastSnapshotByProject[key] || [];
            tryAppendNewMessagesOnly(listEl, prevSnap, items, key);
            ChatPageState.lastSnapshotByProject[key] = items.slice();
            ps.newestId = data.newest_id != null ? data.newest_id : ps.newestId;
            if (isNearBottom(listEl)) markCurrentThreadRead();
          })
          .catch(function () {
            loadMessages(key, { reset: true });
          });
      } else {
        loadMessages(key, { reset: kind === "reaction" }).then(function () {
          if (isNearBottom($("chat-page-messages"))) markCurrentThreadRead();
        });
      }
    }
    updateThreadPreview(key);
  }

  function buildMentionAutocomplete(inputEl, listEl) {
    if (!inputEl || !listEl) return;
    var mentionState = { start: -1, highlight: 0, filtered: [] };

    function hide() {
      listEl.hidden = true;
      listEl.innerHTML = "";
      mentionState.start = -1;
      mentionState.filtered = [];
    }

    function teamList() {
      var key = activeStorageKey();
      return key != null ? teamForKey(key) : [];
    }

    function filterTeam(q) {
      var qq = (q || "").toLowerCase();
      var out = [];
      var team = teamList();
      for (var i = 0; i < team.length; i++) {
        var n = (team[i].name || "").toLowerCase();
        if (!qq || n.indexOf(qq) === 0) out.push(team[i]);
        if (out.length >= 8) break;
      }
      return out;
    }

    function render(items) {
      listEl.innerHTML = "";
      items.forEach(function (t, idx) {
        var li = document.createElement("li");
        li.className = "project-chat-mention-suggestion";
        if (idx === mentionState.highlight) li.classList.add("is-active");
        li.textContent = t.name;
        li.addEventListener("mousedown", function (e) {
          e.preventDefault();
          insert(t.name);
        });
        listEl.appendChild(li);
      });
      listEl.hidden = items.length === 0;
    }

    function insert(name) {
      if (mentionState.start < 0) return;
      var v = inputEl.value;
      var cur = inputEl.selectionStart;
      var end = typeof cur === "number" ? cur : v.length;
      var before = v.slice(0, mentionState.start);
      var after = v.slice(end);
      var ins = "@" + name + " ";
      inputEl.value = before + ins + after;
      inputEl.setSelectionRange(before.length + ins.length, before.length + ins.length);
      hide();
      inputEl.focus();
    }

    function updateMentionUI() {
      var v = inputEl.value;
      var cur = inputEl.selectionStart;
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
      if (query.indexOf("\n") >= 0) {
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

    inputEl.addEventListener("input", updateMentionUI);
    inputEl.addEventListener("keyup", updateMentionUI);
    inputEl.addEventListener("blur", function () {
      setTimeout(hide, 160);
    });
    inputEl.addEventListener("keydown", function (e) {
      if (listEl.hidden || !mentionState.filtered.length) return;
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
  }

  function renderServerSearchResults(projectId) {
    var listEl = $("chat-page-messages");
    if (!listEl) return;
    listEl.innerHTML = "";
    var results = ChatPageState.serverSearchResults || [];
    if (!results.length) {
      var empty = document.createElement("p");
      empty.className = "project-chat-empty muted";
      empty.textContent = "No messages match your search.";
      listEl.appendChild(empty);
      return;
    }
    results.forEach(function (r) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chat-page-search-result";
      btn.innerHTML =
        "<span class='chat-page-search-result-meta'>" +
        (r.sender_name || "") +
        " · " +
        formatTime(r.created_at) +
        "</span><span>" +
        (r.message || "") +
        "</span>";
      btn.addEventListener("click", function () {
        ChatPageState.serverSearchMode = false;
        var msgSearch = $("chat-page-msg-search");
        if (msgSearch) msgSearch.value = "";
        jumpToMessage(projectId, r.message_id);
      });
      listEl.appendChild(btn);
    });
  }

  function loadAttachmentsPanel(projectId, type) {
    var list = $("chat-page-attachments-list");
    if (!list || !fetchChatApi()) return;
    fetchChatApi()
      .fetchAttachments(projectId, type || "all", 1)
      .then(function (data) {
        list.innerHTML = "";
        (data.items || []).forEach(function (item) {
          var row = document.createElement("button");
          row.type = "button";
          row.className = "chat-page-attachment-item";
          if (item.attachment_type === "image") {
            var img = document.createElement("img");
            img.src = item.url;
            img.alt = item.message_excerpt || "Image";
            row.appendChild(img);
          } else {
            row.textContent = (item.sender_name || "") + " · " + (item.message_excerpt || "Audio");
          }
          row.addEventListener("click", function () {
            var dlg = $("chat-page-attachments-dialog");
            if (dlg) dlg.close();
            var key = activeStorageKey() || storageKeyForProjectId(projectId);
            jumpToMessage(key, item.message_id);
          });
          list.appendChild(row);
        });
      })
      .catch(function () {});
  }

  function parseInitialThreadId() {
    var root = ChatPageState.root;
    var raw = root ? root.getAttribute("data-initial-thread-id") : "";
    if (raw) {
      var n = parseInt(raw, 10);
      if (!isNaN(n)) return n;
    }
    var params = new URLSearchParams(window.location.search);
    var qp = params.get("thread_id") || params.get("direct_thread_id");
    if (qp) {
      var p = parseInt(qp, 10);
      if (!isNaN(p)) return p;
    }
    return null;
  }

  function resolveInitialSelection() {
    var threadId = parseInitialThreadId();
    if (threadId != null) {
      var dkey = findKeyForThreadId(threadId);
      if (ChatPageState.threadsMap[dkey]) {
        selectThreadKey(dkey);
        return dkey;
      }
    }
    var initial = parseInitialProjectId();
    if (initial != null) {
      var pkey = storageKeyForProjectId(initial);
      if (ChatPageState.threadsMap[pkey]) {
        selectThreadKey(pkey);
        return pkey;
      }
    }
    return null;
  }

  function wireDirectMessageModal() {
    var btn = $("chat-page-new-dm-btn");
    var dlg = $("chat-page-new-dm-dialog");
    var search = $("chat-page-new-dm-search");
    var list = $("chat-page-new-dm-list");
    var empty = $("chat-page-new-dm-empty");
    if (!btn || !dlg) return;

    function renderUsers(users) {
      if (!list) return;
      list.innerHTML = "";
      if (empty) empty.hidden = users.length > 0;
      users.forEach(function (u) {
        var row = document.createElement("button");
        row.type = "button";
        row.className = "chat-page-new-dm-user";
        var av = document.createElement("span");
        av.className = "chat-page-new-dm-avatar";
        fillAvatarEl(av, {
          avatar_url: u.avatar_url,
          avatar_initial: u.avatar_initial,
          name: u.name,
        });
        var body = document.createElement("span");
        body.className = "chat-page-new-dm-body";
        var name = document.createElement("span");
        name.className = "chat-page-new-dm-name";
        name.textContent = u.name || "User";
        body.appendChild(name);
        if (u.job_title || u.email) {
          var meta = document.createElement("span");
          meta.className = "chat-page-new-dm-meta muted";
          meta.textContent = [u.job_title, u.email].filter(Boolean).join(" · ");
          body.appendChild(meta);
        }
        row.appendChild(av);
        row.appendChild(body);
        row.addEventListener("click", function () {
          var api = fetchChatApi();
          if (!api) return;
          api
            .startDirectChat(u.account_id)
            .then(function (data) {
              if (typeof dlg.close === "function") dlg.close();
              else dlg.removeAttribute("open");
              return loadThreads().then(function () {
                var thread = data && data.thread;
                if (thread) {
                  selectThreadKey(threadStorageKey(thread));
                }
              });
            })
            .catch(function () {});
        });
        list.appendChild(row);
      });
    }

    function loadUsers(q) {
      var api = fetchChatApi();
      if (!api) return;
      api.fetchDirectUsers(q).then(function (data) {
        renderUsers((data && data.users) || []);
      });
    }

    btn.addEventListener("click", function () {
      if (typeof dlg.showModal === "function") dlg.showModal();
      else dlg.setAttribute("open", "");
      if (search) search.value = "";
      loadUsers("");
      if (search) search.focus();
    });

    if (search) {
      var timer = null;
      search.addEventListener("input", function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          loadUsers((search.value || "").trim());
        }, 250);
      });
    }

    dlg.querySelectorAll("[data-chat-page-new-dm-close]").forEach(function (closeBtn) {
      closeBtn.addEventListener("click", function () {
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
      });
    });
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg) {
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
      }
    });
  }

  function wireGroupModal() {
    var btn = $("chat-page-new-group-btn");
    var dlg = $("chat-page-new-group-dialog");
    var search = $("chat-page-new-group-search");
    var list = $("chat-page-new-group-user-list");
    var chips = $("chat-page-new-group-chips");
    var titleInput = $("chat-page-new-group-name");
    var descInput = $("chat-page-new-group-description");
    var createBtn = $("chat-page-new-group-create");
    if (!btn || !dlg) return;
    var selectedMap = {};

    function renderChips() {
      if (!chips) return;
      chips.innerHTML = "";
      Object.keys(selectedMap).forEach(function (aid) {
        var info = selectedMap[aid];
        var chip = document.createElement("span");
        chip.className = "chat-page-new-group-chip";
        chip.textContent = info.name + " ×";
        chip.addEventListener("click", function () {
          delete selectedMap[aid];
          renderChips();
          renderUsers(lastUsers);
        });
        chips.appendChild(chip);
      });
    }

    var lastUsers = [];

    function renderUsers(users) {
      lastUsers = users || [];
      if (!list) return;
      list.innerHTML = "";
      lastUsers.forEach(function (u) {
        if (selectedMap[String(u.account_id)]) return;
        var row = document.createElement("button");
        row.type = "button";
        row.className = "chat-page-new-dm-user";
        row.textContent = u.name || "User";
        row.addEventListener("click", function () {
          selectedMap[String(u.account_id)] = { name: u.name || "User" };
          renderChips();
          renderUsers(lastUsers);
        });
        list.appendChild(row);
      });
    }

    function loadUsers(q) {
      var api = fetchChatApi();
      if (!api) return;
      api.fetchChatUsers(q).then(function (data) {
        renderUsers((data && data.users) || []);
      });
    }

    if (createBtn) {
      createBtn.addEventListener("click", function () {
        var api = fetchChatApi();
        if (!api) return;
        var title = titleInput ? (titleInput.value || "").trim() : "";
        var ids = Object.keys(selectedMap).map(function (k) {
          return parseInt(k, 10);
        });
        api
          .createGroupChat({
            title: title,
            description: descInput ? (descInput.value || "").trim() : "",
            participant_account_ids: ids,
          })
          .then(function (data) {
            if (typeof dlg.close === "function") dlg.close();
            else dlg.removeAttribute("open");
            selectedMap = {};
            renderChips();
            return loadThreads().then(function () {
              var thread = data && data.thread;
              if (thread) selectThreadKey(threadStorageKey(thread));
            });
          })
          .catch(function () {});
      });
    }

    btn.addEventListener("click", function () {
      if (typeof dlg.showModal === "function") dlg.showModal();
      else dlg.setAttribute("open", "");
      selectedMap = {};
      renderChips();
      if (titleInput) titleInput.value = "";
      if (descInput) descInput.value = "";
      if (search) search.value = "";
      loadUsers("");
    });

    if (search) {
      var timer = null;
      search.addEventListener("input", function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          loadUsers((search.value || "").trim());
        }, 250);
      });
    }

    dlg.querySelectorAll("[data-chat-page-new-group-close]").forEach(function (closeBtn) {
      closeBtn.addEventListener("click", function () {
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
      });
    });
  }

  function parseInitialProjectId() {
    var root = ChatPageState.root;
    var raw = root ? root.getAttribute("data-initial-project-id") : "";
    if (raw) {
      var n = parseInt(raw, 10);
      if (!isNaN(n)) return n;
    }
    var params = new URLSearchParams(window.location.search);
    var qp = params.get("project_id");
    if (qp) {
      var p = parseInt(qp, 10);
      if (!isNaN(p)) return p;
    }
    var m = /^gchat-(\d+)$/.exec((window.location.hash || "").replace(/^#/, ""));
    if (m) {
      var h = parseInt(m[1], 10);
      if (!isNaN(h)) return h;
    }
    return null;
  }

  function wireSocket() {
    var s = window.__tmSocket;
    if (!s) return;
    s.on("connect", bindAllSocketRooms);
    s.on("chat_updated", handleSocketChatUpdated);
    s.on("conference_updated", handleConferenceUpdated);
    s.on("conference_invite", handleConferenceUpdated);
    s.on("conference_joined", handleConferenceUpdated);
    s.on("conference_left", handleConferenceUpdated);
    s.on("conference_ended", handleConferenceUpdated);
    s.on("chat_typing", handleChatTyping);
    if (s.connected) bindAllSocketRooms();
  }

  function init() {
    ChatPageState.root = $("chat-page-root");
    if (!ChatPageState.root) return;
    ChatPageState.threadsUrl = ChatPageState.root.getAttribute("data-threads-url") || "/chat/threads";
    var rawV = ChatPageState.root.getAttribute("data-viewer-id");
    ChatPageState.myDirectoryUserId = rawV && rawV !== "" ? parseInt(rawV, 10) : null;
    if (isNaN(ChatPageState.myDirectoryUserId)) ChatPageState.myDirectoryUserId = null;

    document.addEventListener("click", function (e) {
      if (!e.target.closest(".project-chat-msg-menu-btn")) {
        document.querySelectorAll(".project-chat-msg-popover").forEach(function (p) {
          p.hidden = true;
        });
      }
    });

    var threadSearch = $("chat-page-thread-search");
    var globalTimer = null;
    function runGlobalChatSearch(raw) {
      ChatPageState.globalSearchQuery = raw;
      var q = (raw || "").trim();
      if (globalTimer) clearTimeout(globalTimer);
      var panel = $("chat-page-global-search-results");
      if (!panel) return;
      if (q.length < 2) {
        panel.hidden = true;
        panel.innerHTML = "";
        return;
      }
      globalTimer = setTimeout(function () {
        var api = fetchChatApi();
        if (!api) return;
        api.searchGlobal(q, 1, 30).then(function (data) {
          panel.innerHTML = "";
          (data.results || []).forEach(function (r) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "chat-page-global-search-item";
            btn.innerHTML =
              "<strong>" +
              (r.thread_title || r.project_name || "Chat") +
              "</strong><span>" +
              (r.sender_name || "") +
              ": " +
              (r.message || "") +
              "</span>";
            btn.addEventListener("click", function () {
              panel.hidden = true;
              var rkey = null;
              if (r.thread_id != null) rkey = findKeyForThreadId(r.thread_id);
              else if (r.project_id != null) rkey = storageKeyForProjectId(r.project_id);
              if (rkey && ChatPageState.threadsMap[rkey]) {
                selectThreadKey(rkey);
                jumpToMessage(rkey, r.message_id);
              }
            });
            panel.appendChild(btn);
          });
          panel.hidden = !(data.results && data.results.length);
        });
      }, 300);
    }
    if (threadSearch) {
      threadSearch.addEventListener("input", function () {
        ChatPageState.threadSearchQuery = threadSearch.value;
        renderThreadList();
        runGlobalChatSearch(threadSearch.value);
      });
    }

    var msgSearch = $("chat-page-msg-search");
    if (msgSearch) {
      var msgSearchTimer = null;
      msgSearch.addEventListener("input", function () {
        ChatPageState.messageSearchQuery = msgSearch.value;
        var key = activeStorageKey();
        var thread = activeThread();
        var pid = thread && thread.project_id != null ? thread.project_id : null;
        var q = (msgSearch.value || "").trim();
        if (msgSearchTimer) clearTimeout(msgSearchTimer);
        if (q.length >= 2 && pid != null && !isDirectThread(thread) && fetchChatApi()) {
          msgSearchTimer = setTimeout(function () {
            fetchChatApi()
              .searchProject(pid, q, 1, 50)
              .then(function (data) {
                ChatPageState.serverSearchMode = true;
                ChatPageState.serverSearchResults = data.results || [];
                renderServerSearchResults(key);
              })
              .catch(function () {});
          }, 300);
          return;
        }
        ChatPageState.serverSearchMode = false;
        ChatPageState.serverSearchResults = [];
        if (key != null) {
          renderMessages(key, ChatPageState.messagesByProject[key] || []);
        }
      });
    }


    var messagesEl = $("chat-page-messages");
    if (messagesEl) {
      messagesEl.addEventListener("scroll", function () {
        if (messagesEl.scrollTop < 60) {
          var key = activeStorageKey();
          if (key != null) loadOlderMessages(key);
        }
      });
    }

    var jumpUnread = $("chat-page-jump-unread-btn");
    if (jumpUnread) jumpUnread.addEventListener("click", jumpToFirstUnread);

    var newMsgsBtn = $("chat-page-new-msgs-btn");
    if (newMsgsBtn) {
      newMsgsBtn.addEventListener("click", function () {
        var listEl = $("chat-page-messages");
        if (listEl) listEl.scrollTop = listEl.scrollHeight;
        showNewMessagesJump(false);
        markCurrentThreadRead();
      });
    }

    var pinnedBtn = $("chat-page-pinned-btn");
    if (pinnedBtn) {
      pinnedBtn.addEventListener("click", function () {
        var thread = activeThread();
        var pid = thread && thread.project_id != null ? thread.project_id : null;
        var key = activeStorageKey();
        if (pid == null || key == null) return;
        var dlg = $("chat-page-pinned-dialog");
        var list = $("chat-page-pinned-list");
        if (!dlg || !list) return;
        fetchChatApi()
          .fetchPinned(pid)
          .then(function (data) {
            list.innerHTML = "";
            (data.pinned || []).forEach(function (p) {
              var li = document.createElement("li");
              var btn = document.createElement("button");
              btn.type = "button";
              btn.className = "chat-page-pinned-item";
              btn.textContent = (p.sender_name || "") + ": " + (p.message || "");
              btn.addEventListener("click", function () {
                dlg.close();
                jumpToMessage(key, p.message_id);
              });
              li.appendChild(btn);
              list.appendChild(li);
            });
            dlg.showModal();
          })
          .catch(function () {});
      });
    }

    var attachBtn = $("chat-page-attachments-btn");
    if (attachBtn) {
      attachBtn.addEventListener("click", function () {
        var thread = activeThread();
        var pid = thread && thread.project_id != null ? thread.project_id : null;
        if (pid == null) return;
        var dlg = $("chat-page-attachments-dialog");
        if (dlg) dlg.showModal();
        loadAttachmentsPanel(pid, "all");
      });
    }

    var attachTabs = document.querySelectorAll("[data-chat-attach-tab]");
    attachTabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        attachTabs.forEach(function (t) {
          t.classList.toggle("is-active", t === tab);
        });
        var thread = activeThread();
        var pid = thread && thread.project_id != null ? thread.project_id : null;
        if (pid != null) loadAttachmentsPanel(pid, tab.getAttribute("data-chat-attach-tab") || "all");
      });
    });

    var backBtn = $("chat-page-back-btn");
    if (backBtn) {
      backBtn.addEventListener("click", function () {
        ChatPageState.selectedProjectId = null;
        ChatPageState.selectedThreadKey = null;
        showConversation(false);
        renderThreadList();
        if (history.replaceState) {
          history.replaceState(null, "", window.location.pathname);
        }
      });
    }

    var form = $("chat-page-composer-form");
    var input = $("chat-page-composer-input");
    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        sendMessage();
      });
    }
    if (input) {
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          var listEl = $("chat-page-mention-list");
          if (listEl && !listEl.hidden) return;
          e.preventDefault();
          sendMessage();
        }
      });
      input.addEventListener("input", function () {
        syncComposerInputHeight(input);
      });
      syncComposerInputHeight(input);
      wireTypingInput(input);
      buildMentionAutocomplete(input, $("chat-page-mention-list"));
    }

    var replyCancel = $("chat-page-reply-cancel");
    if (replyCancel) replyCancel.addEventListener("click", cancelReply);

    var btnImage = $("chat-page-btn-image");
    var fileImage = $("chat-page-file-image");
    if (btnImage && fileImage) {
      btnImage.addEventListener("click", function () {
        fileImage.click();
      });
      fileImage.addEventListener("change", function () {
        if (fileImage.files && fileImage.files[0]) {
          uploadAttachment(fileImage.files[0]);
        }
      });
    }

    var btnVoice = $("chat-page-btn-voice");
    if (btnVoice) {
      btnVoice.addEventListener("click", startVoiceRecording);
    }

    var teamBtn = $("chat-page-team-btn");
    if (teamBtn) {
      teamBtn.addEventListener("click", function () {
        var thread = activeThread();
        var key = activeStorageKey();
        if (thread && isProjectThread(thread) && thread.project_id != null) {
          openTeamModal(thread.project_id);
        } else if (key != null) {
          openMembersModal(key);
        }
      });
    }

    var teamDlg = $("chat-page-team-dialog");
    if (teamDlg) {
      teamDlg.querySelectorAll("[data-chat-page-team-close]").forEach(function (btn) {
        btn.addEventListener("click", closeTeamModal);
      });
      teamDlg.addEventListener("click", function (e) {
        if (e.target === teamDlg) closeTeamModal();
      });
      teamDlg.addEventListener("close", closeTeamModal);
    }

    var convMeta = $("chat-page-conv-meta");
    if (convMeta) {
      convMeta.addEventListener("click", function () {
        if (!convMeta.classList.contains("chat-page-conv-meta--clickable")) return;
        var tkey = convMeta.dataset.threadKey || "";
        if (tkey) {
          openMembersModal(tkey);
          return;
        }
        var pid = parseInt(convMeta.dataset.projectId || "", 10);
        if (!isNaN(pid)) openTeamModal(pid);
      });
    }

    var lbClose = $("chat-page-lightbox-close");
    var lb = $("chat-page-lightbox");
    if (lbClose) lbClose.addEventListener("click", closeLightbox);
    if (lb) {
      lb.addEventListener("click", function (e) {
        if (e.target === lb) closeLightbox();
      });
    }

    wireDirectMessageModal();
    wireGroupModal();

    var syncDeptBtn = $("chat-page-sync-dept-btn");
    if (syncDeptBtn) {
      syncDeptBtn.addEventListener("click", function () {
        fetch("/admin/chat/departments/sync", { method: "POST", credentials: "same-origin" })
          .then(function (res) {
            return res.json();
          })
          .then(function () {
            return loadThreads();
          })
          .catch(function () {});
      });
    }

    window.ChatPageConference = {
      getActiveThread: activeThread,
      getMemberAccountIds: function () {
        var thread = activeThread();
        var key = activeStorageKey();
        if (!thread) return [];
        if (isDirectThread(thread) && thread.other_account_id != null) {
          return [thread.other_account_id];
        }
        if (isProjectThread(thread) && thread.project_id != null) {
          var team = ChatPageState.teamByProject[thread.project_id] || [];
          var teamIds = team
            .map(function (m) {
              return m.account_id;
            })
            .filter(function (id) {
              return id != null;
            });
          if (teamIds.length) return teamIds;
        }
        var members = key != null ? ChatPageState.membersByThread[key] || [] : [];
        var ids = members
          .map(function (m) {
            return m.account_id;
          })
          .filter(function (id) {
            return id != null;
          });
        return ids;
      },
      refresh: function () {
        var key = activeStorageKey();
        if (key == null) return Promise.resolve();
        return loadThreads().then(function () {
          return loadMessages(key, { reset: true });
        });
      },
    };
    if (window.ChatConferenceUI && window.ChatConferenceUI.init) {
      window.ChatConferenceUI.init();
    }

    loadThreads().then(function () {
      var selectedKey = resolveInitialSelection();
      if (selectedKey != null) {
        var msgRaw = ChatPageState.root.getAttribute("data-initial-message-id");
        var mid = msgRaw ? parseInt(msgRaw, 10) : NaN;
        var urlParams = new URLSearchParams(window.location.search);
        if (isNaN(mid)) {
          mid = parseInt(urlParams.get("message_id") || "", 10);
        }
        if (!isNaN(mid)) {
          jumpToMessage(selectedKey, mid);
          return;
        }
        var confId = parseInt(urlParams.get("conference_id") || "", 10);
        if (!isNaN(confId)) {
          loadMessages(selectedKey, { reset: true }).then(function () {
            var el = document.querySelector('[data-conference-id="' + confId + '"]');
            if (el && typeof el.scrollIntoView === "function") {
              el.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
          });
        }
      }
    });

    ChatPageState.pollTimer = window.setInterval(function () {
      loadThreads();
    }, POLL_MS);

    if (window.__tmSocket) {
      wireSocket();
    } else {
      var tries = 0;
      var iv = window.setInterval(function () {
        tries++;
        if (window.__tmSocket) {
          window.clearInterval(iv);
          wireSocket();
        } else if (tries > 50) {
          window.clearInterval(iv);
        }
      }, 200);
    }

    window.addEventListener("hashchange", function () {
      var m = /^gchat-(\d+)$/.exec((window.location.hash || "").replace(/^#/, ""));
      if (m) {
        var id = parseInt(m[1], 10);
        if (!isNaN(id)) {
          var hkey = storageKeyForProjectId(id);
          if (ChatPageState.threadsMap[hkey]) selectThreadKey(hkey);
        }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
