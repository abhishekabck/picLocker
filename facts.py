import hashlib, io, mimetypes, os
from dataclasses import dataclass
from pathlib import Path
import imagehash
from PIL import Image
import config


@dataclass
class FileFacts:
    path: Path
    data: bytes
    sha256: str
    phash: str
    size: int
    disk_mtime: float
    mime: str

    @property
    def s3_key(self) -> str:
        return config.S3_KEY_TEMPLATE.format(self.sha256)

    @property
    def s3_path(self) -> str:
        return f"{config.PS3_BUCKET}/{self.s3_key}"


def gather_facts(path: Path) -> FileFacts:
    stat = os.stat(path)
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path)
    return FileFacts(
        path=path,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        phash=str(imagehash.phash(Image.open(io.BytesIO(data)))),
        size=stat.st_size,
        disk_mtime=stat.st_mtime,
        mime=mime or "application/octet-stream",
    )

