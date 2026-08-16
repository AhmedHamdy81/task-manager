(function () {
  "use strict";

  var JSON_ACCEPT = { Accept: "application/json", "Content-Type": "application/json" };

  function showError(el, msg) {
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  function todayISO() {
    var n = new Date();
    var y = n.getFullYear();
    var m = String(n.getMonth() + 1).padStart(2, "0");
    var d = String(n.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + d;
  }

  function parseISODateLocal(s) {
    if (!s || typeof s !== "string") return null;
    var p = s.slice(0, 10).split("-");
    if (p.length !== 3) return null;
    var y = parseInt(p[0], 10);
    var m = parseInt(p[1], 10) - 1;
    var d = parseInt(p[2], 10);
    if (!isFinite(y) || !isFinite(m) || !isFinite(d)) return null;
    return new Date(y, m, d);
  }

  function toISODateLocal(d) {
    return (
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0")
    );
  }

  function startOfMonthISOLocal(iso) {
    var d = parseISODateLocal(iso) || parseISODateLocal(todayISO());
    d.setDate(1);
    return toISODateLocal(d);
  }

  function endOfMonthISOLocal(iso) {
    var d = parseISODateLocal(iso) || parseISODateLocal(todayISO());
    d.setMonth(d.getMonth() + 1, 0);
    return toISODateLocal(d);
  }

  function addMonthsISOLocal(iso, n) {
    var d = parseISODateLocal(iso) || parseISODateLocal(todayISO());
    d.setMonth(d.getMonth() + n);
    return startOfMonthISOLocal(toISODateLocal(d));
  }

  function formatBookingForDashboard(b) {
    if (!b) return null;
    return {
      suite_name: b.suite_name || b.edit_suite_name || "Room",
      start_time: b.start_time,
      end_time: b.end_time,
      is_full_day: b.is_full_day,
      project_name: b.project_name || "",
      booked_for_name: b.booked_for_name || "",
      booking_date: b.booking_date,
    };
  }

  function pickBookingForDate(bookingsByDate, iso, viewerUid) {
    var list = bookingsByDate[iso] || [];
    if (!list.length) return null;
    if (viewerUid != null) {
      for (var i = 0; i < list.length; i++) {
        if (Number(list[i].booked_for_id) === Number(viewerUid)) return list[i];
      }
    }
    return list[0];
  }

  function wireFullDay(checkbox, endInput, endWrap) {
    if (!checkbox) return;
    function sync() {
      var on = checkbox.checked;
      if (endInput) {
        endInput.disabled = on;
        if (on) endInput.value = "23:59";
      }
      if (endWrap) endWrap.classList.toggle("is-muted", on);
    }
    checkbox.addEventListener("change", sync);
    sync();
  }

  function setMinDate(input) {
    if (!input) return;
    input.min = todayISO();
    if (input.value && input.value < input.min) input.value = input.min;
  }

  function remindersForDate(state, iso) {
    if (!state || !state.remindersByDate) return [];
    return state.remindersByDate[iso] || [];
  }

  function mergeRemindersByDate(reminders) {
    var byDate = {};
    (reminders || []).forEach(function (r) {
      var iso = String((r && (r.dueDate || r.due_date)) || "").slice(0, 10);
      if (!iso) return;
      if (!byDate[iso]) byDate[iso] = [];
      byDate[iso].push(r);
    });
    Object.keys(byDate).forEach(function (iso) {
      byDate[iso].sort(function (a, b) {
        return String(a.dueTime || "").localeCompare(String(b.dueTime || ""));
      });
    });
    return byDate;
  }

  function applyDashboardCalDayMarkers(day, iso, state) {
    var hasBooking = state.bookingsByDate[iso] && state.bookingsByDate[iso].length;
    var hasReminder = state.remindersByDate[iso] && state.remindersByDate[iso].length;
    if (hasBooking) day.classList.add("has-booking");
    if (hasReminder) day.classList.add("has-reminder");
  }

  function renderDashboardReminders(selectedIso, state) {
    var wrap = document.getElementById("dashboard-booking-reminders");
    var list = document.getElementById("dashboard-booking-reminders-list");
    var label = document.getElementById("db-booking-reminders-label");
    if (!wrap || !list) return;
    var rows = remindersForDate(state, selectedIso);
    list.textContent = "";
    if (!rows.length) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    if (label) {
      var dRem = parseISODateLocal(selectedIso);
      var remDayLabel = dRem
        ? dRem.toLocaleDateString(undefined, { month: "short", day: "numeric" })
        : selectedIso;
      label.textContent =
        selectedIso === todayISO() ? "Reminders today" : "Reminders on " + remDayLabel;
    }
    rows.forEach(function (r) {
      var li = document.createElement("li");
      li.className = "dashboard-booking-reminder-item";
      var text = document.createElement("span");
      text.className = "dashboard-booking-reminder-text";
      text.textContent = r.displayTitle || r.title || r.bodyPreview || r.body || "Reminder";
      li.appendChild(text);
      if (r.dueTime) {
        var time = document.createElement("span");
        time.className = "dashboard-booking-reminder-time";
        time.textContent = r.dueTime;
        li.appendChild(time);
      }
      list.appendChild(li);
    });
  }

  /** @param {HTMLElement} card */
  function renderDashboardBooking(card, payload) {
    if (!card) return;
    var filled = document.getElementById("dashboard-booking-filled");
    var empty = document.getElementById("dashboard-booking-empty");
    if (!filled || !empty) return;
    var b = payload && payload.booking;
    var selectedIso = (payload && payload.selectedDate) || todayISO();
    var state = card._dashCalState || payload || {};
    var emptyTitle = document.getElementById("db-booking-empty-title");
    if (!b) {
      filled.hidden = true;
      empty.hidden = false;
      if (emptyTitle) {
        var dEmpty = parseISODateLocal(selectedIso);
        var dayLabel = dEmpty
          ? dEmpty.toLocaleDateString(undefined, { month: "short", day: "numeric" })
          : selectedIso;
        emptyTitle.textContent =
          selectedIso === todayISO() ? "No booking today" : "No booking on " + dayLabel;
      }
    } else {
      filled.hidden = false;
      empty.hidden = true;
      var suite = document.getElementById("db-booking-suite");
      var time = document.getElementById("db-booking-time");
      var proj = document.getElementById("db-booking-project");
      var forEl = document.getElementById("db-booking-for");
      if (suite) suite.textContent = b.suite_name || "Room";
      if (time) {
        time.textContent =
          (b.start_time || "").slice(0, 5) +
          "–" +
          (b.end_time || "").slice(0, 5) +
          (b.is_full_day ? " · Full day" : "");
      }
      if (proj) proj.textContent = b.project_name || "";
      if (forEl) forEl.textContent = b.booked_for_name ? "For " + b.booked_for_name : "";
    }
    renderDashboardReminders(selectedIso, state);
  }

  function mergeDashboardBookings(payload, viewerUid) {
    var byDate = {};
    function add(b) {
      if (!b || !b.booking_date) return;
      if (viewerUid != null && Number(b.booked_for_id) !== Number(viewerUid)) return;
      var iso = String(b.booking_date).slice(0, 10);
      if (!byDate[iso]) byDate[iso] = [];
      byDate[iso].push(b);
    }
    (payload.bookings_mine || []).forEach(add);
    (payload.bookings_assigned || []).forEach(add);
    Object.keys(byDate).forEach(function (iso) {
      byDate[iso].sort(function (a, b) {
        return String(a.start_time || "").localeCompare(String(b.start_time || ""));
      });
    });
    return byDate;
  }

  function renderDashboardCalendar(card, state) {
    var host = document.getElementById("dashboard-booking-cal-host");
    if (!host) return;
    var anchor = parseISODateLocal(state.monthAnchor || todayISO());
    if (!anchor) return;
    var y = anchor.getFullYear();
    var m = anchor.getMonth();
    host.textContent = "";

    var head = document.createElement("div");
    head.className = "dashboard-booking-cal-head";
    var prev = document.createElement("button");
    prev.type = "button";
    prev.className = "dashboard-booking-cal-nav";
    prev.setAttribute("aria-label", "Previous month");
    prev.textContent = "‹";
    var title = document.createElement("span");
    title.className = "dashboard-booking-cal-title";
    title.textContent = anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    var todayBtn = document.createElement("button");
    todayBtn.type = "button";
    todayBtn.className = "dashboard-booking-cal-today btn btn--small btn--ghost";
    todayBtn.textContent = "Today";
    var next = document.createElement("button");
    next.type = "button";
    next.className = "dashboard-booking-cal-nav";
    next.setAttribute("aria-label", "Next month");
    next.textContent = "›";
    head.appendChild(prev);
    head.appendChild(title);
    head.appendChild(todayBtn);
    head.appendChild(next);
    host.appendChild(head);

    var grid = document.createElement("div");
    grid.className = "dashboard-booking-cal-grid";
    grid.setAttribute("role", "grid");
    grid.setAttribute("aria-label", "Month");
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach(function (dow) {
      var lab = document.createElement("div");
      lab.className = "dashboard-booking-cal-dow";
      lab.textContent = dow;
      grid.appendChild(lab);
    });

    var first = new Date(y, m, 1);
    var firstWeekday = first.getDay();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var daysInPrev = new Date(y, m, 0).getDate();
    var today = todayISO();
    for (var i = 0; i < 42; i++) {
      var day = document.createElement("button");
      day.type = "button";
      day.className = "dashboard-booking-cal-day";
      var dayNum = i - firstWeekday + 1;
      var realY = y;
      var realM = m;
      var realD = dayNum;
      if (dayNum < 1) {
        realM = m - 1;
        if (realM < 0) {
          realM = 11;
          realY = y - 1;
        }
        realD = daysInPrev + dayNum;
        day.classList.add("is-outside");
      } else if (dayNum > daysInMonth) {
        realM = m + 1;
        if (realM > 11) {
          realM = 0;
          realY = y + 1;
        }
        realD = dayNum - daysInMonth;
        day.classList.add("is-outside");
      }
      var iso =
        realY +
        "-" +
        String(realM + 1).padStart(2, "0") +
        "-" +
        String(realD).padStart(2, "0");
      day.textContent = String(realD);
      day.dataset.iso = iso;
      if (iso === state.selectedDate) day.classList.add("is-selected");
      if (iso === today) day.classList.add("is-today");
      applyDashboardCalDayMarkers(day, iso, state);
      day.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        state.selectedDate = this.dataset.iso || todayISO();
        renderDashboardCalendar(card, state);
        var picked = pickBookingForDate(state.bookingsByDate, state.selectedDate, state.viewerUid);
        renderDashboardBooking(card, {
          booking: formatBookingForDashboard(picked),
          selectedDate: state.selectedDate,
        });
      });
      grid.appendChild(day);
    }
    host.appendChild(grid);

    prev.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      state.monthAnchor = addMonthsISOLocal(state.monthAnchor, -1);
      card._dashCalState = state;
      fetchDashboardMonth(card, state);
    });
    next.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      state.monthAnchor = addMonthsISOLocal(state.monthAnchor, 1);
      card._dashCalState = state;
      fetchDashboardMonth(card, state);
    });
    todayBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      state.selectedDate = todayISO();
      state.monthAnchor = startOfMonthISOLocal(todayISO());
      card._dashCalState = state;
      fetchDashboardMonth(card, state);
    });
  }

  function finishDashboardMonth(card, state) {
    card._dashCalState = state;
    renderDashboardCalendar(card, state);
    var picked = pickBookingForDate(state.bookingsByDate, state.selectedDate, state.viewerUid);
    renderDashboardBooking(card, {
      booking: formatBookingForDashboard(picked),
      selectedDate: state.selectedDate,
    });
  }

  function fetchDashboardMonth(card, state) {
    var listUrl = card.getAttribute("data-list-url");
    var remindersUrl = card.getAttribute("data-reminders-url");
    var from = startOfMonthISOLocal(state.monthAnchor);
    var to = endOfMonthISOLocal(state.monthAnchor);
    if (!listUrl && !remindersUrl) {
      finishDashboardMonth(card, state);
      return;
    }
    var tasks = [];
    if (listUrl) {
      var bookingsUrl =
        listUrl +
        (listUrl.indexOf("?") >= 0 ? "&" : "?") +
        "from=" +
        encodeURIComponent(from) +
        "&to=" +
        encodeURIComponent(to);
      tasks.push(
        fetch(bookingsUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(function (j) {
            state.bookingsByDate = mergeDashboardBookings(j || {}, state.viewerUid);
          })
          .catch(function () {
            state.bookingsByDate = state.bookingsByDate || {};
          })
      );
    }
    if (remindersUrl) {
      var remUrl =
        remindersUrl +
        (remindersUrl.indexOf("?") >= 0 ? "&" : "?") +
        "from=" +
        encodeURIComponent(from) +
        "&to=" +
        encodeURIComponent(to);
      tasks.push(
        fetch(remUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(function (j) {
            var rows = (j && j.data && j.data.reminders) || [];
            state.remindersByDate = mergeRemindersByDate(rows);
          })
          .catch(function () {
            state.remindersByDate = state.remindersByDate || {};
          })
      );
    }
    Promise.all(tasks).then(function () {
      finishDashboardMonth(card, state);
    });
  }

  function createBookingRowShell() {
    var li = document.createElement("li");
    li.className = "booking-row-linear";
    var timeEl = document.createElement("div");
    timeEl.className = "booking-row-linear-time";
    timeEl.setAttribute("data-f", "time");
    var main = document.createElement("div");
    main.className = "booking-row-linear-main";
    var title = document.createElement("div");
    title.className = "booking-row-linear-title";
    title.setAttribute("data-f", "title");
    var sub = document.createElement("div");
    sub.className = "booking-row-linear-sub";
    sub.setAttribute("data-f", "sub");
    var meta = document.createElement("div");
    meta.className = "booking-row-linear-meta";
    meta.setAttribute("data-f", "meta");
    main.appendChild(title);
    main.appendChild(sub);
    main.appendChild(meta);
    var actions = document.createElement("div");
    actions.className = "booking-row-linear-actions";
    var status = document.createElement("span");
    status.className = "booking-pill booking-pill--ok";
    status.setAttribute("data-f", "status");
    status.textContent = "Booked";
    var more = document.createElement("div");
    more.className = "booking-booking-actions";
    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn--small btn--ghost";
    editBtn.setAttribute("data-book-act", "edit");
    editBtn.textContent = "⋯";
    editBtn.setAttribute("aria-label", "Edit");
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn btn--small btn--danger";
    cancelBtn.setAttribute("data-book-act", "cancel");
    cancelBtn.textContent = "Cancel";
    more.appendChild(editBtn);
    more.appendChild(cancelBtn);
    actions.appendChild(status);
    actions.appendChild(more);
    li.appendChild(timeEl);
    li.appendChild(main);
    li.appendChild(actions);
    return li;
  }

  function fillBookingRow(li, b) {
    li.setAttribute("data-booking-id", String(b.id));
    li.setAttribute("data-booking-date", b.booking_date || "");
    var timeEl = li.querySelector('[data-f="time"]');
    if (timeEl) {
      timeEl.textContent =
        (b.start_time || "").slice(0, 5) + "–" + (b.end_time || "").slice(0, 5);
    }
    var title = li.querySelector('[data-f="title"]');
    if (title) {
      title.textContent = (b.suite_name || "Room") + "  ·  " + (b.project_name || "—");
    }
    var sub = li.querySelector('[data-f="sub"]');
    if (sub) {
      var subLine = (b.booked_by_name || "—") + "  →  " + (b.booked_for_name || "—");
      if (b.job_type) subLine += " · " + b.job_type;
      if (b.scene_label) subLine += " · " + b.scene_label;
      sub.textContent = subLine;
    }
    var meta = li.querySelector('[data-f="meta"]');
    if (meta) {
      var nt = (b.notes || "").trim();
      meta.textContent = b.booking_date + (nt ? " · " + (nt.length > 60 ? nt.slice(0, 57) + "…" : nt) : "");
      meta.title = nt;
    }
    var st = li.querySelector('[data-f="status"]');
    if (st) {
      st.textContent = b.is_active ? "Booked" : "Cancelled";
      st.className = b.is_active ? "booking-pill booking-pill--ok" : "booking-pill booking-pill--muted";
    }
    li._bookingData = b;
  }

  /**
   * Incremental sync: append/update/remove rows only (no list innerHTML wipe).
   * @param {HTMLUListElement} ul
   * @param {object[]} rows
   * @param {{ onEdit?: function, onCancel?: function }} handlers
   */
  function renderBookings(ul, rows, handlers) {
    if (!ul) return;
    handlers = handlers || {};
    ul._rowMap = ul._rowMap || {};
    if (!ul._delegateAttached) {
      ul._delegateAttached = true;
      ul.addEventListener("click", function (e) {
        var act = e.target.closest("[data-book-act]");
        if (!act || !ul.contains(act)) return;
        var row = act.closest("[data-booking-id]");
        if (!row || !row._bookingData) return;
        var b = row._bookingData;
        if (act.getAttribute("data-book-act") === "edit" && handlers.onEdit) handlers.onEdit(b);
        if (act.getAttribute("data-book-act") === "cancel" && handlers.onCancel) handlers.onCancel(b);
      });
    }
    rows = rows || [];
    var next = {};
    rows.forEach(function (b) {
      next[String(b.id)] = true;
    });
    Object.keys(ul._rowMap).forEach(function (k) {
      if (!next[k]) {
        var li = ul._rowMap[k];
        if (li && li.parentNode === ul) ul.removeChild(li);
        delete ul._rowMap[k];
      }
    });
    rows.forEach(function (b) {
      var key = String(b.id);
      var li = ul._rowMap[key];
      if (!li) {
        li = createBookingRowShell();
        ul.appendChild(li);
        ul._rowMap[key] = li;
      }
      fillBookingRow(li, b);
    });
  }

  function createSuiteRowShell(admin) {
    var li = document.createElement("li");
    li.className = "booking-suite-row";
    var nameSpan = document.createElement("span");
    nameSpan.className = "booking-suite-row-name";
    nameSpan.setAttribute("data-f", "name");
    var statusSpan = document.createElement("span");
    statusSpan.setAttribute("data-f", "status");
    li.appendChild(nameSpan);
    li.appendChild(statusSpan);
    if (admin) {
      var actions = document.createElement("span");
      actions.className = "booking-suite-row-actions";
      var editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn--small btn--ghost";
      editBtn.setAttribute("data-suite-act", "edit");
      editBtn.textContent = "Edit";
      var delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn--small btn--danger";
      delBtn.setAttribute("data-suite-act", "delete");
      delBtn.textContent = "Delete";
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      li.appendChild(actions);
    }
    return li;
  }

  function fillSuiteRow(li, s) {
    li.setAttribute("data-suite-id", String(s.id));
    var nameEl = li.querySelector('[data-f="name"]');
    var stEl = li.querySelector('[data-f="status"]');
    if (nameEl) nameEl.textContent = s.name || "";
    if (stEl) {
      stEl.textContent = s.is_active ? "Active" : "Inactive";
      stEl.className = s.is_active ? "booking-pill booking-pill--ok" : "booking-pill booking-pill--muted";
    }
    var delBtn = li.querySelector('[data-suite-act="delete"]');
    if (delBtn) delBtn.disabled = !s.is_active;
    li._suiteData = s;
  }

  /**
   * @param {HTMLUListElement} listEl
   * @param {Array<{id:number,name:string,is_active:boolean}>} suites
   * @param {{ onEdit?: function, onDelete?: function, admin?: boolean }} opts
   */
  function renderSuites(listEl, suites, opts) {
    if (!listEl) return;
    opts = opts || {};
    listEl._suiteMap = listEl._suiteMap || {};
    if (opts.admin && !listEl._suiteDelegateAttached) {
      listEl._suiteDelegateAttached = true;
      listEl.addEventListener("click", function (e) {
        var act = e.target.closest("[data-suite-act]");
        if (!act || !listEl.contains(act)) return;
        var row = act.closest("[data-suite-id]");
        if (!row || !row._suiteData) return;
        var s = row._suiteData;
        if (act.getAttribute("data-suite-act") === "edit" && opts.onEdit) opts.onEdit(s);
        if (act.getAttribute("data-suite-act") === "delete" && opts.onDelete) opts.onDelete(s);
      });
    }
    suites = suites || [];
    var next = {};
    suites.forEach(function (s) {
      next[String(s.id)] = true;
    });
    Object.keys(listEl._suiteMap).forEach(function (k) {
      if (!next[k]) {
        var li = listEl._suiteMap[k];
        if (li && li.parentNode === listEl) listEl.removeChild(li);
        delete listEl._suiteMap[k];
      }
    });
    suites.forEach(function (s) {
      var key = String(s.id);
      var li = listEl._suiteMap[key];
      if (!li) {
        li = createSuiteRowShell(!!opts.admin);
        listEl.appendChild(li);
        listEl._suiteMap[key] = li;
      }
      fillSuiteRow(li, s);
    });
  }

  function fillSelect(sel, items, getValue, getLabel, placeholder) {
    if (!sel) return;
    var keep = document.createDocumentFragment();
    if (placeholder) {
      var ph = document.createElement("option");
      ph.value = "";
      ph.textContent = placeholder;
      keep.appendChild(ph);
    }
    (items || []).forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = String(getValue(it));
      opt.textContent = getLabel(it);
      keep.appendChild(opt);
    });
    sel.textContent = "";
    sel.appendChild(keep);
    try {
      sel.dispatchEvent(new CustomEvent("tm:options-updated", { bubbles: false }));
    } catch (e) {}
  }

  function initDashboardCard() {
    var card = document.getElementById("dashboard-booking-card");
    if (!card) return;
    var viewerUidParsed = parseInt(card.getAttribute("data-viewer-directory-user-id") || "", 10);
    var viewerUid = isNaN(viewerUidParsed) ? null : viewerUidParsed;
    var state = {
      monthAnchor: startOfMonthISOLocal(todayISO()),
      selectedDate: todayISO(),
      bookingsByDate: {},
      remindersByDate: {},
      viewerUid: viewerUid,
    };
    card._dashCalState = state;

    var calHost = document.getElementById("dashboard-booking-cal-host");
    if (calHost) {
      calHost.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    }

    var todayUrl = card.getAttribute("data-today-url");
    if (todayUrl) {
      fetch(todayUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (state.selectedDate === todayISO()) {
            renderDashboardBooking(card, {
              booking: formatBookingForDashboard(j && j.booking),
              selectedDate: state.selectedDate,
            });
          }
        })
        .catch(function () {
          /* keep server-rendered content */
        });
    }

    fetchDashboardMonth(card, state);
    initBookingRemind(card);
  }

  function renderRemindCalendar(host, state) {
    if (!host) return;
    var anchor = parseISODateLocal(state.monthAnchor || todayISO());
    if (!anchor) return;
    var y = anchor.getFullYear();
    var m = anchor.getMonth();
    host.textContent = "";

    var head = document.createElement("div");
    head.className = "dashboard-booking-cal-head";
    var prev = document.createElement("button");
    prev.type = "button";
    prev.className = "dashboard-booking-cal-nav";
    prev.setAttribute("aria-label", "Previous month");
    prev.textContent = "‹";
    var title = document.createElement("span");
    title.className = "dashboard-booking-cal-title";
    title.textContent = anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    var todayBtn = document.createElement("button");
    todayBtn.type = "button";
    todayBtn.className = "dashboard-booking-cal-today btn btn--small btn--ghost";
    todayBtn.textContent = "Today";
    var next = document.createElement("button");
    next.type = "button";
    next.className = "dashboard-booking-cal-nav";
    next.setAttribute("aria-label", "Next month");
    next.textContent = "›";
    head.appendChild(prev);
    head.appendChild(title);
    head.appendChild(todayBtn);
    head.appendChild(next);
    host.appendChild(head);

    var grid = document.createElement("div");
    grid.className = "dashboard-booking-cal-grid";
    grid.setAttribute("role", "grid");
    grid.setAttribute("aria-label", "Reminder date");
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach(function (dow) {
      var lab = document.createElement("div");
      lab.className = "dashboard-booking-cal-dow";
      lab.textContent = dow;
      grid.appendChild(lab);
    });

    var first = new Date(y, m, 1);
    var firstWeekday = first.getDay();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var daysInPrev = new Date(y, m, 0).getDate();
    var today = todayISO();
    for (var i = 0; i < 42; i++) {
      var day = document.createElement("button");
      day.type = "button";
      day.className = "dashboard-booking-cal-day";
      var dayNum = i - firstWeekday + 1;
      var realY = y;
      var realM = m;
      var realD = dayNum;
      if (dayNum < 1) {
        realM = m - 1;
        if (realM < 0) {
          realM = 11;
          realY = y - 1;
        }
        realD = daysInPrev + dayNum;
        day.classList.add("is-outside");
      } else if (dayNum > daysInMonth) {
        realM = m + 1;
        if (realM > 11) {
          realM = 0;
          realY = y + 1;
        }
        realD = dayNum - daysInMonth;
        day.classList.add("is-outside");
      }
      var iso =
        realY +
        "-" +
        String(realM + 1).padStart(2, "0") +
        "-" +
        String(realD).padStart(2, "0");
      day.textContent = String(realD);
      day.dataset.iso = iso;
      if (iso === state.selectedDate) day.classList.add("is-selected");
      if (iso === today) day.classList.add("is-today");
      if (iso < today) {
        day.disabled = true;
        day.classList.add("is-past");
      }
      day.addEventListener("click", function () {
        state.selectedDate = this.dataset.iso || todayISO();
        if (state.hiddenInput) state.hiddenInput.value = state.selectedDate;
        renderRemindCalendar(host, state);
      });
      grid.appendChild(day);
    }
    host.appendChild(grid);

    prev.addEventListener("click", function () {
      state.monthAnchor = addMonthsISOLocal(state.monthAnchor, -1);
      renderRemindCalendar(host, state);
    });
    next.addEventListener("click", function () {
      state.monthAnchor = addMonthsISOLocal(state.monthAnchor, 1);
      renderRemindCalendar(host, state);
    });
    todayBtn.addEventListener("click", function () {
      state.selectedDate = todayISO();
      state.monthAnchor = startOfMonthISOLocal(todayISO());
      if (state.hiddenInput) state.hiddenInput.value = state.selectedDate;
      renderRemindCalendar(host, state);
    });
  }

  function initBookingRemind(card) {
    var createUrl = card && card.getAttribute("data-remind-create-url");
    var openBtn = document.getElementById("dashboard-booking-remind-open");
    var dialog = document.getElementById("dashboard-booking-remind-dialog");
    var form = document.getElementById("dashboard-booking-remind-form");
    var textIn = document.getElementById("dashboard-booking-remind-text");
    var dateIn = document.getElementById("dashboard-booking-remind-date");
    var calHost = document.getElementById("dashboard-booking-remind-cal-host");
    var errEl = document.getElementById("dashboard-booking-remind-error");
    var submitBtn = document.getElementById("dashboard-booking-remind-submit");
    if (!createUrl || !openBtn || !dialog || !form) return;

    var remindState = {
      monthAnchor: startOfMonthISOLocal(todayISO()),
      selectedDate: todayISO(),
      hiddenInput: dateIn,
    };

    function showRemindError(msg) {
      showError(errEl, msg);
    }

    function resetRemindForm() {
      var dashState = card._dashCalState;
      var picked = (dashState && dashState.selectedDate) || todayISO();
      remindState.selectedDate = picked >= todayISO() ? picked : todayISO();
      remindState.monthAnchor = startOfMonthISOLocal(remindState.selectedDate);
      if (dateIn) dateIn.value = remindState.selectedDate;
      if (textIn) textIn.value = "";
      showRemindError("");
      renderRemindCalendar(calHost, remindState);
    }

    openBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      resetRemindForm();
      if (typeof dialog.showModal === "function") dialog.showModal();
      window.setTimeout(function () {
        if (textIn) textIn.focus();
      }, 50);
    });

    dialog.querySelectorAll("[data-booking-remind-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        dialog.close();
      });
    });
    dialog.addEventListener("click", function (ev) {
      if (ev.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", resetRemindForm);

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var text = (textIn && textIn.value || "").trim();
      var due = (dateIn && dateIn.value || "").trim();
      if (!text) {
        showRemindError("Enter reminder text.");
        if (textIn) textIn.focus();
        return;
      }
      if (!due || due < todayISO()) {
        showRemindError("Pick today or a future date.");
        return;
      }
      showRemindError("");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Saving…";
      }
      fetch(createUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: JSON_ACCEPT,
        body: JSON.stringify({
          body: text,
          due_date: due,
          is_pinned: "0",
        }),
      })
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error((j && j.message) || "Could not save reminder.");
            return j;
          });
        })
        .then(function () {
          dialog.close();
          if (card._dashCalState) fetchDashboardMonth(card, card._dashCalState);
        })
        .catch(function (err) {
          showRemindError(err.message || "Could not save reminder.");
        })
        .finally(function () {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = "Save reminder";
          }
        });
    });
  }

  function initBookingPage(root) {
    var listUrl = root.getAttribute("data-list-url") || "";
    var suitesUrl = root.getAttribute("data-suites-url") || "";
    var projectsUrl = root.getAttribute("data-projects-url") || "";
    var usersUrl = root.getAttribute("data-users-url") || "";
    var projectMembersUrlTmpl = root.getAttribute("data-project-members-url") || "";
    var viewerDirectoryUserIdParsed = parseInt(root.getAttribute("data-directory-user-id") || "", 10);
    var viewerDirectoryUserId = isNaN(viewerDirectoryUserIdParsed) ? null : viewerDirectoryUserIdParsed;
    var todayUrl = root.getAttribute("data-today-url") || "";
    var form = document.getElementById("booking-form");
    var suiteSel = document.getElementById("booking-suite");
    var projectSel = document.getElementById("booking-project");
    var dateIn = document.getElementById("booking-date");
    var startIn = document.getElementById("booking-start");
    var endIn = document.getElementById("booking-end");
    var fullDay = document.getElementById("booking-full-day");
    var bookedForSel = document.getElementById("booking-booked-for");
    var jobSel = document.getElementById("booking-job");
    var notesTa = document.getElementById("booking-notes");
    var errEl = document.getElementById("booking-form-error");
    var okEl = document.getElementById("booking-form-success");
    var submitBtn = document.getElementById("booking-submit");
    var endWrap = document.getElementById("booking-end-wrap");

    var ulMine = document.getElementById("booking-list-mine");
    var ulAsg = document.getElementById("booking-list-assigned");
    var loadMine = document.getElementById("booking-list-mine-loading");
    var loadAsg = document.getElementById("booking-list-assigned-loading");
    var emptyMine = document.getElementById("booking-list-mine-empty");
    var emptyAsg = document.getElementById("booking-list-assigned-empty");
    var listsErr = document.getElementById("booking-lists-error");

    var editHost = document.getElementById("booking-edit-host");
    var editParking = document.getElementById("booking-edit-parking");
    var bookingPageSection = document.getElementById("booking-page-section");
    var editForm = document.getElementById("booking-edit-form");
    var editId = document.getElementById("booking-edit-id");
    var editSuite = document.getElementById("booking-edit-suite");
    var editProject = document.getElementById("booking-edit-project");
    var editBookedFor = document.getElementById("booking-edit-booked-for");
    var editJob = document.getElementById("booking-edit-job");
    var editDate = document.getElementById("booking-edit-date");
    var editStart = document.getElementById("booking-edit-start");
    var editEnd = document.getElementById("booking-edit-end");
    var editFull = document.getElementById("booking-edit-full-day");
    var editNotes = document.getElementById("booking-edit-notes");
    var editErr = document.getElementById("booking-edit-error");
    var editEndWrap = document.getElementById("booking-edit-end-wrap");
    var calPrevBtn = document.getElementById("booking-cal-prev");
    var calTodayBtn = document.getElementById("booking-cal-today");
    var calNextBtn = document.getElementById("booking-cal-next");
    var calPrevCenterBtn = document.getElementById("booking-cal-prev-center");
    var calTodayCenterBtn = document.getElementById("booking-cal-today-center");
    var calNextCenterBtn = document.getElementById("booking-cal-next-center");
    var calScopeSel = document.getElementById("booking-cal-scope");
    var monthTitleEl = document.getElementById("booking-month-title");
    var monthGridEl = document.getElementById("booking-month-grid");
    var roomSearchIn = document.getElementById("booking-room-search");
    var roomListEl = document.getElementById("booking-room-list");
    var onlyAvailableChk = document.getElementById("booking-only-available");
    var repeatSel = document.getElementById("booking-repeat");
    var repeatUntilWrap = document.getElementById("booking-repeat-until-wrap");
    var repeatUntilIn = document.getElementById("booking-repeat-until");
    var summaryRoomEl = document.getElementById("booking-summary-room");
    var summaryDateEl = document.getElementById("booking-summary-date");
    var summaryTimeEl = document.getElementById("booking-summary-time");
    var summaryDurationEl = document.getElementById("booking-summary-duration");

    function reloadNotificationsAfterConflict(x) {
      if (!x || !x.j || x.j.error !== "conflict") return;
      if (typeof window.tmReloadNotifications === "function") window.tmReloadNotifications();
    }

    var cacheSuites = [];
    var cacheProjects = [];
    var cacheUsers = [];
    var mergedForTimeline = [];
    var calendarScope = "day";
    var calendarAnchorDate = todayISO();
    var calendarMonthAnchor = todayISO().slice(0, 7) + "-01";
    var activeRoomId = 0;
    var roomSearchText = "";
    var showOnlyAvailable = false;
    /** Timeline grid step (minutes). */
    var GRID_MIN = 15;

    function bookingProjectToneIndex(projectId) {
      return Math.abs(parseInt(projectId, 10) || 0) % 8;
    }
    var timelineFormEditId = null;
    var submitDefaultLabel = "Book now";

    var H_START = 0;
    var H_END = 24;
    var ROW_PX = 64;

    function timelineHourSpan() {
      return H_END - H_START;
    }

    function enableDatePickerClick(inputEl) {
      if (!inputEl) return;
      var opening = false;
      function openNativePicker() {
        if (opening) return;
        if (typeof inputEl.showPicker !== "function") return;
        opening = true;
        try {
          inputEl.showPicker();
        } catch (e) {
          // Some browsers throw unless triggered from trusted user action.
        } finally {
          setTimeout(function () {
            opening = false;
          }, 80);
        }
      }
      inputEl.addEventListener("click", openNativePicker);
      inputEl.addEventListener("pointerdown", openNativePicker);
    }

    enableDatePickerClick(dateIn);
    enableDatePickerClick(editDate);
    enableDatePickerClick(startIn);
    enableDatePickerClick(endIn);
    enableDatePickerClick(editStart);
    enableDatePickerClick(editEnd);

    function clamp(n, a, b) {
      return Math.max(a, Math.min(b, n));
    }

    function roundToStep(mins, step) {
      step = step || 15;
      return Math.round(mins / step) * step;
    }

    function parseTimeToMin(s) {
      var p = String(s || "").split(":");
      var h = parseInt(p[0], 10);
      var m = parseInt(p[1] || "0", 10);
      if (isNaN(h)) return 0;
      return h * 60 + (isNaN(m) ? 0 : m);
    }

    function minToHHMM(m) {
      m = Math.max(0, parseInt(m, 10) || 0);
      var h = Math.floor(m / 60);
      var mm = m % 60;
      return String(h).padStart(2, "0") + ":" + String(mm).padStart(2, "0");
    }

    // HTML <input type="time"> does not accept 24:00.
    function minToInputHHMM(m) {
      var mins = Math.max(0, parseInt(m, 10) || 0);
      if (mins >= 24 * 60) return "23:59";
      return minToHHMM(mins);
    }

    function getTimelineDate() {
      return (dateIn && dateIn.value) || todayISO();
    }

    function parseISODate(s) {
      var raw = String(s || "").trim();
      if (!raw) return null;
      var d = new Date(raw + "T00:00:00");
      return isNaN(d.getTime()) ? null : d;
    }

    function toISODate(d) {
      return (
        d.getFullYear() +
        "-" +
        String(d.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(d.getDate()).padStart(2, "0")
      );
    }

    function addDays(iso, n) {
      var d = parseISODate(iso) || parseISODate(todayISO());
      d.setDate(d.getDate() + n);
      return toISODate(d);
    }

    function addMonths(iso, n) {
      var d = parseISODate(iso) || parseISODate(todayISO());
      d.setMonth(d.getMonth() + n);
      return toISODate(d);
    }

    function startOfWeekISO(iso) {
      var d = parseISODate(iso) || parseISODate(todayISO());
      var day = d.getDay(); // 0=Sun..6=Sat
      var offset = day === 0 ? -6 : 1 - day; // Monday start
      d.setDate(d.getDate() + offset);
      return toISODate(d);
    }

    function endOfWeekISO(iso) {
      return addDays(startOfWeekISO(iso), 6);
    }

    function startOfMonthISO(iso) {
      var d = parseISODate(iso) || parseISODate(todayISO());
      d.setDate(1);
      return toISODate(d);
    }

    function endOfMonthISO(iso) {
      var d = parseISODate(iso) || parseISODate(todayISO());
      d.setMonth(d.getMonth() + 1, 0);
      return toISODate(d);
    }

    function currentRange() {
      var anchor = calendarAnchorDate || getTimelineDate() || todayISO();
      if (calendarScope === "week") {
        return { from: startOfWeekISO(anchor), to: endOfWeekISO(anchor), anchor: anchor };
      }
      if (calendarScope === "month") {
        return { from: startOfMonthISO(anchor), to: endOfMonthISO(anchor), anchor: anchor };
      }
      return { from: anchor, to: anchor, anchor: anchor };
    }

    function updateTimelineDateLabel() {
      var el = document.getElementById("booking-timeline-date");
      if (!el) return;
      var rng = currentRange();
      if (!rng || !rng.from) {
        el.textContent = "";
        return;
      }
      var fromD = parseISODate(rng.from);
      var toD = parseISODate(rng.to);
      if (!fromD || !toD) {
        el.textContent = rng.from + (rng.to && rng.to !== rng.from ? " → " + rng.to : "");
        return;
      }
      if (calendarScope === "day") {
        var day = fromD.toLocaleDateString(undefined, { weekday: "long" });
        var dateText = fromD.toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "numeric",
        });
        el.textContent = day + " · " + dateText;
        return;
      }
      var fromText = fromD.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
      var toText = toD.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
      el.textContent = fromText + " – " + toText;
    }

    function renderMonthCalendar() {
      if (!monthGridEl) return;
      var anchor = parseISODate(calendarMonthAnchor || todayISO());
      if (!anchor) return;
      var y = anchor.getFullYear();
      var m = anchor.getMonth();
      if (monthTitleEl) {
        monthTitleEl.textContent = anchor.toLocaleDateString(undefined, {
          month: "long",
          year: "numeric",
        });
      }
      monthGridEl.textContent = "";
      ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach(function (dow) {
        var lab = document.createElement("div");
        lab.className = "booking-month-dow";
        lab.textContent = dow;
        monthGridEl.appendChild(lab);
      });
      var first = new Date(y, m, 1);
      var firstWeekday = first.getDay();
      var daysInMonth = new Date(y, m + 1, 0).getDate();
      var daysInPrev = new Date(y, m, 0).getDate();
      var selected = getTimelineDate();
      var today = todayISO();
      for (var i = 0; i < 42; i++) {
        var day = document.createElement("button");
        day.type = "button";
        day.className = "booking-month-day";
        var dayNum = i - firstWeekday + 1;
        var out = dayNum < 1 || dayNum > daysInMonth;
        var realY = y;
        var realM = m;
        var realD = dayNum;
        if (dayNum < 1) {
          realM = m - 1;
          if (realM < 0) {
            realM = 11;
            realY = y - 1;
          }
          realD = daysInPrev + dayNum;
          day.classList.add("is-outside");
        } else if (dayNum > daysInMonth) {
          realM = m + 1;
          if (realM > 11) {
            realM = 0;
            realY = y + 1;
          }
          realD = dayNum - daysInMonth;
          day.classList.add("is-outside");
        }
        var iso =
          realY +
          "-" +
          String(realM + 1).padStart(2, "0") +
          "-" +
          String(realD).padStart(2, "0");
        day.textContent = String(realD);
        day.dataset.iso = iso;
        if (iso === selected) day.classList.add("is-selected");
        if (iso === today) day.classList.add("is-today");
        day.addEventListener("click", function () {
          var isoSel = this.dataset.iso;
          if (!isoSel) return;
          if (dateIn) dateIn.value = isoSel;
          calendarAnchorDate = isoSel;
          calendarMonthAnchor = startOfMonthISO(isoSel);
          updateTimelineDateLabel();
          renderMonthCalendar();
          refreshLists();
        });
        monthGridEl.appendChild(day);
      }
    }

    function updateSelectionSummary() {
      if (!summaryRoomEl || !summaryDateEl || !summaryTimeEl || !summaryDurationEl) return;
      var sid = suiteSel ? parseInt(suiteSel.value, 10) : 0;
      var sName = "-";
      for (var i = 0; i < cacheSuites.length; i++) {
        if (Number(cacheSuites[i].id) === Number(sid)) {
          sName = cacheSuites[i].name || "-";
          break;
        }
      }
      var startVal = (startIn && startIn.value) || "--:--";
      var endVal = fullDay && fullDay.checked ? "23:59" : (endIn && endIn.value) || "--:--";
      summaryRoomEl.textContent = sName;
      summaryDateEl.textContent = (dateIn && dateIn.value) || "-";
      summaryTimeEl.textContent = startVal + " → " + endVal;
      var dur = Math.max(0, parseTimeToMin(endVal) - parseTimeToMin(startVal));
      var h = Math.floor(dur / 60);
      var mm = dur % 60;
      summaryDurationEl.textContent = (h ? h + "h " : "") + mm + "m";
    }

    function currentSuiteId() {
      var sid = suiteSel ? parseInt(suiteSel.value, 10) : 0;
      return sid || 0;
    }

    function canSuiteFitSelection(suiteId) {
      if (!showOnlyAvailable) return true;
      var s = startIn ? parseTimeToMin(startIn.value) : NaN;
      var e = fullDay && fullDay.checked ? H_END * 60 : endIn ? parseTimeToMin(endIn.value) : NaN;
      if (!isFinite(s) || !isFinite(e) || e <= s) return true;
      return !selectionConflicts(getTimelineDate(), suiteId, s, e, timelineFormEditId);
    }

    function renderRoomList() {
      if (!roomListEl) return;
      roomListEl.textContent = "";
      var activeSuites = cacheSuites.filter(function (s) {
        return !!s.is_active;
      });
      var needle = (roomSearchText || "").trim().toLowerCase();
      if (!activeSuites.length) {
        var empty = document.createElement("li");
        empty.className = "booking-room-empty";
        empty.textContent = "No active rooms";
        roomListEl.appendChild(empty);
        return;
      }
      var shown = 0;
      activeSuites.forEach(function (s) {
        if (needle && String(s.name || "").toLowerCase().indexOf(needle) < 0) return;
        if (!canSuiteFitSelection(s.id)) return;
        shown += 1;
        var li = document.createElement("li");
        li.className = "booking-room-item";
        if (Number(activeRoomId) === Number(s.id)) li.classList.add("is-active");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", Number(activeRoomId) === Number(s.id) ? "true" : "false");
        li.dataset.suiteId = String(s.id);
        var dot = document.createElement("span");
        dot.className = "booking-room-dot";
        dot.style.background = "hsl(" + ((Number(s.id) * 47) % 360) + " 60% 58%)";
        var textCol = document.createElement("div");
        textCol.className = "booking-room-text";
        var name = document.createElement("span");
        name.className = "booking-room-name";
        name.textContent = s.name || "Room";
        var sub = document.createElement("span");
        sub.className = "booking-room-subtitle";
        sub.textContent = (s.subtitle && String(s.subtitle).trim()) || "Edit suite";
        textCol.appendChild(name);
        textCol.appendChild(sub);
        li.appendChild(dot);
        li.appendChild(textCol);
        li.addEventListener("click", function () {
          activeRoomId = Number(s.id) || 0;
          if (suiteSel) suiteSel.value = String(activeRoomId);
          renderRoomList();
          renderTimeline();
          updateSelectionSummary();
        });
        roomListEl.appendChild(li);
      });
      if (!shown) {
        var empty2 = document.createElement("li");
        empty2.className = "booking-room-empty";
        empty2.textContent = "No rooms match filters";
        roomListEl.appendChild(empty2);
      }
    }

    function overlap(aStart, aEnd, bStart, bEnd) {
      return aStart < bEnd && bStart < aEnd;
    }

    function selectionConflicts(dateStr, suiteId, startMin, endMin, ignoreBookingId) {
      if (!dateStr || !suiteId) return false;
      var s = Math.min(startMin, endMin);
      var e = Math.max(startMin, endMin);
      if (e - s < 1) return false;
      var list = mergedForTimeline || [];
      for (var i = 0; i < list.length; i++) {
        var bk = list[i];
        if (!bk) continue;
        if (ignoreBookingId && String(bk.id) === String(ignoreBookingId)) continue;
        if (bk.booking_date !== dateStr) continue;
        if (Number(bk.edit_suite_id) !== Number(suiteId)) continue;
        var bs = parseTimeToMin(bk.start_time);
        var be = parseTimeToMin(bk.end_time);
        if (overlap(s, e, bs, be)) return true;
      }
      return false;
    }

    function ensureTimeline(inner, suites) {
      if (!inner) return null;
      var key = (suites || [])
        .map(function (s) {
          return (
            String(s.id) +
            ":" +
            String(s.name || "") +
            ":" +
            String(s.subtitle || "").trim()
          );
        })
        .join("|");
      var state = inner._tmTimeline;
      if (state && state.key === key) return state;

      // Build skeleton once for this suite set.
      inner.textContent = "";
      var wrap = document.createElement("div");
      wrap.className = "timeline";

      var header = document.createElement("div");
      header.className = "timeline-header";
      var leftCorner = document.createElement("div");
      leftCorner.className = "timeline-corner";
      leftCorner.textContent = "Rooms";
      header.appendChild(leftCorner);
      var hoursHead = document.createElement("div");
      hoursHead.className = "timeline-hours timeline-hours--fluid";
      var spanH = timelineHourSpan();
      for (var hh = H_START; hh <= H_END; hh++) {
        var hCell = document.createElement("div");
        hCell.className = "timeline-hour-cell";
        hCell.textContent = (hh < 10 ? "0" : "") + hh + ":00";
        var fr = (hh - H_START) / spanH;
        hCell.style.left = fr * 100 + "%";
        if (hh === H_START) {
          hCell.style.transform = "translateX(0)";
        } else if (hh === H_END) {
          hCell.style.transform = "translateX(-100%)";
        } else {
          hCell.style.transform = "translateX(-50%)";
        }
        hoursHead.appendChild(hCell);
      }
      header.appendChild(hoursHead);
      wrap.appendChild(header);

      var body = document.createElement("div");
      body.className = "timeline-body";
      var labelCol = document.createElement("div");
      labelCol.className = "timeline-room-labels";
      var gridCol = document.createElement("div");
      gridCol.className = "timeline-grid-col timeline-grid-col--fluid";
      body.appendChild(labelCol);
      body.appendChild(gridCol);

      var tracks = {};
      suites.forEach(function (suite) {
        var rowLabel = document.createElement("div");
        rowLabel.className = "timeline-room-label";
        var ld = document.createElement("span");
        ld.className = "timeline-room-label-dot";
        ld.style.background = "hsl(" + ((Number(suite.id) * 47) % 360) + " 60% 58%)";
        var lt = document.createElement("div");
        lt.className = "timeline-room-label-text";
        var ln = document.createElement("span");
        ln.className = "timeline-room-label-name";
        ln.textContent = suite.name || "Room";
        var ls = document.createElement("span");
        ls.className = "timeline-room-label-sub";
        ls.textContent = (suite.subtitle && String(suite.subtitle).trim()) || "Edit suite";
        lt.appendChild(ln);
        lt.appendChild(ls);
        rowLabel.appendChild(ld);
        rowLabel.appendChild(lt);
        labelCol.appendChild(rowLabel);

        var row = document.createElement("div");
        row.className = "booking-timeline-room-col";
        row.dataset.suiteId = String(suite.id);
        var track = document.createElement("div");
        track.className = "booking-timeline-room-track booking-timeline-room-track--fluid";
        track.dataset.suiteId = String(suite.id);
        track.style.height = ROW_PX + "px";

        for (var h2 = H_START; h2 < H_END; h2++) {
          var line = document.createElement("div");
          line.className = "booking-timeline-hour-line";
          line.style.left = ((h2 - H_START) / spanH) * 100 + "%";
          track.appendChild(line);
        }

        var hover = document.createElement("div");
        hover.className = "timeline-hover";
        hover.hidden = true;
        track.appendChild(hover);

        var sel = document.createElement("div");
        sel.className = "timeline-selection";
        sel.hidden = true;
        var selLab = document.createElement("div");
        selLab.className = "timeline-selection-label";
        selLab.setAttribute("data-role", "sel-label");
        sel.appendChild(selLab);
        track.appendChild(sel);

        var nowLn = document.createElement("div");
        nowLn.className = "timeline-now now-line";
        nowLn.hidden = true;
        nowLn.setAttribute("aria-hidden", "true");
        track.appendChild(nowLn);

        row.appendChild(track);
        gridCol.appendChild(row);
        tracks[String(suite.id)] = {
          suite: suite,
          col: row,
          rowLabel: rowLabel,
          track: track,
          hover: hover,
          selection: sel,
          nowLine: nowLn,
          bookingMap: {},
        };
      });

      wrap.appendChild(body);
      inner.appendChild(wrap);

      state = {
        key: key,
        suites: suites,
        tracks: tracks,
        isSelecting: false,
        selSuiteId: 0,
        selStartMin: 0,
        selEndMin: 0,
        selConflict: false,
        drag: null,
      };
      inner._tmTimeline = state;
      return state;
    }

    function minutesFromY(trackEl, clientY, clientX) {
      var rect = trackEl.getBoundingClientRect();
      var x = clamp((typeof clientX === "number" ? clientX : clientY) - rect.left, 0, rect.width);
      var totalMin = (H_END - H_START) * 60;
      var mins = H_START * 60 + (x / rect.width) * totalMin;
      mins = roundToStep(mins, GRID_MIN);
      mins = clamp(mins, H_START * 60, H_END * 60);
      return mins;
    }

    function setSelectionVisual(state, suiteId, startMin, endMin) {
      if (!state) return;
      var t = state.tracks[String(suiteId)];
      if (!t) return;
      var sel = t.selection;
      if (!sel) return;
      var totalMin = (H_END - H_START) * 60;
      var s = clamp(Math.min(startMin, endMin), H_START * 60, H_END * 60);
      var e = clamp(Math.max(startMin, endMin), H_START * 60, H_END * 60);
      if (e - s < GRID_MIN) e = Math.min(H_END * 60, s + GRID_MIN);
      var leftPct = ((s - H_START * 60) / totalMin) * 100;
      var wPct = ((e - s) / totalMin) * 100;
      sel.hidden = false;
      sel.style.left = leftPct + "%";
      sel.style.width = wPct + "%";
      sel.style.top = "4px";
      sel.style.bottom = "4px";
      sel.style.height = "auto";
      sel.classList.add("preview-booking");
      sel.classList.toggle("conflict", !!state.selConflict);
      var selLab = sel.querySelector('[data-role="sel-label"]');
      if (selLab) selLab.textContent = minToHHMM(s) + " → " + minToHHMM(e);
    }

    function hideAllSelection(state) {
      if (!state) return;
      Object.keys(state.tracks || {}).forEach(function (k) {
        var sel = state.tracks[k] && state.tracks[k].selection;
        if (sel) sel.hidden = true;
      });
    }

    function hideAllHover(state) {
      if (!state) return;
      Object.keys(state.tracks || {}).forEach(function (k) {
        var h = state.tracks[k] && state.tracks[k].hover;
        if (h) h.hidden = true;
      });
    }

    function highlightSelectedRoom(state, suiteId) {
      if (!state) return;
      Object.keys(state.tracks || {}).forEach(function (k) {
        var col = state.tracks[k] && state.tracks[k].col;
        if (!col) return;
        col.classList.toggle("is-selected", suiteId && String(suiteId) === String(k));
        col.classList.toggle("is-dimmed", !!suiteId && String(suiteId) !== String(k));
      });
    }

    function applySelectionToForm(suiteId, startMin, endMin) {
      if (!suiteSel || !startIn || !endIn || !dateIn) return;
      if (suiteId) suiteSel.value = String(suiteId);
      // Date stays whatever the timeline is currently showing (the form date input).
      dateIn.value = getTimelineDate();
      var s = clamp(roundToStep(startMin, GRID_MIN), H_START * 60, H_END * 60 - GRID_MIN);
      var e = clamp(roundToStep(endMin, GRID_MIN), H_START * 60, H_END * 60);
      if (e <= s) e = clamp(s + 60, H_START * 60, H_END * 60);
      startIn.value = minToInputHHMM(s);
      endIn.value = minToInputHHMM(e);
      if (fullDay) fullDay.checked = false;
      wireFullDay(fullDay, endIn, endWrap);
      updateSelectionSummary();
    }

    function renderTimeline() {
      var inner = document.getElementById("booking-timeline-inner");
      var wrap = document.getElementById("booking-timeline-wrap");
      if (!inner || !wrap || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) {
        return;
      }
      var suites = cacheSuites.filter(function (s) {
        return s.is_active;
      });
      if (showOnlyAvailable) {
        suites = suites.filter(function (s) {
          return canSuiteFitSelection(s.id);
        });
      }
      if (!suites.length) {
        inner.textContent = "";
        var empty = document.createElement("p");
        empty.className = "empty";
        empty.style.padding = "1rem";
        empty.textContent = "No rooms to display.";
        inner.appendChild(empty);
        return;
      }

      var state = ensureTimeline(inner, suites);
      if (!state) return;
      updateTimelineDateLabel();

      var dateStr = getTimelineDate();
      var totalMin = (H_END - H_START) * 60;

      // Update booking blocks keyed by booking id (no full rebuild).
      Object.keys(state.tracks || {}).forEach(function (sid) {
        var t = state.tracks[sid];
        if (!t || !t.track) return;
        var used = {};
        (mergedForTimeline || []).forEach(function (bk) {
          if (!bk) return;
          if (bk.booking_date !== dateStr) return;
          if (String(bk.edit_suite_id) !== String(sid)) return;
          var sm = parseTimeToMin(bk.start_time);
          var em = parseTimeToMin(bk.end_time);
          var startRel = sm - H_START * 60;
          var dur = Math.max(GRID_MIN, em - sm);
          if (startRel < 0 || startRel >= totalMin) return;
          used[String(bk.id)] = true;

          var masked = !!bk.timeline_masked;
          var blk = t.bookingMap[String(bk.id)];
          if (blk && !!blk._tmTimelineMasked !== masked) {
            if (blk.parentNode) blk.parentNode.removeChild(blk);
            delete t.bookingMap[String(bk.id)];
            blk = null;
          }
          if (!blk) {
            if (masked) {
              blk = document.createElement("div");
              blk.className = "unavailable booking-timeline-block";
              blk.dataset.bookingId = String(bk.id);
              blk.setAttribute("role", "presentation");
              blk.setAttribute("aria-hidden", "true");
              blk._tmTimelineMasked = true;
              blk._bookingData = bk;
              t.bookingMap[String(bk.id)] = blk;
              t.track.appendChild(blk);
            } else {
              blk = document.createElement("button");
              blk.type = "button";
              blk.className =
                "booking booking-timeline-block timeline-booking timeline-booking--tone-" +
                bookingProjectToneIndex(bk.project_id);
              blk.dataset.bookingId = String(bk.id);
              blk._tmTimelineMasked = false;

              var body = document.createElement("span");
              body.className = "timeline-booking-body";
              var projEl = document.createElement("span");
              projEl.className = "timeline-booking-project";
              projEl.setAttribute("data-role", "project");
              var timeEl = document.createElement("span");
              timeEl.className = "timeline-booking-time";
              timeEl.setAttribute("data-role", "time");
              var userEl = document.createElement("span");
              userEl.className = "timeline-booking-user";
              userEl.setAttribute("data-role", "user");
              body.appendChild(projEl);
              body.appendChild(timeEl);
              body.appendChild(userEl);
              blk.appendChild(body);

              var hTop = document.createElement("span");
              hTop.className = "resize-handle resize-top top";
              hTop.setAttribute("aria-hidden", "true");
              var hBottom = document.createElement("span");
              hBottom.className = "resize-handle resize-bottom bottom";
              hBottom.setAttribute("aria-hidden", "true");
              blk.appendChild(hTop);
              blk.appendChild(hBottom);

              blk.addEventListener("click", function (e) {
                if (blk._tmSuppressClick) {
                  blk._tmSuppressClick = false;
                  return;
                }
                e.preventDefault();
                try {
                  if (bk && suiteSel) suiteSel.value = String(bk.edit_suite_id);
                  if (bk && dateIn) dateIn.value = bk.booking_date;
                  if (bk && startIn) startIn.value = (bk.start_time || "").slice(0, 5);
                  if (bk && endIn) endIn.value = (bk.end_time || "").slice(0, 5);
                  if (fullDay) fullDay.checked = !!bk.is_full_day;
                  wireFullDay(fullDay, endIn, endWrap);
                  if (notesTa && bk) notesTa.value = (bk.notes || "").trim();
                  if (jobSel && bk) jobSel.value = (bk.job_type || "").trim();
                  enterTimelineFormEditMode(bk);
                } catch (e2) {}
                highlightSelectedRoom(state, currentSuiteId());
              });

              blk.addEventListener("contextmenu", function (e) {
                e.preventDefault();
                var data = blk._bookingData || bk;
                if (!data || !data.id) return;
                if (!window.confirm("Delete this booking?")) return;
                fetch(listUrl.replace(/\/?$/, "") + "/" + data.id, {
                  method: "DELETE",
                  headers: { Accept: "application/json" },
                  credentials: "same-origin",
                })
                  .then(function (r) {
                    return r.json().then(function (j) {
                      return { ok: r.ok, j: j };
                    });
                  })
                  .then(function (x) {
                    if (!x.ok) {
                      showError(listsErr, (x.j && x.j.message) || "Could not delete.");
                      return;
                    }
                    refreshLists();
                    bumpDashboardIfToday(data);
                  })
                  .catch(function () {
                    showError(listsErr, "Network error.");
                  });
              });

              t.bookingMap[String(bk.id)] = blk;
              t.track.appendChild(blk);
            }
          }

          var leftPct = (startRel / totalMin) * 100;
          var wPct = (dur / totalMin) * 100;
          blk.style.left = leftPct + "%";
          blk.style.width = wPct + "%";
          blk.style.top = "4px";
          blk.style.bottom = "4px";
          blk.style.height = "auto";
          if (masked) {
            blk.className = "unavailable booking-timeline-block";
          } else {
            blk.className =
              "booking booking-timeline-block timeline-booking timeline-booking--tone-" +
              bookingProjectToneIndex(bk.project_id);
            var projEl2 = blk.querySelector('[data-role="project"]');
            var timeEl2 = blk.querySelector('[data-role="time"]');
            var userEl2 = blk.querySelector('[data-role="user"]');
            if (projEl2) projEl2.textContent = ((bk.project_name || "").trim() || "Project").slice(0, 48);
            if (timeEl2) {
              timeEl2.textContent =
                minToHHMM(parseTimeToMin(bk.start_time)) + " → " + minToHHMM(parseTimeToMin(bk.end_time));
            }
            if (userEl2) {
              var userLine = (bk.booked_for_name || "").trim();
              if ((bk.job_type || "").trim()) {
                userLine = userLine ? userLine + " · " + bk.job_type.trim() : bk.job_type.trim();
              }
              userEl2.textContent = userLine;
            }
          }
          blk._bookingData = bk;
        });

        Object.keys(t.bookingMap || {}).forEach(function (bid) {
          if (used[bid]) return;
          var node = t.bookingMap[bid];
          if (node && node.parentNode) node.parentNode.removeChild(node);
          delete t.bookingMap[bid];
        });
      });

      highlightSelectedRoom(state, currentSuiteId());
      updateTimelineNowIndicators();
    }

    function setViewMode(isTimeline) {
      if (!bookingPageSection) return;
      bookingPageSection.classList.toggle("is-timeline", isTimeline);
      bookingPageSection.classList.toggle("booking-list-mode", !isTimeline);
      var wrap = document.getElementById("booking-timeline-wrap");
      var btnL = document.getElementById("booking-view-list");
      var btnT = document.getElementById("booking-view-timeline");
      if (btnL && btnT) {
        btnL.classList.toggle("is-active", !isTimeline);
        btnT.classList.toggle("is-active", isTimeline);
        btnL.setAttribute("aria-pressed", !isTimeline ? "true" : "false");
        btnT.setAttribute("aria-pressed", isTimeline ? "true" : "false");
      }
      if (wrap) wrap.hidden = !isTimeline;
      if (isTimeline) {
        renderTimeline();
        // Auto-scroll to current hour for convenience.
        try {
          var sc = document.getElementById("booking-timeline-wrap");
          var innerEl = document.getElementById("booking-timeline-inner");
          var track0 = innerEl && innerEl.querySelector(".booking-timeline-room-track");
          if (sc && track0 && sc.scrollWidth > sc.clientWidth + 2) {
            var now = new Date();
            var mins = now.getHours() * 60 + now.getMinutes();
            var rel = clamp(mins - H_START * 60, 0, (H_END - H_START) * 60);
            var frac = rel / ((H_END - H_START) * 60);
            var target = frac * sc.scrollWidth - sc.clientWidth * 0.35;
            sc.scrollLeft = Math.max(0, Math.min(target, sc.scrollWidth - sc.clientWidth));
          }
        } catch (e) {}
      }
    }

    function projectMembersFetchUrl(projectId) {
      if (!projectMembersUrlTmpl) return "";
      var pid = parseInt(projectId, 10);
      if (!pid) return "";
      return projectMembersUrlTmpl.replace(/\/\d+$/, "/" + pid);
    }

    function syncTimelineConflictMessage() {
      if (!errEl) return;
      var inner = document.getElementById("booking-timeline-inner");
      var st = inner && inner._tmTimeline;
      var on =
        bookingPageSection &&
        bookingPageSection.classList.contains("is-timeline") &&
        st &&
        st.selConflict;
      if (on) showError(errEl, "Time slot already booked");
      else if (errEl.textContent === "Time slot already booked") showError(errEl, "");
    }

    function refreshBookingFormSubmitState() {
      if (!submitBtn) return;
      var hasSuite = suiteSel && parseInt(suiteSel.value, 10) > 0;
      var hasProject = projectSel && parseInt(projectSel.value, 10) > 0;
      var hasBooked = false;
      if (bookedForSel && bookedForSel.selectedIndex >= 0) {
        var o = bookedForSel.options[bookedForSel.selectedIndex];
        hasBooked = !!(o && !o.disabled && parseInt(bookedForSel.value, 10) > 0);
      }
      var hasJob = !!(jobSel && (jobSel.value || "").trim());
      var inner = document.getElementById("booking-timeline-inner");
      var st = inner && inner._tmTimeline;
      var conflict =
        bookingPageSection &&
        bookingPageSection.classList.contains("is-timeline") &&
        st &&
        st.selConflict;
      submitBtn.disabled = !(hasSuite && hasProject && hasBooked && hasJob) || !!conflict;
    }

    function exitTimelineFormEditMode() {
      timelineFormEditId = null;
      if (submitBtn) submitBtn.textContent = submitDefaultLabel;
      if (startIn) startIn.dispatchEvent(new Event("change", { bubbles: true }));
      else {
        syncTimelineConflictMessage();
        refreshBookingFormSubmitState();
      }
    }

    function enterTimelineFormEditMode(bk) {
      if (!bk || bk.id == null) return;
      timelineFormEditId = parseInt(bk.id, 10) || null;
      if (submitBtn) submitBtn.textContent = "Update booking";
      if (projectSel && bk.project_id != null) projectSel.value = String(bk.project_id);
      if (jobSel && bk.job_type) jobSel.value = String(bk.job_type);
      fetchUsersForProject(projectSel && projectSel.value ? projectSel.value : "", function () {
        if (bookedForSel && bk.booked_for_id != null) bookedForSel.value = String(bk.booked_for_id);
        refreshBookingFormSubmitState();
        if (startIn) startIn.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }

    function updateTimelineNowIndicators() {
      var inner = document.getElementById("booking-timeline-inner");
      var state = inner && inner._tmTimeline;
      if (!state || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) return;
      var d = new Date();
      var isToday = getTimelineDate() === todayISO();
      var mins = d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
      var totalMin = (H_END - H_START) * 60;
      Object.keys(state.tracks || {}).forEach(function (k) {
        var t = state.tracks[k];
        if (!t || !t.nowLine) return;
        if (!isToday || mins < H_START * 60 || mins > H_END * 60) {
          t.nowLine.hidden = true;
          return;
        }
        var rel = mins - H_START * 60;
        var leftPct = (rel / totalMin) * 100;
        t.nowLine.hidden = false;
        t.nowLine.style.left = Math.max(0, leftPct) + "%";
      });
    }

    function fetchUsersForProject(projectId, done) {
      if (!bookedForSel) {
        if (done) done();
        return;
      }
      var url = projectMembersFetchUrl(projectId);
      if (!url) {
        bookedForSel.textContent = "";
        var emptyOpt = document.createElement("option");
        emptyOpt.value = "";
        emptyOpt.disabled = true;
        emptyOpt.selected = true;
        emptyOpt.textContent = "No team members";
        bookedForSel.appendChild(emptyOpt);
        refreshBookingFormSubmitState();
        if (done) done();
        return;
      }
      fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error("bad response");
          return r.json();
        })
        .then(function (data) {
          var users = Array.isArray(data) ? data : [];
          bookedForSel.textContent = "";
          if (!users.length) {
            var noMem = document.createElement("option");
            noMem.value = "";
            noMem.disabled = true;
            noMem.selected = true;
            noMem.textContent = "No team members";
            bookedForSel.appendChild(noMem);
          } else {
            users.forEach(function (u) {
              var opt = document.createElement("option");
              opt.value = String(u.id);
              opt.textContent = u.name || String(u.id);
              bookedForSel.appendChild(opt);
            });
            var pick = -1;
            if (viewerDirectoryUserId != null) {
              for (var i = 0; i < users.length; i++) {
                if (Number(users[i].id) === viewerDirectoryUserId) {
                  pick = i;
                  break;
                }
              }
            }
            bookedForSel.selectedIndex = pick >= 0 ? pick : 0;
          }
          try {
            bookedForSel.dispatchEvent(new CustomEvent("tm:options-updated", { bubbles: false }));
          } catch (e) {}
          refreshBookingFormSubmitState();
          if (done) done();
        })
        .catch(function () {
          bookedForSel.textContent = "";
          var errOpt = document.createElement("option");
          errOpt.value = "";
          errOpt.disabled = true;
          errOpt.selected = true;
          errOpt.textContent = "No team members";
          bookedForSel.appendChild(errOpt);
          refreshBookingFormSubmitState();
          if (done) done();
        });
    }

    function openEditDialog(b) {
      showError(editErr, "");
      function fillEditSelects(usersForBookedFor) {
        usersForBookedFor = usersForBookedFor || cacheUsers;
        fillSelect(
          editSuite,
          cacheSuites.filter(function (s) {
            return s.is_active;
          }),
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        fillSelect(
          editProject,
          cacheProjects,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        fillSelect(
          editBookedFor,
          usersForBookedFor,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        editId.value = String(b.id);
        editSuite.value = String(b.edit_suite_id);
        editProject.value = String(b.project_id);
        editBookedFor.value = String(b.booked_for_id);
        editDate.value = b.booking_date;
        editStart.value = (b.start_time || "").slice(0, 5);
        editFull.checked = !!b.is_full_day;
        if (!b.is_full_day) editEnd.value = (b.end_time || "").slice(0, 5);
        if (editNotes) editNotes.value = (b.notes || "").trim();
        if (editJob) editJob.value = (b.job_type || "").trim();
        setMinDate(editDate);
        if (editEnd) {
          editEnd.disabled = !!editFull.checked;
          editEnd.value = editFull.checked ? "23:59" : (b.end_time || "").slice(0, 5);
        }
        if (editEndWrap) editEndWrap.classList.toggle("is-muted", !!editFull.checked);
        var opened = false;
        if (window.tmShell && editHost && editParking) {
          try {
            window.tmShell.openInspector({
              title: "Edit booking",
              el: editHost,
              parking: editParking,
              modal: true,
              bodyClass: "booking-edit-inspector-modal",
            });
            opened = true;
          } catch (e) {
            opened = false;
          }
        }
        if (!opened && editHost && editParking) {
          try {
            editParking.hidden = false;
            editParking.removeAttribute("aria-hidden");
            editHost.hidden = false;
            editHost.style.display = "block";
          } catch (e) {}
        }
      }
      function loadUsersThenFill() {
        var sep = usersUrl.indexOf("?") >= 0 ? "&" : "?";
        var uUrl =
          usersUrl + sep + "include_user_id=" + encodeURIComponent(String(b.booked_for_id));
        fetch(uUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(function (ju) {
            fillEditSelects((ju && ju.users) || cacheUsers);
          })
          .catch(function () {
            fillEditSelects(cacheUsers);
          });
      }
      if (cacheSuites.length && cacheProjects.length) {
        loadUsersThenFill();
      } else {
        loadMeta(loadUsersThenFill);
      }
    }

    function listHandlers() {
      return {
        onEdit: function (b) {
          openEditDialog(b);
        },
        onCancel: function (b) {
          if (!window.confirm("Cancel this booking?")) return;
          fetch(listUrl.replace(/\/?$/, "") + "/" + b.id, {
            method: "DELETE",
            headers: { Accept: "application/json" },
            credentials: "same-origin",
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(listsErr, (x.j && x.j.message) || "Could not cancel.");
                return;
              }
              refreshLists();
              bumpDashboardIfToday(b);
            })
            .catch(function () {
              showError(listsErr, "Network error.");
            });
        },
      };
    }

    function refreshLists() {
      showError(listsErr, "");
      var rng = currentRange();
      if (dateIn) dateIn.value = rng.anchor;
      var qs =
        "json=1&from=" +
        encodeURIComponent(rng.from) +
        "&to=" +
        encodeURIComponent(rng.to);
      fetch(listUrl + (listUrl.indexOf("?") >= 0 ? "&" : "?") + qs, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var mine = (j && j.bookings_mine) || [];
          var asg = (j && j.bookings_assigned) || [];
          var timelineRows = (j && j.bookings_timeline) || [];
          if (loadMine) loadMine.hidden = true;
          if (loadAsg) loadAsg.hidden = true;
          if (emptyMine) emptyMine.hidden = mine.length > 0;
          if (emptyAsg) emptyAsg.hidden = asg.length > 0;
          if (ulMine) {
            ulMine.hidden = mine.length === 0;
            renderBookings(ulMine, mine, listHandlers());
          }
          if (ulAsg) {
            ulAsg.hidden = asg.length === 0;
            renderBookings(ulAsg, asg, listHandlers());
          }
          mergedForTimeline = timelineRows.length ? timelineRows : mine.concat(asg);
          renderRoomList();
          updateSelectionSummary();
          if (bookingPageSection && bookingPageSection.classList.contains("is-timeline")) {
            renderTimeline();
          }
        })
        .catch(function () {
          showError(listsErr, "Could not load bookings.");
          if (loadMine) loadMine.hidden = true;
          if (loadAsg) loadAsg.hidden = true;
        });
    }

    function bumpDashboardIfToday(b) {
      if (!todayUrl || !b || !b.booking_date) return;
      if (b.booking_date !== todayISO()) return;
      fetch(todayUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var card = document.getElementById("dashboard-booking-card");
          if (card) renderDashboardBooking(card, j);
        })
        .catch(function () {});
    }

    function loadMeta(done) {
      Promise.all([
        fetch(suitesUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
        fetch(projectsUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
        fetch(usersUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
      ])
        .then(function (parts) {
          cacheSuites = (parts[0] && parts[0].suites) || [];
          cacheProjects = (parts[1] && parts[1].projects) || [];
          cacheUsers = (parts[2] && parts[2].users) || [];
          if (done) done();
        })
        .catch(function () {
          if (done) done();
        });
    }

    if (form && suiteSel && projectSel && dateIn && bookedForSel) {
      if (submitBtn) submitDefaultLabel = (submitBtn.textContent && submitBtn.textContent.trim()) || "Book now";
      setMinDate(dateIn);
      dateIn.addEventListener("focus", function () {
        setMinDate(dateIn);
      });
      dateIn.value = todayISO();
      calendarAnchorDate = dateIn.value || todayISO();
      var dSlot = new Date();
      dSlot.setMinutes(0, 0, 0);
      dSlot.setHours(dSlot.getHours() + 1);
      var startMinDefault = clamp(
        roundToStep(dSlot.getHours() * 60 + dSlot.getMinutes(), GRID_MIN),
        H_START * 60,
        (H_END - 2) * 60
      );
      if (startIn) startIn.value = minToInputHHMM(startMinDefault);
      if (endIn) {
        var endMinDefault = clamp(startMinDefault + 120, H_START * 60 + GRID_MIN, H_END * 60);
        endIn.value = minToInputHHMM(endMinDefault);
      }
      wireFullDay(fullDay, endIn, endWrap);

      loadMeta(function () {
        if (bookingPageSection && form) setViewMode(true);
        var activeSuites = cacheSuites.filter(function (s) {
          return s.is_active;
        });
        fillSelect(
          suiteSel,
          activeSuites,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          activeSuites.length ? null : "No rooms"
        );
        if (suiteSel && suiteSel.value) activeRoomId = parseInt(suiteSel.value, 10) || 0;
        calendarMonthAnchor = startOfMonthISO(dateIn.value || todayISO());
        renderMonthCalendar();
        renderRoomList();
        updateSelectionSummary();
        fillSelect(
          projectSel,
          cacheProjects,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          cacheProjects.length ? null : "No projects"
        );
        if (!activeSuites.length || !cacheProjects.length) {
          if (submitBtn) submitBtn.disabled = true;
        } else if (submitBtn) {
          submitBtn.disabled = true;
        }
        fetchUsersForProject(projectSel && projectSel.value ? projectSel.value : "", function () {
          if (bookingPageSection && bookingPageSection.classList.contains("is-timeline")) {
            renderTimeline();
            updateTimelineNowIndicators();
          }
          if (bookingPageSection && !bookingPageSection._tmNowTick) {
            bookingPageSection._tmNowTick = setInterval(updateTimelineNowIndicators, 30000);
          }
        });
        var qsPid = "";
        try {
          qsPid = new URLSearchParams(window.location.search || "").get("project_id") || "";
        } catch (ePre) {}
        if (qsPid && projectSel) {
          projectSel.value = String(qsPid);
          fetchUsersForProject(String(qsPid), function () {
            refreshBookingFormSubmitState();
          });
        }
      });

      if (projectSel) {
        projectSel.addEventListener("change", function () {
          exitTimelineFormEditMode();
          fetchUsersForProject(projectSel.value);
        });
      }
      if (jobSel) {
        jobSel.addEventListener("change", refreshBookingFormSubmitState);
      }

      if (roomSearchIn) {
        roomSearchIn.addEventListener("input", function () {
          roomSearchText = roomSearchIn.value || "";
          renderRoomList();
          renderTimeline();
        });
      }
      if (onlyAvailableChk) {
        onlyAvailableChk.addEventListener("change", function () {
          showOnlyAvailable = !!onlyAvailableChk.checked;
          renderRoomList();
          renderTimeline();
        });
      }
      if (repeatSel && repeatUntilWrap) {
        repeatSel.addEventListener("change", function () {
          var on = repeatSel.value && repeatSel.value !== "none";
          repeatUntilWrap.hidden = !on;
          if (on && repeatUntilIn && !repeatUntilIn.value) repeatUntilIn.value = dateIn ? dateIn.value : todayISO();
        });
      }

      form.addEventListener("submit", function (e) {
        e.preventDefault();
        showError(errEl, "");
        if (okEl) {
          okEl.textContent = "";
          okEl.hidden = true;
        }
        var sid = parseInt(suiteSel.value, 10);
        var pid = parseInt(projectSel.value, 10);
        var fid = parseInt(bookedForSel.value, 10);
        if (!sid) {
          showError(errEl, "Select a room.");
          return;
        }
        if (!pid) {
          showError(errEl, "Select a project.");
          return;
        }
        if (!fid) {
          showError(errEl, "Select who the booking is for.");
          return;
        }
        var jobVal = jobSel ? (jobSel.value || "").trim() : "";
        if (!jobVal) {
          showError(errEl, "Select a job.");
          return;
        }
        setMinDate(dateIn);
        if (dateIn.value < dateIn.min) {
          showError(errEl, "Date cannot be in the past.");
          return;
        }
        if (bookingPageSection && bookingPageSection.classList.contains("is-timeline")) {
          var innerChk = document.getElementById("booking-timeline-inner");
          var stChk = innerChk && innerChk._tmTimeline;
          if (stChk && stChk.selConflict) {
            showError(errEl, "Time slot already booked");
            return;
          }
        }
        var editBookingId = timelineFormEditId;
        var body = {
          edit_suite_id: sid,
          project_id: pid,
          booked_for_id: fid,
          booking_date: dateIn.value,
          start_time: startIn ? startIn.value : "09:00",
          is_full_day: !!(fullDay && fullDay.checked),
          notes: (notesTa && notesTa.value) || "",
          job_type: jobVal,
        };
        if (!body.is_full_day && endIn) body.end_time = endIn.value;
        if (submitBtn) submitBtn.disabled = true;
        var repeatMode = repeatSel ? (repeatSel.value || "none") : "none";
        var repeatUntil = repeatUntilIn ? repeatUntilIn.value : "";
        var datesToSave = [body.booking_date];
        if (!editBookingId && repeatMode !== "none") {
          if (!repeatUntil) {
            if (submitBtn) submitBtn.disabled = false;
            showError(errEl, "Select a repeat end date.");
            return;
          }
          if (repeatUntil < body.booking_date) {
            if (submitBtn) submitBtn.disabled = false;
            showError(errEl, "Repeat end date must be after booking date.");
            return;
          }
          var cursor = body.booking_date;
          var step = repeatMode === "weekly" ? 7 : 1;
          while (true) {
            cursor = addDays(cursor, step);
            if (!cursor || cursor > repeatUntil) break;
            datesToSave.push(cursor);
            if (datesToSave.length >= 90) break;
          }
        }

        function saveOnce(payload, bookingIdForEdit) {
          var saveUrl = bookingIdForEdit ? listUrl.replace(/\/?$/, "") + "/" + bookingIdForEdit : listUrl;
          var saveMethod = bookingIdForEdit ? "PUT" : "POST";
          return fetch(saveUrl, {
            method: saveMethod,
            headers: JSON_ACCEPT,
            credentials: "same-origin",
            body: JSON.stringify(payload),
          }).then(function (r) {
            return r.text().then(function (txt) {
              var j = {};
              if (txt) {
                try {
                  j = JSON.parse(txt);
                } catch (e) {
                  j = {
                    message:
                      "Server returned a non-JSON response (" +
                      r.status +
                      "). If this persists, check the server log.",
                  };
                }
              }
              return { ok: r.ok, j: j };
            });
          });
        }

        var savedCount = 0;
        var idx = 0;
        (function runNext() {
          var bookingIdForEdit = editBookingId && idx === 0 ? editBookingId : null;
          var payload = Object.assign({}, body, {
            booking_date: datesToSave[idx] || body.booking_date,
          });
          saveOnce(payload, bookingIdForEdit)
            .then(function (x) {
              if (!x.ok) {
                if (submitBtn) submitBtn.disabled = false;
                showError(
                  errEl,
                  (x.j && x.j.message) ||
                    (x.j && x.j.error === "conflict"
                      ? "A repeated slot overlaps another booking."
                      : "Could not book.")
                );
                reloadNotificationsAfterConflict(x);
                if (savedCount > 0 && okEl) {
                  okEl.textContent = "Saved " + savedCount + " booking(s) before stopping.";
                  okEl.hidden = false;
                }
                return;
              }
              savedCount += 1;
              bumpDashboardIfToday(x.j && x.j.booking);
              idx += 1;
              if (idx < datesToSave.length) {
                runNext();
                return;
              }
              if (submitBtn) submitBtn.disabled = false;
              if (editBookingId) exitTimelineFormEditMode();
              if (okEl) {
                okEl.textContent =
                  editBookingId
                    ? "Booking updated."
                    : datesToSave.length > 1
                    ? "Saved " + datesToSave.length + " repeated bookings."
                    : "Saved. Your lists below are updated.";
                okEl.hidden = false;
              }
              refreshLists();
            })
            .catch(function () {
              if (submitBtn) submitBtn.disabled = false;
              showError(errEl, "Network error.");
            });
        })();
      });
    }

    wireFullDay(editFull, editEnd, editEndWrap);
    var closeBtn = document.getElementById("booking-edit-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        if (window.tmShell) window.tmShell.closeInspector();
      });
    }

    var btnList = document.getElementById("booking-view-list");
    var btnTimeline = document.getElementById("booking-view-timeline");
    if (btnList) {
      btnList.addEventListener("click", function () {
        setViewMode(false);
      });
    }
    if (btnTimeline) {
      btnTimeline.addEventListener("click", function () {
        setViewMode(true);
      });
    }
    if (dateIn) {
      dateIn.addEventListener("change", function () {
        calendarAnchorDate = dateIn.value || todayISO();
        calendarMonthAnchor = startOfMonthISO(calendarAnchorDate);
        updateTimelineDateLabel();
        renderMonthCalendar();
        renderRoomList();
        updateSelectionSummary();
        refreshLists();
      });
    }
    if (calScopeSel) {
      calScopeSel.value = calendarScope;
      calScopeSel.addEventListener("change", function () {
        var v = (calScopeSel.value || "day").trim().toLowerCase();
        calendarScope = v === "week" || v === "month" ? v : "day";
        updateTimelineDateLabel();
        refreshLists();
      });
    }
    function onCalPrev() {
        calendarMonthAnchor = addMonths(calendarMonthAnchor, -1);
        if (dateIn) {
          var a = parseISODate(calendarMonthAnchor);
          if (a && dateIn.value) {
            var cur = parseISODate(dateIn.value);
            if (cur && (cur.getMonth() !== a.getMonth() || cur.getFullYear() !== a.getFullYear())) {
              dateIn.value = calendarMonthAnchor;
              calendarAnchorDate = dateIn.value;
            }
          }
        }
        renderMonthCalendar();
        updateTimelineDateLabel();
        refreshLists();
    }
    function onCalNext() {
        calendarMonthAnchor = addMonths(calendarMonthAnchor, 1);
        if (dateIn) {
          var a2 = parseISODate(calendarMonthAnchor);
          if (a2 && dateIn.value) {
            var cur2 = parseISODate(dateIn.value);
            if (cur2 && (cur2.getMonth() !== a2.getMonth() || cur2.getFullYear() !== a2.getFullYear())) {
              dateIn.value = calendarMonthAnchor;
              calendarAnchorDate = dateIn.value;
            }
          }
        }
        renderMonthCalendar();
        updateTimelineDateLabel();
        refreshLists();
    }
    function onCalToday() {
        calendarAnchorDate = todayISO();
        calendarMonthAnchor = startOfMonthISO(calendarAnchorDate);
        if (dateIn) dateIn.value = calendarAnchorDate;
        renderMonthCalendar();
        updateTimelineDateLabel();
        refreshLists();
    }
    if (calPrevBtn) calPrevBtn.addEventListener("click", onCalPrev);
    if (calPrevCenterBtn) calPrevCenterBtn.addEventListener("click", onCalPrev);
    if (calNextBtn) calNextBtn.addEventListener("click", onCalNext);
    if (calNextCenterBtn) calNextCenterBtn.addEventListener("click", onCalNext);
    if (calTodayBtn) calTodayBtn.addEventListener("click", onCalToday);
    if (calTodayCenterBtn) calTodayCenterBtn.addEventListener("click", onCalToday);

    // —— Timeline interactions (selection, hover, sync) ——
    (function wireTimelineInteractions() {
      var inner = document.getElementById("booking-timeline-inner");
      var wrap = document.getElementById("booking-timeline-wrap");
      if (!inner || !wrap) return;

      function getState() {
        return inner._tmTimeline || null;
      }

      function updateHover(e) {
        var state = getState();
        if (!state || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) return;
        if (state.isSelecting) return;
        var track = e.target && e.target.closest && e.target.closest(".booking-timeline-room-track");
        if (!track) {
          hideAllHover(state);
          return;
        }
        var sid = parseInt(track.dataset.suiteId, 10) || 0;
        var t = state.tracks[String(sid)];
        if (!t || !t.hover) return;
        hideAllHover(state);
        var startMin = minutesFromY(track, e.clientY, e.clientX);
        var endMin = clamp(roundToStep(startMin + 60, GRID_MIN), H_START * 60 + GRID_MIN, H_END * 60);
        var totalMin = (H_END - H_START) * 60;
        var leftPct = ((startMin - H_START * 60) / totalMin) * 100;
        var wPct = ((endMin - startMin) / totalMin) * 100;
        t.hover.hidden = false;
        t.hover.style.left = leftPct + "%";
        t.hover.style.width = wPct + "%";
        t.hover.style.top = "4px";
        t.hover.style.bottom = "4px";
        t.hover.style.height = "auto";
      }

      function beginSelect(e) {
        if (e.button !== 0) return;
        var state = getState();
        if (!state || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) return;
        if (e.target && e.target.closest && e.target.closest(".timeline-booking")) return;
        if (e.target && e.target.closest && e.target.closest(".resize-handle")) return;
        var track = e.target && e.target.closest && e.target.closest(".booking-timeline-room-track");
        if (!track) return;
        var sid = parseInt(track.dataset.suiteId, 10) || 0;
        if (!sid) return;
        if (timelineFormEditId) exitTimelineFormEditMode();
        state.isSelecting = true;
        state.selSuiteId = sid;
        state.selStartMin = minutesFromY(track, e.clientY, e.clientX);
        state.selEndMin = state.selStartMin;
        state.selConflict = selectionConflicts(getTimelineDate(), sid, state.selStartMin, state.selStartMin + 60, null);
        hideAllSelection(state);
        hideAllHover(state);
        highlightSelectedRoom(state, sid);
        setSelectionVisual(state, sid, state.selStartMin, state.selStartMin + 60);
        try {
          track.setPointerCapture && track.setPointerCapture(e.pointerId);
        } catch (e2) {}
        e.preventDefault();
      }

      function moveSelect(e) {
        var state = getState();
        if (!state || !state.isSelecting) {
          updateHover(e);
          return;
        }
        var t = state.tracks[String(state.selSuiteId)];
        if (!t || !t.track) return;
        var cur = minutesFromY(t.track, e.clientY, e.clientX);
        state.selEndMin = cur;
        var s = Math.min(state.selStartMin, state.selEndMin);
        var end = Math.max(state.selStartMin, state.selEndMin);
        if (end - s < GRID_MIN) end = s + GRID_MIN;
        state.selConflict = selectionConflicts(getTimelineDate(), state.selSuiteId, s, end, timelineFormEditId);
        setSelectionVisual(state, state.selSuiteId, s, end);
        refreshBookingFormSubmitState();
        syncTimelineConflictMessage();
        e.preventDefault();
      }

      function endSelect(e) {
        var state = getState();
        if (!state || !state.isSelecting) return;
        state.isSelecting = false;
        var s = Math.min(state.selStartMin, state.selEndMin);
        var end = Math.max(state.selStartMin, state.selEndMin);
        if (end - s < GRID_MIN) end = s + 60; // treat click as 1h block
        end = clamp(end, H_START * 60, H_END * 60);
        if (end <= s) end = clamp(s + 60, H_START * 60, H_END * 60);
        state.selConflict = selectionConflicts(getTimelineDate(), state.selSuiteId, s, end, timelineFormEditId);
        setSelectionVisual(state, state.selSuiteId, s, end);
        applySelectionToForm(state.selSuiteId, s, end);
        highlightSelectedRoom(state, currentSuiteId());
        refreshBookingFormSubmitState();
        syncTimelineConflictMessage();
        e.preventDefault();
      }

      // Pointer events on the whole timeline for cross-device drag.
      inner.addEventListener("pointerdown", beginSelect);
      inner.addEventListener("pointermove", moveSelect);
      inner.addEventListener("pointerup", endSelect);
      inner.addEventListener("pointercancel", endSelect);
      inner.addEventListener("mouseleave", function () {
        var state = getState();
        if (!state) return;
        if (!state.isSelecting) hideAllHover(state);
      });

      // Form ↔ timeline sync.
      function syncFromForm() {
        var state = getState();
        if (!state || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) return;
        var sid = currentSuiteId();
        highlightSelectedRoom(state, sid);
        if (!sid || !startIn || !endIn) {
          hideAllSelection(state);
          return;
        }
        var s = parseTimeToMin(startIn.value);
        var e = parseTimeToMin(endIn.value);
        if (fullDay && fullDay.checked) {
          s = H_START * 60;
          e = H_END * 60;
        }
        s = clamp(roundToStep(s, GRID_MIN), H_START * 60, H_END * 60);
        e = clamp(roundToStep(e, GRID_MIN), H_START * 60, H_END * 60);
        if (e <= s) e = clamp(s + 60, H_START * 60, H_END * 60);
        state.selSuiteId = sid;
        state.selStartMin = s;
        state.selEndMin = e;
        state.selConflict = selectionConflicts(getTimelineDate(), sid, s, e, timelineFormEditId);
        hideAllSelection(state);
        setSelectionVisual(state, sid, s, e);
        refreshBookingFormSubmitState();
        syncTimelineConflictMessage();
        updateSelectionSummary();
      }

      if (suiteSel)
        suiteSel.addEventListener("change", function () {
          activeRoomId = parseInt(suiteSel.value, 10) || 0;
          renderRoomList();
          syncFromForm();
          updateSelectionSummary();
        });
      if (startIn) {
        startIn.addEventListener("change", syncFromForm);
        startIn.addEventListener("input", syncFromForm);
        startIn.addEventListener("change", updateSelectionSummary);
      }
      if (endIn) {
        endIn.addEventListener("change", syncFromForm);
        endIn.addEventListener("input", syncFromForm);
        endIn.addEventListener("change", updateSelectionSummary);
      }
      if (fullDay) fullDay.addEventListener("change", syncFromForm);
      if (fullDay) fullDay.addEventListener("change", updateSelectionSummary);
      if (dateIn) dateIn.addEventListener("change", syncFromForm);

      // —— Pro interactions: drag/move + resize existing bookings ——
      function suiteIdFromPoint(clientX, clientY) {
        var el = document.elementFromPoint(clientX, clientY);
        var track = el && el.closest && el.closest(".booking-timeline-room-track");
        if (!track) return 0;
        return parseInt(track.dataset.suiteId, 10) || 0;
      }

      function trackElForSuite(state, suiteId) {
        var t = state && state.tracks && state.tracks[String(suiteId)];
        return t && t.track ? t.track : null;
      }

      function setBlockPreview(blk, suiteId, startMin, endMin, conflict) {
        if (!blk) return;
        var totalMin = (H_END - H_START) * 60;
        var s = clamp(Math.min(startMin, endMin), H_START * 60, H_END * 60);
        var e = clamp(Math.max(startMin, endMin), H_START * 60, H_END * 60);
        if (e <= s) e = clamp(s + GRID_MIN, H_START * 60, H_END * 60);
        var leftPct = ((s - H_START * 60) / totalMin) * 100;
        var wPct = ((e - s) / totalMin) * 100;
        blk.style.left = leftPct + "%";
        blk.style.width = wPct + "%";
        blk.style.top = "4px";
        blk.style.bottom = "4px";
        blk.style.height = "auto";
        blk.classList.toggle("conflict", !!conflict);
        var data = blk._bookingData || {};
        var proj = blk.querySelector('[data-role="project"]');
        var time = blk.querySelector('[data-role="time"]');
        if (proj) proj.textContent = ((data.project_name || "").trim() || "Project").slice(0, 48);
        if (time) time.textContent = minToHHMM(s) + " → " + minToHHMM(e);
      }

      function beginBookingDrag(e) {
        if (e.button !== 0) return;
        var state = getState();
        if (!state || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) return;
        var blk = e.target && e.target.closest && e.target.closest(".timeline-booking");
        if (!blk) return;
        var data = blk._bookingData;
        if (!data) return;
        if (data.timeline_masked) return;

        // Ignore when user is selection-dragging on the track.
        if (state.isSelecting) return;

        var handle = e.target && e.target.closest && e.target.closest(".resize-handle");
        var mode = handle ? (handle.classList.contains("top") ? "resize-top" : "resize-bottom") : "move";

        var origSuiteId = parseInt(data.edit_suite_id, 10) || 0;
        var origStart = parseTimeToMin(data.start_time);
        var origEnd = parseTimeToMin(data.end_time);
        if (!origSuiteId || !origStart || !origEnd) return;

        var trackEl = trackElForSuite(state, origSuiteId);
        if (!trackEl) return;

        var downMin = minutesFromY(trackEl, e.clientY, e.clientX);
        var offset = downMin - origStart;

        state.drag = {
          blk: blk,
          id: data.id,
          mode: mode,
          orig: {
            suiteId: origSuiteId,
            start: origStart,
            end: origEnd,
          },
          cur: {
            suiteId: origSuiteId,
            start: origStart,
            end: origEnd,
          },
          offsetMin: offset,
          moved: false,
          conflict: false,
        };

        blk.classList.add("dragging");
        blk._tmSuppressClick = false;
        highlightSelectedRoom(state, origSuiteId);
        hideAllHover(state);
        try {
          blk.setPointerCapture && blk.setPointerCapture(e.pointerId);
        } catch (e2) {}
        e.stopPropagation();
        e.preventDefault();
      }

      function moveBookingDrag(e) {
        var state = getState();
        if (!state || !state.drag) return;
        var d = state.drag;
        var blk = d.blk;
        if (!blk) return;

        var targetSuiteId = d.cur.suiteId;
        if (d.mode === "move") {
          var sid = suiteIdFromPoint(e.clientX, e.clientY);
          if (sid) targetSuiteId = sid;
        }
        var trackEl = trackElForSuite(state, targetSuiteId);
        if (!trackEl) trackEl = trackElForSuite(state, d.cur.suiteId);
        if (!trackEl) return;

        var curMin = minutesFromY(trackEl, e.clientY, e.clientX);
        var s = d.cur.start;
        var en = d.cur.end;
        if (d.mode === "move") {
          var dur = d.orig.end - d.orig.start;
          s = roundToStep(curMin - d.offsetMin, GRID_MIN);
          s = clamp(s, H_START * 60, H_END * 60 - GRID_MIN);
          en = clamp(s + dur, H_START * 60 + GRID_MIN, H_END * 60);
          if (en <= s) en = clamp(s + GRID_MIN, H_START * 60 + GRID_MIN, H_END * 60);
        } else if (d.mode === "resize-top") {
          s = roundToStep(curMin, GRID_MIN);
          s = clamp(s, H_START * 60, d.cur.end - GRID_MIN);
        } else if (d.mode === "resize-bottom") {
          en = roundToStep(curMin, GRID_MIN);
          en = clamp(en, d.cur.start + GRID_MIN, H_END * 60);
        }

        d.cur.suiteId = targetSuiteId;
        d.cur.start = s;
        d.cur.end = en;
        d.moved = true;

        d.conflict = selectionConflicts(getTimelineDate(), targetSuiteId, s, en, d.id);
        blk.style.cursor = d.conflict ? "not-allowed" : "grabbing";
        setBlockPreview(blk, targetSuiteId, s, en, d.conflict);
        highlightSelectedRoom(state, targetSuiteId);
        e.preventDefault();
      }

      function commitBookingDrag(e) {
        var state = getState();
        if (!state || !state.drag) return;
        var d = state.drag;
        var blk = d.blk;
        state.drag = null;
        if (!blk) return;

        blk.classList.remove("dragging");
        blk.style.cursor = "";

        // If user just clicked without moving, allow click handler to open edit.
        if (!d.moved) {
          return;
        }
        blk._tmSuppressClick = true;

        // Revert if conflict.
        if (d.conflict) {
          setBlockPreview(blk, d.orig.suiteId, d.orig.start, d.orig.end, false);
          // Refresh label back to start+project
          renderTimeline();
          return;
        }

        var data = blk._bookingData;
        if (!data) {
          renderTimeline();
          return;
        }

        // Send update via existing PUT API.
        var body = {
          edit_suite_id: d.cur.suiteId,
          project_id: parseInt(data.project_id, 10) || parseInt(data.edit_project_id || 0, 10) || data.project_id,
          booked_for_id: parseInt(data.booked_for_id, 10) || 0,
          booking_date: getTimelineDate(),
          start_time: minToHHMM(d.cur.start),
          end_time: minToHHMM(d.cur.end),
          is_full_day: false,
          notes: (data.notes || "").trim(),
        };
        var dragJob = (data.job_type || "").trim();
        if (dragJob) body.job_type = dragJob;
        // Some payloads use edit_* keys from booking edit lists; preserve if present.
        if (data.project_id) body.project_id = parseInt(data.project_id, 10) || body.project_id;
        if (data.booked_for_id) body.booked_for_id = parseInt(data.booked_for_id, 10) || body.booked_for_id;
        if (data.edit_project_id) body.project_id = parseInt(data.edit_project_id, 10) || body.project_id;

        fetch(listUrl.replace(/\/?$/, "") + "/" + data.id, {
          method: "PUT",
          headers: JSON_ACCEPT,
          credentials: "same-origin",
          body: JSON.stringify(body),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (!x.ok) {
              // Revert on failure.
              setBlockPreview(blk, d.orig.suiteId, d.orig.start, d.orig.end, false);
              showError(listsErr, (x.j && x.j.message) || "Could not move booking.");
              return;
            }
            // Update local data so we don't need a full rebuild; still refresh lists for consistency.
            try {
              data.edit_suite_id = d.cur.suiteId;
              data.booking_date = getTimelineDate();
              data.start_time = minToHHMM(d.cur.start);
              data.end_time = minToHHMM(d.cur.end);
              data.is_full_day = false;
            } catch (e2) {}
            refreshLists();
            bumpDashboardIfToday(x.j && x.j.booking);
          })
          .catch(function () {
            setBlockPreview(blk, d.orig.suiteId, d.orig.start, d.orig.end, false);
            showError(listsErr, "Network error.");
          });
      }

      inner.addEventListener("pointerdown", function (e) {
        // booking block takes precedence over selection.
        if (e.target && e.target.closest && e.target.closest(".timeline-booking")) {
          beginBookingDrag(e);
        }
      }, true);
      inner.addEventListener("pointermove", moveBookingDrag, true);
      inner.addEventListener("pointerup", commitBookingDrag, true);
      inner.addEventListener("pointercancel", commitBookingDrag, true);
    })();
    if (editForm) {
      editForm.addEventListener("submit", function (e) {
        e.preventDefault();
        showError(editErr, "");
        var id = parseInt(editId.value, 10);
        if (!id) return;
        setMinDate(editDate);
        if (editDate.value < editDate.min) {
          showError(editErr, "Date cannot be in the past.");
          return;
        }
        if (!(editJob && (editJob.value || "").trim())) {
          showError(editErr, "Select a job.");
          return;
        }
        var body = {
          edit_suite_id: parseInt(editSuite.value, 10),
          project_id: parseInt(editProject.value, 10),
          booked_for_id: parseInt(editBookedFor.value, 10),
          booking_date: editDate.value,
          start_time: editStart.value,
          is_full_day: editFull.checked,
          notes: (editNotes && editNotes.value) || "",
          job_type: (editJob && editJob.value) || "",
        };
        if (!body.is_full_day) body.end_time = editEnd.value;
        fetch(listUrl.replace(/\/?$/, "") + "/" + id, {
          method: "PUT",
          headers: JSON_ACCEPT,
          credentials: "same-origin",
          body: JSON.stringify(body),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (!x.ok) {
              showError(
                editErr,
                (x.j && x.j.message) ||
                  (x.j && x.j.error === "conflict" ? "That slot overlaps another booking." : "Could not save.")
              );
              reloadNotificationsAfterConflict(x);
              return;
            }
            if (window.tmShell) window.tmShell.closeInspector();
            refreshLists();
            bumpDashboardIfToday(x.j && x.j.booking);
          })
          .catch(function () {
            showError(editErr, "Network error.");
          });
      });
    }

    loadMeta(function () {
      updateTimelineDateLabel();
      refreshLists();
    });
  }

  function initControlSuites() {
    var listEl = document.getElementById("edit-suites-list");
    var emptyEl = document.getElementById("edit-suites-empty");
    var errEl = document.getElementById("edit-suites-error");
    var addBtn = document.getElementById("edit-suite-add-btn");
    var modal = document.getElementById("edit-suite-modal");
    var modalTitle = document.getElementById("edit-suite-modal-title");
    var nameInput = document.getElementById("edit-suite-name");
    var saveBtn = document.getElementById("edit-suite-save");
    var cancelBtn = document.getElementById("edit-suite-cancel");
    var editingId = null;
    var base = (addBtn && addBtn.getAttribute("data-api-base")) || "/booking/edit-suites";
    if (!listEl || !modal) return;

    function toggleEmpty(n) {
      if (emptyEl) emptyEl.hidden = n > 0;
    }

    var suiteOpts = {
      admin: true,
      onEdit: function (s) {
        editingId = s.id;
        if (modalTitle) modalTitle.textContent = "Edit suite";
        if (nameInput) nameInput.value = s.name || "";
        if (modal.showModal) modal.showModal();
      },
      onDelete: function (s) {
        if (!s.is_active) return;
        if (!window.confirm("Deactivate this suite? It will no longer appear for new bookings.")) return;
        fetch(base + "/" + s.id, {
          method: "DELETE",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (!x.ok) {
              showError(errEl, (x.j && x.j.message) || "Could not delete.");
              return;
            }
            load();
          })
          .catch(function () {
            showError(errEl, "Network error.");
          });
      },
    };

    function load() {
      showError(errEl, "");
      fetch(base + "?all=1", { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var suites = (j && j.suites) || [];
          toggleEmpty(suites.length);
          renderSuites(listEl, suites, suiteOpts);
        })
        .catch(function () {
          showError(errEl, "Could not load suites.");
        });
    }

    function closeModal() {
      editingId = null;
      if (modal) modal.close();
      if (nameInput) nameInput.value = "";
    }

    if (addBtn) {
      addBtn.addEventListener("click", function () {
        editingId = null;
        if (modalTitle) modalTitle.textContent = "Add suite";
        if (nameInput) nameInput.value = "";
        if (modal.showModal) modal.showModal();
      });
    }
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var name = (nameInput && nameInput.value.trim()) || "";
        if (!name) return;
        showError(errEl, "");
        if (editingId == null) {
          fetch(base, {
            method: "POST",
            headers: JSON_ACCEPT,
            credentials: "same-origin",
            body: JSON.stringify({ name: name }),
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(errEl, (x.j && x.j.message) || "Could not add.");
                return;
              }
              closeModal();
              load();
            })
            .catch(function () {
              showError(errEl, "Network error.");
            });
        } else {
          fetch(base + "/" + editingId, {
            method: "PUT",
            headers: JSON_ACCEPT,
            credentials: "same-origin",
            body: JSON.stringify({ name: name }),
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(errEl, (x.j && x.j.message) || "Could not save.");
                return;
              }
              closeModal();
              load();
            })
            .catch(function () {
              showError(errEl, "Network error.");
            });
        }
      });
    }

    load();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initDashboardCard();
    var root = document.getElementById("booking-page-root");
    if (root) initBookingPage(root);
    if (document.getElementById("edit-suites-list")) initControlSuites();
  });

  window.renderSuites = renderSuites;
  window.renderBookings = renderBookings;
  window.renderDashboardBooking = renderDashboardBooking;
})();
