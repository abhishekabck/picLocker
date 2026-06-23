import math
import numpy as np
import config, upload, ingest
from db import get_db
import pytest
import shutil
import search
import hashlib


def test_fixtures_wire(temp_db, mock_s3, stub_embed):
    assert config.DB_PATH == temp_db and temp_db.exists()      # temp_db repointed + schema built
    assert upload.get_s3() is mock_s3                          # S3 stubbed at the call site
    v = ingest.get_embedding(None)
    assert v.shape == (512,) and v.dtype == np.float32         # CLIP stubbed, no model load


def test_single_file_upload_with_network(temp_db, mock_s3, stub_embed, sample_image):
    content_id = ingest.ingest_file(sample_image)
    with get_db(temp_db) as db:
        record = db.execute(
            "SELECT status FROM CONTENT where id = ?", [content_id]
        ).fetchone()
        assert record is not None and record[0] == "INDEXED"

def test_single_file_upload_without_network(temp_db, stub_embed, mock_s3, sample_image):
    mock_s3.offline = True
    with pytest.raises(ConnectionError):
        ingest.ingest_file(sample_image)

def test_offline_leaves_recoverable_state(temp_db, stub_embed, mock_s3, sample_image):
    mock_s3.offline = True
    with pytest.raises(ConnectionError):
        ingest.ingest_file(sample_image)
    with get_db(temp_db) as db:
        row = db.execute("SELECT status, embedding FROM CONTENT").fetchone()
    assert row is not None
    assert row[0] == "UPLOADING"
    assert row[1] is None

def test_after_offline_it_can_be_recovered(temp_db, stub_embed, mock_s3, sample_image):
    test_offline_leaves_recoverable_state(temp_db, stub_embed, mock_s3, sample_image)
    mock_s3.offline = False
    content_id = ingest.ingest_file(sample_image)
    with get_db(temp_db) as db:
        row = db.execute("SELECT status, embedding FROM CONTENT WHERE id=?", [content_id]).fetchone()
    assert row is not None
    assert row[0] == "INDEXED"
    assert row[1] is not None

def test_input_fixtures(sample_image, make_facts):
    from PIL import Image
    assert sample_image.exists()
    assert Image.open(sample_image).size == (16, 16)        # valid, decodable
    import config
    f = make_facts(b"x" * (config.SINGLE_FILE_THRESHOLD + 1))
    assert f.size == config.SINGLE_FILE_THRESHOLD + 1 and len(f.sha256) == 64
    assert f.s3_key.startswith("photos/")                   # derived property still works

def test_multipart_upload(temp_db, stub_embed, mock_s3, sample_image, make_facts):
    size = config.SINGLE_FILE_THRESHOLD + 1
    facts = make_facts(b"x" * size)
    with get_db(temp_db) as db:
        content_id = upload.create_and_upload_content(db, facts)
        status = db.execute("SELECT status FROM CONTENT WHERE id = ?", [content_id]).fetchone()[0]
        assert status == "UPLOADED"
        mp = db.execute("SELECT id, status FROM MULTIPART_UPLOADS WHERE content_id = ?", [content_id]).fetchone()
        assert mp is not None and mp[1] == "UPLOADED"
        parts = db.execute("SELECT upload_status, part_etag FROM MULTIPART_ETAGS WHERE multipart_upload_id = ?", [mp[0]]).fetchall()
        assert len(parts) == math.ceil(size / config.MULTIPART_CHUNK_SIZE)
        assert all(st == "UPLOADED" and etag for st, etag in parts)


def test_ingest_idempotency(temp_db, stub_embed, mock_s3, sample_image):
    ingest.ingest_file(sample_image)
    ingest.ingest_file(sample_image)

    with get_db(temp_db) as db:
        content_count = db.execute("SELECT count(*) FROM CONTENT").fetchone()[0]
        files_count = db.execute("SELECT count(*) FROM FILES").fetchone()[0]

    assert content_count == 1
    assert files_count == 1

def test_dedup_image(temp_db, stub_embed, mock_s3, sample_image):
    img2 = sample_image.parent / "copy.png"
    shutil.copy(sample_image, img2)

    cid_img1 = ingest.ingest_file(sample_image)
    cid_img2 = ingest.ingest_file(img2)
    with get_db(temp_db) as db:
        content_count = db.execute("SELECT count(*) FROM CONTENT").fetchone()[0]
        files = db.execute("SELECT content_id, image_type FROM FILES ORDER BY id").fetchall()
    assert 1 == content_count
    assert 2 == len(files)
    assert cid_img1 == cid_img2
    assert files[0][0] == files[1][0]
    assert files[0][1] == "ORIGINAL"
    assert files[1][1] == "DUPLICATE"


def _seed(db, name, vec):
    db.execute(
        "INSERT INTO CONTENT (sha256_hex, phash, s3_path, embedding) VALUES (?, ?, ?, ?)",
        [hashlib.sha256(name.encode()).hexdigest(), "0"*16, f"photos/{name}",
         np.asarray(vec, dtype=np.float32).tobytes()])
    db.commit()

def test_search_ranks_and_thresholds(temp_db, monkeypatch):
    q = np.zeros(8, dtype=np.float32); q[0] = 1.0
    monkeypatch.setattr("search.encode_text", lambda text: q)

    with get_db(temp_db) as db:
        aligned = np.zeros(8, dtype=np.float32); aligned[0] = 1.0
        ortho = np.zeros(8, dtype=np.float32); ortho[1] = 1.0   # unit vector ⟂ q → cosine 0.0
        _seed(db, "match", aligned)
        _seed(db, "nomatch", ortho)

    results = search.search("anything")
    paths = [p for _, _, p in results]
    assert "photos/match" in paths
    assert "photos/nomatch" not in paths


def test_search_absent_returns_empty(temp_db, monkeypatch):
    q = np.zeros(8, dtype=np.float32); q[7] = 1.0
    monkeypatch.setattr("search.encode_text", lambda text: q)
    with get_db(temp_db) as db:
        v = np.zeros(8, dtype=np.float32); v[0] = 1.0
        _seed(db, "x", v)
    assert search.search("anything") == []

def test_near_dup_keep_policy(temp_db, stub_embed, sample_image, monkeypatch):
    with get_db(temp_db) as db:
        original_ivec = np.zeros(8, dtype=np.float32); original_ivec[0] = 1.0
        similar_ivec = np.zeros(8, dtype=np.float32); similar_ivec[1] = 1.0
        _seed(db, "original", original_ivec)
        cid = db.execute("SELECT id FROM CONTENT").fetchone()[0]
        monkeypatch.setattr("ingest.find_near_dup", lambda phash_hex=None, phash_map=None, threshold=None: (10, cid))
        ingest.ingest_file(sample_image, policy="keep")

        content_ = db.execute("SELECT id, dup_group, near_dup_distance FROM CONTENT").fetchall()
        assert len(content_) == 2
        assert content_[0][1] == content_[1][1]
        assert content_[1][2] == 10.0

