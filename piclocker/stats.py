from piclocker.db import get_db


def get_stats(db_path) -> dict:
    with get_db(db_path) as db:
        total_content = db.execute("SELECT count(*) FROM CONTENT").fetchone()[0]
        total_files = db.execute("SELECT count(*) FROM FILES").fetchone()[0]
        dupes = db.execute(
            "SELECT count(*) FROM FILES WHERE image_type IN ('DUPLICATE', 'SIMILAR')"
        ).fetchone()[0]
        stored_bytes = db.execute(
            "SELECT coalesce(sum(uploaded_bytes), 0) FROM CONTENT WHERE status = 'INDEXED'"
        ).fetchone()[0]
        saved_bytes = db.execute("""
            SELECT coalesce(sum(c.uploaded_bytes), 0)
            FROM CONTENT c
            WHERE EXISTS (
                SELECT 1 FROM FILES f
                WHERE f.content_id = c.id AND f.image_type IN ('DUPLICATE', 'SIMILAR')
            )
        """).fetchone()[0]
        near_dup_count = db.execute(
            "SELECT count(*) FROM CONTENT WHERE dup_group IS NOT NULL"
        ).fetchone()[0]
        indexed = db.execute(
            "SELECT count(*) FROM CONTENT WHERE status = 'INDEXED'"
        ).fetchone()[0]

    return {
        "total_content": total_content,
        "total_files": total_files,
        "dupes": dupes,
        "stored_bytes": stored_bytes,
        "saved_bytes": saved_bytes,
        "near_dup_count": near_dup_count,
        "indexed": indexed,
    }
