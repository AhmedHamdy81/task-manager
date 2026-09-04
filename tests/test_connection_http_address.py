"""Connection HTTP address and upload directory helpers."""

from __future__ import annotations

import os
import tempfile
import unittest

import system_seed as sseed


class ConnectionHttpAddressTests(unittest.TestCase):
    def test_normalize_accepts_http_and_https(self):
        self.assertEqual(
            sseed.normalize_connection_http_address("http://127.0.0.1:5001/"),
            "http://127.0.0.1:5001",
        )
        self.assertEqual(
            sseed.normalize_connection_http_address("https://bigbang.example.com"),
            "https://bigbang.example.com",
        )

    def test_normalize_rejects_unsafe_values(self):
        self.assertIsNone(sseed.normalize_connection_http_address(""))
        self.assertIsNone(sseed.normalize_connection_http_address("javascript:alert(1)"))
        self.assertIsNone(sseed.normalize_connection_http_address("ftp://files.local"))
        self.assertIsNone(sseed.normalize_connection_http_address("http://user:pass@host/"))
        self.assertIsNone(sseed.normalize_connection_http_address("http://127.0.0.1:5001/?q=1"))

    def test_absolute_url_from_path_joins_base(self):
        class _Query:
            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        class _Setting:
            query = _Query()

        url = sseed.absolute_url_from_path(
            _Setting,
            "/projects/1",
            fallback="http://192.168.1.20:5001",
        )
        self.assertEqual(url, "http://192.168.1.20:5001/projects/1")


class UploadDirectoryTests(unittest.TestCase):
    def test_normalize_accepts_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            normalized = sseed.normalize_upload_directory(tmp + os.sep)
            self.assertEqual(normalized, os.path.normpath(tmp))

    def test_normalize_rejects_unsafe_paths(self):
        self.assertIsNone(sseed.normalize_upload_directory(""))
        self.assertIsNone(sseed.normalize_upload_directory("/"))
        self.assertIsNone(sseed.normalize_upload_directory("/etc/passwd"))
        self.assertIsNone(sseed.normalize_upload_directory("../relative"))

    def test_pointer_round_trip(self):
        with tempfile.TemporaryDirectory() as app_root:
            with tempfile.TemporaryDirectory() as upload_dir:
                written = sseed.write_upload_directory_pointer(upload_dir, app_root=app_root)
                self.assertEqual(written, os.path.normpath(upload_dir))
                self.assertEqual(
                    sseed.read_upload_directory_pointer(app_root),
                    os.path.normpath(upload_dir),
                )
                self.assertEqual(
                    sseed.resolve_upload_data_directory(app_root=app_root),
                    os.path.normpath(upload_dir),
                )

    def test_history_entity_id_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.normpath(tmp)
            first = sseed.upload_directory_history_entity_id(path)
            second = sseed.upload_directory_history_entity_id(path + os.sep)
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertGreater(first, 0)

    def test_history_add_and_remove(self):
        store: dict[str, object] = {}

        class _Query:
            def filter_by(self, **kwargs):
                self._key = kwargs.get("key")
                return self

            def first(self):
                return store.get(self._key)

        class _Session:
            def add(self, row):
                store[row.key] = row

        class _Db:
            session = _Session()

        class _Setting:
            query = _Query()

            def __init__(self, key, value, description=None, updated_at=None):
                self.key = key
                self.value = value
                self.description = description
                self.updated_at = updated_at

        with tempfile.TemporaryDirectory() as first:
            with tempfile.TemporaryDirectory() as second:
                first_norm = os.path.normpath(first)
                second_norm = os.path.normpath(second)
                history = sseed.add_upload_directory_history(_Db, _Setting, first_norm)
                self.assertEqual(history, [first_norm])
                history = sseed.add_upload_directory_history(_Db, _Setting, second_norm)
                self.assertEqual(history, [second_norm, first_norm])
                history = sseed.add_upload_directory_history(_Db, _Setting, first_norm)
                self.assertEqual(history, [first_norm, second_norm])
                history = sseed.remove_upload_directory_history(_Db, _Setting, second_norm)
                self.assertEqual(history, [first_norm])


if __name__ == "__main__":
    unittest.main()
