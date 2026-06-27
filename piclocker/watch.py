import time
import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler, DirCreatedEvent, FileCreatedEvent
from watchdog.observers import Observer

from piclocker.ingest import is_image, walk_images, ingest_file

log = logging.getLogger("piclocker.watch")


class PhotosDirectoryWatcher(FileSystemEventHandler):
    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        if event.is_directory:
            for img_path in walk_images(event.src_path):
                ingest_file(img_path)
        else:
            img_path = Path(event.src_path)
            if is_image(img_path):
                ingest_file(img_path)

    def on_modified(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        if event.is_directory:
            return
        img_path = Path(event.src_path)
        if is_image(img_path):
            try:
                ingest_file(img_path)
            except Exception as e:
                log.warning("error ingesting modified file %s: %s", img_path, e)


def watch_folder(folder: Path | str):
    observer = Observer()
    observer.schedule(PhotosDirectoryWatcher(), str(folder), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
