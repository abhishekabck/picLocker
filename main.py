"""PicLocker CLI entry point."""

import argparse
import logging

from piclocker import config
from piclocker.db import ensure_db
from piclocker.ingest import ingest_file, sync_folder
from piclocker.search import search
from piclocker.stats import get_stats
from piclocker.watch import watch_folder


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="piclocker")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="show library summary")

    p_watch = sub.add_parser("watch", help="watch a folder for new images")
    p_watch.add_argument("folder")

    p_sync = sub.add_parser("sync", help="recursively ingest a folder")
    p_sync.add_argument("folder")
    p_sync.add_argument("--title", default=None)

    p_ingest = sub.add_parser("ingest", help="ingest a single file")
    p_ingest.add_argument("file")

    p_search = sub.add_parser("search", help="search images with text")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)

    sub.add_parser("serve", help="start the web UI")

    args = parser.parse_args()
    ensure_db(config.DB_PATH)

    if args.command == "sync":
        sync_folder(args.folder, args.title)
    elif args.command == "ingest":
        ingest_file(args.file)
    elif args.command == "search":
        result = search(args.query, args.limit)
        print(f"{len(result)} results")
        for score, id, path in result:
            print(f"{score:.2f} {id} {path}")
    elif args.command == "stats":
        s = get_stats(config.DB_PATH)
        def fmt_bytes(b):
            for unit in ("B", "KB", "MB", "GB"):
                if b < 1024:
                    return f"{b:3.1f} {unit}"
                b /= 1024
            return f"{b:.1f} TB"
        print(f"content:   {s['total_content']:>6,}  unique images")
        print(f"files:     {s['total_files']:>6,}  local paths ({s['dupes']} duplicates/similar)")
        print(f"stored:    {fmt_bytes(s['stored_bytes'])} on S3")
        print(f"saved:     {fmt_bytes(s['saved_bytes'])} by dedup")
        print(f"near-dups: {s['near_dup_count']:>6,}  grouped images")
        print(f"indexed:   {s['indexed']} / {s['total_content']}")
    elif args.command == "watch":
        watch_folder(args.folder)
    elif args.command == "serve":
        from piclocker.server import run
        run()


if __name__ == "__main__":
    main()
