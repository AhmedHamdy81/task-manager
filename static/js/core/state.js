/**
 * Admin "All tasks" state: single source of truth + pub/sub.
 * UI updates via subscribe() → notify() after setState (non-silent).
 */
(function (global) {
  "use strict";

  global.TM = global.TM || {};

  var listeners = [];

  var state = {
    tasks: [],
    filteredTasks: [],
    searchQuery: "",
    sortBy: null,
    sortOrder: "asc",
    page: 1,
    pageSize: 20,
    taskStatus: "",
    apiUrl: "/api/tasks",
    controlPanelPath: "/control",
    loading: false,
    error: null,
  };

  function notify() {
    for (var i = 0; i < listeners.length; i++) {
      try {
        listeners[i](state);
      } catch (e) {
        console.error(e);
      }
    }
  }

  global.TM.adminTasks = {
    getState: function () {
      return state;
    },

    /**
     * @param {object} partial
     * @param {{ silent?: boolean }} [opts] — silent: merge only, no derive/notify/render
     */
    setState: function (partial, opts) {
      Object.assign(state, partial);
      if (opts && opts.silent) {
        return;
      }
      if (typeof global.TM.refreshAdminTasksDerived === "function") {
        global.TM.refreshAdminTasksDerived(state);
      }
      notify();
    },

    subscribe: function (fn) {
      if (typeof fn !== "function") {
        return function () {};
      }
      listeners.push(fn);
      return function () {
        listeners = listeners.filter(function (x) {
          return x !== fn;
        });
      };
    },

    notify: notify,
  };
})(typeof window !== "undefined" ? window : global);
