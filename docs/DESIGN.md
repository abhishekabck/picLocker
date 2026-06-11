# PicLocker — Design

> **How to use this scaffold:** the **bullets** under each section are *your*
> decisions, reflected back from our design session — they're reminders, not
> the answer. The **`✍️ TODO (you)`** blocks are where *you* write the
> defense in your own words (that's the part that matters in an interview).
> Delete each TODO block once you've written its prose.

---

## 1. What this is

> - PicLocker is a Web + CLI application which allows users to have backup of their images stored in their Device.
> - PicLocker uses PersonalS3 verified SIGV4 key to store the images + thumbnails in self deployed cloud.
> - Beside from backup PicLocker allows users to search images based on the content present in them.

---

## 2. Architecture — the ingest pipeline

**Decision (reflected back):** stage-per-worker pipeline, three meaningful lanes,
DB as the single durable source of truth.

```
discover ─▶ PREP lane ─▶ CLIP lane ─▶ UPLOAD lane ─▶ DB commit
            (threads)    (processes)   (threads)
            hash         encode        PutObject /
            decode/resize embedding    multipart
            pHash
```

- **Lanes & why each:** PREP = **threads** (hash/decode/pHash all run in
  C-extensions that release the GIL). CLIP = **processes** (the one heavy,
  sustained CPU stage; torch already saturates cores internally, so a process
  pool gives clean CPU parallelism + isolation). UPLOAD = **threads/async**
  (network I/O). DB write = serialized (SQLite single-writer, fine — writes are
  tiny).
- **Saturates both bottlenecks at once:** uploads (bandwidth) run *while* CLIP
  (CPU) runs — satisfies §5.
- **Crash-safety:** queues live in RAM and vanish on `kill -9`; the **`status`
  column is the durable truth**. Each stage transition commits its result +
  status bump in **one transaction**. Recovery = rebuild queues from
  `WHERE status != 'INDEXED'`, redo the cheap deterministic stages, resume the
  expensive ones (multipart from the parts table).

> - **Threads:-** Threads are used in python where python releases GIL. Shared memory.
> - **Process:-** Process are used when the python does not release GIL. Separate memory 
> - PREP are stages where CPU is occupied, but they use C/C++ bases libraries thus they have their own running loop thus Python GIL is released here, and we can use multiple threads here.
> - CLIP is ML model, and it occupies the CPU fully so using multithreading here looses its purpose as everything executes sequentially here. Thus using separate process for CLIP is best use case.
> - Upload is an IO operation thus we use async/await here for multiple uploads.

---

## 3. Data model

**Decision:** four tables — `CONTENT` (one row per unique bytes, keyed by
`sha256_hex UNIQUE`), `FILES` (one row per disk path), `MULTIPART_UPLOADS`,
`MULTIPART_ETAGS`. Full DDL lives in [`schemas.sql`](../schemas.sql) — single
source of truth, not duplicated here.

> - Files table: stores the file characteristics with respect to disk.
> - Content table: stores the hashes + where does the file exists online
> - File vs content M21 relation: files can have duplicate on local but content ensures that even those many files does not get uploaded twice on the bucket. 
> - transitions commits need to be atomic to avoid any unsynced behavior between status + other columns.
> - Multipart uploads and etags are the tables used for files greater than 8 mb; 
> we split the file in some same sized bytes and the upload them to the bucket, the uploaded part returns ETAG which is recorded in table and used when ordering the parts for the multipart completion. 

---

## 4. The §8 design decisions

### Q1 — Where does the search index live?
- **Decision:** local SQLite next to the program; embeddings stored as BLOBs,
  hydrated into a RAM `(N,512)` numpy matrix on startup. **Not** re-uploaded
  into PersonalS3.

> - we store search indexes(embeddings) on local SQLite as they are faster in comparison to the updating on personalS3.
> - storing embeddings on local and loading on ram is much cheaper than loading from network -> for 10000 images the embedding cost is around 20MB which is much cheaper.
> - we avoid piggybagging to s3 as it only records when everything is completed causing us to repeat everything if upload fails. 

### Q2 — Same photo in two folders? What does "delete" mean?
- **Decision:** content/files split — one `content` row (by `sha256`), one
  `files` row per path. "Delete a file" = its `files` row → `present_locally=0`;
  the S3 object survives while any file references the content.

> - As stated above this application also serves as backup so deleting a file only causes the file table column present_locally from 1 to 2, But it does not affect how the content present in the cloud.

### Q3 — Detect a locally-deleted photo? Remove it from S3 too?
- **Decision:** detect on scan (in DB, absent on disk → `present_locally=0`).
  **Do not** delete from S3 (it's a backup). Explicit web/CLI purge is a later
  opt-in (IDEAS.md).

> - Intentionally deleting a file from cloud just because it is not present locally loses it's properly as backup tool

### Q4 — Photo too large to fit the model in memory?
- **Decision:** decode-time downscaling (Pillow `Image.draft()` for JPEG) so the
  full-res array is never materialized; cap dimensions before CLIP.

> ✍️ TODO (you): defend — why `.resize()` alone doesn't help (decodes full
> first), and the memory math vs. the 2 GB ceiling.

### Q5 — Concurrency unit for ingest?
- **Decision:** pipeline (stage-per-worker), three lanes — see §2.

> ✍️ TODO (you): covered in §2's TODO — make sure the failure-isolation
> comparison (per-file vs. per-batch vs. pipeline) is written down here or there.

### Q6 — Where does the secret key live, leak-free?
- **Decision:** boto3 default credential chain — `~/.aws/credentials` (named
  profile) on the laptop, env vars injected at `docker run`; endpoint via
  `endpoint_url`. `.env` is gitignored; secret never in repo/image/CI.

> ✍️ TODO (you): defend — the resolution-chain (env vars override file → one
> code path for laptop + Docker); the three leak rules; why keyring/secret-
> manager is over-engineering here.

### Q7 — Multipart retry / reap policy?
- **Decision:** PersonalS3 reaps abandoned multipart uploads after **7 days**
  (completed objects safe). Resume from `MULTIPART_ETAGS`. Error fork:
  `NoSuchUpload`/404 → start over; timeout/5xx → retry the same part. Startup
  sweep: `ListMultipartUploads` reconciled against `MULTIPART_UPLOADS` (not in
  table → abort orphan; in table → resume).

> ✍️ TODO (you): defend — why the branch is on error-*code* not a timer; the
> crash-order that creates a server-side orphan (Create succeeds, crash before
> persisting upload_id) and how the sweep reaps it idempotently.

### Q8 — `/search` contract, incl. cold start?
- **Decision:** during warm-up (model + matrix loading) return a "preparing" /
  `503` state. Normal response = ranked list. Empty-result for an absent concept
  via a **minimum-similarity threshold** (CLIP scores run ~0.25–0.3), tuned
  **empirically** against the real library.

> ✍️ TODO (you): defend — why cosine *always* returns a top-N so "empty not
> garbage" *requires* a threshold; note the threshold value is TBD pending tests
> (that's the honest answer, not a number pulled from air).

### Q9 — One bucket or many?
- **Decision:** **single bucket**, object key = content hash
  (`photos/<sha256>`). Folder-agnostic. Watched folders tracked in a table for
  *scanning*, not mapped to buckets.
> - having single bucket + <sha256> as name is always unique. reason: we never upload the exact 
> duplicate but point to uploaded image thus sha256 remains exact same. + having bucket + folder
> means uploading the same bytes again even if the image with byte exists but in different bucket
> for the policy.


### Q10 — What logs, where?
- **Decision:** log **reason + file location + stage** on failure; a **stable
  identifier** (content_id / sha256) on *every* line so one photo's journey is
  greppable; **structured** (key=value / JSON); to **stdout** (Docker-friendly);
  INFO for transitions, ERROR for failures.

> - suppose a photo never uploaded due to some error. now 6 months later we are checking logs then we only need to know what the file was where it was and the reason for failure; as other things are computable.
> - here we do not believe in the hashes but recompute them because it may be possible that the image itself is relaced with same name of image. 


---

## 5. How the non-functionals are met

> ✍️ TODO (you): a short table mapping each §5 requirement → where in the design
> it's satisfied. Throughput (pipeline saturates CPU+bandwidth), latency
> (in-RAM matmul <200 ms), memory (decode-discard, draft mode, <2 GB),
> crash-safety (status column + atomic commits + multipart resume + orphan
> sweep), security (Q6), idempotency (sha256 UNIQUE, path+mtime skip).
