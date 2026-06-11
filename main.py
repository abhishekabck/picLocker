"""PicLocker CLI entry point."""

import argparse
import logging
import config
from db import ensure_db
from ingest import ingest_file, sync_folder
from search import search


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="piclocker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="recursively ingest a folder")
    p_sync.add_argument("folder")
    p_sync.add_argument("--title", default=None)

    p_ingest = sub.add_parser("ingest", help="ingest a single file")
    p_ingest.add_argument("file")

    p_search = sub.add_parser("search", help="search the Images with text.")
    p_search.add_argument("query", help="query text")
    p_search.add_argument("--limit", type=int, default=20, help="max results")

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


if __name__ == "__main__":
    main()
