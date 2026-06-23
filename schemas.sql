
CREATE TABLE IF NOT EXISTS CONTENT (
    id INTEGER PRIMARY KEY,
    sha256_hex CHAR(64) NOT NULL UNIQUE,
    phash VARCHAR(64) NOT NULL,
    uploaded_bytes INTEGER DEFAULT 0,
    uploaded_at DATETIME,
    content_mime_type VARCHAR(255),
    s3_path TEXT,
    thumbnail_path TEXT,
    embedding BLOB,
    dup_group INTEGER,
    near_dup_distance INTEGER,
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    CHECK(status in ('PENDING', 'UPLOADING', 'UPLOADED', 'INDEXING', 'INDEXED', 'ERROR'))
);

CREATE TABLE IF NOT EXISTS FILES(
    id INTEGER PRIMARY KEY,
    local_path TEXT NOT NULL unique,
    sha256_hex CHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disk_mtime DATETIME NOT NULL,
    present_locally INTEGER(1) NOT NULL DEFAULT 1,
    image_type VARCHAR(10),
    content_id INTEGER,
    parent_folder_id INTEGER,
    FOREIGN KEY(parent_folder_id) REFERENCES SYNCED_FOLDERS(id) ON DELETE SET NULL,
    FOREIGN KEY(content_id) REFERENCES CONTENT(id) ON DELETE SET NULL,
    check (present_locally in (0, 1)),
    check (image_type in ('ORIGINAL', 'DUPLICATE', 'SIMILAR'))  -- Original -> no duplicate exists, DUPLICATE -> exact copy of already uploaded file, similar -> similar image exists.
);

CREATE TABLE IF NOT EXISTS MULTIPART_UPLOADS(
    id INTEGER PRIMARY KEY,
    upload_id varchar(255) UNIQUE,
    content_id INTEGER,
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    total_size INTEGER NOT NULL,
    initiated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(status in ('PENDING', 'UPLOADING', 'UPLOADED', 'ERROR')),
    FOREIGN KEY(content_id) REFERENCES CONTENT(id)
);

CREATE TABLE IF NOT EXISTS MULTIPART_ETAGS(
    id INTEGER PRIMARY KEY,
    multipart_upload_id INTEGER NOT NULL,
    part_number INTEGER,
    part_size INTEGER,
    part_etag VARCHAR(255),
    upload_status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    CHECK(upload_status in ('PENDING', 'UPLOADING', 'UPLOADED', 'ERROR')),
    FOREIGN KEY(multipart_upload_id) REFERENCES MULTIPART_UPLOADS(id)
);

CREATE TABLE IF NOT EXISTS SYNCED_FOLDERS(
    id INTEGER PRIMARY KEY,
    parent_folder_path TEXT NOT NULL unique,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    title VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_multipart_etags_upload_id ON MULTIPART_ETAGS(multipart_upload_id);

CREATE INDEX IF NOT EXISTS idx_files_sha256 ON FILES(sha256_hex);
CREATE INDEX IF NOT EXISTS idx_files_content_id ON FILES(content_id);
CREATE INDEX IF NOT EXISTS idx_content_status ON CONTENT(status);
CREATE INDEX IF NOT EXISTS idx_content_dup_group ON CONTENT(dup_group);