/**
 * Tasks list: debounced search, client filters/sort, inspector panel.
 * Row clicks use delegation on #tasks-page-root so list HTML can be replaced (realtime).
 */
(function () {
  "use strict";

  var root = null;
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

  function isMrTaskStreamRoot() {
    return !!(root && root.getAttribute("data-tm-mr-task-stream") === "1");
  }

  function rowCssSelector() {
    return isMrTaskStreamRoot() ? ".task-item" : ".tm-task-line";
  }

  function filteredOutClass() {
    return isMrTaskStreamRoot() ? "task-item--filtered-out" : "tm-task-line--filtered-out";
  }

  function bindRefs() {
    if (!root) return;
    stream = root.querySelector("#tm-task-stream");
    searchEl = root.querySelector("#tasks-filter-search");
    projectEl = root.querySelector("#tasks-filter-project");
    userEl = root.querySelector("#tasks-filter-user");
    statusEl = root.querySelector("#tasks-filter-status");
    sortEl = root.querySelector("#tasks-filter-sort");
    parking = root.querySelector("#tasks-inspector-parking");
  }

  function rows() {
    return stream ? Array.prototype.slice.call(stream.querySelectorAll(rowCssSelector())) : [];
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
    var hideCls = filteredOutClass();
    rows().forEach(function (row) {
      var ok = rowMatches(row);
      row.classList.toggle(hideCls, !ok);
      row.setAttribute("aria-hidden", ok ? "false" : "true");
      row.tabIndex = ok ? 0 : -1;
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
    if (isMrTaskStreamRoot()) return;
    if (!window.tmShell || !row) return;
    if (activeRow === row && inspectorWrap) return;

    restoreActionsToRow();
    bindRefs();

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
    var copyLive = row.getAttribute("data-is-copy") === "1" ? row.querySelector(".task-copy-live") : null;
    addRow("Task", document.createTextNode(title));
    addRow(
      "Details",
      copyLive
        ? document.createTextNode(copyLive.innerText.replace(/\s+/g, " ").trim())
        : desc
          ? document.createTextNode(desc.textContent.trim())
          : "—"
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

  function ensureRowTabIndexes() {
    rows().forEach(function (row) {
      row.setAttribute("tabindex", "0");
    });
  }

  function wireDelegationsOnce() {
    if (!root || root.getAttribute("data-tm-tasks-delegate") === "1") return;
    root.setAttribute("data-tm-tasks-delegate", "1");
    root.addEventListener("click", function (e) {
      if (isMrTaskStreamRoot()) return;
      var row = e.target.closest && e.target.closest(".tm-task-line");
      if (!row || !root.contains(row)) return;
      bindRefs();
      if (!stream || !stream.contains(row)) return;
      if (e.target.closest("a")) return;
      openTaskInspector(row);
    });
    root.addEventListener("keydown", function (e) {
      if (isMrTaskStreamRoot()) return;
      if (e.key !== "Enter" && e.key !== " ") return;
      var row = e.target.closest && e.target.closest(".tm-task-line");
      if (!row || !root.contains(row)) return;
      bindRefs();
      if (!stream || !stream.contains(row)) return;
      if (e.target.closest("a")) return;
      e.preventDefault();
      openTaskInspector(row);
    });
  }

  function wireFiltersOnce() {
    if (!root || root.getAttribute("data-tm-tasks-filters") === "1") return;
    root.setAttribute("data-tm-tasks-filters", "1");
    bindRefs();

    var debouncedSearch = debounce(function () {
      applyFilters();
      sortRows();
    }, 300);

    if (searchEl) {
      searchEl.addEventListener("input", debouncedSearch);
      searchEl.addEventListener("change", debouncedSearch);
    }
    function onDiscreteFilterChange() {
      applyFilters();
      sortRows();
    }
    [projectEl, userEl, statusEl].forEach(function (el) {
      if (el) el.addEventListener("change", onDiscreteFilterChange);
    });
    if (sortEl) sortEl.addEventListener("change", onDiscreteFilterChange);
  }

  function init() {
    root = document.getElementById("tasks-page-root");
    if (!root) return;
    wireDelegationsOnce();
    wireFiltersOnce();
    bindRefs();
    populateFilterOptions();
    if (stream) ensureRowTabIndexes();
    applyFilters();
    sortRows();
  }

  window.__tmTasksPageRefreshStream = function () {
    if (!root) root = document.getElementById("tasks-page-root");
    if (!root) return;
    /* Filter bar may have been replaced (e.g. realtime MR zone); re-attach listeners. */
    root.removeAttribute("data-tm-tasks-filters");
    wireFiltersOnce();
    bindRefs();
    populateFilterOptions();
    if (stream) ensureRowTabIndexes();
    applyFilters();
    sortRows();
  };

  document.addEventListener("DOMContentLoaded", init);
})();
