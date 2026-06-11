# IDEAS — parked, not built

> Ideas that came up during design and build. **None of these are in v1**
> (see the brief §4 for what v1 *is*, §9 for what's explicitly out of scope).
> This file exists so an exciting idea gets written down and *out of the way*
> instead of derailing the build. Each entry says what it is, **why it's
> parked**, and **when it would actually earn its keep** — so future-me
> doesn't re-litigate a decision already reasoned through.
>
> Several of these only make sense once PicLocker stops being a single-user,
> single-laptop tool. Those are tagged **[multi-user / decentralized]**.

---

## Local-only / offline-first search (decouple index from cloud backup)  [product direction]

Semantic search (CLIP embedding + cosine) is **100% local** — it never touches
the server. So a user could search their photos offline / without a compulsory
upload to PersonalS3 at all. Today the index is coupled to the upload (`upload
→ embed`), so no internet → nothing new is searchable.

- **Why parked:** the brief *defines* PicLocker as an S3 client (§1–3: "all
  photo bytes live in PersonalS3 buckets"); backup is the project's whole
  purpose and the §6 skill targets (SigV4, multipart, presigned) *are* that S3
  client work. Dropping mandatory backup changes what the project is.
- **Two sub-ideas:**
  1. *Offline-graceful (mostly in-scope):* keep backup mandatory but **embed
     independent of upload**, so a photo is searchable the instant it's indexed
     and the upload becomes a separate retryable backup. Needs a two-axis status
     (index-status vs upload-status) instead of the linear state machine.
  2. *Full local-only mode:* backup becomes optional — a different product (a
     local photo-search tool), not the brief's S3-backed library.
- **Earns its keep when:** PicLocker is pitched as a standalone product, not a
  take-home demonstrating S3-client engineering.

## `.piclocker` per-folder manifest  [multi-user / decentralized]

A `.git`-style `.piclocker` directory in each synced folder, holding a local
manifest of what's been synced — to speed up re-scans or make folders portable.

- **Why parked:** the central SQLite DB already does fast re-sync via
  `files.local_path` + `files.disk_mtime` (stat each file, skip if unchanged —
  no hashing). A per-folder manifest is the *same data in a second store*, with
  no speed win (you must `stat()` every file either way) and a new consistency
  problem (which wins after a crash, the manifest or the DB?). Single source of
  truth = the DB.
- **Earns its keep when:** folders need to be **portable across machines** — a
  folder carries its own sync state so a second machine can pick it up. That's
  inherently multi-machine, i.e. the decentralized future.

## Multiple buckets (per-folder / per-year / per-source)  [multi-user / decentralized]

Partition objects across several PersonalS3 buckets instead of one.

- **Why parked:** one bucket + **content-hash object keys** (`photos/<sha256>`)
  is cleaner — keys never collide, and same-content-same-key makes dedup fall
  out for free. Per-folder buckets actively *break* dedup (same photo in two
  folders → upload twice) and couple durable remote storage to fluid local
  folder names. You also can't rename a bucket, so a wrong split costs a full
  re-upload to fix.
- **Earns its keep when:** per-bucket **lifecycle policies** (e.g. cold-storage
  archival of old photos), or **per-user buckets / access control** in a
  multi-user deployment.

## Interactive near-dup resolution + `review` command

Let the user choose per near-duplicate (keep-first / keep-both / merge) instead
of one global automated policy, via a `review` command over near-dup clusters.

- **Why parked:** ingest must run **unattended** (1,000-photo backfill,
  continuous watch) — blocking on a human prompt per near-dup fights the §5
  throughput requirement. v1 uses one global, automated, non-destructive policy.
- **Earns its keep when:** a deliberate, user-driven curation flow is wanted —
  decoupled from ingest, run on demand.

## FAISS / approximate-nearest-neighbor index

Replace the brute-force cosine scan with an ANN index (FAISS, HNSW) for
sub-linear search.

- **Why parked:** at 10k vectors, a brute-force `(N,512)` numpy matmul is ~5 ms
  — far under the 200 ms bar. ANN is "FAISS for 10k" over-engineering.
- **Earns its keep when:** the library reaches **millions** of vectors, where
  the linear scan finally costs real wall-clock.

## Explicit web delete (destructive purge from S3)

A UI action to actually remove an object from PersonalS3 (vs. v1's
`present_locally=0`, which only records local removal and keeps the bytes).

- **Why parked:** §4's web bar is **browse-only**; a destructive mutation is
  beyond it. v1 never deletes cloud bytes automatically (it's a backup).
- **Earns its keep when:** time allows in v1 as a small add, or as a deliberate
  later feature (with confirmation + reference-count check before reaping).

## External persistent queue (Redis, etc.)  [multi-user / decentralized]

Back the ingest pipeline with a durable queue service instead of in-memory
queues rebuilt from the DB.

- **Why parked:** SQLite is already the single source of truth; in-memory
  queues rebuilt on startup from `WHERE status != 'INDEXED'` are simpler *and*
  more correct for one process. Redis would re-introduce the two-stores-disagree
  problem.
- **Earns its keep when:** **multiple processes or machines** share one ingest
  queue over a network.

## Index stored in PersonalS3 (piggyback)

Keep the search index/DB as an object in S3, re-uploaded on change.

- **Why parked:** the index lives locally (SQLite, 20 MB for 10k); re-uploading
  it on every change is wasteful and just relocates the crash-safety problem
  onto the index object.
- **Earns its keep when:** the index must **sync across machines** — again, the
  decentralized future.

---

## Brief §12 stretch goals (only after §7 is green)

Listed in the brief, captured here so this is the one place to look:
- `compare` command — photos in folder A but not B (by dedup logic, not names).
- `migrate` command — move all photos matching a query between buckets.
- embedding-space nearest-neighbor of an image ("find more like this").
- a second (audio) embedding model so the same architecture indexes voice memos.
