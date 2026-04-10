/**
 * Wires admin All tasks: events, URL sync, modal. UI via state.subscribe → render.
 */
(function (global) {
  "use strict";

  global.TM = global.TM || {};

  var SEARCH_DEBOUNCE_MS = 300;
  var searchDebounce = null;
  var MAX_TASKS_FETCH = 1000;
  var viewSubscribed = false;

  function replaceUrlFromState() {
    var s = global.TM.adminTasks.getState();
    var url = global.TM.buildAdminTasksNextUrl(s);
    try {
      history.replaceState({}, "", url);
    } catch (e) {
      /* ignore */
    }
  }

  function loadBaseTasks() {
    var s = global.TM.adminTasks.getState();
    global.TM.adminTasks.setState({ loading: true, error: null });
    global.TM.api
      .getAdminTasks({
        apiUrl: s.apiUrl,
        status: s.taskStatus,
        search: "",
        limit: MAX_TASKS_FETCH,
        offset: 0,
      })
      .then(function (data) {
        if (!data || data.ok !== true) {
          throw new Error("Invalid task list response");
        }
        var mapped = global.TM.mapApiTasksToRows(data.tasks, s.controlPanelPath);
        global.TM.adminTasks.setState({
          tasks: mapped,
          loading: false,
          error: null,
        });
        replaceUrlFromState();
      })
      .catch(function (err) {
        global.TM.adminTasks.setState({
          loading: false,
          error: err.message || String(err),
        });
      });
  }

  global.TM.syncAdminFiltersUI = function (s) {
    var sel = document.getElementById("status-filter");
    var inp = document.getElementById("search-input");
    if (sel && sel.value !== (s.taskStatus || "")) {
      sel.value = s.taskStatus || "";
    }
    if (inp && document.activeElement !== inp) {
      inp.value = s.searchQuery || "";
    }
    document.querySelectorAll(".admin-tasks-sortbar .sort-btn").forEach(function (b) {
      var k = b.getAttribute("data-field") || "";
      var active = Boolean(s.sortBy && k === s.sortBy);
      var arrow = b.querySelector(".arrow");
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
      b.setAttribute("data-direction", active ? s.sortOrder : "");
      if (arrow) {
        arrow.textContent = active ? (s.sortOrder === "asc" ? "↑" : "↓") : "";
      }
    });
  };

  function bindViewPipeline() {
    if (viewSubscribed) {
      return;
    }
    viewSubscribed = true;
    global.TM.adminTasks.subscribe(function () {
      var p0 = global.TM.adminTasks.getState().page;
      var s = global.TM.adminTasks.getState();
      global.TM.syncAdminFiltersUI(s);
      global.TM.renderAdminTaskListMeta(s);
      if (global.TM.adminTasks.getState().page !== p0) {
        replaceUrlFromState();
      }
    });
  }

  function openEditModal(btn) {
    var modal = document.getElementById("admin-task-edit-modal");
    var editForm = document.getElementById("admin-task-edit-form");
    var editTitle = document.getElementById("admin-task-edit-title");
    var editStatus = document.getElementById("admin-task-edit-status");
    var editPriority = document.getElementById("admin-task-edit-priority");
    var editNext = document.getElementById("admin-task-edit-next");
    if (!modal || !editForm) {
      return;
    }
    editForm.action = btn.getAttribute("data-update-url") || "";
    if (editNext) {
      editNext.value = btn.getAttribute("data-next-url") || "";
    }
    if (editTitle) {
      editTitle.value = btn.getAttribute("data-task-title") || "";
    }
    if (editStatus) {
      editStatus.value = btn.getAttribute("data-task-status") || "open";
    }
    if (editPriority) {
      editPriority.value = btn.getAttribute("data-task-priority") || "medium";
    }
    try {
      modal.showModal();
    } catch (e) {
      modal.setAttribute("open", "");
    }
    setTimeout(function () {
      try {
        editTitle.focus();
      } catch (e2) {
        /* ignore */
      }
    }, 0);
  }

  function closeEditModal() {
    var modal = document.getElementById("admin-task-edit-modal");
    if (!modal) {
      return;
    }
    try {
      modal.close();
    } catch (e) {
      modal.removeAttribute("open");
    }
  }

  function bindAllTasksRoot() {
    var root = document.querySelector('[data-admin-panel="all-tasks"]');
    if (!root || root.getAttribute("data-tm-admin-tasks") === "1") {
      return;
    }
    root.setAttribute("data-tm-admin-tasks", "1");

    var closeBtn = document.getElementById("admin-task-edit-close");
    var modal = document.getElementById("admin-task-edit-modal");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeEditModal);
    }
    if (modal) {
      modal.addEventListener("click", function (e) {
        var r = modal.getBoundingClientRect();
        var inDialog =
          e.clientX >= r.left &&
          e.clientX <= r.right &&
          e.clientY >= r.top &&
          e.clientY <= r.bottom;
        if (!inDialog) {
          closeEditModal();
        }
      });
    }

    root.addEventListener("submit", function (e) {
      var f = e.target;
      if (!(f instanceof HTMLFormElement)) {
        return;
      }
      if (!root.contains(f)) {
        return;
      }
      var msg = f.getAttribute("data-confirm");
      if (msg && !global.confirm(msg)) {
        e.preventDefault();
      }
    });

    root.addEventListener("click", function (e) {
      var editBtn = e.target.closest(".admin-task-edit");
      if (editBtn && root.contains(editBtn)) {
        openEditModal(editBtn);
        return;
      }
      var pgBtn = e.target.closest("[data-admin-tasks-page]");
      if (pgBtn && root.contains(pgBtn)) {
        var p = parseInt(pgBtn.getAttribute("data-admin-tasks-page"), 10);
        if (!isNaN(p) && p > 0) {
          global.TM.adminTasks.setState({ page: p });
          replaceUrlFromState();
        }
      }
    });

    var statusFilter = document.getElementById("status-filter");
    var searchInput = document.getElementById("search-input");
    if (statusFilter) {
      statusFilter.addEventListener("change", function () {
        global.TM.adminTasks.setState({
          taskStatus: statusFilter.value || "",
          page: 1,
        });
        loadBaseTasks();
      });
    }
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        global.TM.adminTasks.setState(
          {
            searchQuery: searchInput.value,
            page: 1,
          },
          { silent: true }
        );
        if (searchDebounce) {
          global.clearTimeout(searchDebounce);
        }
        searchDebounce = global.setTimeout(function () {
          global.TM.adminTasks.setState({});
          replaceUrlFromState();
        }, SEARCH_DEBOUNCE_MS);
      });
    }

    document.querySelectorAll(".admin-tasks-sortbar .sort-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var s = global.TM.adminTasks.getState();
        var key = btn.getAttribute("data-field") || "";
        var nextOrder = "asc";
        if (s.sortBy === key) {
          nextOrder = s.sortOrder === "asc" ? "desc" : "asc";
        }
        global.TM.adminTasks.setState({
          sortBy: key,
          sortOrder: nextOrder,
        });
        replaceUrlFromState();
      });
    });
  }

  function handleSearchFocusParam() {
    var searchInput = document.getElementById("search-input");
    try {
      var params = new URLSearchParams(global.location.search || "");
      if (params.get("focus") !== "1" || !searchInput) {
        return;
      }
      global.addEventListener("load", function () {
        searchInput.focus();
        var val = searchInput.value;
        searchInput.value = "";
        searchInput.value = val;
        try {
          params.delete("focus");
          var next = global.location.pathname + "?" + params.toString() + global.location.hash;
          history.replaceState({}, "", next);
        } catch (e2) {
          /* ignore */
        }
      });
    } catch (e) {
      /* ignore */
    }
  }

  function initFromBoot() {
    var raw = document.getElementById("admin-tasks-boot");
    if (!raw) {
      return;
    }
    bindViewPipeline();
    bindAllTasksRoot();
    var boot = JSON.parse(raw.textContent);
    var sortBy = boot.sort && String(boot.sort).trim() ? boot.sort : null;
    global.TM.adminTasks.setState(
      {
        apiUrl: boot.apiUrl,
        controlPanelPath: boot.controlPanelPath,
        pageSize: boot.perPage || 20,
        taskStatus: boot.taskStatus || "",
        searchQuery: boot.search || "",
        page: boot.page || 1,
        sortBy: sortBy,
        sortOrder: boot.direction === "desc" ? "desc" : "asc",
        tasks: [],
        filteredTasks: [],
        loading: true,
        error: null,
      },
      { silent: true }
    );
    loadBaseTasks();
    handleSearchFocusParam();
  }

  document.addEventListener("DOMContentLoaded", initFromBoot);
})(typeof window !== "undefined" ? window : global);
