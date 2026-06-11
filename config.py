"""Central configuration — every env var is read here and nowhere else."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# PersonalS3 (S3-compatible surface, SigV4 via boto3)
PS3_HOST = os.getenv("PS3_HOST")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
PS3_BUCKET = os.getenv("PS3_BUCKET")

# Object keys are content-addressed: photos/<sha256>
S3_KEY_TEMPLATE = os.getenv("S3_KEY", "photos/{}")

DB_PATH = Path(__file__).parent / os.getenv("PICLOCKER_DB", "piclocker.db")

# Near-duplicate handling (global policy, §8: decided once, not per file)
#   keep    -> near-dup is uploaded as its own content (no data loss)
#   discard -> near-dup is NOT uploaded; its file row links to the similar content
NEAR_DUP_POLICY = os.getenv("PICLOCKER_NEAR_DUP_POLICY", "keep")
NEAR_DUP_THRESHOLD = int(os.getenv("PICLOCKER_NEAR_DUP_THRESHOLD", "5"))

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".ico",
}

ORPHAN_FOLDER_PATH = "/"
ORPHAN_FOLDER_TITLE = "Orphan Files"

# Models
CLIP_MODEL = os.getenv("PICLOCKER_MODEL", "sentence-transformers/clip-ViT-B-32")

similarity_threshold = 0.22

UPLOAD_WORKERS = int(os.getenv("PICLOCKER_UPLOAD_WORKERS", "8"))

SINGLE_FILE_THRESHOLD = 1024 * 1024 * 8
MULTIPART_CHUNK_SIZE = 1024 * 1024 * 8

MULTIPART_UPLOAD_TIME_LIMIT = "-7 days"