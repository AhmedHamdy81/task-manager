"""Tests for the Project Working Hours ledger, integrations, and routes."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta

# conftest.py sets TASK_MANAGER_TEST_DATABASE before app import; keep a local fallback.
_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_working_hours.db")
os.close(_fd)
if not (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip():
    os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"

import project_activity_events as pae
import project_work_ledger_service as pwls
from app import app, db
from permissions import register_permission_models, seed_permissions

# Manual entries are validated against the real clock, so posted dates must track it.
TODAY_STR = date.today().isoformat()


class WorkLedgerServiceUnitTests(unittest.TestCase):
    """Pure functions — no database involved."""

    def test_format_minutes_label(self):
        self.assertEqual(pwls.format_minutes_label(0), "0m")
        self.assertEqual(pwls.format_minutes_label(45), "45m")
        self.assertEqual(pwls.format_minutes_label(60), "1h")
        self.assertEqual(pwls.format_minutes_label(195), "3h 15m")

    def test_minutes_between_rounds_up_and_floors_at_zero(self):
        start = datetime(2026, 7, 31, 10, 0, 0)
        self.assertEqual(pwls.minutes_between(start, start + timedelta(seconds=61)), 2)
        self.assertEqual(pwls.minutes_between(start, start - timedelta(hours=1)), 0)
        self.assertEqual(pwls.minutes_between(None, start), 0)

    def test_normalizers(self):
        self.assertEqual(pwls.normalize_source_type("Media Copy"), "media_copy")
        self.assertEqual(pwls.normalize_source_type("nonsense"), "other")
        self.assertEqual(pwls.normalize_work_type("Offline Editing"), "offline_editing")
        self.assertEqual(pwls.canonical_work_type("offline"), "offline_editing")
        self.assertEqual(pwls.canonical_work_type("Offline"), "offline_editing")
        self.assertIn("offline", pwls.work_type_equivalent_keys("offline_editing"))
        self.assertEqual(pwls.normalize_department_key("color_grading"), "color")
        self.assertEqual(pwls.normalize_status("bogus"), "submitted")

    def test_validate_work_duration(self):
        self.assertEqual(pwls.validate_work_duration(120)[0], 120)
        self.assertIsNotNone(pwls.validate_work_duration(-5)[1])
        self.assertIsNotNone(pwls.validate_work_duration(0)[1])
        self.assertIsNotNone(pwls.validate_work_duration(25 * 60)[1])
        self.assertIsNone(pwls.validate_work_duration(25 * 60, is_admin=True)[1])

    def test_validate_work_date_rejects_far_future(self):
        today = date(2026, 7, 31)
        self.assertIsNone(pwls.validate_work_date("2026-07-30", today=today)[1])
        self.assertIsNotNone(pwls.validate_work_date("2026-09-30", today=today)[1])
        self.assertIsNone(
            pwls.validate_work_date("2026-08-10", today=today, is_admin=True)[1]
        )
        self.assertIsNotNone(pwls.validate_work_date("not-a-date", today=today)[1])

    def test_parse_filters_sort_and_group(self):
        parsed = pwls.parse_filters(
            {
                "sort": "billable",
                "dir": "asc",
                "group_by": "department",
            }
        )
        self.assertEqual(parsed["sort"], "billable")
        self.assertEqual(parsed["dir"], "asc")
        self.assertEqual(parsed["group_by"], "department")
        bad = pwls.parse_filters({"sort": "nope", "dir": "sideways", "group_by": "title"})
        self.assertEqual(bad["sort"], "date")
        self.assertEqual(bad["dir"], "desc")
        self.assertIsNone(bad["group_by"])

    def test_next_sort_dir_and_build_log_display_rows(self):
        self.assertEqual(pwls.next_sort_dir({"sort": "user", "dir": "asc"}, "user"), "desc")
        self.assertEqual(pwls.next_sort_dir({"sort": "date", "dir": "desc"}, "user"), "asc")
        self.assertEqual(pwls.next_sort_dir({}, "billable"), "desc")

        rows = [
            {
                "user_id": 1,
                "user_name": "Ada",
                "department_key": "editorial",
                "department_label": "Editorial",
                "billable_minutes": 30,
                "actual_minutes": 30,
                "status": "approved",
                "status_label": "Approved",
            },
            {
                "user_id": 1,
                "user_name": "Ada",
                "department_key": "editorial",
                "department_label": "Editorial",
                "billable_minutes": 0,
                "actual_minutes": 15,
                "status": "approved",
                "status_label": "Approved",
            },
            {
                "user_id": 2,
                "user_name": "Ben",
                "department_key": "color",
                "department_label": "Color",
                "billable_minutes": 60,
                "actual_minutes": 60,
                "status": "rejected",
                "status_label": "Rejected",
            },
        ]
        grouped = pwls.build_log_display_rows(rows, "user")
        kinds = [item["kind"] for item in grouped]
        self.assertEqual(
            kinds,
            ["group", "entry", "entry", "group_summary", "group", "entry", "group_summary"],
        )
        self.assertEqual(grouped[0]["label"], "Ada")
        self.assertEqual(grouped[3]["kind"], "group_summary")
        self.assertEqual(grouped[3]["count"], 2)
        self.assertEqual(grouped[3]["actual_minutes"], 45)
        self.assertEqual(grouped[4]["label"], "Ben")

        arranged = pwls.build_log_display_rows(rows, "user", include_headers=False)
        self.assertEqual(
            [item["kind"] for item in arranged],
            ["entry", "entry", "group_summary", "entry", "group_summary"],
        )
        self.assertEqual(arranged[2]["actual_minutes"], 45)
        self.assertEqual(arranged[2]["billable_minutes"], 30)
        self.assertEqual(pwls.display_group_by({"sort": "user", "group_by": None}), ("user", False))
        self.assertEqual(
            pwls.display_group_by({"sort": "user", "group_by": "department"}),
            ("department", True),
        )
        self.assertEqual(pwls.display_group_by({"sort": "date", "group_by": None}), (None, False))

        billable_groups = pwls.build_log_display_rows(rows, "billable")
        self.assertEqual(billable_groups[0]["label"], "Billable")
        # Rows stay in input order; billable meta differs between row 0 and 1.
        self.assertEqual(
            [item["kind"] for item in billable_groups],
            [
                "group",
                "entry",
                "group_summary",
                "group",
                "entry",
                "group_summary",
                "group",
                "entry",
                "group_summary",
            ],
        )
        self.assertIn("work_type", pwls.SORT_KEYS)
        self.assertIn("work_type", pwls.GROUP_KEYS)

    def test_working_hours_events_are_registered(self):
        for event in (
            pae.WORKING_HOURS_MANUAL_CREATED,
            pae.WORKING_HOURS_APPROVED,
            pae.WORKING_HOURS_REJECTED,
            pae.WORKING_HOURS_BILLABLE_UPDATED,
        ):
            self.assertTrue(pae.is_valid_event_type(event), event)
        self.assertEqual(
            pae.module_for_event(pae.WORKING_HOURS_APPROVED), pae.MODULE_WORKING_HOURS
        )


class RateCardLockTests(unittest.TestCase):
    """Studio PDF seed services stay named, unit-locked, and undeletable."""

    def test_locked_default_keys(self):
        import rate_card_service as rcs

        self.assertTrue(rcs.is_locked_default_key("copy_convert_sync"))
        self.assertTrue(rcs.is_locked_default_key("offline"))
        self.assertTrue(rcs.is_locked_default_key("offline_editing"))
        self.assertFalse(rcs.is_locked_default_key("sync"))
        self.assertFalse(rcs.is_locked_default_key("selection"))
        self.assertFalse(rcs.is_locked_default_key("custom_vfx"))

    def test_apply_locked_defaults_restores_catalog_identity(self):
        import rate_card_service as rcs
        from decimal import Decimal

        merged = rcs.apply_locked_defaults(
            [
                {
                    "service_name": "Offline",
                    "service_key": "offline_editing",
                    "billing_unit": "Fee",
                    "rate_hour": Decimal("2600"),
                    "rate_day": Decimal("26000"),
                    "include_in_pdf": True,
                    "currency": "USD",
                },
                {
                    "service_name": "Night Conform",
                    "service_key": "night_conform",
                    "billing_unit": "Hour",
                    "rate_hour": Decimal("900"),
                    "rate_day": None,
                    "include_in_pdf": True,
                    "currency": "USD",
                },
            ],
            existing_rows=[],
        )
        keys = [row["service_key"] for row in merged]
        self.assertEqual(keys[:8], [item["service_key"] for item in rcs.DEFAULT_RATE_CARD_ITEMS])
        self.assertEqual(keys[-1], "night_conform")
        offline = next(row for row in merged if row["service_key"] == "offline_editing")
        self.assertEqual(offline["service_name"], "Offline Editing")
        self.assertEqual(offline["billing_unit"], "Hour")
        self.assertEqual(offline["rate_hour"], Decimal("2600"))


class WorkLedgerDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.drop_all()
            db.create_all()
            seed_permissions(
                db, register_permission_models(db), app.extensions["tm_test_models"]["JobTitle"]
            )
            db.session.remove()
            db.engine.dispose()

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.M = app.extensions["tm_test_models"]
        self.Ledger = self.M["ProjectWorkLedger"]
        for key in (
            "ProjectWorkLedger",
            "StudioRateCardItem",
            "WorkSession",
            "Booking",
            "ProjectActivityLog",
            "ProjectMember",
            "User",
            "Account",
            "Project",
            "EditSuite",
        ):
            db.session.query(self.M[key]).delete()
        db.session.commit()

        self.project = self.M["Project"](
            name="Working Hours Test",
            project_type="TV series",
            production_house="PH",
            director="Director",
        )
        db.session.add(self.project)
        self.suite = self.M["EditSuite"](name="Suite A")
        db.session.add(self.suite)
        db.session.flush()

        self.admin_acc, self.admin_user = self._make_person("admin@wh.test", "Admin", role="admin")
        self.editor_acc, self.editor_user = self._make_person("editor@wh.test", "Editor")
        self.other_acc, self.other_user = self._make_person("other@wh.test", "Other")
        self.producer_acc, self.producer_user = self._make_person(
            "producer@wh.test", "Producer", role="producer"
        )
        for user in (self.admin_user, self.editor_user, self.other_user, self.producer_user):
            db.session.add(
                self.M["ProjectMember"](project_id=self.project.id, user_id=user.id)
            )
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.ctx.pop()

    # -- helpers -----------------------------------------------------------

    def _make_person(self, email, name, *, role="user"):
        acc = self.M["Account"](email=email, password_hash="x", role=role)
        db.session.add(acc)
        db.session.flush()
        user = self.M["User"](name=name, email=email, account_id=acc.id)
        db.session.add(user)
        db.session.flush()
        return acc, user

    def _make_session(self, *, minutes=90, user=None, ended=True):
        user = user or self.editor_user
        started = datetime(2026, 7, 31, 10, 0, 0)
        booking = self.M["Booking"](
            edit_suite_id=self.suite.id,
            user_id=user.id,
            project_id=self.project.id,
            booked_by_id=user.id,
            booked_for_id=user.id,
            booking_date=started.date(),
            start_time=time(10, 0),
            end_time=time(12, 0),
            job_type="Offline Editing",
        )
        db.session.add(booking)
        db.session.flush()
        sess = self.M["WorkSession"](
            user_id=user.id,
            project_id=self.project.id,
            edit_suite_id=self.suite.id,
            job_type="Offline Editing",
            started_at=started,
            ended_at=started + timedelta(minutes=minutes) if ended else None,
            booking_id=booking.id,
        )
        db.session.add(sess)
        db.session.flush()
        return sess

    def _login(self, client, account):
        with client.session_transaction() as sess:
            sess["account_id"] = account.id

    # -- session integration ----------------------------------------------

    def test_ended_session_creates_ledger_row(self):
        sess = self._make_session(minutes=90)
        pwls.upsert_work_ledger_from_session(
            db=db, session=sess, model=self.Ledger, directory_user=self.editor_user
        )
        db.session.commit()
        row = self.Ledger.query.one()
        self.assertEqual(row.source_type, "work_session")
        self.assertEqual(row.source_id, sess.id)
        self.assertEqual(row.work_session_id, sess.id)
        self.assertEqual(row.project_id, self.project.id)
        self.assertEqual(row.user_id, self.editor_user.id)
        self.assertEqual(row.booking_id, sess.booking_id)
        self.assertEqual(row.actual_minutes, 90)
        self.assertEqual(row.estimated_minutes, 120)
        self.assertEqual(row.billable_minutes, 90)
        self.assertEqual(row.work_date, date(2026, 7, 31))
        self.assertEqual(row.work_type, "offline_editing")
        self.assertEqual(row.title, "Work session")
        self.assertEqual(row.status, pwls.STATUS_SUBMITTED)

    def test_replaying_session_end_does_not_duplicate(self):
        sess = self._make_session(minutes=60)
        for _ in range(3):
            pwls.upsert_work_ledger_from_session(db=db, session=sess, model=self.Ledger)
            db.session.commit()
        self.assertEqual(self.Ledger.query.count(), 1)

    def test_approved_session_row_is_not_downgraded_by_replay(self):
        sess = self._make_session(minutes=60)
        row = pwls.upsert_work_ledger_from_session(db=db, session=sess, model=self.Ledger)
        db.session.commit()
        row.status = pwls.STATUS_APPROVED
        db.session.commit()
        pwls.upsert_work_ledger_from_session(db=db, session=sess, model=self.Ledger)
        db.session.commit()
        self.assertEqual(self.Ledger.query.one().status, pwls.STATUS_APPROVED)

    # -- media integration -------------------------------------------------

    def test_media_copy_start_then_complete_updates_one_row(self):
        started = datetime(2026, 7, 31, 9, 0, 0)
        pwls.upsert_work_ledger_from_media_event(
            db=db,
            model=self.Ledger,
            project_id=self.project.id,
            kind="copy",
            task_id=501,
            operation_id="mr-task-501",
            phase="started",
            started_at=started,
            estimated_minutes=45,
            shooting_day_id=7,
        )
        db.session.commit()
        row = self.Ledger.query.one()
        self.assertEqual(row.status, pwls.STATUS_STARTED)
        self.assertEqual(row.department_key, "machine_room")
        self.assertEqual(row.work_type, "copy_media")
        self.assertEqual(row.title, "Copy media")
        self.assertEqual(row.shooting_day_id, 7)

        pwls.upsert_work_ledger_from_media_event(
            db=db,
            model=self.Ledger,
            project_id=self.project.id,
            kind="copy",
            task_id=501,
            operation_id="mr-task-501",
            phase="completed",
            started_at=started,
            completed_at=started + timedelta(minutes=52),
        )
        db.session.commit()
        self.assertEqual(self.Ledger.query.count(), 1)
        row = self.Ledger.query.one()
        self.assertEqual(row.status, pwls.STATUS_AUTO_APPROVED)
        self.assertEqual(row.actual_minutes, 52)
        self.assertEqual(row.billable_minutes, 52)

    def test_media_convert_uses_its_own_row_and_labels(self):
        pwls.upsert_work_ledger_from_media_event(
            db=db,
            model=self.Ledger,
            project_id=self.project.id,
            kind="convert",
            task_id=502,
            operation_id="mr-task-502",
            phase="completed",
            started_at=datetime(2026, 7, 31, 11, 0, 0),
            completed_at=datetime(2026, 7, 31, 11, 30, 0),
        )
        db.session.commit()
        row = self.Ledger.query.one()
        self.assertEqual(row.source_type, "media_convert")
        self.assertEqual(row.work_type, "convert_transcode")
        self.assertEqual(row.title, "Convert / Transcode")
        self.assertEqual(row.actual_minutes, 30)

    def test_cancelled_media_is_not_billable(self):
        pwls.upsert_work_ledger_from_media_event(
            db=db,
            model=self.Ledger,
            project_id=self.project.id,
            kind="copy",
            task_id=503,
            phase="cancelled",
            started_at=datetime(2026, 7, 31, 8, 0, 0),
            completed_at=datetime(2026, 7, 31, 8, 20, 0),
        )
        db.session.commit()
        row = self.Ledger.query.one()
        self.assertEqual(row.status, pwls.STATUS_CANCELLED)
        self.assertEqual(row.actual_minutes, 20)
        self.assertEqual(row.billable_minutes, 0)

    def test_media_hours_are_not_listed_as_pending_approval(self):
        db.session.add(
            self.Ledger(
                project_id=self.project.id,
                user_id=self.editor_user.id,
                work_date=date.today(),
                source_type="media_copy",
                department_key="machine_room",
                work_type="copy_media",
                title="Copy Media",
                actual_minutes=12,
                billable_minutes=12,
                status=pwls.STATUS_AUTO_APPROVED,
            )
        )
        db.session.commit()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode("utf-8")
        self.assertIn('aria-label="Copy and Convert hours"', body)
        self.assertIn("not waiting for approval", body)
        self.assertNotIn('aria-label="Pending Approval"', body)

    # -- summaries ---------------------------------------------------------

    def test_totals_exclude_uncounted_statuses(self):
        base = dict(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 31),
            department_key="editorial",
            work_type="offline_editing",
        )
        db.session.add_all(
            [
                self.Ledger(
                    source_type="manual",
                    actual_minutes=60,
                    billable_minutes=60,
                    status=pwls.STATUS_APPROVED,
                    **base,
                ),
                self.Ledger(
                    source_type="manual",
                    actual_minutes=30,
                    billable_minutes=30,
                    status=pwls.STATUS_SUBMITTED,
                    **base,
                ),
                self.Ledger(
                    source_type="manual",
                    actual_minutes=999,
                    billable_minutes=999,
                    status=pwls.STATUS_REJECTED,
                    **base,
                ),
                self.Ledger(
                    source_type="media_copy",
                    actual_minutes=15,
                    billable_minutes=0,
                    status=pwls.STATUS_FAILED,
                    **base,
                ),
            ]
        )
        db.session.commit()
        summary = pwls.summarize_project_work_hours(
            self.project.id, model=self.Ledger, today=date(2026, 7, 31)
        )
        self.assertEqual(summary["actual_minutes"], 90)
        self.assertEqual(summary["billable_minutes"], 90)
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["pending_minutes"], 30)
        self.assertEqual(summary["by_department"][0]["label"], "Editorial")

    def test_booked_hours_are_separate_from_actual(self):
        sess = self._make_session(minutes=45)
        pwls.upsert_work_ledger_from_session(db=db, session=sess, model=self.Ledger)
        db.session.commit()
        booked = pwls.summarize_booked_minutes(
            self.project.id, Booking=self.M["Booking"]
        )
        summary = pwls.summarize_project_work_hours(
            self.project.id, model=self.Ledger, today=date(2026, 7, 31)
        )
        self.assertEqual(booked, 120)
        self.assertEqual(summary["actual_minutes"], 45)

    def test_summarize_user_today(self):
        db.session.add(
            self.Ledger(
                project_id=self.project.id,
                user_id=self.editor_user.id,
                work_date=date(2026, 7, 31),
                source_type="manual",
                actual_minutes=75,
                billable_minutes=60,
                status=pwls.STATUS_SUBMITTED,
            )
        )
        db.session.commit()
        today = pwls.summarize_user_today(
            model=self.Ledger, user_id=self.editor_user.id, today=date(2026, 7, 31)
        )
        self.assertEqual(today["actual_minutes"], 75)
        self.assertEqual(today["billable_minutes"], 60)
        self.assertEqual(today["actual_label"], "1h 15m")

    # -- backfill ----------------------------------------------------------

    def test_backfill_creates_missing_rows_and_skips_duplicates(self):
        first = self._make_session(minutes=30)
        second = self._make_session(minutes=45, user=self.other_user)
        db.session.commit()
        pwls.upsert_work_ledger_from_session(db=db, session=first, model=self.Ledger)
        db.session.commit()

        report = pwls.backfill_from_sessions(
            db=db, model=self.Ledger, WorkSession=self.M["WorkSession"]
        )
        db.session.commit()
        self.assertEqual(report["sessions_scanned"], 2)
        self.assertEqual(report["session_rows_created"], 1)
        self.assertEqual(report["skipped_duplicates"], 1)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(self.Ledger.query.count(), 2)
        self.assertIsNotNone(
            self.Ledger.query.filter_by(source_id=second.id, source_type="work_session").first()
        )

    # -- routes ------------------------------------------------------------

    def test_page_requires_project_access(self):
        outsider_acc, _ = self._make_person("outsider@wh.test", "Outsider")
        db.session.commit()
        client = app.test_client()
        self._login(client, outsider_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/projects", resp.headers["Location"])

    def test_member_can_open_page(self):
        client = app.test_client()
        self._login(client, self.editor_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Working Hours", resp.data)
        self.assertIn(b"Booked Hours", resp.data)
        body = resp.data.decode("utf-8")
        dialog = body.split('id="working-hours-manual-dialog"', 1)[1].split("</dialog>", 1)[0]
        self.assertNotIn("Department", dialog)
        self.assertNotIn('name="department_key"', dialog)
        self.assertIn('name="work_type"', dialog)
        self.assertIn("Offline Editing", dialog)
        self.assertIn('value="offline_editing"', dialog)
        self.assertIn("Copy &amp; Convert &amp; Sync", dialog)

    def test_rate_card_modal_save_and_export(self):
        RateCard = self.M["StudioRateCardItem"]
        client = app.test_client()
        self._login(client, self.producer_acc)
        page = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(page.status_code, 200)
        body = page.data.decode("utf-8")
        self.assertIn("Rate Card", body)
        self.assertIn("working-hours-rate-card-dialog", body)
        self.assertIn("Copy &amp; Convert &amp; Sync", body)
        self.assertIn("data-rate-card-locked", body)
        self.assertIn("is-default", body)
        self.assertIn("data-rate-card-remove", body)
        self.assertIn("project-working-hours-rate-card-add", body)
        self.assertIn("btn--danger", body)
        self.assertGreaterEqual(RateCard.query.count(), 8)

        save = client.post(
            f"/projects/{self.project.id}/working-hours/rate-card",
            data={
                "currency": "USD",
                "service_name": ["Offline", "Online"],
                "rate_hour": ["2600", "3100"],
                "rate_day": ["26000", ""],
                "include_in_pdf": ["1", "0"],
            },
            follow_redirects=False,
        )
        self.assertEqual(save.status_code, 302)
        rows = RateCard.query.order_by(RateCard.sort_order.asc()).all()
        self.assertGreaterEqual(len(rows), 8)
        by_key = {row.service_key: row for row in rows}
        self.assertEqual(by_key["offline_editing"].service_name, "Offline Editing")
        self.assertEqual(float(by_key["offline_editing"].rate_hour), 2600.0)
        self.assertEqual(float(by_key["offline_editing"].rate_day), 26000.0)
        self.assertEqual(by_key["offline_editing"].currency, "USD")
        self.assertTrue(by_key["offline_editing"].include_in_pdf)
        self.assertEqual(by_key["online_editing"].service_name, "Online Editing")
        self.assertEqual(by_key["online_editing"].currency, "USD")
        self.assertIsNone(by_key["online_editing"].rate_day)
        self.assertFalse(by_key["online_editing"].include_in_pdf)
        self.assertEqual(by_key["copy_convert_sync"].service_name, "Copy & Convert & Sync")

        import rate_card_service as rcs

        locked_id = by_key["copy_convert_sync"].id
        removed, delete_err = rcs.delete_item(db, RateCard, locked_id)
        self.assertIsNone(removed)
        self.assertEqual(delete_err, "locked_default")
        self.assertIsNotNone(RateCard.query.filter_by(id=locked_id).first())

        page_after = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(page_after.status_code, 200)
        after_body = page_after.data.decode("utf-8")
        self.assertIn('name="currency"', after_body)
        self.assertIn('value="USD" selected', after_body)
        self.assertIn('value="EGP"', after_body)
        self.assertIn('value="EUR"', after_body)

        pdf = client.get(f"/projects/{self.project.id}/working-hours/rate-card.pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        self.assertIn("RATE_CARD_USD_2024.pdf", pdf.headers.get("Content-Disposition", ""))
        self.assertIn(b">Include<", page.data)
        # Cover + rates + back, matching the studio reference PDF.
        import fitz

        exported = fitz.open(stream=pdf.data, filetype="pdf")
        try:
            self.assertEqual(exported.page_count, 3)
            self.assertIn("RATE CARD", exported[0].get_text("text"))
            rates_text = exported[1].get_text("text")
            self.assertIn("RATE/HOUR", rates_text)
            self.assertIn("Offline", rates_text)
            self.assertIn("USD", rates_text)
            self.assertIn("tbbstudios", exported[2].get_text("text").replace(" ", "").lower())
        finally:
            exported.close()

        # Selected currency query overrides stored row currency for export labels.
        pdf_eur = client.get(
            f"/projects/{self.project.id}/working-hours/rate-card.pdf?currency=EUR"
        )
        self.assertEqual(pdf_eur.status_code, 200)
        self.assertIn("RATE_CARD_EUR_2024.pdf", pdf_eur.headers.get("Content-Disposition", ""))
        exported_eur = fitz.open(stream=pdf_eur.data, filetype="pdf")
        try:
            rates_eur = exported_eur[1].get_text("text")
            self.assertIn("EUR", rates_eur)
            self.assertNotIn("USD", rates_eur)
        finally:
            exported_eur.close()

    def test_work_log_sort_and_group_controls(self):
        db.session.add_all(
            [
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.editor_user.id,
                    work_date=date.today(),
                    source_type="manual",
                    department_key="editorial",
                    title="Edit A",
                    actual_minutes=30,
                    billable_minutes=30,
                    status=pwls.STATUS_APPROVED,
                ),
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.other_user.id,
                    work_date=date.today(),
                    source_type="manual",
                    department_key="color",
                    title="Grade B",
                    actual_minutes=45,
                    billable_minutes=0,
                    status=pwls.STATUS_APPROVED,
                ),
            ]
        )
        db.session.commit()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours"
            f"?sort=user&dir=asc&group_by=department"
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode("utf-8")
        self.assertIn('aria-sort="ascending"', body)
        self.assertIn("project-working-hours-group-row", body)
        self.assertIn("project-working-hours-group-summary", body)
        self.assertIn("Editorial", body)
        self.assertIn("Color", body)
        self.assertIn('id="working-hours-group-by"', body)
        self.assertIn("Work Type", body)
        self.assertIn("sort=work_type", body)

        by_user = client.get(
            f"/projects/{self.project.id}/working-hours?sort=user&dir=asc"
        )
        self.assertEqual(by_user.status_code, 200)
        user_body = by_user.data.decode("utf-8")
        self.assertIn("project-working-hours-group-summary", user_body)
        self.assertNotIn("project-working-hours-group-row", user_body)
        self.assertIn("Total", user_body)

    def test_member_adds_own_manual_hours(self):
        client = app.test_client()
        self._login(client, self.editor_acc)
        resp = client.post(
            f"/projects/{self.project.id}/working-hours/manual",
            data={
                "work_date": TODAY_STR,
                "work_type": "offline",
                "duration_hours": "2",
                "duration_minutes": "30",
                "title": "Assembly pass",
            },
        )
        self.assertEqual(resp.status_code, 302)
        row = self.Ledger.query.one()
        self.assertEqual(row.source_type, "manual")
        self.assertIsNone(row.source_id)
        self.assertEqual(row.user_id, self.editor_user.id)
        self.assertEqual(row.work_type, "offline")
        self.assertEqual(row.department_key, "editorial")
        self.assertEqual(row.actual_minutes, 150)
        self.assertEqual(row.billable_minutes, 150)
        self.assertEqual(row.status, pwls.STATUS_SUBMITTED)
        logged = self.M["ProjectActivityLog"].query.filter_by(
            event_type=pae.WORKING_HOURS_MANUAL_CREATED
        ).count()
        self.assertEqual(logged, 1)

    def test_normal_user_cannot_log_hours_for_another_user(self):
        client = app.test_client()
        self._login(client, self.editor_acc)
        resp = client.post(
            f"/projects/{self.project.id}/working-hours/manual",
            data={
                "work_date": TODAY_STR,
                "user_id": str(self.other_user.id),
                "work_type": "offline",
                "duration_hours": "1",
                "duration_minutes": "0",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.Ledger.query.count(), 0)

    def test_producer_can_log_hours_for_another_user(self):
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.post(
            f"/projects/{self.project.id}/working-hours/manual",
            data={
                "work_date": TODAY_STR,
                "user_id": str(self.other_user.id),
                "work_type": "color_grading_colorist",
                "duration_hours": "3",
                "duration_minutes": "0",
            },
        )
        self.assertEqual(resp.status_code, 302)
        row = self.Ledger.query.one()
        self.assertEqual(row.user_id, self.other_user.id)
        self.assertEqual(row.work_type, "color_grading_colorist")
        self.assertEqual(row.department_key, "color")
        self.assertEqual(row.actual_minutes, 180)

    def test_manual_hours_reject_negative_and_oversized_durations(self):
        client = app.test_client()
        self._login(client, self.editor_acc)
        for hours, minutes in (("-1", "0"), ("0", "0"), ("25", "0")):
            client.post(
                f"/projects/{self.project.id}/working-hours/manual",
                data={
                    "work_date": TODAY_STR,
                    "work_type": "offline",
                    "duration_hours": hours,
                    "duration_minutes": minutes,
                },
            )
        self.assertEqual(self.Ledger.query.count(), 0)

    def test_manual_hours_reject_entity_from_another_project(self):
        other_project = self.M["Project"](
            name="Other",
            project_type="TV series",
            production_house="PH",
            director="Director",
        )
        db.session.add(other_project)
        db.session.flush()
        foreign_day = self.M["ShootingDay"](
            project_id=other_project.id, day_name="D1", shooting_date=date(2026, 7, 30)
        )
        db.session.add(foreign_day)
        db.session.commit()
        client = app.test_client()
        self._login(client, self.editor_acc)
        client.post(
            f"/projects/{self.project.id}/working-hours/manual",
            data={
                "work_date": TODAY_STR,
                "work_type": "offline",
                "duration_hours": "1",
                "duration_minutes": "0",
                "shooting_day_id": str(foreign_day.id),
            },
        )
        self.assertEqual(self.Ledger.query.count(), 0)

    def test_owner_cannot_approve_own_entry_but_producer_can(self):
        entry = self.Ledger(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            account_id=self.editor_acc.id,
            work_date=date(2026, 7, 31),
            source_type="manual",
            actual_minutes=60,
            billable_minutes=60,
            status=pwls.STATUS_SUBMITTED,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

        owner_client = app.test_client()
        self._login(owner_client, self.editor_acc)
        owner_client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/approve"
        )
        self.assertEqual(
            db.session.get(self.Ledger, entry_id).status, pwls.STATUS_SUBMITTED
        )

        producer_client = app.test_client()
        self._login(producer_client, self.producer_acc)
        producer_client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/approve"
        )
        approved = db.session.get(self.Ledger, entry_id)
        self.assertEqual(approved.status, pwls.STATUS_APPROVED)
        self.assertEqual(approved.approved_by_account_id, self.producer_acc.id)
        self.assertEqual(
            self.M["ProjectActivityLog"].query.filter_by(
                event_type=pae.WORKING_HOURS_APPROVED
            ).count(),
            1,
        )

    def test_approved_entry_is_locked_for_non_admin_and_deletable_by_admin(self):
        entry = self.Ledger(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 31),
            source_type="manual",
            actual_minutes=60,
            billable_minutes=60,
            status=pwls.STATUS_APPROVED,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

        producer_client = app.test_client()
        self._login(producer_client, self.producer_acc)
        producer_client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/delete"
        )
        self.assertIsNotNone(db.session.get(self.Ledger, entry_id))

        admin_client = app.test_client()
        self._login(admin_client, self.admin_acc)
        admin_client.post(f"/projects/{self.project.id}/working-hours/{entry_id}/delete")
        self.assertIsNone(db.session.get(self.Ledger, entry_id))

    def test_update_billable_hours(self):
        entry = self.Ledger(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 31),
            source_type="manual",
            actual_minutes=180,
            billable_minutes=180,
            status=pwls.STATUS_SUBMITTED,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        client = app.test_client()
        self._login(client, self.producer_acc)
        client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/update-billable",
            data={"billable_hours": "2", "billable_minutes": "0"},
        )
        self.assertEqual(db.session.get(self.Ledger, entry_id).billable_minutes, 120)
        self.assertEqual(
            self.M["ProjectActivityLog"].query.filter_by(
                event_type=pae.WORKING_HOURS_BILLABLE_UPDATED
            ).count(),
            1,
        )

    def test_billable_checkbox_toggles_zero_and_actual(self):
        entry = self.Ledger(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 31),
            source_type="manual",
            actual_minutes=90,
            billable_minutes=90,
            status=pwls.STATUS_SUBMITTED,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        client = app.test_client()
        self._login(client, self.producer_acc)

        client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/update-billable",
            data={"billable_toggle": "1"},
        )
        self.assertEqual(db.session.get(self.Ledger, entry_id).billable_minutes, 0)

        client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/update-billable",
            data={"billable_toggle": "1", "is_billable": "1"},
        )
        self.assertEqual(db.session.get(self.Ledger, entry_id).billable_minutes, 90)

    def test_manager_can_edit_pending_hours_from_approval_panel(self):
        entry = self.Ledger(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 31),
            source_type="work_session",
            title="Work session",
            actual_minutes=2,
            billable_minutes=2,
            status=pwls.STATUS_SUBMITTED,
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id
        client = app.test_client()
        self._login(client, self.producer_acc)
        client.post(
            f"/projects/{self.project.id}/working-hours/{entry_id}/edit",
            data={
                "duration_hours": "1",
                "duration_minutes": "15",
                "billable_hours": "1",
                "billable_minutes": "0",
                "title": "Sync pass",
            },
        )
        updated = db.session.get(self.Ledger, entry_id)
        self.assertEqual(updated.actual_minutes, 75)
        self.assertEqual(updated.billable_minutes, 60)
        self.assertEqual(updated.title, "Sync pass")
        self.assertEqual(updated.status, pwls.STATUS_SUBMITTED)

    def test_member_only_sees_own_rows(self):
        db.session.add_all(
            [
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.editor_user.id,
                    work_date=date(2026, 7, 31),
                    source_type="manual",
                    title="Editor entry",
                    actual_minutes=60,
                    billable_minutes=60,
                    status=pwls.STATUS_APPROVED,
                ),
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.other_user.id,
                    work_date=date(2026, 7, 31),
                    source_type="manual",
                    title="Somebody else entry",
                    actual_minutes=90,
                    billable_minutes=90,
                    status=pwls.STATUS_APPROVED,
                ),
            ]
        )
        db.session.commit()
        client = app.test_client()
        self._login(client, self.editor_acc)
        body = client.get(f"/projects/{self.project.id}/working-hours").data
        self.assertIn(b"Editor entry", body)
        self.assertNotIn(b"Somebody else entry", body)

        producer_client = app.test_client()
        self._login(producer_client, self.producer_acc)
        producer_body = producer_client.get(
            f"/projects/{self.project.id}/working-hours"
        ).data
        self.assertIn(b"Editor entry", producer_body)
        self.assertIn(b"Somebody else entry", producer_body)

    def test_log_table_lists_approved_rows_only_by_default(self):
        db.session.add_all(
            [
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.editor_user.id,
                    work_date=date(2026, 7, 31),
                    source_type="manual",
                    title="Approved entry",
                    actual_minutes=60,
                    billable_minutes=60,
                    status=pwls.STATUS_APPROVED,
                ),
                self.Ledger(
                    project_id=self.project.id,
                    user_id=self.editor_user.id,
                    work_date=date(2026, 7, 31),
                    source_type="manual",
                    title="Waiting entry",
                    actual_minutes=90,
                    billable_minutes=90,
                    status=pwls.STATUS_SUBMITTED,
                ),
            ]
        )
        db.session.commit()
        client = app.test_client()
        self._login(client, self.editor_acc)

        body = client.get(f"/projects/{self.project.id}/working-hours").data
        self.assertIn(b"Approved entry", body)
        self.assertNotIn(b"Waiting entry", body)
        # Totals still account for pending hours (60 + 90 = 2h 30m actual).
        self.assertIn(b"2h 30m", body)

        filtered = client.get(
            f"/projects/{self.project.id}/working-hours?status={pwls.STATUS_SUBMITTED}"
        ).data
        self.assertIn(b"Waiting entry", filtered)
        self.assertNotIn(b"Approved entry", filtered)

    def test_csv_export(self):
        db.session.add(
            self.Ledger(
                project_id=self.project.id,
                user_id=self.editor_user.id,
                work_date=date(2026, 7, 31),
                source_type="manual",
                department_key="editorial",
                work_type="offline_editing",
                title="Assembly",
                actual_minutes=90,
                billable_minutes=90,
                status=pwls.STATUS_APPROVED,
            )
        )
        db.session.commit()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])
        self.assertIn("attachment", resp.headers["Content-Disposition"])
        text = resp.data.decode("utf-8")
        self.assertIn("billable_minutes", text.splitlines()[0])
        self.assertIn("Assembly", text)
        self.assertIn("TOTAL BY DEPARTMENT", text)

    def test_backfill_route_is_admin_only(self):
        client = app.test_client()
        self._login(client, self.producer_acc)
        # The control-panel page guard redirects before the route's own admin check.
        self.assertIn(client.post("/control/working-hours/backfill").status_code, (302, 403))

        admin_client = app.test_client()
        self._login(admin_client, self.admin_acc)
        resp = admin_client.post(
            "/control/working-hours/backfill", headers={"Accept": "application/json"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
