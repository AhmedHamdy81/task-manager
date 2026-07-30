# Project Log Book (Activity Audit)

Operational, append-only audit trail for meaningful project actions.

## Adding a new event type

1. Add a constant to `project_activity_events.py` (format: `module.entity.action`).
2. Add it to `ALL_EVENT_TYPES`.
3. Optionally extend `build_summary()` in `project_activity_service.py`.
4. Call the logger from the mutation site (prefer `project_activity_hooks.py`).

Do not invent ad-hoc event strings in route files.

## Calling the logger

```python
from flask import current_app

log = current_app.extensions["project_activity"]["log"]
log(
    project_id=27,
    event_type="shooting_item.updated",
    entity_type="shooting_item",
    entity_id=123,
    entity_label="Scene 48B (Episode 04)",
    changes={"duration_seconds": {"old": 135, "new": 161}},
    metadata={"shooting_day_id": 12},
)
```

Or use helpers in `project_activity_hooks.py`.

Logging is best-effort: failures are written to the app log and **must not** abort the business operation (SAVEPOINT-isolated).

## What to log / not log

**Log:** creates, updates with real field changes, deletes, status/workflow changes, media copy/convert lifecycle, bookings, team membership, settings field changes.

**Do not log:** page views, searches, filters, sorts, modal opens, previews, hover, read-only GETs.

## `changes_json` shape

Only changed fields:

```json
{
  "duration_seconds": {"old": 135, "new": 161},
  "location": {"old": "Studio A", "new": "Downtown Cairo"}
}
```

Use `build_change_set(before, after, tracked_fields)`.

## Operation IDs (long-running media work)

Media copy/convert events share `operation_id = mr-task-<task_id>`.

Lifecycle:

- `media.copy.started` → `media.copy.completed` | `failed` | `cancelled`
- Same pattern for `media.convert.*`

Duration is computed server-side from `started_at` / `completed_at` when possible.

## Log Book UI

- Route: `/projects/<id>/log-book`
- Server-side pagination (default 50; allowed 25/50/100; max 100)
- Filters via query string; summary cards act as bucket filters
- Detail modal loads `/projects/<id>/log-book/<log_id>.json`
- No edit/delete controls for log rows

## Permissions

- `can_view_project_log_book` — project members with access
- `can_view_sensitive_log_details` — elevated / full project control (IP, UA)

## Future modules (Phase 2)

Tasks, VFX, Color, Edit, Sound, episode versions, uploads — register new event types and call the same logger; no table redesign required.

## Archive strategy (future)

Keep recent rows in `project_activity_logs`. Move older rows to an archive table with the same schema. Preserve summaries, entity ids, and `operation_id`. Never silently discard audit records. Phase 1 does not auto-delete.
