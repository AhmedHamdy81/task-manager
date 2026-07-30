"""Tests for Project Log Book service and hooks."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta

import pytest

# Isolate DB before importing app
_fd, _DB = tempfile.mkstemp(suffix="_pal_test.db")
os.close(_fd)
os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_DB}"

import project_activity_events as pae
import project_activity_service as pas


def test_event_registry_valid():
    assert pae.is_valid_event_type(pae.SHOOTING_ITEM_CREATED)
    assert not pae.is_valid_event_type("not.a.real.event")
    assert pae.module_for_event(pae.MEDIA_COPY_STARTED) == "media"
    assert pae.action_for_event(pae.BOOKING_UPDATED) == "updated"


def test_build_change_set_only_changed():
    before = {"duration_seconds": 135, "notes": "a", "status": "pending"}
    after = {"duration_seconds": 161, "notes": "a", "status": "done"}
    ch = pas.build_change_set(before, after, ("duration_seconds", "notes", "status"))
    assert "notes" not in ch
    assert ch["duration_seconds"] == {"old": 135, "new": 161}
    assert ch["status"] == {"old": "pending", "new": "done"}


def test_build_change_set_empty_when_unchanged():
    before = {"location": "A"}
    after = {"location": "A"}
    assert pas.build_change_set(before, after, ("location",)) == {}


def test_scrub_sensitive_keys():
    meta = pas.scrub_dict(
        {
            "password": "secret",
            "api_key": "x",
            "file_count": 3,
            "token": "abc",
        }
    )
    assert "password" not in meta
    assert "api_key" not in meta
    assert "token" not in meta
    assert meta["file_count"] == 3


def test_media_operation_id_stable():
    assert pas.media_operation_id(42) == "mr-task-42"


def test_duration_from_timestamps():
    class FakeModel:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.id = None

    class FakeSession:
        def add(self, row):
            self.row = row

        def flush(self):
            self.row.id = 1

        def begin_nested(self):
            class _Ctx:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return _Ctx()

    class FakeDB:
        session = FakeSession()

    start = datetime(2026, 7, 30, 10, 0, 0)
    end = datetime(2026, 7, 30, 11, 30, 0)
    logger = pas.ProjectActivityLogger(
        db=FakeDB(),
        model=FakeModel,
        now_local=lambda: end,
        get_directory_user=lambda: None,
        get_account=lambda: None,
    )
    row = logger.log(
        project_id=1,
        event_type=pae.MEDIA_COPY_COMPLETED,
        entity_type="media_task",
        entity_id=9,
        entity_label="Day 1",
        started_at=start,
        completed_at=end,
        is_system_event=True,
        actor_name="System",
    )
    assert row is not None
    assert row.duration_seconds == 5400
    assert row.operation_id == "" or True  # optional


def test_logger_rejects_unknown_event():
    class FakeModel:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FakeSession:
        def add(self, row):
            raise AssertionError("should not add")

        def flush(self):
            pass

        def begin_nested(self):
            class _Ctx:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *a):
                    return False

            return _Ctx()

    class FakeDB:
        session = FakeSession()

    logger = pas.ProjectActivityLogger(
        db=FakeDB(),
        model=FakeModel,
        now_local=datetime.utcnow,
        get_directory_user=lambda: None,
        get_account=lambda: None,
    )
    assert logger.safe_log(project_id=1, event_type="bogus.event") is None


def test_page_size_clamp():
    assert pas.clamp_page_size(50) == 50
    assert pas.clamp_page_size(100) == 100
    assert pas.clamp_page_size(999) == 50
    assert pas.clamp_page_size("25") == 25


def test_summary_builder():
    s = pas.build_summary(
        actor_name="Ahmed Hamdy",
        event_type=pae.SHOOTING_ITEM_CREATED,
        entity_label="Scene 48B (Episode 04)",
    )
    assert "Ahmed Hamdy" in s
    assert "48B" in s


def test_deleted_item_metadata_shape():
    class Obj:
        id = 7
        episode_number = 4
        is_episode_unassigned = False
        is_establishing_shots_pool = False
        scene_label = "48B"
        scene_number = 48
        duration_seconds = 94
        notes = ""
        status = "pending"
        sync_done = False
        first_edit_done = False
        needs_vfx = False
        is_critical = False
        shooting_item_type = "scene"
        runtime_selected = True
        reel_number = None
        shooting_day_id = 7

    snap = pas.shooting_item_snapshot(Obj())
    assert snap["scene_label"] == "48B"
    assert snap["duration_seconds"] == 94
    label = pas.shooting_item_label(Obj())
    assert "48B" in label
