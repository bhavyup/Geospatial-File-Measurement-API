"""In-memory registry of uploaded files.

Design note (see README "Design decisions"): uploads are processed
synchronously, so every record is COMPLETED by the time it is stored.
The registry is deliberately in-memory to keep the service self-contained;
the documented production step is Postgres (+ PostGIS) for metadata and
object storage (S3/GCS) for the raw files.
"""

from __future__ import annotations

import os
import uuid

from .models import StoredFile

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "uploads"))

_files: dict[str, StoredFile] = {}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def save_upload(file_id: str, filename: str, data: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, f"{file_id}_{filename}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def put(record: StoredFile) -> None:
    _files[record.id] = record


def get(file_id: str) -> StoredFile | None:
    return _files.get(file_id)


def list_all() -> list[StoredFile]:
    return list(_files.values())
