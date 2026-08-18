/**
 * Derived state + DOM task rows (diff updates, no search bar touched).
 */
(function (global) {
  "use strict";

  global.TM = global.TM || {};

  function statusLabel(st) {
    if (st === "open") return "Pending";
    if (st === "in_progress") return "In Progress";
    if (st === "done") return "Finished";
    return String(st || "").replace(/_/g, " ");
  }

  function conformResultLabel(result) {
    var r = (result || "").toLowerCase();
    if (r === "success") return "Success";
    if (r === "issues") return "Finished with issues";
    if (r === "failed") return "Failed";
    if (r === "pending") return "Pending";
    return result ? result.charAt(0).toUpperCase() + result.slice(1) : "—";
  }

  function priorityRank(v) {
    if (v === "high" || v === "urgent") {
      return 3;
    }
    if (v === "medium") {
      return 2;
    }
    if (v === "low") {
      return 1;
    }
    return 0;
  }

  function statusUrlFromTemplate(template, taskId) {
    var tpl = String(template || "/control/tasks/{id}/status");
    return tpl.replace("{id}", String(taskId));
  }

  global.TM.sortTasksByField = function (tasks, key, direction) {
    var copy = tasks.slice();
    copy.sort(function (a, b) {
      var av;
      var bv;
      if (key === "id") {
        av = Number(a.id) || 0;
        bv = Number(b.id) || 0;
        return direction === "asc" ? av - bv : bv - av;
      } else if (key === "task") {
        av = (a.title || "").toLowerCase();
        bv = (b.title || "").toLowerCase();
      } else if (key === "scope") {
        av = (a.scopeLabel || "").toLowerCase();
        bv = (b.scopeLabel || "").toLowerCase();
      } else if (key === "project") {
        av = (a.projectName || "").toLowerCase();
        bv = (b.projectName || "").toLowerCase();
      } else if (key === "editing_item") {
        av = (a.editingItemLabel || "").toLowerCase();
        bv = (b.editingItemLabel || "").toLowerCase();
      } else if (key === "requested_by") {
        av = (a.requestedByName || "").toLowerCase();
        bv = (b.requestedByName || "").toLowerCase();
      } else if (key === "user" || key === "assigned_to") {
        av = (a.userName || "").toLowerCase();
        bv = (b.userName || "").toLowerCase();
      } else if (key === "status") {
        av = (a.status || "").toLowerCase();
        bv = (b.status || "").toLowerCase();
      } else if (key === "due_date") {
        av = a.dueDate || "";
        bv = b.dueDate || "";
      } else if (key === "priority") {
        var ar = priorityRank(String(a.priority || "medium").toLowerCase());
        var br = priorityRank(String(b.priority || "medium").toLowerCase());
        if (ar !== br) {
          return direction === "asc" ? ar - br : br - ar;
        }
        return 0;
      } else {
        return 0;
      }
      if (av < bv) {
        return direction === "asc" ? -1 : 1;
      }
      if (av > bv) {
        return direction === "asc" ? 1 : -1;
      }
      return 0;
    });
    return copy;
  };

  global.TM.refreshAdminTasksDerived = function (state) {
    var base = state.tasks || [];
    var q = (state.searchQuery || "").trim().toLowerCase();
    var filtered = base;
    // Server applies search when query is non-empty; keep client filter for instant typing feedback.
    if (q) {
      filtered = base.filter(function (t) {
        var hay = (
          (t.title || "") +
          " " +
          (t.description || "") +
          " " +
          (t.projectName || "") +
          " " +
          (t.userName || "") +
          " " +
          (t.requestedByName || "") +
          " " +
          (t.scopeLabel || "") +
          " " +
          (t.scopeKey || "") +
          " " +
          (t.editingItemLabel || "") +
          " " +
          (t.status || "") +
          " " +
          (t.priority || "")
        ).toLowerCase();
        return hay.indexOf(q) !== -1;
      });
    }
    state.filteredTasks = state.sortBy
      ? global.TM.sortTasksByField(filtered, state.sortBy, state.sortOrder || "asc")
      : filtered.slice();
  };

  global.TM.getAdminTasksDerivedView = function (s) {
    var sorted = s.filteredTasks || [];
    var total = sorted.length;
    var per = s.pageSize || 20;
    var pageCount = Math.max(1, Math.ceil(total / per) || 1);
    var page = Math.min(Math.max(1, s.page || 1), pageCount);
    var start = (page - 1) * per;
    var slice = sorted.slice(start, start + per);
    return { slice: slice, total: total, pageCount: pageCount, page: page };
  };

  global.TM.buildAdminTasksNextUrl = function (s) {
    var p = new URLSearchParams();
    p.set("section", "all-tasks");
    if (s.taskStatus) {
      p.set("task_status", s.taskStatus);
    }
    if (s.searchQuery) {
      p.set("search", s.searchQuery);
    }
    if (s.scopeKey) {
      p.set("scope", s.scopeKey);
    }
    if (s.projectId) {
      p.set("project_id", String(s.projectId));
    }
    if (s.requestedById) {
      p.set("requested_by_id", String(s.requestedById));
    }
    if (s.assignedToId) {
      p.set("assigned_to_id", String(s.assignedToId));
    }
    if (s.priority) {
      p.set("priority", s.priority);
    }
    if (s.dueFrom) {
      p.set("due_from", s.dueFrom);
    }
    if (s.dueTo) {
      p.set("due_to", s.dueTo);
    }
    if (s.includeCompleted === false) {
      p.set("include_completed", "0");
    }
    p.set("page", String(s.page));
    if (s.sortBy) {
      p.set("sort", s.sortBy);
      p.set("direction", s.sortOrder || "asc");
    }
    var base = s.controlPanelPath || "/control";
    var q = p.toString();
    if (!q) {
      return base;
    }
    return base + (base.indexOf("?") >= 0 ? "&" : "?") + q;
  };

  global.TM.mapApiTasksToRows = function (tasks, controlPanelPath, statusUrlTemplate) {
    var base = String(controlPanelPath || "/control").replace(/\/?$/, "");
    var statusTpl = statusUrlTemplate || base + "/tasks/{id}/status";
    return (tasks || []).map(function (t) {
      var p = t.project;
      var u = t.assigned_to || t.user;
      var requester = t.requested_by;
      var item = t.editing_item;
      var pid = t.id;
      var itemLabel = "—";
      if (item) {
        itemLabel = (item.code || "").trim();
        if (item.title) {
          itemLabel = itemLabel ? itemLabel + " — " + item.title : item.title;
        }
        if (t.conform_handoff_label) {
          itemLabel = itemLabel + " · " + t.conform_handoff_label;
        }
      }
      return {
        id: pid,
        title: t.title || "",
        description: t.description || "",
        status: t.status,
        priority: t.priority || "medium",
        scopeLabel: t.post_scope_label || "Unassigned",
        scopeKey: t.post_scope_key || "",
        projectName: p && p.name ? p.name : "No project",
        editingItemLabel: itemLabel,
        requestedByName: requester && requester.name ? requester.name : "—",
        userName: u && u.name ? u.name : "",
        dueDate: t.due_date || "—",
        conformResult: t.conform_result || "",
        conformReason: t.conform_reason || "",
        isConformRequest: !!t.is_conform_request,
        conformStatusUrl: t.conform_status_url || "/api/tasks/" + pid + "/conform-status",
        conformFailedUrl: t.conform_failed_url || "/conform-tasks/" + pid + "/fail",
        updateUrl: base + "/tasks/" + pid + "/update",
        statusUpdateUrl: statusUrlFromTemplate(statusTpl, pid),
        deleteUrl: base + "/tasks/" + pid + "/delete",
      };
    });
  };

  function appendCol(row, className, content) {
    var col = document.createElement("div");
    col.className = "task-col" + (className ? " " + className : "");
    if (typeof content === "string") {
      col.textContent = content;
    } else if (content) {
      col.appendChild(content);
    }
    row.appendChild(col);
    return col;
  }

  function buildTaskTitleCell(t) {
    var wrap = document.createElement("div");
    wrap.textContent = t.title || "";
    if (t.conformReason) {
      var reason = document.createElement("span");
      reason.className = "task-conform-reason";
      reason.textContent = t.conformReason;
      wrap.appendChild(reason);
    }
    return wrap;
  }

  function buildStatusSelect(t) {
    var wrap = document.createElement("div");
    wrap.className = "admin-task-inline-status";
    var sel = document.createElement("select");
    var statuses = t.isConformRequest
      ? ["open", "in_progress", "done"]
      : ["open", "in_progress", "done"];
    if (t.isConformRequest) {
      sel.className = "admin-task-status-select conform-status-select";
      sel.setAttribute("data-conform-task-id", String(t.id));
      sel.setAttribute("data-conform-status-url", t.conformStatusUrl || "");
      sel.setAttribute("data-last-committed", t.status || "open");
    } else {
      sel.className = "admin-task-status-select";
    }
    sel.setAttribute("aria-label", "Change status for " + (t.title || "task"));
    statuses.forEach(function (st) {
      var opt = document.createElement("option");
      opt.value = st;
      opt.textContent = statusLabel(st);
      if ((t.status || "") === st) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    wrap.appendChild(sel);
    if (!t.isConformRequest) {
      var saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "btn btn--small btn--ghost admin-task-status-save";
      saveBtn.textContent = "Save";
      saveBtn.setAttribute("data-status-url", t.statusUpdateUrl || "");
      wrap.appendChild(saveBtn);
    }
    return wrap;
  }

  function buildTaskRowElement(t, nextUrl) {
    var row = document.createElement("div");
    row.className = "task-row";
    row.setAttribute("data-task-id", String(t.id));

    appendCol(row, "task-id", t.id != null ? "#" + String(t.id) : "—");
    appendCol(row, "task-name", buildTaskTitleCell(t));
    appendCol(row, "", t.scopeLabel || "Unassigned");
    appendCol(row, "", t.projectName || "No project");
    appendCol(row, "", t.editingItemLabel || "—");
    appendCol(row, "", t.requestedByName || "—");
    appendCol(row, "", t.userName || "");
    appendCol(row, "", buildStatusSelect(t));
    var resultLabel = t.conformResult
      ? conformResultLabel(t.conformResult)
      : t.isConformRequest
        ? "Pending"
        : "—";
    appendCol(row, "", resultLabel);
    var pri = t.priority || "medium";
    var pb = document.createElement("span");
    pb.className = "admin-badge admin-badge--priority admin-badge--priority-" + pri;
    pb.textContent = pri;
    appendCol(row, "", pb);
    appendCol(row, "", t.dueDate || "—");

    var actions = document.createElement("div");
    actions.className = "task-col actions";
    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn--small admin-task-edit";
    editBtn.setAttribute("data-task-id", String(t.id));
    editBtn.setAttribute("data-task-title", t.title || "");
    editBtn.setAttribute("data-task-status", t.status || "");
    editBtn.setAttribute("data-task-priority", pri);
    editBtn.setAttribute("data-update-url", t.updateUrl);
    editBtn.setAttribute("data-next-url", nextUrl);
    editBtn.textContent = "Edit";
    actions.appendChild(editBtn);
    var form = document.createElement("form");
    form.method = "post";
    form.action = t.deleteUrl;
    form.className = "inline";
    form.setAttribute("data-confirm", 'Delete task "' + (t.title || "") + '"?');
    var hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "next";
    hidden.value = nextUrl;
    form.appendChild(hidden);
    var delBtn = document.createElement("button");
    delBtn.type = "submit";
    delBtn.className = "btn btn--small btn--danger";
    delBtn.textContent = "Delete";
    form.appendChild(delBtn);
    actions.appendChild(form);
    row.appendChild(actions);

    return row;
  }

  function patchTaskRowElement(row, t, nextUrl) {
    var ch = row.children;
    if (ch[0]) ch[0].textContent = t.id != null ? "#" + String(t.id) : "—";
    if (ch[1]) {
      ch[1].innerHTML = "";
      ch[1].appendChild(buildTaskTitleCell(t));
    }
    if (ch[2]) ch[2].textContent = t.scopeLabel || "Unassigned";
    if (ch[3]) ch[3].textContent = t.projectName || "No project";
    if (ch[4]) ch[4].textContent = t.editingItemLabel || "—";
    if (ch[5]) ch[5].textContent = t.requestedByName || "—";
    if (ch[6]) ch[6].textContent = t.userName || "";
    if (ch[8]) {
      var resultLabel = t.conformResult
        ? conformResultLabel(t.conformResult)
        : t.hasConformChecklist
          ? "Pending"
          : "—";
      ch[8].textContent = resultLabel;
    }
    if (ch[9]) {
      var pb = ch[9].querySelector(".admin-badge--priority");
      var pri = t.priority || "medium";
      if (pb) {
        pb.className = "admin-badge admin-badge--priority admin-badge--priority-" + pri;
        pb.textContent = pri;
      }
    }
    if (ch[10]) ch[10].textContent = t.dueDate || "—";

    var editBtn = row.querySelector(".admin-task-edit");
    if (editBtn) {
      editBtn.setAttribute("data-task-title", t.title || "");
      editBtn.setAttribute("data-task-status", t.status || "");
      editBtn.setAttribute("data-task-priority", t.priority || "medium");
      editBtn.setAttribute("data-update-url", t.updateUrl);
      editBtn.setAttribute("data-next-url", nextUrl);
    }
    var form = row.querySelector("form.inline");
    if (form) {
      form.action = t.deleteUrl;
      var nx = form.querySelector('input[name="next"]');
      if (nx) nx.value = nextUrl;
      form.setAttribute("data-confirm", 'Delete task "' + (t.title || "") + '"?');
    }
    var sel = row.querySelector(".admin-task-status-select");
    if (sel) sel.value = t.status || "open";
  }

  global.TM.renderTasks = function (container, slice, urlState) {
    if (!container) {
      return;
    }
    var nextUrl = global.TM.buildAdminTasksNextUrl(urlState);
    var want = {};
    for (var i = 0; i < slice.length; i++) {
      want[String(slice[i].id)] = slice[i];
    }

    var existing = container.querySelectorAll(".task-row[data-task-id]");
    for (var j = 0; j < existing.length; j++) {
      var el = existing[j];
      var id = el.getAttribute("data-task-id");
      if (!want[id]) {
        el.remove();
      }
    }

    for (var k = 0; k < slice.length; k++) {
      var t = slice[k];
      var idStr = String(t.id);
      var row = container.querySelector('.task-row[data-task-id="' + idStr + '"]');
      if (!row) {
        row = buildTaskRowElement(t, nextUrl);
        container.appendChild(row);
      } else {
        patchTaskRowElement(row, t, nextUrl);
      }
    }

    for (var n = 0; n < slice.length; n++) {
      var t2 = slice[n];
      var row2 = container.querySelector('.task-row[data-task-id="' + String(t2.id) + '"]');
      if (row2) {
        container.appendChild(row2);
      }
    }
  };

  function setMessage(msgEl, rowsEl, text, isError) {
    if (!msgEl || !rowsEl) {
      return;
    }
    if (text) {
      msgEl.hidden = false;
      msgEl.textContent = text;
      msgEl.className =
        "admin-tasks-message" + (isError ? " admin-tasks-message--error" : " muted");
      while (rowsEl.firstChild) {
        rowsEl.removeChild(rowsEl.firstChild);
      }
    } else {
      msgEl.hidden = true;
      msgEl.textContent = "";
    }
  }

  function syncPaginationNav(navEl, view) {
    if (!navEl) {
      return;
    }
    while (navEl.firstChild) {
      navEl.removeChild(navEl.firstChild);
    }
    if (view.page > 1) {
      var prev = document.createElement("button");
      prev.type = "button";
      prev.className = "btn btn--ghost btn--small";
      prev.setAttribute("data-admin-tasks-page", String(view.page - 1));
      prev.textContent = "← Prev";
      navEl.appendChild(prev);
    } else {
      var prevSp = document.createElement("span");
      prevSp.className = "btn btn--ghost btn--small admin-tasks-pagination__disabled";
      prevSp.setAttribute("aria-disabled", "true");
      prevSp.textContent = "← Prev";
      navEl.appendChild(prevSp);
    }
    var status = document.createElement("span");
    status.className = "muted admin-tasks-pagination__status";
    status.textContent = "Page " + view.page + " of " + (view.pageCount || 1);
    navEl.appendChild(status);
    if (view.page < view.pageCount) {
      var next = document.createElement("button");
      next.type = "button";
      next.className = "btn btn--ghost btn--small";
      next.setAttribute("data-admin-tasks-page", String(view.page + 1));
      next.textContent = "Next →";
      navEl.appendChild(next);
    } else {
      var nextSp = document.createElement("span");
      nextSp.className = "btn btn--ghost btn--small admin-tasks-pagination__disabled";
      nextSp.setAttribute("aria-disabled", "true");
      nextSp.textContent = "Next →";
      navEl.appendChild(nextSp);
    }
  }

  global.TM.renderAdminTaskListMeta = function (s) {
    var listSection = document.getElementById("admin-tasks-list");
    var msgEl = document.getElementById("admin-tasks-message");
    var rowsEl = document.getElementById("admin-tasks-rows");
    var countEl = document.getElementById("admin-tasks-count");
    var navEl = document.getElementById("admin-tasks-pagination");
    if (!listSection || !rowsEl) {
      return;
    }

    var view = global.TM.getAdminTasksDerivedView(s);
    if (view.page !== s.page) {
      global.TM.adminTasks.setState({ page: view.page }, { silent: true });
    }

    var urlState = Object.assign({}, s, { page: view.page });

    if (s.loading && !(s.tasks && s.tasks.length)) {
      setMessage(msgEl, rowsEl, "Loading…", false);
      if (countEl) countEl.textContent = "";
      if (navEl) {
        while (navEl.firstChild) navEl.removeChild(navEl.firstChild);
      }
      return;
    }

    if (s.error) {
      setMessage(msgEl, rowsEl, "Error: " + s.error, true);
      if (countEl) countEl.textContent = "";
      if (navEl) {
        while (navEl.firstChild) navEl.removeChild(navEl.firstChild);
      }
      return;
    }

    if (!view.slice.length) {
      setMessage(msgEl, rowsEl, "No tasks match your filter.", false);
      if (countEl) {
        countEl.textContent = "Showing 0 of " + (view.total || 0);
      }
      syncPaginationNav(navEl, view);
      return;
    }

    setMessage(msgEl, rowsEl, "", false);
    global.TM.renderTasks(rowsEl, view.slice, urlState);

    if (countEl) {
      countEl.textContent = "Showing " + view.slice.length + " of " + (view.total || 0);
    }
    syncPaginationNav(navEl, view);
  };
})(typeof window !== "undefined" ? window : global);
