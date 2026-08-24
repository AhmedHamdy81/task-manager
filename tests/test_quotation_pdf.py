"""Tests for Working Hours quotation PDF export."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix="_tm_quotation.db")
os.close(_fd)
if not (os.environ.get("TASK_MANAGER_TEST_DATABASE") or "").strip():
    os.environ["TASK_MANAGER_TEST_DATABASE"] = f"sqlite:///{_TEST_DB_PATH}"

import project_work_ledger_service as pwls
import quotation_pdf_service as qps
import rate_card_service as rcs
from app import app, db
from permissions import register_permission_models, seed_permissions


class QuotationRowBuilderTests(unittest.TestCase):
    def test_offline_editing_combines_selection(self):
        offline = SimpleNamespace(
            work_date=date(2026, 7, 10),
            source_type="manual",
            work_type="offline_editing",
            billable_minutes=120,
            actual_minutes=120,
        )
        selection = SimpleNamespace(
            work_date=date(2026, 7, 11),
            source_type="manual",
            work_type="selection",
            billable_minutes=60,
            actual_minutes=60,
        )
        rate_items = [
            {
                "service_key": "offline_editing",
                "service_name": "Offline Editing",
                "billing_unit": "Hour",
                "rate_hour": 2500,
                "include_in_pdf": True,
            }
        ]
        built = qps.build_quotation_rows([offline, selection], rate_items=rate_items)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["description"], "Offline Editing")
        self.assertEqual(built[0]["qty"], Decimal("3.00"))
        self.assertEqual(built[0]["cost"], Decimal("7500.00"))

    def test_copy_and_convert_combine(self):
        copy = SimpleNamespace(
            work_date=date(2026, 7, 12),
            source_type=pwls.SOURCE_MEDIA_COPY,
            work_type="copy_media",
            billable_minutes=90,
            actual_minutes=90,
        )
        convert = SimpleNamespace(
            work_date=date(2026, 7, 12),
            source_type=pwls.SOURCE_MEDIA_CONVERT,
            work_type="convert_transcode",
            billable_minutes=30,
            actual_minutes=30,
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
        built = qps.build_quotation_rows([copy, convert], rate_items=rate_items)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["description"], "Copy & Convert")
        self.assertEqual(built[0]["qty"], Decimal("2.00"))
        self.assertEqual(built[0]["cost"], Decimal("1500.00"))

    def test_sync_stays_separate(self):
        copy = SimpleNamespace(
            work_date=date(2026, 7, 12),
            source_type=pwls.SOURCE_MEDIA_COPY,
            work_type="copy_media",
            billable_minutes=60,
            actual_minutes=60,
        )
        sync = SimpleNamespace(
            work_date=date(2026, 7, 13),
            source_type="manual",
            work_type="sync",
            billable_minutes=60,
            actual_minutes=60,
        )
        rate_items = [
            {
                "service_key": "copy_convert",
                "service_name": "Copy&Convert",
                "billing_unit": "Hour",
                "rate_hour": 750,
                "include_in_pdf": True,
            },
            {
                "service_key": "sync",
                "service_name": "Sync",
                "billing_unit": "Hour",
                "rate_hour": 750,
                "include_in_pdf": True,
            },
        ]
        built = qps.build_quotation_rows([copy, sync], rate_items=rate_items)
        labels = [row["description"] for row in built]
        self.assertEqual(labels, ["Copy & Convert", "Sync"])

    def test_commercial_type_is_tvc(self):
        self.assertEqual(qps.quotation_type_label("commercial"), "TVC")

    def test_header_attention_uses_producer_name(self):
        project = SimpleNamespace(
            production_house="Rhino",
            producer_name="Salma Akrab",
            name="Orange - Amr Diab",
            director="Tarek Al Arian",
            project_type="commercial",
        )
        header = qps.build_quotation_header(project, quote_date=date(2026, 8, 24))
        self.assertEqual(header["attention"], "Salma Akrab")
        override = qps.build_quotation_header(
            project, attention="Someone Else", quote_date=date(2026, 8, 24)
        )
        self.assertEqual(override["attention"], "Someone Else")

    def test_render_pdf_bytes(self):
        pdf = qps.render_quotation_pdf(
            header={
                "production": "RHINO PRODUCTIONS",
                "attention": "SALMA",
                "date": "26-07-2026",
                "project": "ORANGE",
                "director": "TAREQ",
                "type": "TVC",
                "year": "2026",
            },
            rows=[
                {
                    "description": "Copy & Convert",
                    "qty": Decimal("15.5"),
                    "unit_price": Decimal("750"),
                    "cost": Decimal("11625"),
                    "currency": "EGP",
                }
            ],
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 800)

    def test_numbers_type_ramp_and_watermark(self):
        self.assertEqual(qps.SIZE_TITLE, 36)
        self.assertEqual(qps.SIZE_TABLE, 10)
        self.assertAlmostEqual(qps.WATERMARK_OPACITY, 0.0548)
        self.assertTrue(qps.LOGO_PATH.is_file())
        self.assertTrue(qps.WATERMARK_PATH.is_file())
        fonts = qps.quotation_fonts()
        self.assertIn(fonts["title"], {"DINCondensed-Bold", "HelveticaNeue-CondensedBold", "Helvetica-Bold"})
        self.assertIn(fonts["light"], {"HelveticaNeue-Light", "Helvetica"})
        self.assertIn(fonts["mono"], {"CourierNew", "Courier"})


class QuotationRouteTests(unittest.TestCase):
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
            name="Quote Demo",
            project_type="commercial",
            production_house="Rhino",
            director="Director",
        )
        db.session.add(self.project)
        db.session.flush()

        self.admin_acc, self.admin_user = self._make_person("admin@q.test", "Admin", role="admin")
        self.editor_acc, self.editor_user = self._make_person("editor@q.test", "Editor")
        self.producer_acc, self.producer_user = self._make_person(
            "producer@q.test", "Producer", role="producer"
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
            work_type="offline_editing",
            title="Offline",
            actual_minutes=120,
            billable_minutes=120,
            status=pwls.STATUS_APPROVED,
        )
        defaults.update(kwargs)
        row = self.Ledger(**defaults)
        db.session.add(row)
        db.session.commit()
        return row

    def test_manager_can_export_quotation_pdf(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours/export-quotation.pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/pdf")
        self.assertTrue(resp.data.startswith(b"%PDF"))
        self.assertIn("Quote_Demo_Quotation_", resp.headers.get("Content-Disposition", ""))

    def test_page_includes_quotation_button(self):
        client = app.test_client()
        self._login(client, self.producer_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Export QUOTATION", resp.data)
        self.assertIn(b"working-hours-quotation-btn", resp.data)

    def test_normal_member_cannot_export_quotation(self):
        self._add_approved_row()
        client = app.test_client()
        self._login(client, self.editor_acc)
        resp = client.get(f"/projects/{self.project.id}/working-hours/export-quotation.pdf")
        self.assertIn(resp.status_code, (302, 403))
