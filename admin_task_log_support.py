"""Admin Task Log — query helpers, filters, and row serialization."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode

from sqlalchemy import case, func, or_

# Main Task workflow statuses (see tasks_set_status in app.py).
TASK_STATUSES: tuple[str, ...] = ("open", "in_progress", "done")
CONFORM_TASK_STATUSES: tuple[str, ...] = ("open", "in_progress", "done")
TASK_STATUS_LABELS: dict[str, str] = {
    "open": "Pending",
    "in_progress": "In Progress",
    "done": "Finished",
    "failed": "Failed",
}

TASK_PRIORITY_LABELS: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Urgent",
}

# TODO: TodoItem / Action Board items use separate tables; include when unified task log is needed.


def _parse_date_arg(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_task_log_filters(args: Any) -> dict[str, Any]:
    """Parse GET query params for /admin/task-log."""
    q = (args.get("q") or "").strip()
    status = (args.get("status") or "").strip().lower()
    if status not in TASK_STATUSES and status not in CONFORM_TASK_STATUSES:
        status = ""
    priority = (args.get("priority") or "").strip().lower()
    if priority not in TASK_PRIORITY_LABELS:
        priority = ""
    hide_completed = (args.get("hide_completed") or "").strip().lower() in ("1", "true", "on", "yes")
    project_id = args.get("project_id", type=int)
    assigned_to = args.get("assigned_to", type=int)
    requested_by = args.get("requested_by", type=int)
    created_from = _parse_date_arg(args.get("created_from"))
    created_to = _parse_date_arg(args.get("created_to"))
    due_from = _parse_date_arg(args.get("due_from"))
    due_to = _parse_date_arg(args.get("due_to"))
    page = max(1, int(args.get("page", 1) or 1))
    return {
        "q": q,
        "status": status,
        "priority": priority,
        "hide_completed": hide_completed,
        "project_id": project_id,
        "assigned_to": assigned_to,
        "requested_by": requested_by,
        "created_from": created_from,
        "created_to": created_to,
        "due_from": due_from,
        "due_to": due_to,
        "page": page,
    }


def filters_to_query_args(filters: dict[str, Any], *, page: int | None = None) -> dict[str, str | int]:
    out: dict[str, str | int] = {}
    if filters.get("q"):
        out["q"] = filters["q"]
    if filters.get("status"):
        out["status"] = filters["status"]
    if filters.get("priority"):
        out["priority"] = filters["priority"]
    if filters.get("hide_completed"):
        out["hide_completed"] = "1"
    if filters.get("project_id"):
        out["project_id"] = int(filters["project_id"])
    if filters.get("assigned_to"):
        out["assigned_to"] = int(filters["assigned_to"])
    if filters.get("requested_by"):
        out["requested_by"] = int(filters["requested_by"])
    if filters.get("created_from"):
        out["created_from"] = filters["created_from"].isoformat()
    if filters.get("created_to"):
        out["created_to"] = filters["created_to"].isoformat()
    if filters.get("due_from"):
        out["due_from"] = filters["due_from"].isoformat()
    if filters.get("due_to"):
        out["due_to"] = filters["due_to"].isoformat()
    if page is not None:
        out["page"] = int(page)
    elif filters.get("page") and int(filters["page"]) > 1:
        out["page"] = int(filters["page"])
    return out


def task_log_page_url(endpoint: str, filters: dict[str, Any], *, page: int | None = None, url_for: Callable) -> str:
    params = filters_to_query_args(filters, page=page)
    if not params:
        return url_for(endpoint)
    return f"{url_for(endpoint)}?{urlencode(params)}"


def apply_task_log_filters(q, *, Task, Project, User, filters: dict[str, Any]):
    """Apply server-side filters to a Task query."""
    if filters.get("status"):
        q = q.filter(Task.status == filters["status"])
    elif filters.get("hide_completed"):
        q = q.filter(Task.status != "done")
    if filters.get("priority"):
        q = q.filter(Task.priority == filters["priority"])
    if filters.get("project_id"):
        q = q.filter(Task.project_id == int(filters["project_id"]))
    if filters.get("assigned_to"):
        q = q.filter(Task.user_id == int(filters["assigned_to"]))
  # TODO: Task model has no created_by / requested_by yet — filter is reserved.
    if filters.get("requested_by"):
        pass
    if filters.get("created_from"):
        q = q.filter(func.date(Task.created_at) >= filters["created_from"])
    if filters.get("created_to"):
        q = q.filter(func.date(Task.created_at) <= filters["created_to"])
  # TODO: Task model has no due_date — due_from / due_to are ignored until migrated.
    if filters.get("q"):
        like = f"%{filters['q']}%"
        q = q.filter(or_(Task.title.ilike(like), Task.description.ilike(like)))
    return q


def task_log_sort_clauses(Task):
    """Open / in-progress first, then latest activity, then priority."""
    status_rank = case(
        (Task.status == "open", 1),
        (Task.status == "in_progress", 2),
        (Task.status == "failed", 3),
        (Task.status == "done", 4),
        else_=5,
    )
    latest_update = func.coalesce(Task.completed_at, Task.created_at)
    priority_rank = case(
        (Task.priority == "high", 3),
        (Task.priority == "urgent", 4),
        (Task.priority == "medium", 2),
        (Task.priority == "low", 1),
        else_=0,
    )
    return (
        status_rank.asc(),
        latest_update.desc(),
        priority_rank.desc(),
        Task.id.desc(),
    )


def task_latest_update_dt(task) -> datetime | None:
    """Best-effort latest activity timestamp for a task row."""
    # TODO: prefer Task.updated_at when that column exists.
    if (task.status or "").strip().lower() == "done" and task.completed_at:
        return task.completed_at
    return task.created_at


def compute_task_log_summary_from_query(q, *, Task) -> dict[str, int]:
    """Summary counts for the filtered task query (pre-pagination)."""
    total = q.count()
    open_n = q.filter(Task.status == "open").count()
    in_progress_n = q.filter(Task.status == "in_progress").count()
    done_n = q.filter(Task.status == "done").count()
    # TODO: overdue / due this week need Task.due_date.
    return {
        "total": total,
        "open": open_n,
        "in_progress": in_progress_n,
        "completed": done_n,
        "overdue": 0,
        "due_this_week": 0,
    }


def serialize_task_log_row(
    task,
    *,
    format_datetime: Callable,
    format_date: Callable,
    url_for: Callable,
) -> dict[str, Any]:
    import conform_task_support as cts

    project = task.project
    assignee = task.assignee
    requester = getattr(task, "requested_by", None)
    st = (task.status or "open").strip().lower()
    pr = (task.priority or "medium").strip().lower()
    latest = task_latest_update_dt(task)
    desc = (task.description or "").strip()
    notes_preview = desc if len(desc) <= 120 else desc[:117] + "…"
    is_conform = cts.is_conform_task(task)
    status_options = list(CONFORM_TASK_STATUSES if is_conform else TASK_STATUSES)
    failure_note = None
    for note in getattr(task, "task_notes", None) or []:
        if (getattr(note, "note_type", "") or "") == "conform_failure":
            failure_note = note
            break
    return {
        "id": int(task.id),
        "title": (task.title or "").strip() or "—",
        "status": st,
        "status_label": TASK_STATUS_LABELS.get(st, st.replace("_", " ").title() or "Unknown"),
        "status_options": status_options,
        "is_conform_task": is_conform,
        "priority": pr,
        "priority_label": TASK_PRIORITY_LABELS.get(pr, pr.replace("_", " ").title() or "—"),
        "project_id": int(task.project_id) if task.project_id is not None else None,
        "project_name": (project.name or "").strip() if project else "",
        "project_href": url_for("project_detail", project_id=task.project_id) if task.project_id else "",
        "color_href": url_for("project_color_overview", project_id=task.project_id)
        if task.project_id
        else "",
        "assignee_id": int(task.user_id) if task.user_id is not None else None,
        "assignee_name": (assignee.name or "").strip() if assignee else "Unknown user",
        "requested_by_name": (requester.name or "").strip() if requester else "—",
        "due_date": task.due_date.isoformat() if getattr(task, "due_date", None) else "—",
        "created_at": format_datetime(task.created_at) if task.created_at else "—",
        "completed_at": format_datetime(task.completed_at) if task.completed_at else "—",
        "latest_update": format_datetime(latest) if latest else "—",
        "notes_preview": notes_preview or "—",
        "notes_full": desc,
        "archived": bool(task.archived),
        "tasks_href": url_for("tasks_list"),
        "status_update_url": url_for("admin_task_log_task_status_update", task_id=task.id),
        "conform_status_url": f"/api/tasks/{int(task.id)}/conform-status",
        "conform_failed_url": f"/conform-tasks/{int(task.id)}/fail",
        "failure_note_title": (failure_note.title or "") if failure_note else "",
        "failure_note_body": (failure_note.body or "") if failure_note else "",
    }
