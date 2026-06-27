import logging
import time

import numpy as np

from piclocker import config
from piclocker.db import get_db
from piclocker.embeddings import encode_text

log = logging.getLogger("piclocker.search")


def search(query, k=20):
    t0 = time.perf_counter()
    q = encode_text(query)
    q = q / np.linalg.norm(q)
    t_embed = time.perf_counter()

    with get_db(config.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, s3_path, embedding FROM CONTENT WHERE embedding IS NOT NULL;"
        ).fetchall()

    if not rows:
        log.warning("search query=%r aborted: index empty (no embedded content)", query)
        return []

    ids = [row[0] for row in rows]
    paths = [row[1] for row in rows]
    matrix = np.vstack([np.frombuffer(row[2], dtype=np.float32) for row in rows])
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)

    scores = matrix @ q
    top = np.argsort(-scores)[:k]
    results = [
        (float(scores[i]), ids[i], paths[i])
        for i in top
        if scores[i] >= config.similarity_threshold
    ]

    log.info(
        "search query=%r candidates=%d results=%d top=%.3f embed=%.0fms search=%.1fms",
        query, len(rows), len(results),
        results[0][0] if results else 0.0,
        (t_embed - t0) * 1000,
        (time.perf_counter() - t_embed) * 1000,
    )
    return results
