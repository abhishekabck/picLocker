# PicLocker — Project Brief

> A problem statement. Read it like a take-home interview prompt. Your
> job is to think, design, and build — **not** to follow a recipe. There
> is no architecture diagram, file layout, library checklist, or
> hour-by-hour plan in this document on purpose.

---

## 1. The problem

You have a self-hosted S3-compatible object store (PersonalS3) running
on your home server. You also have a folder of photos on your laptop
that grows every week. Today that folder is a black hole — you can't
find that one beach photo from two summers ago, you have no idea which
shots are duplicates, and your laptop dies tomorrow you lose
everything.

You want a tool that turns your PersonalS3 instance into a real
personal photo library: it backs the folder up, deduplicates it, makes
the photos searchable by what's *in* them (not just by filename), and
lets you browse them from a tiny web page.

You will build that tool. You will be the only user.

## 2. What you're building (one paragraph)

A program (CLI + a small local web UI) that watches a folder on your
machine, uploads new images to your PersonalS3 buckets via the public
S3 protocol, indexes them with a lightweight ML model so they're
searchable by natural-language query ("dog on a beach", "screenshot of
code", "blurry"), and serves the results back through a browser. It
must keep working when you add 1,000 photos at once, when the network
flaps mid-upload, and when you re-run it on a folder it has already
seen.

## 3. Hard constraints

These are not negotiable. The whole point is that you sit on the user
side of your own service.

1. **PersonalS3 is the storage backend.** All photo bytes live in
   PersonalS3 buckets. You access PersonalS3 **only through its public
   S3-compatible HTTP API** — the same surface AWS S3 exposes
   (`PutObject`, `GetObject`, `ListObjectsV2`, multipart upload,
   presigned URLs, etc.). You may NOT reach into the database, the
   `worker/`, the cleaner, or any internal endpoint. If a feature can't
   be built through the public S3 surface, it can't be built. Period.
2. **You authenticate as a regular PersonalS3 user**, with an access
   key + secret key, using SigV4. No bypass.
3. **Primary language: Python.**
4. **Runs on a single laptop**, no Kubernetes, no cloud spend. Docker
   is allowed (and expected for the release build).
5. **Lives in its own GitHub repo.** PersonalS3 is a dependency you
   talk to over the network, not a submodule you fork.

## 4. Required capabilities (what the program must do)

Each bullet is a *what*, not a *how*. You choose the how.

- **Ingest.** Given a folder path, the program finds every image inside
  it (recursively) and ensures each one is stored exactly once in
  PersonalS3. Re-running on the same folder must not re-upload anything
  and must not produce duplicate index entries.
- **Continuous mode.** The program can run as a long-lived process
  that picks up new files added to the watched folder after it
  started, without restarting.
- **Resilient uploads.** Large files (multi-hundred-MB camera RAWs,
  long videos) upload via the S3 multipart protocol and survive a
  process restart in the middle — the next run resumes, it does not
  start over.
- **Deduplication.** Two photos that are visually the same (same shot,
  different filename / different format / re-saved at lower quality)
  are detected as duplicates. The second one is recorded but not
  re-uploaded. You choose the duplicate policy (keep first? keep
  highest quality? ask?) — but the choice must be defensible.
- **Semantic tagging + search.** Each new photo gets passed through a
  small ML model that produces some representation (tags, embeddings,
  or both — your call). A user can type a natural-language query
  ("snow", "people laughing", "screenshot") and get the most relevant
  photos back, ranked. The search runs against a local index; it does
  not re-download all images per query.
- **Browse.** A small web UI shows query results as thumbnails. The
  thumbnails are served **directly from PersonalS3 via presigned URLs**
  — your web server must not proxy image bytes. The page should render
  for a 500-photo result set without breaking.
- **Stats.** A `stats` endpoint or CLI command tells you: how many
  photos indexed, total bytes stored, duplicates skipped, last upload
  timestamp, search index size on disk.

## 5. Non-functional requirements

- **Throughput.** Ingesting a fresh 1,000-photo folder must saturate
  either your CPU or your upload bandwidth (whichever is the bottleneck)
  — not sit at 5% CPU because everything's serial. Demonstrate that you
  understand the difference between I/O parallelism and CPU
  parallelism in Python.
- **Latency.** Search must return in under 200 ms for a 10,000-photo
  index, measured on your laptop, cold cache.
- **Memory.** Steady-state memory must stay under 2 GB even while
  ingesting. Loading every image into RAM at once is disqualifying.
- **Correctness under crash.** Kill the program with `SIGKILL` at any
  point during ingest. Restart it. End state must be the same as if
  you had let it finish naturally: no orphan multipart uploads on
  PersonalS3, no half-indexed entries that point to non-existent
  objects, no duplicate uploads of the same file.
- **Security.** Your PersonalS3 secret key must never end up in the
  repo, in the docker image, or in CI logs. You decide where it lives
  at runtime.
- **Idempotency.** Every write operation must be safe to retry. Every
  CLI command must be safe to run twice in a row.

## 6. Skill targets

The brief is structured so that solving it well naturally exercises
each of these. You must be able to point at code in the final repo and
explain *which problem this skill solved* — not "I sprinkled async
because the brief asked for it."

- **HTTP APIs** — both consuming (S3 against PersonalS3) and exposing
  (your own web UI).
- **async** — for the parts that are network-bound.
- **threads** — for the parts that are GIL-friendly and I/O-bound, OR
  the parts that have to bridge a synchronous library into an async
  event loop.
- **processes** — for the parts that are CPU-bound and GIL-bound. You
  must be able to justify why you used a process here and a thread
  there.
- **Basic ML** — model choice is yours. It must run locally on CPU. It
  must do something a hand-written rule could not (i.e., zero-shot or
  embedding-based, not "extract EXIF tags"). You must understand and
  be able to explain what the model does.
- **CI/CD** — at minimum: lint + tests run on every PR; a tagged
  release produces a versioned, runnable artifact (docker image OR
  installable wheel — pick one and defend it).
- **GitHub** — the repo must look like a maintained open-source
  project, not a private notebook dump. The bar: a stranger should be
  able to clone, run the tests, and understand the architecture in
  under 15 minutes.

## 7. Acceptance criteria (your "done" definition)

You can mark this project complete when **all** of the following are
true and demonstrable on your machine:

- [ ] `pip install` (or `docker run`) from a clean machine, configure
      with PersonalS3 credentials, point at a folder, get a working
      indexed library — no manual file editing required.
- [ ] You ingest your real Pictures folder end-to-end. It survives at
      least one mid-ingest `Ctrl-C` and one mid-ingest `kill -9`.
- [ ] You run `aws s3 ls s3://<bucket>` against your PersonalS3
      endpoint and see the files there — proving you really did use
      the S3 protocol and not some side channel.
- [ ] You search for `"sunset"` (or any other concept absent from
      filenames) and get correctly-ranked results.
- [ ] You search for a concept that doesn't exist in your library and
      get an empty result, not garbage.
- [ ] Search latency on your full library is under 200 ms (you can
      measure it).
- [ ] You can articulate, without re-reading the code, why you used
      threads in module X and processes in module Y.
- [ ] CI on GitHub runs and is green on the main branch.
- [ ] Tagging a commit on the main branch produces a release artifact
      automatically.
- [ ] A second person could clone the repo, follow the README, and
      run the project against their own PersonalS3 instance.

## 8. Open design decisions

You have to make every one of these calls yourself. There is no
"right" answer — but you must be able to defend the one you pick.

1. **Where does the search index live?** Inside PersonalS3 (as an
   object you re-upload on every change)? Locally next to the program?
   Both?
2. **What happens when the same photo exists in two different folders
   on disk?** One PersonalS3 object with multiple local paths? Two
   objects? What does "delete" mean?
3. **How do you detect that a previously-uploaded photo has been
   deleted locally?** Do you remove it from PersonalS3 too?
4. **How do you handle a photo so large your model can't fit it in
   memory at full resolution?**
5. **What is the right concurrency unit for ingest — one task per
   file, one batch per N files, one pipeline stage per worker?**
   What's the failure-isolation cost of each?
6. **Where does the user's secret key live, and how does the running
   process get it without exposing it to other processes or logs?**
7. **What's your retry policy for a partial multipart upload? How
   long do you keep the upload ID before giving up and reaping it?**
   (Hint: PersonalS3 has opinions about this — read its docs.)
8. **What's the contract for the web UI's `/search` endpoint? What
   does it return when the model is still warming up on the first
   request after a cold start?**
9. **Single bucket for everything, or one bucket per year / per
   source folder? What does the cost of getting that wrong look like
   later?**
10. **What logs do you write, and where?** Imagine you have to debug
    a "this photo didn't upload" bug six months from now with only
    the log file.

These are the questions that separate a script from a system. Write
a short `DESIGN.md` in the repo answering them *before* writing the
code that depends on them.

## 9. Out of scope

Resist scope creep. Don't build:

- Multi-user / multi-tenant. You are the only user.
- Mobile apps. Browser-only.
- Face recognition. Generic semantic tags are enough — and face
  recognition opens a consent / legal can of worms you don't need.
- A fancy front-end framework. A single static HTML page with a
  search box and a grid is the bar.
- Video transcoding. PersonalS3 already does that. You're a customer
  of that capability if you want it — don't reimplement it.
- An admin UI for PersonalS3 itself. Wrong project.

## 10. Suggested timebox

**10–12 focused hours.** If you blow past 15 hours you are
over-engineering — stop, cut a feature from §4, and ship.

When you start hitting "but what if…" thoughts that aren't in §4 or
§5, write them down in `IDEAS.md` and don't build them.

## 11. What to deliver

A GitHub repo containing:

1. Working code that satisfies §7.
2. A `README.md` that a stranger can use to get the project running
   in 10 minutes.
3. A `DESIGN.md` answering the questions in §8 in your own words.
4. A green CI pipeline.
5. At least one tagged release with a downloadable artifact.
6. Tests that fail when you break the things you most care about
   getting right (you choose what those are — and the choice itself
   is part of the design).

## 12. Stretch (only after §7 is fully green)

- A `compare` command: given two folders, tell me which photos are in
  A but not in B (using your dedup logic, not filenames).
- A `migrate` command: move all photos matching a query from one
  bucket to another.
- A CLI subcommand that prints the *embedding-space* nearest neighbor
  of an image — useful for "find more like this."
- A second model: an audio embedding model so the same architecture
  also indexes voice memos.

---

## How to start (not how to build)

1. Read PersonalS3's `docs/` end-to-end, especially `api-reference.md`,
   `multipart.md`, and the section on presigned URLs. You're the
   customer now — those docs are your contract.
2. Spin up PersonalS3 locally (or point at your live instance) and
   manually `aws s3 cp` one file in. Verify it lands. You should
   understand the auth flow before writing any Python.
3. Open a blank file called `DESIGN.md`. Answer the questions in §8.
   *Then* write code.
4. Start with the dumbest possible version: serial, no ML, no UI,
   just "given a folder, upload one file." Get it working
   end-to-end against real PersonalS3 in under an hour. THEN start
   adding the parallelism, the ML, the resumability.

Build the spine first. Hang the muscles on it after.

---

**Good luck.** When you're done, you'll be able to honestly say in
an interview: *"I built and operate a self-hosted S3 service, and I
built a real client application against my own service's public API."*
That sentence is worth this whole project.
