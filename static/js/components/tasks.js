/**
 * Derived state + DOM task rows (diff updates, no search bar touched).
 */
(function (global) {
  "use strict";

  global.TM = global.TM || {};

  function statusLabel(st) {
    return String(st || "").replace(/_/g, " ");
  }

  function priorityRank(v) {
    if (v === "high") {
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

  global.TM.sortTasksByField = function (tasks, key, direction) {
    var copy = tasks.slice();
    copy.sort(function (a, b) {
      var av;
      var bv;
      if (key === "task") {
        av = (a.title || "").toLowerCase();
        bv = (b.title || "").toLowerCase();
      } else if (key === "project") {
        av = (a.projectName || "").toLowerCase();
        bv = (b.projectName || "").toLowerCase();
      } else if (key === "user") {
        av = (a.userName || "").toLowerCase();
        bv = (b.userName || "").toLowerCase();
      } else if (key === "status") {
        av = (a.status || "").toLowerCase();
        bv = (b.status || "").toLowerCase();
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
    if (q) {
      filtered = base.filter(function (t) {
        var hay =
          ((t.title || "") + " " + (t.projectName || "") + " " + (t.userName || "")).toLowerCase();
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

  global.TM.mapApiTasksToRows = function (tasks, controlPanelPath) {
    var base = String(controlPanelPath || "/control").replace(/\/?$/, "");
    return (tasks || []).map(function (t) {
      var p = t.project;
      var u = t.user;
      var pid = t.id;
      return {
        id: pid,
        title: t.title || "",
        status: t.status,
        priority: t.priority || "medium",
        projectName: p && p.name ? p.name : "No project",
        userName: u && u.name ? u.name : "",
        updateUrl: base + "/tasks/" + pid + "/update",
        deleteUrl: base + "/tasks/" + pid + "/delete",
      };
    });
  };

  function buildTaskRowElement(t, nextUrl) {
    var pnm = t.projectName || "No project";
    var unm = t.userName || "";
    var pri = t.priority || "medium";
    var st = t.status || "";
    var row = document.createElement("div");
    row.className = "task-row";
    row.setAttribute("data-task-id", String(t.id));
    row.setAttribute("data-task", (t.title || "").toLowerCase());
    row.setAttribute("data-project", pnm.toLowerCase());
    row.setAttribute("data-user", unm.toLowerCase());
    row.setAttribute("data-status", st.toLowerCase());
    row.setAttribute("data-priority", String(pri).toLowerCase());

    var c1 = document.createElement("div");
    c1.className = "task-col task-name";
    c1.textContent = t.title || "";
    row.appendChild(c1);

    var c2 = document.createElement("div");
    c2.className = "task-col";
    c2.textContent = pnm;
    row.appendChild(c2);

    var c3 = document.createElement("div");
    c3.className = "task-col";
    c3.textContent = unm;
    row.appendChild(c3);

    var c4 = document.createElement("div");
    c4.className = "task-col";
    var sb = document.createElement("span");
    sb.className = "admin-badge admin-badge--status admin-badge--status-" + st;
    sb.textContent = statusLabel(st);
    c4.appendChild(sb);
    row.appendChild(c4);

    var c5 = document.createElement("div");
    c5.className = "task-col";
    var pb = document.createElement("span");
    pb.className = "admin-badge admin-badge--priority admin-badge--priority-" + pri;
    pb.textContent = pri;
    c5.appendChild(pb);
    row.appendChild(c5);

    var c6 = document.createElement("div");
    c6.className = "task-col actions";
    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn--small admin-task-edit";
    editBtn.setAttribute("data-task-id", String(t.id));
    editBtn.setAttribute("data-task-title", t.title || "");
    editBtn.setAttribute("data-task-status", st);
    editBtn.setAttribute("data-task-priority", pri);
    editBtn.setAttribute("data-update-url", t.updateUrl);
    editBtn.setAttribute("data-next-url", nextUrl);
    editBtn.textContent = "Edit";
    c6.appendChild(editBtn);

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
    c6.appendChild(form);
    row.appendChild(c6);

    return row;
  }

  function patchTaskRowElement(row, t, nextUrl) {
    var pnm = t.projectName || "No project";
    var unm = t.userName || "";
    var pri = t.priority || "medium";
    var st = t.status || "";
    row.setAttribute("data-task", (t.title || "").toLowerCase());
    row.setAttribute("data-project", pnm.toLowerCase());
    row.setAttribute("data-user", unm.toLowerCase());
    row.setAttribute("data-status", st.toLowerCase());
    row.setAttribute("data-priority", String(pri).toLowerCase());

    var ch = row.children;
    if (ch[0]) {
      ch[0].textContent = t.title || "";
    }
    if (ch[1]) {
      ch[1].textContent = pnm;
    }
    if (ch[2]) {
      ch[2].textContent = unm;
    }

    var sb = row.querySelector(".admin-badge--status");
    if (sb) {
      sb.className = "admin-badge admin-badge--status admin-badge--status-" + st;
      sb.textContent = statusLabel(st);
    }
    var pb = row.querySelector(".admin-badge--priority");
    if (pb) {
      pb.className = "admin-badge admin-badge--priority admin-badge--priority-" + pri;
      pb.textContent = pri;
    }

    var editBtn = row.querySelector(".admin-task-edit");
    if (editBtn) {
      editBtn.setAttribute("data-task-title", t.title || "");
      editBtn.setAttribute("data-task-status", st);
      editBtn.setAttribute("data-task-priority", pri);
      editBtn.setAttribute("data-update-url", t.updateUrl);
      editBtn.setAttribute("data-next-url", nextUrl);
    }
    var form = row.querySelector("form.inline");
    if (form) {
      form.action = t.deleteUrl;
      var nx = form.querySelector('input[name="next"]');
      if (nx) {
        nx.value = nextUrl;
      }
      form.setAttribute("data-confirm", 'Delete task "' + (t.title || "") + '"?');
    }
  }

  /**
   * Diff-update task rows only (preserves search input elsewhere in DOM).
   */
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
      if (countEl) {
        countEl.textContent = "";
      }
      if (navEl) {
        while (navEl.firstChild) {
          navEl.removeChild(navEl.firstChild);
        }
      }
      return;
    }

    if (s.error) {
      setMessage(msgEl, rowsEl, "Error: " + s.error, true);
      if (countEl) {
        countEl.textContent = "";
      }
      if (navEl) {
        while (navEl.firstChild) {
          navEl.removeChild(navEl.firstChild);
        }
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
