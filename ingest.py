"""Ingest pipeline: discover -> dedup (sha exact, pHash near) -> upload -> record.

Crash-safety contract: CONTENT.status is the single source of truth.
Every transition commits together with the data it describes, so a
kill -9 at any point leaves a recoverable row, never a lie.
"""
import os, io, config, hashlib, sqlite3, logging, mimetypes, imagehash
from PIL import Image
from db import get_db
from pathlib import Path
from s3_client import get_s3
from dataclasses import dataclass
from datetime import datetime, timezone
from upload import create_and_upload_content
from facts import FileFacts, gather_facts
from embeddings import get_model, get_embedding
from concurrent.futures import ThreadPoolExecutor, as_completed


log = logging.getLogger("piclocker.ingest")

# ----------------------------------------------------------------- discovery

def is_image(path: Path) -> bool:
    return path.suffix.lower() in config.IMAGE_EXTENSIONS


def walk_images(root):
    """Lazily yield absolute paths of every image under root, recursively."""
    root = Path(root).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} does not exist or is not a directory")
    for p in root.rglob("*"):
        if p.is_file() and is_image(p):
            yield p.absolute()


# ------------------------------------------------------------------- dedup

def load_dedup_maps(db):
    """sha256 -> content_id and phash -> content_id for every known content."""
    phash_map = {}
    for cid, sha, ph in db.execute("SELECT id, sha256_hex, phash FROM CONTENT WHERE status in ('UPLOADED', 'INDEXED', 'INDEXING')"):
        phash_map[ph] = cid
    return phash_map


def find_near_dup(phash_hex, phash_map, threshold):
    """Closest stored content within Hamming distance <= threshold, else None."""
    current = imagehash.hex_to_hash(phash_hex)
    best = None
    for stored_hex, content_id in phash_map.items():
        distance = imagehash.hex_to_hash(stored_hex) - current
        if distance <= threshold and (best is None or distance < best[0]):
            best = (distance, content_id)
    return best


# ----------------------------------------------------------------- folders

def get_orphan_folder_id(db):
    row = db.execute(
        "SELECT id FROM SYNCED_FOLDERS WHERE parent_folder_path = ?",
        [config.ORPHAN_FOLDER_PATH],
    ).fetchone()
    if row:
        return row[0]
    folder_id = db.execute(
        "INSERT INTO SYNCED_FOLDERS (parent_folder_path, title) VALUES (?, ?)",
        [config.ORPHAN_FOLDER_PATH, config.ORPHAN_FOLDER_TITLE],
    ).lastrowid
    db.commit()
    return folder_id


def resolve_parent_id(db, image_path: Path, parent_id):
    """Explicit id wins; else longest synced-folder prefix; else orphan."""
    if parent_id is not None:
        return parent_id
    best = None
    for folder_id, folder_path in db.execute(
        "SELECT id, parent_folder_path FROM SYNCED_FOLDERS"
    ):
        if folder_path == config.ORPHAN_FOLDER_PATH:
            continue
        if str(image_path).startswith(folder_path):
            if best is None or len(folder_path) > len(best[1]):
                best = (folder_id, folder_path)
    return best[0] if best else get_orphan_folder_id(db)


# ------------------------------------------------------------------ content



# -------------------------------------------------------------- file records

def upsert_file_row(db, facts: FileFacts, image_type, content_id, parent_id):
    """One row per local path: INSERT when new, UPDATE when the path changed.

    The UPDATE arm is what keeps a touched/edited file from being
    re-ingested forever: the stored disk_mtime must always end up
    matching the disk.
    """
    row = db.execute(
        "SELECT id, content_id FROM FILES WHERE local_path = ?", [str(facts.path)]
    ).fetchone()

    if row is None:
        db.execute(
            "INSERT INTO FILES (local_path, sha256_hex, file_size, disk_mtime,"
            " image_type, content_id, parent_folder_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [str(facts.path), facts.sha256, facts.size, facts.disk_mtime,
             image_type, content_id, parent_id],
        )
    else:
        file_id, old_content_id = row
        if old_content_id == content_id:
            # touch / metadata-only change: same bytes, keep the row's type
            db.execute(
                "UPDATE FILES SET disk_mtime = ?, file_size = ? WHERE id = ?",
                [facts.disk_mtime, facts.size, file_id],
            )
        else:
            # the path now holds different content
            db.execute(
                "UPDATE FILES SET sha256_hex = ?, file_size = ?, disk_mtime = ?,"
                " image_type = ?, content_id = ? WHERE id = ?",
                [facts.sha256, facts.size, facts.disk_mtime,
                 image_type, content_id, file_id],
            )
    db.commit()


# ------------------------------------------------------------------- public

def ingest_file(path, parent_id=None, policy=None):
    """Idempotent single-file ingest. Safe to call twice; never uploads known bytes."""
    policy = policy or config.NEAR_DUP_POLICY
    if policy not in ("keep", "discard"):
        raise ValueError(f"unknown near-dup policy: {policy!r}")

    path = Path(path).expanduser().absolute()
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist or is not a file")

    facts = gather_facts(path)

    with get_db(config.DB_PATH) as db:
        phash_map = load_dedup_maps(db)
        parent_id = resolve_parent_id(db, path, parent_id)

        existing = db.execute(
            "SELECT id, status FROM CONTENT WHERE sha256_hex = ?", [facts.sha256]
        ).fetchone()
        if existing:
            content_id, status = existing
            if status in ("UPLOADED", "INDEXING", "INDEXED"):
                # exact duplicate — bytes already fully in PersonalS3
                has_files = db.execute(
                    "SELECT 1 FROM FILES WHERE content_id = ? LIMIT 1", [content_id]
                ).fetchone()
                image_type = "DUPLICATE" if has_files else "ORIGINAL"
                log.info("exact-dup path=%s content_id=%s (no upload)", path, content_id)
            else:
                # row exists but the upload was interrupted -> resume it
                content_id = create_and_upload_content(db, facts)
                image_type = "ORIGINAL"
                log.info("resumed interrupted upload path=%s content_id=%s", path, content_id)
        else:
            near = find_near_dup(facts.phash, phash_map, config.NEAR_DUP_THRESHOLD)
            if near is not None and policy == "discard":
                distance, content_id = near
                image_type = "SIMILAR"
                log.info(
                    "near-dup path=%s distance=%s content_id=%s (policy=discard, no upload)",
                    path, distance, content_id,
                )
            else:
                content_id = create_and_upload_content(db, facts)
                if near is not None:
                    log.info(
                        "near-dup path=%s distance=%s kept as own content (policy=keep)",
                        path, near[0],
                    )
                    distance, matched_id = near
                    row = db.execute(
                        "SELECT dup_group FROM CONTENT WHERE id = ?",
                        [matched_id]
                    ).fetchall()
                    if row is None:
                        dup_group = matched_id
                    else:
                        dup_group = row[0][0]
                    db.execute(
                        "UPDATE CONTENT SET dup_group = ?, near_dup_distance = ? WHERE id = ?",
                        [dup_group, distance, content_id]
                    )
                db.commit()
                image_type = "ORIGINAL"

        upsert_file_row(db, facts, image_type, content_id, parent_id)
        embedded_image(Image.open(io.BytesIO(facts.data)), content_id, db)
        return content_id

def embedded_image(image: Image, content_id: int, db: get_db, force=False):
    if image is None:
        raise Exception("Invalid Image bytes.")

    row = db.execute(
        "SELECT id, status, embedding FROM CONTENT WHERE id = ? ", [content_id]
    ).fetchone()

    if content_id is None or row is None:
        raise Exception("Invalid Content ID.")

    if not force and row[1] == "INDEXED" and row[2] is not None:
        # already indexed skipping
        return

    db.execute(
        "UPDATE CONTENT SET status = 'INDEXING' "
        "WHERE id = ?;",
        [content_id]
    )
    db.commit()
    try:
        vec = get_embedding(image)
    except Exception as e:
        db.execute("UPDATE CONTENT SET status = 'ERROR' "
                   "WHERE id = ?;", [content_id])
        db.commit()
        raise Exception(f"Error while embedding image: {e}")

    vec = vec.astype("float32").tobytes()
    db.execute("UPDATE CONTENT SET status = 'INDEXED', embedding = ? WHERE id = ?;",
               [vec, content_id])
    db.commit()


def sync_folder(folder, title=None):
    """Recursively ingest a folder; cheap on re-run (path+mtime skip)."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} does not exist or is not a directory")
    folder = folder.absolute()

    image_paths = []
    with get_db(config.DB_PATH) as db:
        row = db.execute(
            "SELECT id FROM SYNCED_FOLDERS WHERE parent_folder_path = ?",
            [str(folder)],
        ).fetchone()
        if row is None:
            folder_id = db.execute(
                "INSERT INTO SYNCED_FOLDERS (parent_folder_path, title) VALUES (?, ?)",
                [str(folder), title or folder.name],
            ).lastrowid
            db.commit()
        else:
            folder_id = row[0]

        stats = {"ingested": 0, "skipped": 0, "errors": 0}
        for image_path in walk_images(folder):
            known = db.execute(
                "SELECT disk_mtime FROM FILES WHERE local_path = ?",
                [str(image_path)],
            ).fetchone()
            if known and known[0] == os.stat(image_path).st_mtime:
                stats["skipped"] += 1
                continue
            image_paths.append(image_path)
        get_model()           # Pre Warming the CLIP model.. to avoid concurrent calls
        with ThreadPoolExecutor(max_workers=config.UPLOAD_WORKERS) as executor:
            futures = {executor.submit(
                ingest_file,
                image_path,
                parent_id=folder_id,
                policy=config.NEAR_DUP_POLICY
            ): image_path for image_path in image_paths}
            for future in as_completed(futures):
                image_path = futures[future]
                try:
                    future.result()
                    stats["ingested"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    log.exception("error ingesting image '%s': %s", image_path, e)


    log.info("sync folder=%s %s", folder, stats)
    return stats
