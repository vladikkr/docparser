"""Storage and document retrieval.

Both were broken in ways the earlier suite never checked:

- `/upload` recorded a storage path but never wrote the bytes, so the parse task
  was handed an empty buffer and could never succeed.
- `GET /documents/{id}` returned a 500, because `parsed_data` is a JSON string
  in the database while the response schema expects a mapping.
"""

from __future__ import annotations

import json

import pytest

from app.services import storage


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    return tmp_path


class TestStorage:
    def test_save_then_read_round_trips(self, store) -> None:
        payload = b"\x89PNG\r\n\x1a\nfake image bytes"
        path = storage.save(payload, "user-1", "receipt.jpg")
        assert storage.read(path) == payload

    def test_saved_file_exists_on_disk(self, store) -> None:
        path = storage.save(b"bytes", "user-1", "receipt.jpg")
        assert (store / path).is_file()

    def test_path_is_sharded_by_date(self, store) -> None:
        path = storage.save(b"bytes", "user-1", "receipt.jpg")
        assert path.startswith("users/user-1/")
        assert path.endswith(".jpg")

    def test_two_uploads_do_not_collide(self, store) -> None:
        first = storage.save(b"a", "user-1", "receipt.jpg")
        second = storage.save(b"b", "user-1", "receipt.jpg")
        assert first != second
        assert storage.read(first) == b"a"
        assert storage.read(second) == b"b"

    def test_unsafe_filename_is_reduced_to_a_suffix(self, store) -> None:
        path = storage.save(b"bytes", "user-1", "../../evil.png")
        assert ".." not in path
        assert path.endswith(".png")

    def test_unknown_extension_falls_back(self, store) -> None:
        path = storage.save(b"bytes", "user-1", "payload.exe")
        assert path.endswith(".bin")

    def test_delete_removes_the_file(self, store) -> None:
        path = storage.save(b"bytes", "user-1", "receipt.jpg")
        storage.delete(path)
        assert not (store / path).is_file()

    def test_delete_of_absent_file_is_quiet(self, store) -> None:
        storage.delete("users/nobody/missing.jpg")

    def test_read_of_missing_file_raises(self, store) -> None:
        with pytest.raises(storage.StorageError):
            storage.read("users/nobody/missing.jpg")

    @pytest.mark.parametrize(
        "path",
        ["../outside.jpg", "../../etc/passwd", "users/../../escape.jpg"],
    )
    def test_paths_escaping_the_root_are_refused(self, store, path: str) -> None:
        with pytest.raises(storage.StorageError):
            storage.read(path)

    def test_total_bytes_counts_what_was_written(self, store) -> None:
        assert storage.total_bytes() == 0
        storage.save(b"x" * 100, "user-1", "a.jpg")
        storage.save(b"y" * 50, "user-2", "b.jpg")
        assert storage.total_bytes() == 150


class TestParsedDataSerialisation:
    """`parsed_data` is stored as text and must come back as a mapping."""

    @staticmethod
    def _row(parsed_data):
        from datetime import datetime, timezone
        from types import SimpleNamespace

        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            filename="receipt.jpg",
            mime_type="image/jpeg",
            file_size=123,
            document_type="receipt_kkt",
            status="completed",
            parsed_data=parsed_data,
            error_message=None,
            processing_time_ms=42,
            # The fake must carry every column _to_response reads. It had
            # webhook_status only, so adding the delivery fields to the
            # response raised AttributeError here and the test failed for a
            # reason that had nothing to do with what it was checking.
            webhook_status=None,
            webhook_attempts=0,
            webhook_last_attempt=None,
            created_at=now,
            updated_at=now,
            completed_at=now,
        )

    def test_stored_json_string_is_parsed_back(self) -> None:
        from app.api.v1.documents import _to_response

        stored = json.dumps({"total_sum": 20.0, "unp": "790730816"}, ensure_ascii=False)
        result = _to_response(self._row(stored))
        assert result.parsed_data == {"total_sum": 20.0, "unp": "790730816"}

    def test_already_decoded_mapping_passes_through(self) -> None:
        from app.api.v1.documents import _to_response

        payload = {"total_sum": 20.0}
        result = _to_response(self._row(payload))
        assert result.parsed_data == payload

    def test_absent_data_stays_none(self) -> None:
        from app.api.v1.documents import _to_response

        assert _to_response(self._row(None)).parsed_data is None

    def test_corrupt_json_does_not_break_the_response(self) -> None:
        from app.api.v1.documents import _to_response

        result = _to_response(self._row("{not json"))
        assert result.parsed_data is None
        assert result.status == "completed"
