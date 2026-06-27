import sqlite3
from datetime import datetime, timezone
import logging

from piclocker import config
from piclocker.s3_client import get_s3
from piclocker.facts import FileFacts

log = logging.getLogger("piclocker.upload")

def create_and_upload_content(db, facts: FileFacts) -> int:
    """INSERT (PENDING) -> UPLOADING -> put_object -> UPLOADED. Returns content id.

    The PENDING row is committed before any network I/O so a crash
    mid-upload leaves a row that restart logic can find and finish.
    """
    try:
        content_id = db.execute(
            "INSERT INTO CONTENT (sha256_hex, phash, content_mime_type, s3_path)"
            " VALUES (?, ?, ?, ?)",
            [facts.sha256, facts.phash, facts.mime, facts.s3_path],
        ).lastrowid
        db.commit()
    except sqlite3.IntegrityError:
        content_id, status = db.execute(
            "SELECT id, status FROM CONTENT WHERE sha256_hex = ?",
            [facts.sha256],
        ).fetchone()
        if status in ('UPLOADED', 'INDEXED', 'INDEXING'):
            return content_id

    db.execute("UPDATE CONTENT SET status = 'UPLOADING' WHERE id = ?", [content_id])
    db.commit()

    if facts.size > config.SINGLE_FILE_THRESHOLD:
        upload_multipart_content(db, content_id, facts)
    else:
        upload_single_content(db, content_id, facts)

    db.execute(
        "UPDATE CONTENT SET status = 'UPLOADED', uploaded_bytes = ?, uploaded_at = ?"
        " WHERE id = ?",
        [facts.size, datetime.now(timezone.utc).isoformat(), content_id],
    )
    db.commit()
    log.info("uploaded content_id=%s key=%s bytes=%s", content_id, facts.s3_key, facts.size)
    return content_id


def upload_single_content(db, content_id: int, facts: FileFacts):
    get_s3().put_object(
        Bucket=config.PS3_BUCKET,
        Key=facts.s3_key,
        Body=facts.data,
        ContentType=facts.mime,
    )
    log.info("uploaded single content_id=%s key=%s bytes=%s", content_id, facts.s3_key, facts.size)


def __create_multipart_upload_record(db, content_id: int, facts: FileFacts) -> int:
    multipart_id = db.execute(
        "INSERT INTO MULTIPART_UPLOADS (content_id, total_size) VALUES (?, ?)",
        [content_id, facts.size]
    ).lastrowid
    db.commit()
    return multipart_id


def __fresh_multipart_upload(db, content_id: int, facts: FileFacts, upload_id=None, multipart_id=None):
    if multipart_id is None:
        multipart_id = __create_multipart_upload_record(db, content_id, facts)
    log.info("initiated multipart upload content_id=%s key=%s", content_id, facts.s3_key)
    db.execute("UPDATE MULTIPART_UPLOADS SET status = 'UPLOADING' where id = ?", [multipart_id])

    if upload_id is None:
        upload_id = get_s3().create_multipart_upload(
            Bucket=config.PS3_BUCKET,
            Key=facts.s3_key,
            ContentType=facts.mime,
        ).get("UploadId", None)
        if upload_id is None:
            raise Exception("Failed to create multipart upload")
        db.execute(
            "UPDATE MULTIPART_UPLOADS SET upload_id = ? WHERE id = ?",
            [upload_id, multipart_id]
        )
        db.commit()

    done = {pn for (pn,) in db.execute(
        "SELECT part_number FROM MULTIPART_ETAGS WHERE multipart_upload_id = ? and upload_status='UPLOADED'",
        [multipart_id]
    )}
    non_uploaded_pn = {pn: etag_id for (pn, etag_id) in db.execute(
        "SELECT part_number, id FROM MULTIPART_ETAGS WHERE multipart_upload_id = ? and upload_status<>'UPLOADED'",
        [multipart_id]
    )}

    for index, i in enumerate(range(0, len(facts.data), config.MULTIPART_CHUNK_SIZE), start=1):
        if index in done:
            continue
        if non_uploaded_pn.get(index) is None:
            etag_id = db.execute(
                "INSERT INTO MULTIPART_ETAGS (multipart_upload_id, part_number) VALUES (?, ?)",
                [multipart_id, index]
            ).lastrowid
            db.commit()
        else:
            etag_id = non_uploaded_pn[index]

        db.execute("UPDATE MULTIPART_ETAGS SET upload_status = 'UPLOADING' WHERE id = ?", [etag_id])
        db.commit()

        etag = get_s3().upload_part(
            Bucket=config.PS3_BUCKET,
            Key=facts.s3_key,
            PartNumber=index,
            UploadId=upload_id,
            Body=facts.data[i:i + config.MULTIPART_CHUNK_SIZE],
        ).get("ETag", None)

        if etag is None:
            db.execute("UPDATE MULTIPART_ETAGS SET upload_status = 'ERROR' WHERE id = ?", [etag_id])
            db.commit()
            raise Exception("Failed to upload part")

        part_size = min(config.MULTIPART_CHUNK_SIZE, len(facts.data) - i)
        db.execute(
            "UPDATE MULTIPART_ETAGS SET upload_status = 'UPLOADED', part_etag = ?, part_size = ? WHERE id = ?",
            [etag, part_size, etag_id]
        )
        db.commit()
        if index in non_uploaded_pn:
            del non_uploaded_pn[index]
        log.info("uploaded part content_id=%s key=%s part=%s", content_id, facts.s3_key, index)

    parts = [
        {"PartNumber": pn, "ETag": etag} for pn, etag in db.execute(
            "SELECT part_number, part_etag FROM MULTIPART_ETAGS "
            "WHERE multipart_upload_id = ? ORDER BY part_number", [multipart_id]
        )
    ]
    get_s3().complete_multipart_upload(
        Bucket=config.PS3_BUCKET,
        Key=facts.s3_key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    db.execute("UPDATE MULTIPART_UPLOADS SET status = 'UPLOADED' where id = ?", [multipart_id])
    db.commit()
    log.info("completed multipart content_id=%s key=%s", content_id, facts.s3_key)


def upload_multipart_content(db, content_id: int, facts: FileFacts):
    row = db.execute(
        "SELECT id, upload_id, status from MULTIPART_UPLOADS WHERE content_id = ? and initiated_at > datetime('now', ?)",
        [content_id, config.MULTIPART_UPLOAD_TIME_LIMIT]
    ).fetchone()
    if row is None:
        __fresh_multipart_upload(db, content_id, facts)
    elif row[2] == "UPLOADED":
        return
    else:
        multipart_id, upload_id, status = row
        if upload_id is None:
            __fresh_multipart_upload(db, content_id, facts)
        else:
            __fresh_multipart_upload(db, content_id, facts, upload_id=upload_id, multipart_id=multipart_id)
