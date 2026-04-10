(function () {
  var root = document.getElementById('production-day-app');
  if (!root) return;

  var projectId = root.getAttribute('data-project-id');
  var dayId = root.getAttribute('data-day-id');
  var rowsCreateUrl = root.getAttribute('data-rows-create-url');
  var tbody = document.getElementById('production-scenes-tbody');
  var totalEl = document.getElementById('production-duration-total');
  var addBtn = document.getElementById('production-add-row-btn');

  function rowPatchUrl(rowId) {
    return '/projects/' + projectId + '/production/scene-rows/' + rowId;
  }

  function parseDurationInput(s) {
    s = (s || '').trim();
    if (!s) return 0;
    if (/^\d+$/.test(s)) return Math.max(0, parseInt(s, 10));
    var parts = s.split(':').map(function (x) { return x.trim(); });
    try {
      if (parts.length === 2) {
        return Math.max(0, parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10));
      }
      if (parts.length === 3) {
        return Math.max(0, parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseInt(parts[2], 10));
      }
    } catch (e) {}
    return 0;
  }

  function formatMmss(sec) {
    sec = Math.max(0, Math.floor(sec));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function formatTotal(sec) {
    sec = Math.max(0, Math.floor(sec));
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function setTotalFromServer(sec) {
    if (totalEl) totalEl.textContent = formatTotal(sec);
  }

  function localSumDurations() {
    var sum = 0;
    if (!tbody) return sum;
    tbody.querySelectorAll('.production-duration-input').forEach(function (inp) {
      sum += parseDurationInput(inp.value);
    });
    return sum;
  }

  function refreshTotalDisplay() {
    if (totalEl) totalEl.textContent = formatTotal(localSumDurations());
  }

  function patchRow(rowId, body) {
    return fetch(rowPatchUrl(rowId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) throw new Error('save');
      return res.json();
    });
  }

  function bindTextField(input, field) {
    var rowId = input.closest('tr').getAttribute('data-row-id');
    if (!rowId) return;
    var t;
    input.addEventListener('input', function () {
      if (field === 'duration') refreshTotalDisplay();
    });
    input.addEventListener('blur', function () {
      clearTimeout(t);
      t = setTimeout(function () {
        var payload = {};
        if (field === 'duration') {
          payload.duration_seconds = parseDurationInput(input.value);
          input.value = formatMmss(payload.duration_seconds);
        } else {
          payload[field] = input.value;
        }
        patchRow(rowId, payload)
          .then(function (data) {
            setTotalFromServer(data.total_seconds);
          })
          .catch(function () {});
      }, 200);
    });
  }

  function bindCheckbox(box, field) {
    var rowId = box.closest('tr').getAttribute('data-row-id');
    if (!rowId) return;
    box.addEventListener('change', function () {
      var payload = {};
      payload[field] = !!box.checked;
      patchRow(rowId, payload)
        .then(function (data) {
          setTotalFromServer(data.total_seconds);
        })
        .catch(function () {
          box.checked = !box.checked;
        });
    });
  }

  function bindRemove(btn) {
    var tr = btn.closest('tr');
    var rowId = tr && tr.getAttribute('data-row-id');
    if (!rowId) return;
    btn.addEventListener('click', function () {
      if (!window.confirm('Remove this row?')) return;
      fetch(rowPatchUrl(rowId), { method: 'DELETE', headers: { Accept: 'application/json' } })
        .then(function (res) {
          if (!res.ok) throw new Error('del');
          return res.json();
        })
        .then(function (data) {
          tr.remove();
          setTotalFromServer(data.total_seconds);
          refreshTotalDisplay();
        })
        .catch(function () {});
    });
  }

  function bindRow(tr) {
    tr.querySelectorAll('.production-field').forEach(function (inp) {
      var field = inp.getAttribute('data-field');
      if (!field) return;
      if (field === 'sync' || field === 'first_edit' || field === 'final_edit') return;
      bindTextField(inp, field);
    });
    tr.querySelectorAll('.production-chk').forEach(function (box) {
      var field = box.getAttribute('data-field');
      if (field) bindCheckbox(box, field);
    });
    var rm = tr.querySelector('.production-row-remove');
    if (rm) bindRemove(rm);
  }

  if (tbody) {
    tbody.querySelectorAll('.production-scene-tr').forEach(bindRow);
  }

  function appendRowFromServer(row) {
    var tr = document.createElement('tr');
    tr.className = 'production-scene-tr';
    tr.setAttribute('data-row-id', String(row.id));
    tr.innerHTML =
      '<td><input type="text" class="input input--table production-field" data-field="episode" value="' +
      escapeAttr(row.episode) +
      '" maxlength="120" aria-label="Episode"></td>' +
      '<td><input type="text" class="input input--table production-field" data-field="scene" value="' +
      escapeAttr(row.scene) +
      '" maxlength="120" aria-label="Scene"></td>' +
      '<td class="production-chk-cell"><input type="checkbox" class="production-chk" data-field="sync"' +
      (row.sync ? ' checked' : '') +
      ' aria-label="Sync"></td>' +
      '<td class="production-chk-cell"><input type="checkbox" class="production-chk" data-field="first_edit"' +
      (row.first_edit ? ' checked' : '') +
      ' aria-label="First edit"></td>' +
      '<td class="production-chk-cell"><input type="checkbox" class="production-chk" data-field="final_edit"' +
      (row.final_edit ? ' checked' : '') +
      ' aria-label="Final edit"></td>' +
      '<td><input type="text" class="input input--table production-field production-duration-input" data-field="duration" value="' +
      escapeAttr(formatMmss(row.duration_seconds)) +
      '" inputmode="numeric" placeholder="MM:SS" aria-label="Duration"></td>' +
      '<td><input type="text" class="input input--table production-field" data-field="notes" value="' +
      escapeAttr(row.notes) +
      '" maxlength="8000" aria-label="Notes"></td>' +
      '<td><button type="button" class="btn btn--small btn--ghost production-row-remove" title="Remove row">×</button></td>';
    tbody.appendChild(tr);
    bindRow(tr);
  }

  function escapeAttr(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  if (addBtn && rowsCreateUrl) {
    addBtn.addEventListener('click', function () {
      fetch(rowsCreateUrl, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      })
        .then(function (res) {
          if (!res.ok) throw new Error('add');
          return res.json();
        })
        .then(function (data) {
          appendRowFromServer(data.row);
          setTotalFromServer(data.total_seconds);
        })
        .catch(function () {});
    });
  }
})();
