/**
 * Tasks list: debounced search, client filters/sort, inspector panel (no list innerHTML wipes).
 */
(function () {
  "use strict";

  var stream;
  var searchEl;
  var projectEl;
  var userEl;
  var statusEl;
  var sortEl;
  var parking;
  var activeRow = null;
  var inspectorWrap = null;
  var debounceTimer = null;

  function debounce(fn, ms) {
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        fn.apply(ctx, args);
      }, ms);
    };
  }

  function rows() {
    return stream ? Array.prototype.slice.call(stream.querySelectorAll(".tm-task-line")) : [];
  }

  function populateFilterOptions() {
    if (!projectEl || !userEl) return;
    var projects = {};
    var users = {};
    rows().forEach(function (row) {
      var p = row.dataset.project || "";
      if (p && projects[p] === undefined) {
        projects[p] = row.dataset.projectLabel || p;
      }
      var u = row.dataset.user || "";
      if (u && users[u] === undefined) {
        users[u] = row.dataset.userLabel || u;
      }
    });
    var pKeep = projectEl.value;
    while (projectEl.options.length > 1) projectEl.remove(1);
    Object.keys(projects)
      .sort()
      .forEach(function (p) {
        var o = document.createElement("option");
        o.value = p;
        o.textContent = projects[p];
        projectEl.appendChild(o);
      });
    if (pKeep && Object.prototype.hasOwnProperty.call(projects, pKeep)) projectEl.value = pKeep;

    var uKeep = userEl.value;
    while (userEl.options.length > 1) userEl.remove(1);
    Object.keys(users)
      .sort()
      .forEach(function (u) {
        var o = document.createElement("option");
        o.value = u;
        o.textContent = users[u];
        userEl.appendChild(o);
      });
    if (uKeep && Object.prototype.hasOwnProperty.call(users, uKeep)) userEl.value = uKeep;
  }

  function rowMatches(row) {
    var q = (searchEl && searchEl.value.trim().toLowerCase()) || "";
    if (q) {
      var hay = (row.dataset.search || "").toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    var fp = projectEl && projectEl.value;
    if (fp && (row.dataset.project || "") !== fp) return false;
    var fu = userEl && userEl.value;
    if (fu && (row.dataset.user || "") !== fu) return false;
    var fs = statusEl && statusEl.value;
    if (fs && (row.dataset.status || "") !== fs) return false;
    return true;
  }

  function applyFilters() {
    if (!stream) return;
    rows().forEach(function (row) {
      var ok = rowMatches(row);
      row.hidden = !ok;
      row.setAttribute("aria-hidden", ok ? "false" : "true");
    });
  }

  function sortRows() {
    if (!stream || !sortEl) return;
    var sort = sortEl.value;
    var list = rows();
    list.sort(function (a, b) {
      if (sort === "priority") {
        var pr =
          (parseInt(b.dataset.priorityRank, 10) || 0) - (parseInt(a.dataset.priorityRank, 10) || 0);
        if (pr !== 0) return pr;
      }
      return (parseInt(b.dataset.createdMs, 10) || 0) - (parseInt(a.dataset.createdMs, 10) || 0);
    });
    list.forEach(function (r) {
      stream.appendChild(r);
    });
  }

  function restoreActionsToRow() {
    if (!activeRow || !inspectorWrap) return;
    var act = inspectorWrap.querySelector(".tm-task-line-actions");
    if (act) {
      act.hidden = true;
      act.setAttribute("aria-hidden", "true");
      activeRow.appendChild(act);
    }
    inspectorWrap = null;
    if (activeRow) activeRow.classList.remove("is-active");
    activeRow = null;
  }

  function openTaskInspector(row) {
    if (!window.tmShell || !row) return;
    if (activeRow === row && inspectorWrap) return;

    restoreActionsToRow();

    var titleEl = row.querySelector(".task-item-title");
    var title = titleEl ? titleEl.textContent.trim() : "Task";

    var wrap = document.createElement("div");
    wrap.className = "tm-task-inspector";

    var body = document.createElement("div");
    body.className = "tm-task-inspector-body";

    function addRow(label, node) {
      var d = document.createElement("div");
      d.className = "tm-task-inspector-kv";
      var lab = document.createElement("span");
      lab.className = "tm-task-inspector-k";
      lab.textContent = label;
      var val = document.createElement("div");
      val.className = "tm-task-inspector-v";
      if (typeof node === "string") {
        val.textContent = node;
      } else if (node) {
        val.appendChild(node);
      }
      d.appendChild(lab);
      d.appendChild(val);
      body.appendChild(d);
    }

    var desc = row.querySelector(".tm-task-desc");
    addRow(
      "Task",
      document.createTextNode(title)
    );
    addRow(
      "Details",
      desc ? document.createTextNode(desc.textContent.trim()) : "—"
    );

    var projLink = row.querySelector(".tm-task-line-project a");
    if (projLink) {
      var a = projLink.cloneNode(true);
      a.className = "tm-task-inspector-link";
      addRow("Project", a);
    } else {
      addRow("Project", "—");
    }

    var userCol = row.querySelector(".tm-task-line-user span");
    addRow("User", userCol ? userCol.textContent.trim() : "—");

    var st = row.querySelector(".tm-task-line-status .tm-task-status");
    addRow("Status", st ? st.textContent.trim() : "—");

    var pr = row.querySelector(".tm-task-line-priority .task-priority");
    addRow("Priority", pr ? pr.textContent.trim() : "—");

    wrap.appendChild(body);

    var act = row.querySelector(".tm-task-line-actions");
    if (act) {
      act.hidden = false;
      act.removeAttribute("aria-hidden");
      var actionsShell = document.createElement("div");
      actionsShell.className = "tm-task-inspector-actions";
      actionsShell.appendChild(act);
      wrap.appendChild(actionsShell);
    }

    activeRow = row;
    inspectorWrap = wrap;
    row.classList.add("is-active");

    window.tmShell.openInspector({
      title: "Task details",
      el: wrap,
      parking: parking,
    });
  }

  window.__tmInspectorBeforeClose = function () {
    restoreActionsToRow();
  };

  function onRowClick(e) {
    if (e.target.closest("a")) return;
    var row = e.currentTarget;
    openTaskInspector(row);
  }

  function init() {
    var root = document.getElementById("tasks-page-root");
    stream = document.getElementById("tm-task-stream");
    if (!root || !stream) return;

    searchEl = document.getElementById("tasks-filter-search");
    projectEl = document.getElementById("tasks-filter-project");
    userEl = document.getElementById("tasks-filter-user");
    statusEl = document.getElementById("tasks-filter-status");
    sortEl = document.getElementById("tasks-filter-sort");
    parking = document.getElementById("tasks-inspector-parking");

    populateFilterOptions();

    rows().forEach(function (row) {
      row.addEventListener("click", onRowClick);
      row.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          if (e.target.closest("a")) return;
          e.preventDefault();
          openTaskInspector(row);
        }
      });
      row.setAttribute("tabindex", "0");
    });

    var debouncedSearch = debounce(function () {
      applyFilters();
      sortRows();
    }, 300);

    if (searchEl) {
      searchEl.addEventListener("input", debouncedSearch);
    }
    function onDiscreteFilterChange() {
      applyFilters();
      sortRows();
    }
    [projectEl, userEl, statusEl].forEach(function (el) {
      if (el) el.addEventListener("change", onDiscreteFilterChange);
    });
    if (sortEl) sortEl.addEventListener("change", onDiscreteFilterChange);

    onDiscreteFilterChange();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
