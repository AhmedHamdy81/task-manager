/**
 * Format naive datetimes from the API (stored as Africa/Cairo wall clock).
 * No timeZone conversion — values are shown in the browser's local interpretation
 * of the same calendar / clock fields (use a Cairo-set device for exact match).
 */
(function (global) {
  "use strict";

  /**
   * Parse API datetime strings. Naive "YYYY-MM-DDTHH:mm:ss" is treated as local wall
   * time (not UTC), matching server-stored Cairo naive columns.
   */
  function parseStoredInstant(s) {
    if (s == null || s === "") return null;
    if (typeof s === "number" && isFinite(s)) {
      var dn = new Date(s);
      return isNaN(dn.getTime()) ? null : dn;
    }
    var str = String(s).trim();
    if (!str) return null;
    if (/^\d+$/.test(str)) {
      var dnum = new Date(parseInt(str, 10));
      return isNaN(dnum.getTime()) ? null : dnum;
    }
    var normalized = str.indexOf("T") >= 0 ? str : str.replace(" ", "T");
    if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
      var d0 = new Date(normalized + "T00:00:00");
      return isNaN(d0.getTime()) ? null : d0;
    }
    if (/Z$/i.test(normalized) || /[+\-]\d{2}:\d{2}$/.test(normalized) || /[+\-]\d{4}$/.test(normalized)) {
      var d1 = new Date(normalized);
      return isNaN(d1.getTime()) ? null : d1;
    }
    var d2 = new Date(normalized);
    return isNaN(d2.getTime()) ? null : d2;
  }

  function instantMs(s) {
    var d = parseStoredInstant(s);
    return d ? d.getTime() : 0;
  }

  /** Value for HTML <time datetime="…"> (naive ISO from server, no Z). */
  function utcIsoForAttr(s) {
    var str = String(s || "").trim().replace(" ", "T");
    if (!str) return "";
    if (/Z$/i.test(str) || /[+\-]\d{2}:\d{2}$/.test(str)) {
      var d = parseStoredInstant(s);
      return d ? d.toISOString() : str;
    }
    return str.length >= 19 ? str.slice(0, 19) : str;
  }

  function formatDateTimeCairo(iso) {
    var d = parseStoredInstant(iso);
    if (!d) return iso ? String(iso) : "";
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function formatTimeCairo(iso) {
    var d = parseStoredInstant(iso);
    if (!d) return iso ? String(iso) : "";
    return d.toLocaleString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function formatLocalTime(utcString) {
    return formatTimeCairo(utcString);
  }

  function formatDigitalClockCairo() {
    return new Date().toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function formatDashboardDateCairo() {
    return new Date().toLocaleDateString("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  }

  global.tmDateTime = {
    parseUtcInstant: parseStoredInstant,
    instantMs: instantMs,
    utcIsoForAttr: utcIsoForAttr,
    formatLocalTime: formatLocalTime,
    formatDateTimeCairo: formatDateTimeCairo,
    formatTimeCairo: formatTimeCairo,
    formatDigitalClockCairo: formatDigitalClockCairo,
    formatDashboardDateCairo: formatDashboardDateCairo,
  };
})(typeof window !== "undefined" ? window : self);
