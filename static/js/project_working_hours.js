(function () {
  "use strict";

  var root = document.getElementById("project-working-hours-root");
  if (!root) return;

  var manualDialog = document.getElementById("working-hours-manual-dialog");
  var billableDialog = document.getElementById("working-hours-billable-dialog");
  var billableForm = document.getElementById("working-hours-billable-form");
  var billableContext = document.getElementById("working-hours-billable-context");
  var pendingDialog = document.getElementById("working-hours-pending-edit-dialog");
  var pendingForm = document.getElementById("working-hours-pending-edit-form");
  var pendingWho = document.getElementById("working-hours-pending-edit-who");
  var pendingMeta = document.getElementById("working-hours-pending-edit-meta");
  var pendingTitle = document.getElementById("working-hours-pending-edit-title");
  var rateCardDialog = document.getElementById("working-hours-rate-card-dialog");
  var rateCardRows = document.getElementById("working-hours-rate-card-rows");
  var rateCardRowTemplate = document.getElementById("working-hours-rate-card-row-template");
  var worksheetDialog = document.getElementById("working-hours-worksheet-dialog");
  var worksheetBtn = document.getElementById("working-hours-worksheet-btn");
  var worksheetFrame = document.getElementById("working-hours-worksheet-frame");
  var worksheetStatus = document.getElementById("working-hours-worksheet-status");
  var worksheetDownload = document.getElementById("working-hours-worksheet-download");
  var worksheetObjectUrl = null;
  var durationWheel = document.getElementById("working-hours-duration");
  var manualBillableWheel = document.getElementById("working-hours-manual-billable");
  var billableWheel = document.getElementById("working-hours-billable-wheel");
  var pendingActualWheel = document.getElementById("working-hours-pending-actual");
  var pendingBillableWheel = document.getElementById("working-hours-pending-billable");

  function open(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "open");
  }

  // Wheels position themselves by scrollTop, which only works once the dialog
  // is on screen, so every wheel is seeded after the dialog opens.
  function setWheel(wheel, totalMinutes) {
    if (!wheel || !window.Dts) return;
    window.Dts.setTotalMinutes(wheel, totalMinutes);
  }

  function close(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function revokeWorksheetPreview() {
    if (worksheetObjectUrl) {
      try {
        URL.revokeObjectURL(worksheetObjectUrl);
      } catch (err) {}
      worksheetObjectUrl = null;
    }
    if (worksheetFrame) {
      worksheetFrame.onload = null;
      worksheetFrame.onerror = null;
      worksheetFrame.removeAttribute("src");
      worksheetFrame.hidden = true;
    }
    if (worksheetDownload) {
      worksheetDownload.hidden = true;
    }
  }

  function setWorksheetStatus(message, isError) {
    if (!worksheetStatus) return;
    if (!message) {
      worksheetStatus.hidden = true;
      worksheetStatus.textContent = "";
      worksheetStatus.classList.remove("is-error");
      return;
    }
    worksheetStatus.hidden = false;
    worksheetStatus.textContent = message;
    worksheetStatus.classList.toggle("is-error", !!isError);
  }

  function withPreviewParam(url) {
    var next = String(url || "");
    if (!next) return next;
    return next + (next.indexOf("?") >= 0 ? "&" : "?") + "preview=1";
  }

  function openWorksheetPreview() {
    if (!worksheetDialog || !worksheetBtn) return;
    var exportUrl = worksheetBtn.getAttribute("data-worksheet-url") || "";
    if (!exportUrl) return;
    revokeWorksheetPreview();
    setWorksheetStatus("Loading worksheet preview…", false);
    open(worksheetDialog);

    var previewUrl = withPreviewParam(exportUrl);
    if (worksheetDownload) {
      worksheetDownload.href = exportUrl;
    }

    // Load a server-rendered HTML preview (page images). Raw PDF blobs stay
    // blank in browsers without a built-in PDF viewer (e.g. Cursor preview).
    if (worksheetFrame) {
      worksheetFrame.onload = function () {
        setWorksheetStatus("", false);
        if (worksheetDownload) worksheetDownload.hidden = false;
        worksheetFrame.hidden = false;
      };
      worksheetFrame.onerror = function () {
        revokeWorksheetPreview();
        setWorksheetStatus("Could not load Daily Worksheet preview.", true);
      };
      worksheetFrame.src = previewUrl;
      worksheetFrame.hidden = false;
    }
  }

  var addBtn = document.getElementById("working-hours-add-btn");
  if (addBtn) {
    addBtn.addEventListener("click", function () {
      open(manualDialog);
      setWheel(durationWheel, 60);
      setWheel(manualBillableWheel, 0);
    });
  }

  var rateCardCurrency = document.getElementById("working-hours-rate-card-currency");
  var rateCardExport = document.getElementById("working-hours-rate-card-export");

  function syncRateCardExportHref() {
    if (!rateCardExport) return;
    var base = rateCardExport.getAttribute("data-export-base") || rateCardExport.getAttribute("href") || "";
    if (!base) return;
    var currency = rateCardCurrency ? String(rateCardCurrency.value || "").trim().toUpperCase() : "";
    var path = String(base).split("?")[0];
    rateCardExport.setAttribute(
      "href",
      currency ? path + "?currency=" + encodeURIComponent(currency) : path
    );
  }

  if (rateCardCurrency) {
    rateCardCurrency.addEventListener("change", syncRateCardExportHref);
  }
  syncRateCardExportHref();

  var rateCardBtn = document.getElementById("working-hours-rate-card-btn");
  if (rateCardBtn) {
    rateCardBtn.addEventListener("click", function () {
      syncRateCardExportHref();
      open(rateCardDialog);
    });
  }

  if (worksheetBtn) {
    worksheetBtn.addEventListener("click", function () {
      openWorksheetPreview();
    });
  }

  if (worksheetDialog) {
    worksheetDialog.addEventListener("close", function () {
      revokeWorksheetPreview();
      setWorksheetStatus("", false);
    });
  }

  var rateCardAddRow = document.getElementById("working-hours-rate-card-add-row");

  function syncRateCardRemoveButtons() {
    if (!rateCardRows) return;
    var rows = rateCardRows.querySelectorAll("tr.project-working-hours-rate-card-row");
    var disable = rows.length <= 1;
    for (var i = 0; i < rows.length; i += 1) {
      var btn = rows[i].querySelector("[data-rate-card-remove]");
      if (btn) btn.disabled = disable;
    }
  }

  if (rateCardAddRow && rateCardRows && rateCardRowTemplate) {
    rateCardAddRow.addEventListener("click", function () {
      var fragment = rateCardRowTemplate.content.cloneNode(true);
      rateCardRows.appendChild(fragment);
      syncRateCardRemoveButtons();
      var inputs = rateCardRows.querySelectorAll("tr:last-child input[name='service_name']");
      if (inputs.length) inputs[inputs.length - 1].focus();
    });
  }

  if (rateCardRows) {
    syncRateCardRemoveButtons();

    rateCardRows.addEventListener("click", function (event) {
      var removeBtn = event.target.closest("[data-rate-card-remove]");
      if (!removeBtn || removeBtn.disabled) return;
      event.preventDefault();
      var row = removeBtn.closest("tr.project-working-hours-rate-card-row");
      if (!row || row.getAttribute("data-rate-card-locked") === "1") return;
      var rows = rateCardRows.querySelectorAll("tr.project-working-hours-rate-card-row");
      if (rows.length <= 1) return;
      var deleteUrl = (removeBtn.getAttribute("data-delete-url") || "").trim();
      var entityId = (removeBtn.getAttribute("data-entity-id") || "").trim();
      var nameInput = row.querySelector("input[name='service_name']");
      var serviceName = nameInput ? String(nameInput.value || "").trim() : "";
      var form = document.getElementById("working-hours-rate-card-form");
      var projectId = form ? form.getAttribute("data-project-id") : "";

      function dropRow() {
        row.remove();
        syncRateCardRemoveButtons();
      }

      if (deleteUrl && entityId && window.SafeDelete && typeof window.SafeDelete.open === "function") {
        window.SafeDelete.open({
          entityType: "rate_card_item",
          entityId: entityId,
          entityName: serviceName || "Rate card service",
          entityLabel: "Rate card service",
          projectId: projectId || null,
          deleteUrl: deleteUrl,
          warningText: "This removes the service from the studio rate card. Save is not required — this cannot be undone.",
          confirmButtonLabel: "Delete Permanently",
          onSuccess: dropRow,
        });
        return;
      }
      dropRow();
    });

    rateCardRows.addEventListener("change", function (event) {
      var includeRoot = event.target.closest("[data-rate-card-include]");
      if (!includeRoot) return;
      var checkbox = includeRoot.querySelector('input[type="checkbox"]');
      var row = includeRoot.closest("tr");
      if (!checkbox || !row) return;
      var hidden = row.querySelector('input[name="include_in_pdf"]');
      if (hidden) hidden.value = checkbox.checked ? "1" : "0";
      includeRoot.classList.toggle("is-selected", checkbox.checked);
    });

    rateCardRows.addEventListener("beforeinput", function (event) {
      var input = event.target.closest("[data-rate-card-number]");
      if (!input) return;
      if (event.inputType && event.inputType.indexOf("delete") === 0) return;
      if (event.inputType === "historyUndo" || event.inputType === "historyRedo") return;
      var data = event.data == null ? "" : String(event.data);
      if (data && /\D/.test(data)) event.preventDefault();
    });

    rateCardRows.addEventListener("input", function (event) {
      var input = event.target.closest("[data-rate-card-number]");
      if (!input) return;
      var cleaned = String(input.value || "").replace(/\D+/g, "");
      if (input.value !== cleaned) input.value = cleaned;
    });

    rateCardRows.addEventListener("paste", function (event) {
      var input = event.target.closest("[data-rate-card-number]");
      if (!input) return;
      event.preventDefault();
      var text = "";
      try {
        text = (event.clipboardData || window.clipboardData).getData("text") || "";
      } catch (err) {
        text = "";
      }
      var digits = String(text).replace(/\D+/g, "");
      var start = input.selectionStart == null ? input.value.length : input.selectionStart;
      var end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
      var next = input.value.slice(0, start) + digits + input.value.slice(end);
      input.value = next.replace(/\D+/g, "");
    });
  }

  root.addEventListener("click", function (event) {
    var closeManual = event.target.closest("[data-close-manual]");
    if (closeManual) {
      event.preventDefault();
      close(manualDialog);
      return;
    }
    var closeBillable = event.target.closest("[data-close-billable]");
    if (closeBillable) {
      event.preventDefault();
      close(billableDialog);
      return;
    }
    var closePending = event.target.closest("[data-close-pending-edit]");
    if (closePending) {
      event.preventDefault();
      close(pendingDialog);
      return;
    }
    var closeRateCard = event.target.closest("[data-close-rate-card]");
    if (closeRateCard) {
      event.preventDefault();
      close(rateCardDialog);
      return;
    }
    var closeWorksheet = event.target.closest("[data-close-worksheet]");
    if (closeWorksheet) {
      event.preventDefault();
      close(worksheetDialog);
      return;
    }

    var pendingTrigger = event.target.closest("[data-pending-edit]");
    if (pendingTrigger && pendingForm) {
      event.preventDefault();
      var actual = parseInt(pendingTrigger.getAttribute("data-pending-actual"), 10) || 0;
      var billable = parseInt(pendingTrigger.getAttribute("data-pending-billable"), 10) || 0;
      pendingForm.setAttribute("action", pendingTrigger.getAttribute("data-pending-url") || "");
      if (pendingWho) {
        pendingWho.textContent = pendingTrigger.getAttribute("data-pending-who") || "";
      }
      if (pendingMeta) {
        pendingMeta.textContent = pendingTrigger.getAttribute("data-pending-meta") || "";
      }
      if (pendingTitle) {
        pendingTitle.value = pendingTrigger.getAttribute("data-pending-title") || "";
      }
      open(pendingDialog);
      setWheel(pendingActualWheel, actual);
      setWheel(pendingBillableWheel, billable > 0 ? billable : actual);
      return;
    }

    var trigger = event.target.closest("[data-billable-edit]");
    if (!trigger || !billableForm) return;
    event.preventDefault();
    var minutes = parseInt(trigger.getAttribute("data-billable-minutes"), 10) || 0;
    billableForm.setAttribute("action", trigger.getAttribute("data-billable-url") || "");
    if (billableContext) {
      billableContext.textContent = trigger.getAttribute("data-billable-title") || "";
    }
    open(billableDialog);
    setWheel(billableWheel, minutes);
  });

  // A date input only opens its calendar from the icon; let the whole box do it.
  root.addEventListener("click", function (event) {
    var input = event.target.closest("[data-open-picker]");
    if (!input || typeof input.showPicker !== "function") return;
    try {
      input.showPicker();
    } catch (e) {
      // Chrome throws when not user-activated; the icon still works.
    }
  });

  // Filters submit on change so the page behaves like the rest of the project pages.
  var filterForm = root.querySelector(".project-working-hours-filters");
  if (filterForm) {
    filterForm.addEventListener("change", function (event) {
      if (event.target.closest("select, input[type=date]")) filterForm.submit();
    });
  }

  // Group-by lives in the log toolbar but posts with the filter form.
  var groupBy = document.getElementById("working-hours-group-by");
  if (groupBy && filterForm) {
    groupBy.addEventListener("change", function () {
      filterForm.submit();
    });
  }
})();
