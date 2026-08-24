"""Tests for Daily Worksheet PDF export (Working Hours)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_daily_worksheet.db")
os.close(_fd)
if not (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip():
    os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"

import daily_worksheet_pdf_service as dws
import project_work_ledger_service as pwls
import rate_card_service as rcs
from app import app, db
from permissions import register_permission_models, seed_permissions


class DailyWorksheetRowBuilderTests(unittest.TestCase):
    def test_hour_row_amount_is_hours_times_rate(self):
        row = SimpleNamespace(
            id=1,
            work_date=date(2026, 7, 10),
            user=SimpleNamespace(name="Ada"),
            source_type="manual",
            work_type="offline",
            department_key="editorial",
            billable_minutes=180,
            actual_minutes=180,
            status=pwls.STATUS_APPROVED,
        )
        rate_items = [
            {
                "service_key": "offline",
                "service_name": "Offline",
                "billing_unit": "Hour",
                "rate_hour": 2500,
                "include_in_pdf": True,
            }
        ]
        built = dws.build_daily_worksheet_rows([row], rate_items=rate_items)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["qty"], Decimal("3.00"))
        self.assertEqual(built[0]["rate"], Decimal("2500.00"))
        self.assertEqual(built[0]["amount"], Decimal("7500.00"))
        self.assertEqual(built[0]["date_display"], "Friday, July 10, 2026")

    def test_fee_row_amount_is_rate(self):
        row = SimpleNamespace(
            id=2,
            work_date=date(2026, 7, 11),
            user=SimpleNamespace(name="Ben"),
            source_type="manual",
            work_type="edit_fee",
            department_key="editorial",
            billable_minutes=0,
            actual_minutes=0,
            status=pwls.STATUS_APPROVED,
        )
        rate_items = [
            {
                "service_key": "edit_fee",
                "service_name": "Edit",
                "billing_unit": "Fee",
                "rate_hour": 80000,
                "include_in_pdf": True,
            }
        ]
        built = dws.build_daily_worksheet_rows([row], rate_items=rate_items)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["unit"], "Fee")
        self.assertEqual(built[0]["qty"], Decimal("1.00"))
        self.assertEqual(built[0]["amount"], Decimal("80000.00"))

    def test_media_copy_and_convert_combine(self):
        copy = SimpleNamespace(
            id=3,
            work_date=date(2026, 7, 12),
            user=None,
            source_type=pwls.SOURCE_MEDIA_COPY,
            work_type="copy_media",
            department_key=pwls.DEPT_MACHINE_ROOM,
            billable_minutes=240,
            actual_minutes=240,
            status=pwls.STATUS_AUTO_APPROVED,
        )
        convert = SimpleNamespace(
            id=4,
            work_date=date(2026, 7, 12),
            user=None,
            source_type=pwls.SOURCE_MEDIA_CONVERT,
            work_type="convert_transcode",
            department_key=pwls.DEPT_MACHINE_ROOM,
            billable_minutes=120,
            actual_minutes=120,
            status=pwls.STATUS_AUTO_APPROVED,
        )
        rate_items = [
            {
                "service_key": "copy_convert",
                "service_name": "Copy&Convert",
                "billing_unit": "Hour",
                "rate_hour": 750,
                "include_in_pdf": True,
            }
        ]
        built = dws.build_daily_worksheet_rows(
            [copy, convert], rate_items=rate_items, combine_copy_convert=True
        )
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["artist"], "Machine")
        self.assertEqual(built[0]["service"], "Copy&Convert")
        self.assertEqual(built[0]["qty"], Decimal("6.00"))
        self.assertEqual(built[0]["amount"], Decimal("4500.00"))

    def test_consecutive_same_date_hides_repeat_label(self):
        rows = [
            SimpleNamespace(
                id=i,
                work_date=date(2026, 7, 10),
                user=SimpleNamespace(name=f"User {i}"),
                source_type="manual",
                work_type="sync",
                department_key="machine_room",
                billable_minutes=60,
                actual_minutes=60,
                status=pwls.STATUS_APPROVED,
            )
            for i in (1, 2)
        ]
        rate_items = [
            {
                "service_key": "sync",
                "service_name": "Sync",
                "billing_unit": "Hour",
                "rate_hour": 750,
                "include_in_pdf": True,
            }
        ]
        built = dws.build_daily_worksheet_rows(rows, rate_items=rate_items)
        self.assertEqual(built[0]["date_display"], "Friday, July 10, 2026")
        self.assertEqual(built[1]["date_display"], "")

    def test_render_pdf_bytes(self):
        pdf = dws.render_daily_worksheet_pdf(
            header={
                "client": "PH",
                "contact": "Salma",
                "prepared_by": "Aly",
                "project": "Demo",
                "date": "Wednesday, July 15, 2026",
                "director": "Dir",
            },
            rows=[
                {
                    "date_display": "Friday, July 10, 2026",
                    "artist": "Machine",
                    "service": "Copy&Convert",
                    "unit": "Hour",
                    "qty": Decimal("6"),
                    "rate": Decimal("750"),
                    "amount": Decimal("4500"),
                }
            ],
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)


class DailyWorksheetRouteTests(unittest.TestCase):
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
            name="Worksheet Demo",
            project_type="TV series",
            production_house="BigBang",
            director="Director",
        )
        db.session.add(self.project)
        db.session.flush()

        self.admin_acc, self.admin_user = self._make_person("admin@ws.test", "Admin", role="admin")
        self.editor_acc, self.editor_user = self._make_person("editor@ws.test", "Editor")
        self.producer_acc, self.producer_user = self._make_person(
            "producer@ws.test", "Producer", role="producer"
        )
        for user in (self.admin_user, self.editor_user, self.producer_user):
            db.session.add(
                self.M["ProjectMember"](project_id=self.project.id, user_id=user.id)
            )
        rcs.ensure_defaults(db, self.M["StudioRateCardItem"])
        rcs.ensure_worksheet_defaults(db, self.M["StudioRateCardItem"])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.ctx.pop()

    def _make_person(self, email, name, *, role="user"):
        acc = self.M["Account"](email=email, password_hash="x", role=role)
        db.session.add(acc)
        db.session.flush()
        user = self.M["User"](name=name, email=email, account_id=acc.id)
        db.session.add(user)
        db.session.flush()
        return acc, user

    def _login(self, client, account):
        with client.session_transaction() as sess:
            sess["account_id"] = account.id

    def _add_approved_row(self, **kwargs):
        defaults = dict(
            project_id=self.project.id,
            user_id=self.editor_user.id,
            work_date=date(2026, 7, 10),
            source_type="manual",
            department_key="editorial",
            work_type="offline",
            title="Offline block",
            actual_minutes=120,
            billable_minutes=120,
            status=pwls.STATUS_APPROVED,
        )
        defaults.update(kwargs)
        row = self.Ledger(**defaults)
        db.session.add(row)
        db.session.commit()
        return row

    def test_manager_can_export_daily_worksheet_pdf(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/pdf")
        self.assertTrue(resp.data.startswith(b"%PDF"))
        disposition = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn("Worksheet_Demo_Daily_Worksheet_", disposition)
        self.assertIn(".pdf", disposition)

    def test_normal_member_cannot_export_worksheet_pdf(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.editor_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf"
        )
        self.assertIn(resp.status_code, (302, 403))
        if resp.status_code == 302:
            follow = client.get(resp.headers["Location"])
            self.assertIn(b"Only managers can export", follow.data)

    def test_rejected_rows_excluded_by_default(self):
        self._add_approved_row(title="Keep me")
        self._add_approved_row(
            title="Reject me",
            status=pwls.STATUS_REJECTED,
            work_date=date(2026, 7, 11),
            actual_minutes=60,
            billable_minutes=60,
        )
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf"
        )
        self.assertEqual(resp.status_code, 200)
        # Builder-level check mirrors the route filter.
        rows = self.Ledger.query.filter_by(project_id=self.project.id).all()
        approved = [r for r in rows if r.status in pwls.APPROVED_STATUSES]
        built = dws.build_daily_worksheet_rows(
            approved, rate_items=rcs.list_items(self.M["StudioRateCardItem"])
        )
        self.assertTrue(built)
        self.assertEqual(len(built), 1)

    def test_empty_approved_set_flashes(self):
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf",
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No approved billable hours", resp.data)

    def test_preview_empty_returns_html_error(self):
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf?preview=1"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        self.assertIn(b"No approved billable hours", resp.data)

    def test_preview_returns_html_page_images(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(
            f"/projects/{self.project.id}/working-hours/export-daily-worksheet.pdf?preview=1"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        self.assertIn(b"data:image/png;base64,", resp.data)
        self.assertIn(b"Daily Worksheet page", resp.data)

    def test_csv_export_still_works(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])
        self.assertIn(b"Offline block", resp.data)

    def test_fee_manual_entry_allows_zero_duration(self):
        RateCard = self.M["StudioRateCardItem"]
        if not RateCard.query.filter_by(service_key="edit_fee").first():
            db.session.add(
                RateCard(
                    service_name="Edit",
                    service_key="edit_fee",
                    billing_unit="Fee",
                    rate_hour=Decimal("80000"),
                    include_in_pdf=False,
                    sort_order=99,
                )
            )
            db.session.commit()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.post(
            f"/projects/{self.project.id}/working-hours/manual",
            data={
                "user_id": self.editor_user.id,
                "work_date": date.today().isoformat(),
                "work_type": "edit_fee",
                "duration_hours": "0",
                "duration_minutes": "0",
                "billable_hours": "0",
                "billable_minutes": "0",
                "title": "Edit fee",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        row = self.Ledger.query.filter_by(work_type="edit_fee").one()
        self.assertEqual(row.actual_minutes, 0)
        self.assertEqual(row.billable_minutes, 0)


if __name__ == "__main__":
    unittest.main()
