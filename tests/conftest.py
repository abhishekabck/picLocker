"""Shared pytest fixtures.

Three seams that let the whole suite run fast, offline, and without the 600MB
CLIP model:
  - temp_db    : a throwaway SQLite DB per test (config.DB_PATH points at it)
  - mock_s3    : the S3 client the upload code calls, replaced by an in-memory stub
  - stub_embed : CLIP replaced by a fixed vector (no model load)

The `yield` setup/teardown shape is the same one in docs/python-generators.md §8.
monkeypatch reverts every patch automatically when the test ends.
"""
import sys
from pathlib import Path

# the app modules live at the repo root (flat layout); put root on sys.path so
# `import config`, `import upload`, etc. resolve when pytest runs from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib

import pytest
from PIL import Image

import config
from db import ensure_db
from facts import FileFacts
from _stubs import S3Stub, stub_embedding


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Fresh, isolated SQLite DB per test. Repoints config.DB_PATH at a temp
    file (the app reads that attribute at call time) and initialises the schema."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    ensure_db(db_path)
    yield db_path


@pytest.fixture
def mock_s3(monkeypatch):
    """Replace the S3 client with an in-memory stub.

    Patched at `upload.get_s3` — the name in the module that actually CALLS it
    (upload.py did `from s3_client import get_s3`, so that's a separate binding;
    patching `s3_client.get_s3` would miss this copy). Returns the stub so a test
    can flip `mock_s3.offline = True` to simulate a network failure.
    """
    stub = S3Stub()
    monkeypatch.setattr("upload.get_s3", lambda: stub)
    return stub


@pytest.fixture
def stub_embed(monkeypatch):
    """Replace CLIP so no model ever loads.

    - ingest.get_embedding -> a fixed float32 vector (the real one is called as
      get_embedding(image), so the lambda accepts and ignores the arg).
    - ingest.get_model -> no-op (sync_folder pre-warms the model; without this it
      would download/load the real 600MB CLIP).
    """
    monkeypatch.setattr("ingest.get_embedding", lambda image=None: stub_embedding())
    monkeypatch.setattr("ingest.get_model", lambda: None)


@pytest.fixture
def sample_image(tmp_path):
    """A tiny, valid, deterministic PNG on disk — for tests that hit the real
    decode path (gather_facts -> Pillow + pHash). Self-contained, public-repo-safe."""
    p = tmp_path / "sample.png"
    Image.new("RGB", (16, 16), (123, 50, 200)).save(p)
    return p


@pytest.fixture
def make_facts():
    """Factory: build a FileFacts straight from bytes (no real file, no decode),
    so upload/multipart tests can pass arbitrary sizes — e.g.
    `make_facts(b"\\x00" * (config.SINGLE_FILE_THRESHOLD + 1))`. pHash is a dummy:
    these tests exercise the upload logic, not dedup."""
    def _make(data: bytes, mime="application/octet-stream"):
        return FileFacts(
            path=Path("/fake/test-input.bin"),
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
            phash="0" * 16,
            size=len(data),
            disk_mtime=0.0,
            mime=mime,
        )
    return _make
