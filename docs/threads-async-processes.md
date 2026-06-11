# Threads vs. Async vs. Processes — a working reference

> The three ways to "do more than one thing at once" in Python. This is the
> conceptual core of the §6 skill target (and PicLocker's parallel ingest).
> Part 1 = general/OS-level (language-agnostic). Part 2 = Python specifics +
> the GIL. Part 3 = the exact differences. Part 4 = when to use which. Part 5 =
> how it maps to PicLocker.

---

## 0. First, two words people mix up

- **Concurrency** = *dealing with* many things at once — structure: tasks that
  can be in progress at the same time (interleaved). One cook juggling 3 dishes.
- **Parallelism** = *doing* many things at once — execution: literally running
  simultaneously on multiple cores. Three cooks, three dishes.

Threads/async give you **concurrency**. Only processes (or true multi-core
execution) give you **parallelism**. This distinction is the whole answer to
"why threads here, processes there."

---

## PART 1 — The general picture (OS level, any language)

### Process
The OS's unit of **resource ownership**. Each process has its **own isolated
memory space** (virtual address space), its own file descriptors, and at least
one thread. Process A literally cannot read process B's memory (the MMU/OS
enforces it). Creating one is expensive (new address space, etc.). Talking
between processes needs **IPC** — pipes, sockets, shared memory, message
passing — because they share no memory.

### Thread
The OS's unit of **scheduling/execution**. A thread lives *inside* a process and
**shares that process's memory** with its sibling threads, but has its own
**stack, registers, and program counter**. The OS scheduler time-slices threads
across CPU cores — so two threads of one process can run **truly in parallel on
two cores** (at the OS level). Cheaper than a process (shares the address
space), but still real OS objects (~MB of stack each).

**How the OS runs them — preemptive scheduling:** the OS scheduler decides who
runs. It can **interrupt** a running thread at almost any instruction (a timer
interrupt, ~every few ms), save its registers (a **context switch**), and resume
another. The thread has no say — it's *preempted*. This is why shared data needs
**locks**: a switch can happen mid-update.

### Async / event loop (cooperative concurrency in ONE thread)
A totally different idea, older than Python (select/poll, Node.js). **One**
thread runs an **event loop**: a `while True` that asks the OS "which of my
sockets/files are ready?" (via `epoll` on Linux, `kqueue` on macOS, `IOCP` on
Windows), runs the tasks that are ready until they hit their *next* wait, then
loops. Tasks **voluntarily yield** at I/O points ("I'm about to wait for the
network — go run someone else"). This is **cooperative** scheduling: no
preemption, the task chooses when to give up control. The trick underneath is
**non-blocking I/O** — instead of "read this socket (block until data)", it's
"read if ready, else tell me later," and the loop multiplexes thousands of these
on one thread.

**The key mechanical contrast (this is your exact question):**

|                | Threads (for I/O)                        | Async/await                                  |
|----------------|------------------------------------------|----------------------------------------------|
| how many OS threads | many                                | **one**                                      |
| who switches   | the **OS**, preemptively, anywhere       | the **event loop**, cooperatively, only at `await` |
| you write      | normal blocking code                     | `async`/`await`, non-blocking libraries      |
| switch happens | involuntarily, any instruction           | only where *you* wrote `await`               |
| cost per task  | a real OS thread (~MB stack)             | a tiny object (KBs) → millions feasible      |
| shared-state races | yes — need locks (switch is anywhere) | far fewer — code between two `await`s runs uninterrupted |
| one bad actor  | a CPU-hog thread is preempted, others still run | a coroutine that never `await`s (or makes a *blocking* call) **freezes the whole loop** |

Both let "other work proceed while one task waits on I/O" — but threads achieve
it with **many OS threads the OS juggles**, while async achieves it with **one
thread that juggles tasks itself, switching only at `await`**.

---

## PART 2 — In Python specifically (and the GIL)

### The GIL (Global Interpreter Lock)
CPython has **one lock that must be held to execute Python bytecode**. So even
with 8 threads on 8 cores, **only one thread runs Python at a time**. It exists
because CPython's memory management (reference counting) isn't thread-safe, and
one big lock was the simplest way to make the interpreter safe.

**Crucially, the GIL is released:**
- during **blocking I/O** (socket read, disk read, `time.sleep`) — the thread
  drops the GIL while the OS does the wait, so *another* Python thread runs;
- by many **C extensions** during heavy compute — `hashlib` on big buffers,
  NumPy, Pillow's decoder, PyTorch — they explicitly release it
  (`Py_BEGIN_ALLOW_THREADS`) while their C/C++ inner loop runs;
- periodically for CPU-bound Python (every ~5 ms, `sys.getswitchinterval()`),
  so threads are still **preemptive**.

### `threading` — real OS threads, GIL-limited
Real OS threads, **preemptively** scheduled. But the GIL means:
- **Pure-Python CPU work does NOT speed up** with threads — they take turns
  holding the GIL (often *slower* than serial, due to lock contention).
- **I/O-bound work DOES speed up** — the GIL is released during the wait, so
  while thread A waits on a socket, thread B runs.
- **GIL-releasing C work speeds up too** — numpy/Pillow/torch drop the GIL.

```python
from concurrent.futures import ThreadPoolExecutor
import requests   # a normal *blocking* library — fine with threads

def fetch(url):
    return requests.get(url).status_code   # blocks; GIL released during the wait

with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(fetch, urls))    # 8 requests in flight at once
```

### `asyncio` / `async`/`await` — one thread, one event loop
A single thread runs the event loop; coroutines `await` at I/O points and yield.
**No GIL contention** — there's only one thread, so the GIL is never fought
over. Async **sidesteps** the GIL by never having two threads, rather than
fighting it. But:
- You must use **async libraries** (`aiohttp`, `asyncpg`, `aioboto3`) — a normal
  blocking call (`requests.get`, `time.sleep`) **freezes the entire loop**.
- A coroutine doing heavy **CPU** also freezes the loop (no `await` to yield at)
  — async does nothing for CPU-bound work.

```python
import asyncio, aiohttp     # async library required

async def fetch(session, url):
    async with session.get(url) as r:   # `await` points: yields to the loop
        return r.status

async def main():
    async with aiohttp.ClientSession() as s:
        return await asyncio.gather(*(fetch(s, u) for u in urls))  # all at once

asyncio.run(main())
```

### `multiprocessing` — separate interpreters, true CPU parallelism
Each process is a **full, separate Python interpreter with its OWN GIL** and its
own memory. So CPU-bound Python **actually runs in parallel** across cores. Cost:
- **no shared memory** — arguments/results are **pickled** and sent over IPC;
- **startup overhead** (fork/spawn a new interpreter);
- can't pickle everything (locks, open sockets, lambdas under `spawn`).

```python
from concurrent.futures import ProcessPoolExecutor

def heavy(n):                      # pure-Python CPU work
    return sum(i*i for i in range(n))

with ProcessPoolExecutor(max_workers=8) as ex:   # 8 real parallel interpreters
    results = list(ex.map(heavy, [10_000_000]*8))
```

> Note: Python 3.13 ships an experimental **free-threaded ("no-GIL") build**
> where threads *can* run Python in parallel. Not the default yet; the GIL model
> above is still what you reason about in 2026.

---

## PART 3 — The exact differences, side by side

| dimension | `threading` | `asyncio` | `multiprocessing` |
|---|---|---|---|
| OS threads | many | **one** | many (1+ per process) |
| memory | shared | shared (1 thread) | **isolated** (pickled IPC) |
| scheduling | OS, **preemptive** | event loop, **cooperative** | OS, preemptive |
| switch point | any instruction | only at `await` | any instruction |
| CPU parallelism (pure Python) | ❌ (GIL) | ❌ (1 thread) | ✅ (own GIL each) |
| I/O concurrency | ✅ | ✅ | ✅ (overkill) |
| needs special libraries | no (blocking libs fine) | **yes** (async libs) | no |
| cost per unit | medium (~MB stack) | tiny (KBs) | high (whole interpreter) |
| shared-state hazard | high → locks | low (between awaits) | none (isolated) |
| one task hogs | preempted, others run | **stalls everything** (no await) | unaffected |
| GIL relevance | the central limit | sidestepped (1 thread) | each has its own |

---

## PART 4 — Which to use (decide by what you're bound on)

**First: profile. Are you I/O-bound or CPU-bound?** Don't guess.

- **CPU-bound** (image resize, ML inference *if not already C-parallel*, math,
  compression, parsing huge data): → **processes** (`ProcessPoolExecutor`).
  Exception: if the heavy work is in a **C extension that releases the GIL**
  (NumPy, Pillow, torch), threads *can* parallelize it without process overhead.
- **I/O-bound, moderate concurrency (tens–hundreds), using sync libraries**
  (`requests`, `boto3`, a sync DB driver): → **threads** (`ThreadPoolExecutor`).
  Simplest — keep your blocking code, get concurrency for free.
- **I/O-bound, massive concurrency (thousands–millions of sockets), async
  ecosystem available** (web servers, chat, scrapers, proxies): → **async**.
  One thread handles 10k connections that threads couldn't (10k × MB stacks).
- **Mix** (CPU + I/O): pipeline them — e.g. a thread/async layer for I/O feeding
  a process pool for CPU. Or `asyncio.run_in_executor` to call blocking/CPU code
  from async without freezing the loop.

Rules of thumb:
- Threads vs async for I/O: **async scales higher and is cheaper per task, but
  demands async-all-the-way**; **threads are simpler and work with any blocking
  library** but cost more per task and need locks. If your library is sync and
  your concurrency is in the dozens, threads win on simplicity.
- "CPU-bound" → process — *unless* it's already C-parallel (then thread or even
  leave it serial).

---

## PART 5 — How this maps to PicLocker (decided by measurement)

We profiled ingest (30 real photos, model warm):

| stage | % wall-clock | bound by |
|---|---|---|
| upload | **82%** | network I/O |
| CLIP encode | 14% | CPU (but torch releases GIL + uses all cores) |
| hash/decode/pHash | 4% | trivial (C-ext, GIL released) |

- **Upload (the bottleneck) → threads.** It's I/O-bound (82%, blocked on the
  socket → GIL released), and `boto3` is a **synchronous** library. A
  `ThreadPoolExecutor` of ~8 uploaders saturates upload bandwidth while keeping
  the simple sync client. (Async/`aioboto3` would also work and scale higher,
  but we don't have thousands of concurrent uploads — we have one home server's
  bandwidth to fill. Threads are the right tool at this scale.)
- **CLIP → NOT processes.** It's "CPU-bound," but (a) it's only 14% — fix the
  82% first (Amdahl), and (b) torch already parallelizes one inference across
  all cores, so a process pool would **oversubscribe** the CPU. Keep it serial /
  in the thread layer.
- **hash/pHash** ride along on the threads — they're C-extension work that
  releases the GIL, so threads handle them fine.

That's the §6 skill target answered with data: **threads for the I/O bottleneck,
deliberately not processes for the CPU stage, because measurement (not dogma)
showed I/O dominates and the CPU stage is already core-saturated.**

---

## Gotchas checklist
- **Threads don't speed up pure-Python CPU** — GIL. If it's a `for` loop
  crunching numbers in Python, threads won't help; use processes.
- **One blocking call kills an async loop** — never `requests.get`/`time.sleep`
  inside a coroutine; use the async equivalent or `run_in_executor`.
- **Processes can't share objects** — everything crosses the boundary by
  pickling; large data is expensive to ship, some objects can't be pickled.
- **Threads need locks** for shared mutable state (preemption strikes anywhere);
  prefer `queue.Queue` (thread-safe) over raw shared dicts.
- **"CPU-bound C extension" is the exception to every rule** — NumPy/Pillow/torch
  release the GIL, so threads *can* parallelize them; profile before assuming.
