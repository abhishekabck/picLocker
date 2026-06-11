# Python Generators — a working reference

> You hit these in `db.py` (the `yield` + `next()` thing). This is the mental
> model + the API, with runnable examples, and where they actually fit in
> PicLocker.

---

## 1. What a generator *is*

A **generator** is a function that produces values **lazily, one at a time**,
remembering where it left off between values. You write it like a normal
function but use **`yield`** instead of `return`.

```python
def count_up_to(n):
    i = 1
    while i <= n:
        yield i        # hand back i, then PAUSE here
        i += 1
```

Calling it does **not** run the body — it returns a **generator object**:

```python
g = count_up_to(3)     # nothing has run yet
print(g)               # <generator object count_up_to at 0x...>
```

The body runs only as you pull values out of it.

---

## 2. How it works mechanically — suspend & resume

The magic: at each `yield`, the function **freezes** — its local variables, its
position in the code, everything — and hands one value back. The next time you
ask for a value, it **resumes exactly where it paused**.

```python
g = count_up_to(3)
next(g)   # runs until first yield -> 1   (now PAUSED after `yield i`)
next(g)   # resumes, i becomes 2, loops, yields -> 2
next(g)   # resumes, i becomes 3, yields -> 3
next(g)   # resumes, loop ends, function returns -> raises StopIteration
```

A normal function runs start-to-finish and returns once. A generator runs in
**slices**, pausing at every `yield`, keeping its state alive in between. That
"keeps its state across pauses" is the whole point — it's why the `finally` in
your `db.py` only ran at the wrong time (more in §8).

---

## 3. Two ways to make one

**(a) Generator function** — a `def` with `yield` (as above).

**(b) Generator expression** — like a list comprehension but with `()`:

```python
squares = (x * x for x in range(1_000_000))   # lazy — computes nothing yet
```

The difference from a list comp `[x*x for x in ...]` is **memory**: the list
builds all 1,000,000 values in RAM *now*; the generator builds them **one at a
time, on demand**, holding only one in memory.

---

## 4. How you consume a generator

**Most common — just loop:**
```python
for n in count_up_to(3):
    print(n)        # 1, 2, 3  — the for-loop calls next() for you and
                    # stops cleanly on StopIteration
```

**Manually with `next()`:**
```python
g = count_up_to(2)
next(g)             # 1
next(g)             # 2
next(g)             # raises StopIteration
next(g, "done")     # 2nd arg = default returned instead of raising
```

**Drain it into a list** (only if it's finite and fits in memory — this defeats
the laziness):
```python
list(count_up_to(3))   # [1, 2, 3]
```

**Key property — generators are single-use (exhaustible).** Once consumed, they
don't reset:
```python
g = count_up_to(2)
list(g)   # [1, 2]
list(g)   # []  <- already exhausted, nothing left
```

---

## 5. The generator methods (the full API)

| call            | what it does                                                        |
|-----------------|---------------------------------------------------------------------|
| `next(g)`       | resume until the next `yield`; return that value; raise `StopIteration` when the function ends |
| `g.send(value)` | resume, and make the *paused* `yield` expression evaluate to `value` (two-way communication) |
| `g.throw(exc)`  | resume by **raising** `exc` at the paused `yield` (inject an error)  |
| `g.close()`     | raise `GeneratorExit` at the paused `yield` so the generator stops — **this is what runs your `finally`** |

`send` example (advanced — generators can *receive*, not just produce):
```python
def echo():
    while True:
        got = yield          # `got` = whatever someone sends in
        print("got:", got)

g = echo()
next(g)          # prime it (run to the first yield)
g.send("hi")     # prints: got: hi
```
You'll rarely write `send`/`throw` yourself, but knowing they exist explains how
things like coroutines and `@contextmanager` work under the hood.

---

## 6. `return` inside a generator, and `yield from`

- A bare `return` (or falling off the end) ends the generator → `StopIteration`.
- `return value` stashes `value` on the exception (`StopIteration.value`) — used
  by `yield from`.
- `yield from other_gen` **delegates** to another generator, yielding all its
  values:
```python
def chain(a, b):
    yield from a
    yield from b

list(chain([1, 2], [3, 4]))   # [1, 2, 3, 4]
```

---

## 7. Where to USE them (and where not)

**Use a generator when:**
- The data is **large or unbounded** and you don't want it all in RAM at once
  (stream a million rows, read a file in chunks, an infinite sequence).
- You're building a **pipeline** — each stage pulls from the previous lazily.
- You only need to iterate **once**, forward.

**Don't use one when:**
- You need **random access** (`x[5]`), `len()`, or to iterate **multiple
  times** — use a list/tuple. (A generator has no length and no indexing.)
- The dataset is small and simple — a list is clearer.

The headline tradeoff: **generator = O(1) memory, lazy, single-pass;
list = O(n) memory, eager, reusable + indexable.**

---

## 8. `@contextmanager` — the fix for your `db.py`

This is *why* generators matter for your code right now. `contextlib.contextmanager`
turns a **one-yield generator** into a `with`-block resource manager:

```python
from contextlib import contextmanager
import sqlite3

@contextmanager
def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn          # <- everything before = setup (__enter__)
    finally:
        conn.close()        # <- everything after = teardown (__exit__)

# usage:
with get_db("piclocker.db") as conn:
    conn.execute("...")
# conn.close() runs HERE, guaranteed, even if the block raised
```

**Why this fixes your bug:** in your original `db.py` you had the `try/finally:
conn.close()` + `yield`, but you drove it with `next(db)` and never closed the
generator. `finally` runs when the generator is **closed** (`.close()`, or `with`
exiting, or GC) — and a dangling `next()` never triggers it deterministically.
`@contextmanager` + `with` calls `.close()` for you at the end of the block, so
the `finally` fires exactly when it should. Same `yield`, correct lifecycle.

---

## 9. Generators in PicLocker (where you'll actually reach for them)

- **Recursive folder walk (task #9):** `walk_images(folder)` should **yield**
  image paths one at a time, not build a list of 10,000 `Path`s in memory. The
  ingest loop pulls them lazily:
  ```python
  def walk_images(root):
      for p in Path(root).rglob("*"):
          if p.suffix.lower() in IMAGE_EXTS and p.is_file():
              yield p
  ```
- **Chunked reads for multipart:** yield fixed-size byte chunks of a big file so
  you never load a 400 MB RAW into RAM at once.
- **Pipeline stages:** a producer generator feeds a consumer — the §8 ingest
  pipeline is generators/queues at heart.
- **`@contextmanager` for DB + any resource** that needs guaranteed cleanup.

---

## 10. Gotchas checklist

- **Single-use:** consumed once, then empty. Re-create to re-iterate.
- **No `len()`, no indexing** — it doesn't know how many values it'll produce.
- **Lazy means errors surface late** — a bug in the body doesn't fire until you
  pull the value that hits it.
- **`finally`/cleanup runs on `.close()` / `with`-exit / GC**, *not* when you
  stop calling `next()`. Drive resource-holding generators with `with`
  (`@contextmanager`), never a bare `next()`.
